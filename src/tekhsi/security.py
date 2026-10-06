"""TLS channel negotiation, credentials, and security exceptions for TekHSI."""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import socket
import ssl
import time
import uuid

from collections.abc import Callable
from typing import Any, cast, Dict, Tuple, Union

import grpc

from tekhsi._tek_highspeed_server_pb2 import ConnectRequest  # pylint: disable=no-name-in-module
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.auth_basic import build_basic_authorization_value, DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import CertInfo, TekHSICredentialStore, tls_server_name_from_pem

_LOGGER = logging.getLogger(__name__)


class TekSecurityError(Exception):
    """Base class for all security-related errors."""


class TekUnknownInstrument(TekSecurityError):
    """Instrument not in credential store, no callback provided."""

    def __init__(self, host: str, cert_info: CertInfo) -> None:
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


class TekCertificateMismatch(TekSecurityError):
    """Stored fingerprint doesn't match server certificate."""

    def __init__(self, host: str, stored_fingerprint: str, current_fingerprint: str) -> None:
        self.host = host
        self.stored_fingerprint = stored_fingerprint
        self.current_fingerprint = current_fingerprint
        super().__init__(
            f"Certificate mismatch for {host}.\n"
            f"  Stored:  {stored_fingerprint[:24]}...\n"
            f"  Current: {current_fingerprint[:24]}...\n"
            f"  If the instrument was reconfigured, remove and re-trust it."
        )


class TekAuthenticationFailed(TekSecurityError):
    """Password rejected or missing."""

    def __init__(self, host: str, message: str) -> None:
        self.host = host
        super().__init__(f"{host}: {message}")


TekHSIUnknownInstrument = TekUnknownInstrument


def _parse_host_port(host_port: str) -> Tuple[str, int]:
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
        return True
    except ValueError:
        return False


def _tls_server_name_for_entry(entry: Dict[str, str | None]) -> str | None:
    name = entry.get("tls_server_name")
    if name:
        return name
    cert_path = entry.get("cert_path")
    if not cert_path:
        return None
    try:
        with open(cert_path, "rb") as f:
            return tls_server_name_from_pem(f.read())
    except OSError:
        return None


def _tls_channel_options(
    connect_host: str, tls_server_name: str | None
) -> Tuple[Tuple[str, str], ...]:
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
    return (("grpc.ssl_target_name_override", cert_name),)


def _secure_channel(
    url: str,
    creds: grpc.ChannelCredentials,
    entry: Dict[str, str | None] | None = None,
    tls_server_name: str | None = None,
) -> grpc.Channel:
    host, _ = _parse_host_port(url)
    if tls_server_name is None and entry is not None:
        tls_server_name = _tls_server_name_for_entry(entry)
    opts = _tls_channel_options(host, tls_server_name)
    if opts:
        return grpc.secure_channel(url, creds, options=opts)
    return grpc.secure_channel(url, creds)


def _build_creds_from_entry(entry: Dict[str, str | None], mode: str) -> grpc.ChannelCredentials:
    """Build gRPC credentials from a store entry (must have cert_path)."""
    ca_path = entry.get("cert_path")
    if not ca_path:
        msg = "Store entry missing cert_path"
        raise ValueError(msg)
    with open(ca_path, "rb") as f:
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
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
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
        rem = max(0.5, deadline - time.time())
        if rem <= 0:
            try:
                ch.close()
            except Exception as exc:
                _LOGGER.debug("Failed to close an expired insecure gRPC channel", exc_info=exc)
            return None
        stub = ConnectStub(ch)
        stub.Connect(ConnectRequest(name=probe), timeout=rem)
        with contextlib.suppress(grpc.RpcError):
            stub.Disconnect(ConnectRequest(name=probe), timeout=min(rem, 3.0))
    except grpc.RpcError:
        try:
            ch.close()
        except Exception as exc:
            _LOGGER.debug(
                "Failed to close an insecure gRPC channel after an RPC error", exc_info=exc
            )
        return None
    except Exception:
        try:
            ch.close()
        except Exception as exc:
            _LOGGER.debug(
                "Failed to close an insecure gRPC channel after an unexpected error", exc_info=exc
            )
        return None
    else:  # pylint: disable=no-else-return  # else only runs when Connect/Disconnect succeeded
        try:
            ch.close()
        except Exception as exc:
            _LOGGER.debug("Failed to close a successful insecure gRPC probe channel", exc_info=exc)
        return grpc.insecure_channel(url)


def _call_on_trust(
    cb: Callable[..., Any], host_port: str, cert_info: CertInfo, auth_required: bool
) -> Any:
    """Invoke on_trust_prompt with (host, cert_info) or (host, cert_info, auth_required)."""
    import inspect  # pylint: disable=import-outside-toplevel  # avoid cost on the hot path

    callback = cast(Callable[..., Any], cb)
    try:
        sig = inspect.signature(callback)
        if len(sig.parameters) >= 3:
            arguments: tuple[Any, ...] = (host_port, cert_info, auth_required)
            return callback(*arguments)
    except (TypeError, ValueError) as exc:
        _LOGGER.debug(
            "Could not inspect trust callback signature; using the two-argument form", exc_info=exc
        )
    arguments = (host_port, cert_info)
    return callback(*arguments)


def _resolve_credentials_from_store(
    host_port: str,
    store: TekHSICredentialStore,
    mode: str,
    on_trust_prompt: Callable[..., Union[bool, Tuple[bool, str | None]]] | None,
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
        result = _call_on_trust(on_trust_prompt, host_port, cert_info, False)
        if result is True:
            store.trust(host_port, cert_info, password=None)
            store.save()
        elif isinstance(result, (list, tuple)) and len(result) >= 1 and result[0]:
            password = result[1] if len(result) > 1 else None
            login = result[2] if len(result) > 2 else None
            if login == "":
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


def _auto_negotiate_channel(
    url: str,
    store: TekHSICredentialStore,
    on_trust_prompt: Callable[..., Any] | None,
    require_tls: bool,
    deadline: float,
    timeout: float,
) -> grpc.Channel:
    """Pick insecure or TLS channel when credentials=None (auto-negotiation)."""
    host, port = _parse_host_port(url)
    entry = store.get(url)

    if entry and entry.get("cert_path"):
        if not require_tls:
            plain = _try_plain_grpc_channel(url, deadline)
            if plain is not None:
                return plain
        tmo = max(0.5, min(8.0, deadline - time.time()))
        live = _fetch_server_cert(host, port, tmo)
        fp = entry.get("cert_fingerprint")
        if fp and live.cert_fingerprint != fp:
            raise TekCertificateMismatch(url, fp, live.cert_fingerprint)
        if entry.get("password"):
            return _secure_channel(url, _build_creds_from_entry(entry, "token"), entry=entry)
        return _secure_channel(url, _build_creds_from_entry(entry, "tls"), entry=entry)

    if not require_tls:
        plain = _try_plain_grpc_channel(url, deadline)
        if plain is not None:
            return plain
        rem = max(0.5, deadline - time.time())
        if rem <= 0:
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
    result = _call_on_trust(on_trust_prompt, url, cert_info, False)
    if result is True:
        store.trust(url, cert_info, password=None)
        store.save()
    elif isinstance(result, (list, tuple)) and len(result) >= 1 and result[0]:
        pwd = result[1] if len(result) > 1 else None
        login = result[2] if len(result) > 2 else None
        if not login:
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


class TekHSICredentials:
    """User-facing builder for TLS and TLS+Basic channel credentials."""

    def __init__(
        self,
        channel_credentials: grpc.ChannelCredentials | None = None,
        _use_store: bool = False,
        _store_mode: str = "tls",
        _tls_server_name: str | None = None,
    ) -> None:
        self._channel_credentials = channel_credentials
        self._use_store = _use_store
        self._store_mode = _store_mode
        self._tls_server_name = _tls_server_name

    @staticmethod
    def tls(ca_cert_path: str | None = None) -> TekHSICredentials:
        """Build credentials for Mode 2 (TLS only)."""
        if ca_cert_path is None:
            return TekHSICredentials(None, _use_store=True, _store_mode="tls")
        with open(ca_cert_path, "rb") as f:
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
        with open(ca_cert_path, "rb") as f:
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
