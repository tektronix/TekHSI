"""TLS channel negotiation, credentials, and security exceptions for TekHSI."""

from __future__ import annotations

import contextlib
import inspect
import ipaddress
import socket
import ssl
import time
import uuid

from pathlib import Path
from typing import Any, TYPE_CHECKING, Union

import grpc

from tekhsi._tek_highspeed_server_pb2 import ConnectRequest  # pylint: disable=no-name-in-module
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.auth_basic import build_basic_authorization_value, DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import CertInfo, TekHSICredentialStore, tls_server_name_from_pem

if TYPE_CHECKING:
    from collections.abc import Callable

# Minimum positional-parameter counts for on_trust_prompt callbacks.
_ON_TRUST_ARGS_WITH_AUTH_REQUIRED = 3
# Minimum tuple length from on_trust_prompt to include an explicit login.
_ON_TRUST_RESULT_HAS_LOGIN_LEN = 2


class TekSecurityError(Exception):
    """Base class for all security-related errors."""


class TekUnknownInstrument(TekSecurityError):  # noqa: N818
    """Instrument not in credential store, no callback provided."""

    def __init__(self, host: str, cert_info: CertInfo) -> None:
        """Instrument not in credential store, no callback provided."""
        self.host = host
        self.cert_info = cert_info
        fp = cert_info.cert_fingerprint
        msg = (
            f"Unknown instrument {host}\n"
            f"  Fingerprint: {fp[:16]}...\n"
            f"  Provide on_trust_prompt callback or trust via TekCredentialStore."
            if fp
            else f"Unknown instrument {host}. Provide on_trust_prompt or TekCredentialStore."
        )
        super().__init__(msg)


class TekCertificateMismatch(TekSecurityError):  # noqa: N818
    """Stored fingerprint doesn't match server certificate."""

    def __init__(self, host: str, stored_fingerprint: str, current_fingerprint: str) -> None:
        """Stored fingerprint doesn't match server certificate."""
        self.host = host
        self.stored_fingerprint = stored_fingerprint
        self.current_fingerprint = current_fingerprint
        super().__init__(
            f"Certificate mismatch for {host}.\n"
            f"  Stored:  {stored_fingerprint[:24]}...\n"
            f"  Current: {current_fingerprint[:24]}...\n"
            f"  If the instrument was reconfigured, remove and re-trust it."
        )


class TekAuthenticationFailed(TekSecurityError):  # noqa: N818
    """Password rejected or missing."""

    def __init__(self, host: str, message: str) -> None:
        """Password rejected or missing."""
        self.host = host
        super().__init__(f"{host}: {message}")


TekHSIUnknownInstrument = TekUnknownInstrument


def _parse_host_port(host_port: str) -> tuple[str, int]:
    s = host_port.strip()
    if s.startswith("["):
        end = s.index("]")
        host = s[1:end]
        if len(s) > end + 1 and s[end + 1] == ":":
            return host, int(s[end + 2 :])
        return host, 5000
    if ":" in s:
        host, port_str = s.rsplit(":", 1)
        return host, int(port_str)
    return s, 5000


def _is_ip_literal(host: str) -> bool:
    """True if host is an IPv4 or IPv6 address literal (not a DNS name)."""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        ipaddress.ip_address(h)
    except ValueError:
        return False
    return True


def _tls_server_name_for_entry(entry: dict[str, str | None]) -> str | None:
    if name := entry.get("tls_server_name"):
        return name
    if not (cert_path := entry.get("cert_path")):
        return None
    try:
        with Path(cert_path).open("rb") as f:
            return tls_server_name_from_pem(f.read())
    except OSError:
        return None


def _tls_channel_options(  # pylint: disable=too-many-return-statements  # noqa: PLR0911
    connect_host: str, tls_server_name: str | None
) -> tuple[tuple[str, str], ...]:
    """GRPC channel options when URL host differs from the cert name (IP or .local)."""
    if not tls_server_name:
        return ()
    cert_name = tls_server_name.strip()
    host = connect_host.strip()
    host_lower = host.lower()
    cert_lower = cert_name.lower()
    if host_lower == cert_lower:
        return ()
    if host_lower == cert_lower + ".local":
        return (("grpc.ssl_target_name_override", cert_name),)
    if host_lower.endswith(".local") and host_lower[: -len(".local")] == cert_lower:
        return (("grpc.ssl_target_name_override", cert_name),)
    if _is_ip_literal(host):
        return (("grpc.ssl_target_name_override", cert_name),)
    if host_lower != cert_lower:
        return (("grpc.ssl_target_name_override", cert_name),)
    return ()


def _secure_channel(
    url: str,
    creds: grpc.ChannelCredentials,
    entry: dict[str, str | None] | None = None,
    tls_server_name: str | None = None,
) -> grpc.Channel:
    host, _ = _parse_host_port(url)
    if tls_server_name is None and entry is not None:
        tls_server_name = _tls_server_name_for_entry(entry)
    if opts := _tls_channel_options(host, tls_server_name):
        return grpc.secure_channel(url, creds, options=opts)
    return grpc.secure_channel(url, creds)


def _build_creds_from_entry(entry: dict[str, str | None], mode: str) -> grpc.ChannelCredentials:
    """Build gRPC credentials from a store entry (must have cert_path)."""
    if not (ca_path := entry.get("cert_path")):
        msg = "Store entry missing cert_path"
        raise ValueError(msg)
    with Path(ca_path).open("rb") as f:
        root = f.read()
    if mode == "token":
        password = entry.get("password") or ""
        login = entry.get("login") or DEFAULT_MODE3_USERNAME
        ssl_creds = grpc.ssl_channel_credentials(root_certificates=root)

        def meta_cb(_ctx: object, cb: Callable[..., None]) -> None:
            val = build_basic_authorization_value(login, password)
            cb((("authorization", val),), None)

        return grpc.composite_channel_credentials(
            ssl_creds, grpc.metadata_call_credentials(meta_cb)
        )
    return grpc.ssl_channel_credentials(root_certificates=root)


def _fetch_server_cert(host: str, port: int, timeout: float = 5.0) -> CertInfo:
    """Connect via TLS without verification and return server cert info (for TOFU)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection((host, port), timeout=timeout) as sock,
        context.wrap_socket(sock, server_hostname=host) as ssock,
    ):
        der = ssock.getpeercert(binary_form=True)
    if not der:
        msg = "Server did not present a certificate"
        raise ConnectionError(msg)
    pem = ssl.DER_cert_to_PEM_cert(der)
    return CertInfo.from_pem(pem.encode() if isinstance(pem, str) else pem)


def _try_plain_grpc_channel(url: str, deadline: float) -> grpc.Channel | None:
    """If the server accepts plain gRPC Connect, return a new insecure channel; else None."""
    ch = grpc.insecure_channel(url)
    probe = str(uuid.uuid4())
    try:
        if (rem := max(0.5, deadline - time.time())) <= 0:
            with contextlib.suppress(Exception):
                ch.close()
            return None
        stub = ConnectStub(ch)
        stub.Connect(ConnectRequest(name=probe), timeout=rem)
        with contextlib.suppress(grpc.RpcError):
            stub.Disconnect(ConnectRequest(name=probe), timeout=min(rem, 3.0))
    except grpc.RpcError:
        with contextlib.suppress(Exception):
            ch.close()
        return None
    except (OSError, ValueError, TypeError):
        with contextlib.suppress(Exception):
            ch.close()
        return None
    with contextlib.suppress(Exception):
        ch.close()
    return grpc.insecure_channel(url)


def _call_on_trust(
    cb: Callable[..., Any],
    host_port: str,
    cert_info: CertInfo,
    *,
    auth_required: bool,
) -> Any:
    """Invoke on_trust_prompt with (host, cert_info) or (host, cert_info, auth_required)."""
    try:
        sig = inspect.signature(cb)
        if len(sig.parameters) >= _ON_TRUST_ARGS_WITH_AUTH_REQUIRED:
            return cb(host_port, cert_info, auth_required)
    except TypeError:
        pass
    return cb(host_port, cert_info)


def _resolve_credentials_from_store(  # pylint: disable=too-many-locals
    host_port: str,
    store: TekHSICredentialStore,
    mode: str,
    on_trust_prompt: Callable[..., Union[bool, tuple[bool, str | None]]] | None,
    deadline: float,
) -> grpc.ChannelCredentials:
    """Resolve gRPC credentials from store or TOFU."""
    host, port = _parse_host_port(host_port)
    if time.time() > deadline:
        msg = f"Connection to {host_port} timed out during security negotiation."
        raise TekSecurityError(msg)
    entry = store.get(host_port)
    if entry and entry.get("cert_path"):
        tmo = max(0.5, min(5.0, deadline - time.time()))
        live = _fetch_server_cert(host, port, tmo)
        fp = entry.get("cert_fingerprint")
        if fp and live.cert_fingerprint != fp:
            raise TekCertificateMismatch(host_port, fp, live.cert_fingerprint)
        return _build_creds_from_entry(entry, mode)
    try:
        tmo = max(0.5, min(5.0, deadline - time.time()))
        cert_info = _fetch_server_cert(host, port, tmo)
    except Exception as e:
        raise TekUnknownInstrument(host_port, CertInfo(cert_fingerprint="")) from e
    if on_trust_prompt:
        if (
            result := _call_on_trust(on_trust_prompt, host_port, cert_info, auth_required=False)
        ) is True:
            store.trust(host_port, cert_info, password=None)
            store.save()
        elif isinstance(result, (list, tuple)) and len(result) >= 1 and result[0]:
            password = result[1] if len(result) > 1 else None
            if not (login := result[2] if len(result) > _ON_TRUST_RESULT_HAS_LOGIN_LEN else None):
                login = None
            store.trust(host_port, cert_info, password=password, login=login)
            store.save()
        else:
            raise TekUnknownInstrument(host_port, cert_info)
    else:
        raise TekUnknownInstrument(host_port, cert_info)
    entry = store.get(host_port)
    if not entry or not entry.get("cert_path"):
        raise TekUnknownInstrument(host_port, cert_info)
    return _build_creds_from_entry(entry, mode)


def _channel_from_trusted_entry(
    url: str,
    host: str,
    port: int,
    entry: dict[str, str | None],
    deadline: float,
    *,
    require_tls: bool,
) -> grpc.Channel:
    """Build a channel for a host that is already in the credential store."""
    if not require_tls and (plain := _try_plain_grpc_channel(url, deadline)) is not None:
        return plain
    tmo = max(0.5, min(8.0, deadline - time.time()))
    live = _fetch_server_cert(host, port, tmo)
    fp = entry.get("cert_fingerprint")
    if fp and live.cert_fingerprint != fp:
        raise TekCertificateMismatch(url, fp, live.cert_fingerprint)
    if entry.get("password"):
        return _secure_channel(url, _build_creds_from_entry(entry, "token"), entry=entry)
    return _secure_channel(url, _build_creds_from_entry(entry, "tls"), entry=entry)


def _apply_prompt_and_channel(
    url: str,
    store: TekHSICredentialStore,
    on_trust_prompt: Callable[..., Any],
    cert_info: CertInfo,
) -> grpc.Channel:
    """Handle the prompt result, persist trust, and return the resulting TLS channel."""
    if (result := _call_on_trust(on_trust_prompt, url, cert_info, auth_required=False)) is True:
        store.trust(url, cert_info, password=None)
        store.save()
    elif isinstance(result, (list, tuple)) and len(result) >= 1 and result[0]:
        pwd = result[1] if len(result) > 1 else None
        if not (login := result[2] if len(result) > _ON_TRUST_RESULT_HAS_LOGIN_LEN else None):
            login = None
        store.trust(url, cert_info, password=pwd, login=login)
        store.save()
    else:
        raise TekUnknownInstrument(url, cert_info)
    entry = store.get(url)
    if not entry or not entry.get("cert_path"):
        raise TekUnknownInstrument(url, cert_info)
    if entry.get("password"):
        return _secure_channel(url, _build_creds_from_entry(entry, "token"), entry=entry)
    return _secure_channel(url, _build_creds_from_entry(entry, "tls"), entry=entry)


def _auto_negotiate_channel(
    url: str,
    store: TekHSICredentialStore,
    on_trust_prompt: Callable[..., Any] | None,
    require_tls: bool,  # noqa: FBT001  (kept positional for backward compatibility)
    deadline: float,
    timeout: float,
) -> grpc.Channel:
    """Pick insecure or TLS channel when credentials=None (auto-negotiation)."""
    host, port = _parse_host_port(url)

    if (entry := store.get(url)) and entry.get("cert_path"):
        return _channel_from_trusted_entry(
            url, host, port, entry, deadline, require_tls=require_tls
        )

    if not require_tls:
        if (plain := _try_plain_grpc_channel(url, deadline)) is not None:
            return plain
        if max(0.5, deadline - time.time()) <= 0:
            msg = f"Connection to {url} timed out during security negotiation ({timeout}s)."
            raise TekSecurityError(msg)
    elif not on_trust_prompt:
        msg = (
            f"TLS required but cannot establish secure connection to {url}. "
            f"Instrument not in credential store. Use on_trust_prompt or populate the store."
        )
        raise TekSecurityError(msg)

    if time.time() > deadline:
        msg = f"Connection to {url} timed out during security negotiation ({timeout}s)."
        raise TekSecurityError(msg)
    tmo = max(0.5, min(8.0, deadline - time.time()))
    cert_info = _fetch_server_cert(host, port, tmo)
    if not on_trust_prompt:
        raise TekUnknownInstrument(url, cert_info)
    return _apply_prompt_and_channel(url, store, on_trust_prompt, cert_info)


class TekHSICredentials:
    """User-facing builder for TLS and TLS+Basic channel credentials."""

    def __init__(
        self,
        channel_credentials: grpc.ChannelCredentials | None = None,
        *,
        _use_store: bool = False,
        _store_mode: str = "tls",
        _tls_server_name: str | None = None,
    ) -> None:
        """Initialize credentials. Use static methods tls() or token() to build."""
        self._channel_credentials = channel_credentials
        self._use_store = _use_store
        self._store_mode = _store_mode
        self._tls_server_name = _tls_server_name

    @staticmethod
    def tls(ca_cert_path: str | None = None) -> TekHSICredentials:
        """Build credentials for Mode 2 (TLS only)."""
        if ca_cert_path is None:
            return TekHSICredentials(None, _use_store=True, _store_mode="tls")
        with Path(ca_cert_path).open("rb") as f:
            root_certificates = f.read()
        creds = grpc.ssl_channel_credentials(root_certificates=root_certificates)
        tls_name = tls_server_name_from_pem(root_certificates)
        return TekHSICredentials(creds, _tls_server_name=tls_name)

    @staticmethod
    def token(
        ca_cert_path: str | None = None,
        token: str | None = None,
        username: str | None = None,
    ) -> TekHSICredentials:
        """Build credentials for Mode 3 (TLS + HTTP Basic client auth)."""
        if ca_cert_path is None and token is None:
            return TekHSICredentials(None, _use_store=True, _store_mode="token")
        if ca_cert_path is None or token is None:
            msg = "token() requires both ca_cert_path and token, or neither (use store)"
            raise ValueError(msg)
        with Path(ca_cert_path).open("rb") as f:
            root_certificates = f.read()
        ssl_creds = grpc.ssl_channel_credentials(root_certificates=root_certificates)
        user = username if username is not None else DEFAULT_MODE3_USERNAME

        def metadata_cb(_context: object, callback: Callable[..., None]) -> None:
            callback(
                (("authorization", build_basic_authorization_value(user, token)),),
                None,
            )

        auth_creds = grpc.metadata_call_credentials(metadata_cb)
        composite = grpc.composite_channel_credentials(ssl_creds, auth_creds)
        tls_name = tls_server_name_from_pem(root_certificates)
        return TekHSICredentials(composite, _tls_server_name=tls_name)

    def _grpc_credentials(self) -> grpc.ChannelCredentials:
        """Return the underlying gRPC channel credentials (for TekHSIConnect)."""
        if self._channel_credentials is None:
            msg = "Store-based credentials must be resolved via credential_store"
            raise ValueError(msg)
        return self._channel_credentials
