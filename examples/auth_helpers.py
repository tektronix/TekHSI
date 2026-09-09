"""Shared TekHSI auth-discovery helpers for the ``examples/`` scripts.

Isolates the (private) TekHSI security API surface in one place so the
example scripts don't each depend on ``tekhsi.security._*`` internals.

Do NOT rely on this module from application code - the underlying
``tekhsi.security._*`` symbols are private and may change in any release.
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
import time
import uuid

from pathlib import Path
from typing import TYPE_CHECKING

import grpc

from tekhsi._tek_highspeed_server_pb2 import ConnectRequest  # pylint: disable=no-name-in-module
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.security import (  # pylint: disable=import-private-name
    _build_creds_from_entry,
    _fetch_server_cert,
    _parse_host_port,
    _secure_channel,
    _try_plain_grpc_channel,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_PROBE_TIMEOUT_S = 8.0
_DISCOVERY_DEADLINE_S = 12.0

# Placeholder addresses used in example scripts that must be edited by the user
# before running. Detected up-front to give a friendly error instead of a
# confusing TLS/gRPC failure.
_PLACEHOLDER_ADDRS = frozenset({"192.168.0.0", "192.168.0.1"})


def guard_placeholder_addr(addr: str, extras: Iterable[str] = ()) -> None:
    """Exit with a friendly message if ``addr`` is still the example placeholder."""
    placeholders = _PLACEHOLDER_ADDRS | frozenset(extras)
    if addr.strip() in placeholders:
        print(
            f"The scope IP is still the placeholder '{addr}'. "
            f"Edit the 'addr' variable at the top of this script to your instrument's IP.",
        )
        sys.exit(2)


def _probe(stub: ConnectStub) -> tuple[bool, str | None]:
    """Connect + Disconnect round trip. Returns ``(ok, grpc_error_code_name)``."""
    name = str(uuid.uuid4())
    try:
        stub.Connect(ConnectRequest(name=name), timeout=_PROBE_TIMEOUT_S)
    except grpc.RpcError as e:
        return False, e.code().name
    finally:
        with contextlib.suppress(grpc.RpcError):
            stub.Disconnect(ConnectRequest(name=name), timeout=3.0)
    return True, None


def discover(url: str) -> tuple[bool, Path | None, dict, bool]:
    """Fresh-probe ``url`` and return ``(plain_ok, cert_path, entry, needs_password)``."""
    deadline = time.time() + _DISCOVERY_DEADLINE_S

    if (plain_channel := _try_plain_grpc_channel(url, deadline)) is not None:
        with contextlib.suppress(Exception):
            plain_channel.close()
        return True, None, {}, False

    host, port = _parse_host_port(url)
    try:
        cert = _fetch_server_cert(host, port, timeout=_PROBE_TIMEOUT_S)
    except OSError as exc:
        print(f"Could not reach TekHSI on {url}: {exc}")
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as tmp:
        tmp.write(cert.cert_pem or b"")
        pem_path = Path(tmp.name)

    probe_entry = {
        "cert_fingerprint": cert.cert_fingerprint,
        "cert_path": str(pem_path),
        "tls_server_name": cert.tls_server_name,
        "login": None,
        "password": None,
    }

    ch = _secure_channel(url, _build_creds_from_entry(probe_entry, "tls"), entry=probe_entry)
    try:
        ok, err = _probe(ConnectStub(ch))
    finally:
        with contextlib.suppress(Exception):
            ch.close()

    if ok:
        return False, pem_path, probe_entry, False
    if err == "UNAUTHENTICATED":
        return False, pem_path, probe_entry, True

    print(f"TLS probe failed: {err}")
    pem_path.unlink(missing_ok=True)
    sys.exit(1)


def verify_password(url: str, store_entry: dict, secret: str, cert_path: Path | None) -> None:
    """Probe with ``secret``; on failure, clean up ``cert_path`` and exit."""
    auth_entry = {**store_entry, "password": secret, "login": DEFAULT_MODE3_USERNAME}
    ch = _secure_channel(url, _build_creds_from_entry(auth_entry, "token"), entry=auth_entry)
    try:
        ok, err = _probe(ConnectStub(ch))
    finally:
        with contextlib.suppress(Exception):
            ch.close()
    if not ok:
        print(f"Authentication failed: {err}")
        if cert_path is not None:
            cert_path.unlink(missing_ok=True)
        sys.exit(1)
