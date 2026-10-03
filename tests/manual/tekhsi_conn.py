"""TekHSI connection builder with automatic security-mode detection.

Probes the TekHSI endpoint to determine whether it requires TLS and/or
password authentication (Mode 1 / Mode 2 / Mode 3), then builds the
appropriate ``TekHSICredentials`` and ``TekHSIConnect`` keyword arguments.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
import uuid

from typing import Any

import grpc

import tekhsi.security as _sec

from tekhsi import TekHSICredentials
from tekhsi._tek_highspeed_server_pb2 import ConnectRequest  # pylint: disable=no-name-in-module
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import TekHSICredentialStore


def _probe_connect(stub: ConnectStub, timeout: float) -> tuple[bool, str | None]:
    """Attempt a gRPC Connect/Disconnect round-trip.

    Returns:
        ``(True, None)`` on success; ``(False, error_code_name)`` on failure.
    """
    name = str(uuid.uuid4())
    try:
        stub.Connect(ConnectRequest(name=name), timeout=timeout)
    except grpc.RpcError as exc:
        return False, exc.code().name  # type: ignore[union-attr]
    finally:
        with contextlib.suppress(grpc.RpcError):
            stub.Disconnect(ConnectRequest(name=name), timeout=min(timeout, 3.0))
    return True, None


def _entry_from_cert(cert: Any, pem_path: str) -> dict[str, str | None]:
    return {
        "cert_fingerprint": cert.cert_fingerprint,
        "cert_path": pem_path,
        "tls_server_name": cert.tls_server_name,
        "login": None,
        "password": None,
    }


def _write_temp_pem(cert_pem: bytes | None) -> str:
    """Write cert PEM bytes to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    try:
        tmp.write(cert_pem or b"")
    finally:
        tmp.close()
    return tmp.name


def _classify_mode(
    *,
    plain_ok: bool,
    tls_handshake: bool,
    tls_no_auth_ok: bool,
    tls_needs_password: bool,
) -> tuple[bool, bool, str]:
    """Classify detected probe results into (needs_encryption, needs_password, mode_str)."""
    if plain_ok or not tls_handshake:
        needs_encryption, needs_password = False, False
    elif tls_no_auth_ok:
        needs_encryption, needs_password = True, False
    else:
        needs_encryption, needs_password = True, True

    if not needs_encryption and not needs_password:
        mode_str = "Mode 1 (plain, no auth)"
    elif needs_encryption and not needs_password:
        mode_str = "Mode 2 (TLS, no password)"
    else:
        mode_str = "Mode 3 (TLS + password)"
    return needs_encryption, needs_password, mode_str


def _tls_connect_result(
    url: str,
    entry: dict[str, str | None],
    *,
    password: str | None = None,
    login: str | None = None,
) -> tuple[bool, str | None]:
    """Attempt a TLS Connect RPC and return ``(ok, grpc_error_code_name)``."""
    if password:
        entry = {**entry, "password": password, "login": login or DEFAULT_MODE3_USERNAME}
        mode = "token"
    else:
        mode = "tls"
    creds = _sec._build_creds_from_entry(entry, mode)
    channel = _sec._secure_channel(url, creds, entry=entry)
    try:
        return _probe_connect(ConnectStub(channel), 8.0)
    finally:
        with contextlib.suppress(Exception):
            channel.close()


def detect_server_mode(
    url: str,
) -> tuple[bool, bool, Any | None, str | None, str]:
    """Probe the TekHSI endpoint and determine its security requirements.

    Args:
        url: Scope address in ``host:port`` format.

    Returns:
        ``(needs_encryption, needs_password, cert, pem_path, mode_str)``

        * ``needs_encryption`` — server requires TLS.
        * ``needs_password`` — server requires HTTP Basic auth.
        * ``cert`` — ``CertInfo`` from the TLS handshake, or ``None``.
        * ``pem_path`` — temp file path containing the PEM, or ``None``.
        * ``mode_str`` — human-readable mode label (``"Mode 1"`` / ``"Mode 2"``
          / ``"Mode 3"``).
    """
    host, port = _sec._parse_host_port(url)
    deadline = time.time() + 12.0

    plain_channel = _sec._try_plain_grpc_channel(url, deadline)
    plain_ok = plain_channel is not None
    if plain_channel is not None:
        with contextlib.suppress(Exception):
            plain_channel.close()

    cert = None
    pem_path: str | None = None
    tls_handshake = False
    try:
        cert = _sec._fetch_server_cert(host, port, timeout=8.0)
        tls_handshake = True
    except Exception:
        cert = None

    tls_no_auth_ok = False
    tls_needs_password = False
    if cert is not None:
        pem_path = _write_temp_pem(cert.cert_pem)
        entry = _entry_from_cert(cert, pem_path)
        ok, err = _tls_connect_result(url, entry)
        if ok:
            tls_no_auth_ok = True
        elif err == "UNAUTHENTICATED":
            tls_needs_password = True

    needs_encryption, needs_password, mode_str = _classify_mode(
        plain_ok=plain_ok,
        tls_handshake=tls_handshake,
        tls_no_auth_ok=tls_no_auth_ok,
        tls_needs_password=tls_needs_password,
    )

    return needs_encryption, needs_password, cert, pem_path, mode_str


def build_credentials(
    url: str,
    password: str | None,
    *,
    needs_encryption: bool,
    needs_password: bool,
    cert: Any | None,
    pem_path: str | None,
    login: str = DEFAULT_MODE3_USERNAME,
) -> TekHSICredentials | None:
    """Build ``TekHSICredentials`` matching the detected server mode.

    Args:
        url: Scope address (used to look up cached credential store entry).
        password: Explicit password; falls back to credential store, then env.
        needs_encryption: Server requires TLS.
        needs_password: Server requires HTTP Basic auth.
        cert: ``CertInfo`` from `detect_server_mode`.
        pem_path: Path to PEM temp file from `detect_server_mode`.
        login: HTTP Basic username (Mode 3 only).

    Returns:
        A ``TekHSICredentials`` instance, or ``None`` for plain connections.
    """
    store = TekHSICredentialStore()
    store_entry = store.get(url)

    # Resolve password: argument → credential store → environment variable.
    resolved_password = (
        password
        or (store_entry.get("password") if store_entry else None)
        or os.environ.get("TEKHSI_PASSWORD")
    )

    if not needs_encryption:
        return None  # Mode 1 — plain connection, no credentials needed

    # Use stored cert path if available.
    effective_pem = (store_entry.get("cert_path") if store_entry else None) or pem_path

    if needs_password and not resolved_password:
        raise RuntimeError(
            "Server requires a password (Mode 3) but none was provided. "
            "Set TEKHSI_PASSWORD in HSI_Benchmark/config.py or the environment."
        )

    if not effective_pem:
        host, port = _sec._parse_host_port(url)
        cert = _sec._fetch_server_cert(host, port, timeout=8.0)
        effective_pem = _write_temp_pem(cert.cert_pem)

    if needs_password:
        return TekHSICredentials.token(effective_pem, resolved_password, username=login)
    return TekHSICredentials.tls(effective_pem)


def build_connect_kwargs(
    credentials: TekHSICredentials | None,
    channel: str,
    on_trust_prompt: Any = None,
    credential_store: TekHSICredentialStore | None = None,
) -> dict[str, Any]:
    """Build keyword arguments for ``TekHSIConnect``.

    Always configures for running (continuous) acquisition mode.

    Args:
        credentials: Credentials from `build_credentials`, or ``None``.
        channel: Channel symbol to read (e.g. ``"ch1"``).
        on_trust_prompt: Optional trust-prompt callback.
        credential_store: Optional credential store instance.

    Returns:
        Dict suitable for ``TekHSIConnect(url, **kwargs)``.
    """
    kwargs: dict[str, Any] = {
        "activesymbols": [channel],
    }

    # Enable background acquisition thread if the installed version supports it.
    with contextlib.suppress(Exception):
        from inspect import signature  # pylint: disable=import-outside-toplevel

        from tekhsi import TekHSIConnect  # pylint: disable=import-outside-toplevel

        sig = signature(TekHSIConnect.__init__)
        if "background_thread" in sig.parameters:
            kwargs["background_thread"] = True

    if on_trust_prompt is not None:
        kwargs["on_trust_prompt"] = on_trust_prompt
    if credential_store is not None:
        kwargs["credential_store"] = credential_store
    if credentials is not None:
        kwargs["credentials"] = credentials
    return kwargs
