"""Unit tests for security helpers and exceptions."""

from __future__ import annotations

import base64
import inspect
import time

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import grpc
import pytest

from tekhsi import security
from tekhsi.credential_store import CertInfo, TekHSICredentialStore
from tekhsi.security import (  # pylint: disable=import-private-name
    _auto_negotiate_channel,
    _build_creds_from_entry,
    _call_on_trust,
    _fetch_server_cert,
    _is_ip_literal,
    _parse_host_port,
    _resolve_credentials_from_store,
    _secure_channel,
    _tls_channel_options,
    _tls_server_name_for_entry,
    _try_plain_grpc_channel,  # pylint: disable=import-private-name
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekHSICredentials,
    TekSecurityError,
    TekUnknownInstrument,
)


def test_parse_host_port_variants() -> None:
    """Host/port parsing handles common URL forms."""
    assert _parse_host_port("scope.local") == ("scope.local", 5000)
    assert _parse_host_port("192.168.1.1:5000") == ("192.168.1.1", 5000)
    assert _parse_host_port("[::1]:5000") == ("::1", 5000)
    assert _parse_host_port("[::1]") == ("::1", 5000)


def test_is_ip_literal() -> None:
    """IP literal detection."""
    assert _is_ip_literal("192.168.1.1") is True
    assert _is_ip_literal("[::1]") is True
    assert _is_ip_literal("scope.local") is False


def test_tls_channel_options_matching_name() -> None:
    """Matching host/cert name needs no override."""
    assert _tls_channel_options("scope.local", "scope.local") == ()


def test_tls_channel_options_ip_override() -> None:
    """IP literal with different cert name sets override."""
    opts = _tls_channel_options("192.168.1.1", "MSO58B-ABC123")
    assert opts == (("grpc.ssl_target_name_override", "MSO58B-ABC123"),)


def test_tls_channel_options_local_suffix() -> None:
    """Bonjour .local host sets override when cert name differs."""
    opts = _tls_channel_options("mso58b-abc123.local", "MSO58B-ABC123")
    assert opts == (("grpc.ssl_target_name_override", "MSO58B-ABC123"),)


def test_tek_unknown_instrument_attributes() -> None:
    """TekUnknownInstrument exposes host and cert_info."""
    info = CertInfo(cert_fingerprint="abc" * 10)
    err = TekUnknownInstrument("host:5000", info)
    assert err.host == "host:5000"
    assert err.cert_info.fingerprint == info.cert_fingerprint
    assert "Unknown instrument" in str(err)


def test_tek_certificate_mismatch_attributes() -> None:
    """TekCertificateMismatch exposes fingerprints."""
    err = TekCertificateMismatch("host:5000", "stored" * 4, "current" * 4)
    assert err.host == "host:5000"
    assert err.stored_fingerprint.startswith("stored")
    assert err.current_fingerprint.startswith("current")
    assert "Certificate mismatch" in str(err)


def test_tek_authentication_failed_message() -> None:
    """TekAuthenticationFailed prefixes host in message."""
    err = TekAuthenticationFailed("host:5000", "bad password")
    assert err.host == "host:5000"
    assert "host:5000: bad password" in str(err)


def test_security_error_is_base() -> None:
    """Subclasses are catchable as TekSecurityError."""
    assert isinstance(TekUnknownInstrument("h", CertInfo("")), TekSecurityError)


# ---------------------------------------------------------------------------
# _tls_server_name_for_entry
# ---------------------------------------------------------------------------


def test_tls_server_name_for_entry_direct() -> None:
    """Explicit tls_server_name in the entry is returned as-is."""
    assert _tls_server_name_for_entry({"tls_server_name": "scope.local"}) == "scope.local"


def test_tls_server_name_for_entry_no_cert_path() -> None:
    """No tls_server_name and no cert_path returns None."""
    assert _tls_server_name_for_entry({}) is None


def test_tls_server_name_for_entry_reads_cert_path(tmp_path: Path) -> None:
    """cert_path is read and passed to tls_server_name_from_pem."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"fake-pem-bytes")
    with patch.object(security, "tls_server_name_from_pem", return_value="derived.local") as fn:
        result = _tls_server_name_for_entry({"cert_path": str(cert_path)})
    assert result == "derived.local"
    fn.assert_called_once_with(b"fake-pem-bytes")


def test_tls_server_name_for_entry_oserror_returns_none() -> None:
    """Unreadable cert_path returns None instead of raising."""
    assert _tls_server_name_for_entry({"cert_path": "/no/such/file.pem"}) is None


# ---------------------------------------------------------------------------
# _tls_channel_options (remaining branches)
# ---------------------------------------------------------------------------


def test_tls_channel_options_no_tls_name() -> None:
    """No tls_server_name means no override."""
    assert _tls_channel_options("scope.local", None) == ()
    assert _tls_channel_options("scope.local", "") == ()


def test_tls_channel_options_fallback_mismatch() -> None:
    """Unrelated host/cert names (not IP, not .local) still get an override."""
    opts = _tls_channel_options("foo.example.com", "BAR-DEVICE")
    assert opts == (("grpc.ssl_target_name_override", "BAR-DEVICE"),)


# ---------------------------------------------------------------------------
# _secure_channel
# ---------------------------------------------------------------------------


def test_secure_channel_without_options() -> None:
    """Matching host/cert name creates a channel without options kwarg."""
    creds = grpc.local_channel_credentials()
    with patch.object(security.grpc, "secure_channel", wraps=security.grpc.secure_channel) as sc:
        ch = _secure_channel("scope.local:5000", creds, tls_server_name="scope.local")
        ch.close()
    sc.assert_called_once_with("scope.local:5000", creds)


def test_secure_channel_with_options_from_tls_server_name() -> None:
    """Mismatched cert name passes ssl_target_name_override options."""
    creds = grpc.local_channel_credentials()
    with patch.object(security.grpc, "secure_channel", wraps=security.grpc.secure_channel) as sc:
        ch = _secure_channel("192.168.1.1:5000", creds, tls_server_name="SCOPE-XYZ")
        ch.close()
    _, kwargs = sc.call_args
    assert kwargs["options"] == (("grpc.ssl_target_name_override", "SCOPE-XYZ"),)


def test_secure_channel_with_options_from_entry(tmp_path: Path) -> None:
    """entry-derived tls_server_name is used when tls_server_name arg is None."""
    creds = grpc.local_channel_credentials()
    entry = {"tls_server_name": "SCOPE-XYZ"}
    with patch.object(security.grpc, "secure_channel", wraps=security.grpc.secure_channel) as sc:
        ch = _secure_channel("192.168.1.1:5000", creds, entry=entry)
        ch.close()
    _, kwargs = sc.call_args
    assert kwargs["options"] == (("grpc.ssl_target_name_override", "SCOPE-XYZ"),)


# ---------------------------------------------------------------------------
# _build_creds_from_entry
# ---------------------------------------------------------------------------


def test_build_creds_from_entry_missing_cert_path_raises() -> None:
    """Entry without cert_path raises ValueError."""
    with pytest.raises(ValueError, match="missing cert_path"):
        _build_creds_from_entry({}, "tls")


def test_build_creds_from_entry_tls_mode(tmp_path: Path) -> None:
    """Tls mode returns plain ssl channel credentials."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"root-cert-bytes")
    creds = _build_creds_from_entry({"cert_path": str(cert_path)}, "tls")
    assert isinstance(creds, grpc.ChannelCredentials)


def test_build_creds_from_entry_token_mode_invokes_metadata_callback(tmp_path: Path) -> None:
    """Token mode builds composite creds whose metadata callback sends Basic auth."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"root-cert-bytes")
    entry = {"cert_path": str(cert_path), "login": "myuser", "password": "mypass"}

    captured: dict[str, Any] = {}

    def fake_metadata_call_credentials(cb: Any) -> MagicMock:
        captured["cb"] = cb
        return MagicMock()

    with patch.object(
        security.grpc, "metadata_call_credentials", side_effect=fake_metadata_call_credentials
    ):
        creds = _build_creds_from_entry(entry, "token")
    assert creds is not None

    recorder = MagicMock()
    captured["cb"](None, recorder)
    (metadata, error), _ = recorder.call_args
    assert error is None
    assert metadata[0][0] == "authorization"
    assert metadata[0][1].startswith("Basic ")


def test_build_creds_from_entry_token_mode_defaults_login(tmp_path: Path) -> None:
    """Token mode uses DEFAULT_MODE3_USERNAME when entry has no login/password."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"root-cert-bytes")
    entry = {"cert_path": str(cert_path)}

    captured: dict[str, Any] = {}

    def fake_metadata_call_credentials(cb: Any) -> MagicMock:
        captured["cb"] = cb
        return MagicMock()

    with patch.object(
        security.grpc, "metadata_call_credentials", side_effect=fake_metadata_call_credentials
    ):
        _build_creds_from_entry(entry, "token")

    recorder = MagicMock()
    captured["cb"](None, recorder)
    (metadata, _), _ = recorder.call_args
    decoded = base64.b64decode(metadata[0][1].split(" ", 1)[1]).decode()
    assert decoded == "Tektronix:"


# ---------------------------------------------------------------------------
# _fetch_server_cert
# ---------------------------------------------------------------------------


def _make_ssl_mock(der_bytes: bytes | None) -> MagicMock:
    ssock = MagicMock()
    ssock.getpeercert.return_value = der_bytes
    wrap_cm = MagicMock()
    wrap_cm.__enter__.return_value = ssock
    wrap_cm.__exit__.return_value = False
    ctx = MagicMock()
    ctx.wrap_socket.return_value = wrap_cm
    return ctx


def test_fetch_server_cert_success() -> None:
    """Successful TLS handshake returns CertInfo built from the DER cert."""
    sock_cm = MagicMock()
    sock_cm.__enter__.return_value = MagicMock()
    sock_cm.__exit__.return_value = False
    ctx = _make_ssl_mock(b"der-cert-bytes")
    with (
        patch.object(security.socket, "create_connection", return_value=sock_cm),
        patch.object(security.ssl, "SSLContext", return_value=ctx),
    ):
        info = _fetch_server_cert("scope.local", 5000, timeout=1.0)
    assert isinstance(info, CertInfo)
    assert info.cert_fingerprint


def test_fetch_server_cert_no_certificate_raises() -> None:
    """Missing peer certificate raises ConnectionError."""
    sock_cm = MagicMock()
    sock_cm.__enter__.return_value = MagicMock()
    sock_cm.__exit__.return_value = False
    ctx = _make_ssl_mock(None)
    with (
        patch.object(security.socket, "create_connection", return_value=sock_cm),
        patch.object(security.ssl, "SSLContext", return_value=ctx),
        pytest.raises(ConnectionError, match="did not present a certificate"),
    ):
        _fetch_server_cert("scope.local", 5000, timeout=1.0)


# ---------------------------------------------------------------------------
# _try_plain_grpc_channel
# ---------------------------------------------------------------------------


def test_try_plain_grpc_channel_success() -> None:
    """Successful Connect/Disconnect returns a fresh insecure channel."""
    stub = MagicMock()
    stub.Connect.return_value = None
    stub.Disconnect.return_value = None
    with (
        patch.object(security, "ConnectStub", return_value=stub),
        patch.object(security.grpc, "insecure_channel", return_value=MagicMock()) as ic,
    ):
        result = _try_plain_grpc_channel("scope.local:5000", time.time() + 5)
    assert result is not None
    assert ic.call_count == 2  # probe channel + returned channel


def test_try_plain_grpc_channel_disconnect_rpcerror_still_succeeds() -> None:
    """RpcError during Disconnect is swallowed; channel is still returned."""
    stub = MagicMock()
    stub.Connect.return_value = None
    stub.Disconnect.side_effect = grpc.RpcError("disconnect failed")
    with (
        patch.object(security, "ConnectStub", return_value=stub),
        patch.object(security.grpc, "insecure_channel", return_value=MagicMock()),
    ):
        result = _try_plain_grpc_channel("scope.local:5000", time.time() + 5)
    assert result is not None


def test_try_plain_grpc_channel_connect_rpcerror_returns_none() -> None:
    """RpcError during Connect returns None."""
    stub = MagicMock()
    stub.Connect.side_effect = grpc.RpcError("no plain grpc")
    with (
        patch.object(security, "ConnectStub", return_value=stub),
        patch.object(security.grpc, "insecure_channel", return_value=MagicMock()),
    ):
        result = _try_plain_grpc_channel("scope.local:5000", time.time() + 5)
    assert result is None


def test_try_plain_grpc_channel_connect_generic_exception_returns_none() -> None:
    """Unexpected exception during Connect returns None."""
    stub = MagicMock()
    stub.Connect.side_effect = RuntimeError("boom")
    with (
        patch.object(security, "ConnectStub", return_value=stub),
        patch.object(security.grpc, "insecure_channel", return_value=MagicMock()),
    ):
        result = _try_plain_grpc_channel("scope.local:5000", time.time() + 5)
    assert result is None


# ---------------------------------------------------------------------------
# _call_on_trust
# ---------------------------------------------------------------------------


def test_call_on_trust_three_arg_callback() -> None:
    """Callback accepting 3 params receives auth_required."""

    def cb(host: str, info: CertInfo, auth_required: bool) -> tuple:
        return (host, info, auth_required)

    result = _call_on_trust(cb, "host:5000", CertInfo("fp"), True)
    assert result == ("host:5000", CertInfo("fp"), True)


def test_call_on_trust_two_arg_callback() -> None:
    """Callback accepting 2 params does not receive auth_required."""

    def cb(host: str, info: CertInfo) -> tuple:
        return (host, info)

    result = _call_on_trust(cb, "host:5000", CertInfo("fp"), True)
    assert result == ("host:5000", CertInfo("fp"))


def test_call_on_trust_signature_inspection_failure_falls_back() -> None:
    """If signature introspection raises TypeError, fall back to 2-arg call."""

    def cb(host: str, info: CertInfo) -> tuple:
        return (host, info)

    with patch.object(inspect, "signature", side_effect=TypeError("no signature")):
        result = _call_on_trust(cb, "host:5000", CertInfo("fp"), True)
    assert result == ("host:5000", CertInfo("fp"))


# ---------------------------------------------------------------------------
# _resolve_credentials_from_store
# ---------------------------------------------------------------------------


def test_resolve_credentials_deadline_exceeded_raises() -> None:
    """Deadline already passed raises TekSecurityError immediately."""
    store = MagicMock(spec=TekHSICredentialStore)
    with pytest.raises(TekSecurityError, match="timed out"):
        _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() - 1)


def test_resolve_credentials_cert_match_returns_creds() -> None:
    """Matching fingerprint in store builds creds from the entry."""
    store = MagicMock(spec=TekHSICredentialStore)
    entry = {"cert_path": "/x.pem", "cert_fingerprint": "abc"}
    store.get.return_value = entry
    live = CertInfo(cert_fingerprint="abc")
    sentinel = object()
    with (
        patch.object(security, "_fetch_server_cert", return_value=live),
        patch.object(security, "_build_creds_from_entry", return_value=sentinel) as build,
    ):
        result = _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 10)
    assert result is sentinel
    build.assert_called_once_with(entry, "tls")


def test_resolve_credentials_cert_mismatch_raises() -> None:
    """Fingerprint mismatch raises TekCertificateMismatch."""
    store = MagicMock(spec=TekHSICredentialStore)
    entry = {"cert_path": "/x.pem", "cert_fingerprint": "abc"}
    store.get.return_value = entry
    live = CertInfo(cert_fingerprint="different")
    with (
        patch.object(security, "_fetch_server_cert", return_value=live),
        pytest.raises(TekCertificateMismatch),
    ):
        _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 10)


def test_resolve_credentials_no_entry_no_prompt_raises_unknown() -> None:
    """No stored entry and no on_trust_prompt raises TekUnknownInstrument."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="new")
    with patch.object(security, "_fetch_server_cert", return_value=cert_info):
        with pytest.raises(TekUnknownInstrument):
            _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 10)


def test_resolve_credentials_fetch_fails_raises_unknown() -> None:
    """Failure to fetch server cert raises TekUnknownInstrument."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    with patch.object(security, "_fetch_server_cert", side_effect=OSError("unreachable")):
        with pytest.raises(TekUnknownInstrument):
            _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 10)


def test_resolve_credentials_trust_prompt_true_trusts_and_builds() -> None:
    """on_trust_prompt returning True trusts, saves, then builds creds."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": "/x.pem"}]
    cert_info = CertInfo(cert_fingerprint="new")
    sentinel = object()
    with (
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
        patch.object(security, "_build_creds_from_entry", return_value=sentinel),
    ):
        result = _resolve_credentials_from_store(
            "host:5000", store, "tls", lambda h, i: True, time.time() + 10
        )
    assert result is sentinel
    store.trust.assert_called_once_with("host:5000", cert_info, password=None)
    store.save.assert_called_once()


def test_resolve_credentials_trust_prompt_tuple_with_password_and_login() -> None:
    """on_trust_prompt returning a tuple passes password/login through to trust()."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": "/x.pem"}]
    cert_info = CertInfo(cert_fingerprint="new")
    with (
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
        patch.object(security, "_build_creds_from_entry", return_value=object()),
    ):
        _resolve_credentials_from_store(
            "host:5000",
            store,
            "tls",
            lambda h, i: (True, "secret", "myuser"),
            time.time() + 10,
        )
    store.trust.assert_called_once_with("host:5000", cert_info, password="secret", login="myuser")


def test_resolve_credentials_trust_prompt_tuple_empty_login_becomes_none() -> None:
    """Empty-string login in the tuple result normalizes to None."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": "/x.pem"}]
    cert_info = CertInfo(cert_fingerprint="new")
    with (
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
        patch.object(security, "_build_creds_from_entry", return_value=object()),
    ):
        _resolve_credentials_from_store(
            "host:5000", store, "tls", lambda h, i: (True, "secret", ""), time.time() + 10
        )
    store.trust.assert_called_once_with("host:5000", cert_info, password="secret", login=None)


def test_resolve_credentials_trust_prompt_false_raises_unknown() -> None:
    """on_trust_prompt returning a falsy value raises TekUnknownInstrument."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="new")
    with patch.object(security, "_fetch_server_cert", return_value=cert_info):
        with pytest.raises(TekUnknownInstrument):
            _resolve_credentials_from_store(
                "host:5000", store, "tls", lambda h, i: False, time.time() + 10
            )


def test_resolve_credentials_trust_saved_but_entry_still_missing_cert_path() -> None:
    """After trust(), if the store still lacks cert_path, raise TekUnknownInstrument."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": None}]
    cert_info = CertInfo(cert_fingerprint="new")
    with patch.object(security, "_fetch_server_cert", return_value=cert_info):
        with pytest.raises(TekUnknownInstrument):
            _resolve_credentials_from_store(
                "host:5000", store, "tls", lambda h, i: True, time.time() + 10
            )


# ---------------------------------------------------------------------------
# _auto_negotiate_channel
# ---------------------------------------------------------------------------


def test_auto_negotiate_entry_with_cert_plain_succeeds() -> None:
    """Stored entry + plain gRPC success returns the plain channel directly."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = {"cert_path": "/x.pem"}
    sentinel = MagicMock()
    with patch.object(security, "_try_plain_grpc_channel", return_value=sentinel):
        result = _auto_negotiate_channel(
            "url:5000", store, None, require_tls=False, deadline=time.time() + 10, timeout=10
        )
    assert result is sentinel


def test_auto_negotiate_entry_with_cert_mismatch_raises() -> None:
    """Stored fingerprint mismatch raises TekCertificateMismatch."""
    store = MagicMock(spec=TekHSICredentialStore)
    entry = {"cert_path": "/x.pem", "cert_fingerprint": "abc"}
    store.get.return_value = entry
    live = CertInfo(cert_fingerprint="different")
    with patch.object(security, "_fetch_server_cert", return_value=live):
        with pytest.raises(TekCertificateMismatch):
            _auto_negotiate_channel(
                "url:5000", store, None, require_tls=True, deadline=time.time() + 10, timeout=10
            )


def test_auto_negotiate_entry_with_cert_token_mode() -> None:
    """Stored entry with a password uses token-mode creds."""
    store = MagicMock(spec=TekHSICredentialStore)
    entry = {"cert_path": "/x.pem", "cert_fingerprint": "abc", "password": "pw"}
    store.get.return_value = entry
    live = CertInfo(cert_fingerprint="abc")
    sentinel = MagicMock()
    with (
        patch.object(security, "_fetch_server_cert", return_value=live),
        patch.object(security, "_build_creds_from_entry", return_value=object()) as build,
        patch.object(security, "_secure_channel", return_value=sentinel),
    ):
        result = _auto_negotiate_channel(
            "url:5000", store, None, require_tls=True, deadline=time.time() + 10, timeout=10
        )
    assert result is sentinel
    build.assert_called_once_with(entry, "token")


def test_auto_negotiate_entry_with_cert_tls_mode() -> None:
    """Stored entry without a password uses tls-mode creds."""
    store = MagicMock(spec=TekHSICredentialStore)
    entry = {"cert_path": "/x.pem", "cert_fingerprint": "abc"}
    store.get.return_value = entry
    live = CertInfo(cert_fingerprint="abc")
    sentinel = MagicMock()
    with (
        patch.object(security, "_fetch_server_cert", return_value=live),
        patch.object(security, "_build_creds_from_entry", return_value=object()) as build,
        patch.object(security, "_secure_channel", return_value=sentinel),
    ):
        result = _auto_negotiate_channel(
            "url:5000", store, None, require_tls=True, deadline=time.time() + 10, timeout=10
        )
    assert result is sentinel
    build.assert_called_once_with(entry, "tls")


def test_auto_negotiate_no_entry_plain_succeeds() -> None:
    """No stored entry, plain gRPC succeeds, returns plain channel."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    sentinel = MagicMock()
    with patch.object(security, "_try_plain_grpc_channel", return_value=sentinel):
        result = _auto_negotiate_channel(
            "url:5000", store, None, require_tls=False, deadline=time.time() + 10, timeout=10
        )
    assert result is sentinel


def test_auto_negotiate_no_entry_plain_fails_timeout_raises() -> None:
    """No entry, plain fails, deadline already exceeded raises TekSecurityError."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    with patch.object(security, "_try_plain_grpc_channel", return_value=None):
        with pytest.raises(TekSecurityError, match="timed out"):
            _auto_negotiate_channel(
                "url:5000", store, None, require_tls=False, deadline=time.time() - 1, timeout=10
            )


def test_auto_negotiate_no_entry_require_tls_no_prompt_raises() -> None:
    """require_tls with no on_trust_prompt raises TekSecurityError before any network I/O."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    with pytest.raises(TekSecurityError, match="TLS required"):
        _auto_negotiate_channel(
            "url:5000", store, None, require_tls=True, deadline=time.time() + 10, timeout=10
        )


def test_auto_negotiate_no_entry_deadline_exceeded_before_fetch_raises() -> None:
    """Deadline exceeded after unsuccessful plain attempt (require_tls False branch)."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    with patch.object(security, "_try_plain_grpc_channel", return_value=None):
        with pytest.raises(TekSecurityError, match="timed out"):
            _auto_negotiate_channel(
                "url:5000",
                store,
                lambda h, i: True,
                require_tls=False,
                deadline=time.time() - 1,
                timeout=10,
            )


def test_auto_negotiate_no_entry_no_prompt_after_fetch_raises_unknown() -> None:
    """require_tls False, plain fails, cert fetched, but no on_trust_prompt raises Unknown."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="new")
    with (
        patch.object(security, "_try_plain_grpc_channel", return_value=None),
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
    ):
        with pytest.raises(TekUnknownInstrument):
            _auto_negotiate_channel(
                "url:5000", store, None, require_tls=False, deadline=time.time() + 10, timeout=10
            )


def test_auto_negotiate_prompt_true_trusts_and_returns_channel() -> None:
    """on_trust_prompt True trusts, saves, and builds a channel from new entry."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": "/x.pem"}]
    cert_info = CertInfo(cert_fingerprint="new")
    sentinel = MagicMock()
    with (
        patch.object(security, "_try_plain_grpc_channel", return_value=None),
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
        patch.object(security, "_build_creds_from_entry", return_value=object()),
        patch.object(security, "_secure_channel", return_value=sentinel),
    ):
        result = _auto_negotiate_channel(
            "url:5000",
            store,
            lambda h, i: True,
            require_tls=False,
            deadline=time.time() + 10,
            timeout=10,
        )
    assert result is sentinel
    store.trust.assert_called_once_with("url:5000", cert_info, password=None)
    store.save.assert_called_once()


def test_auto_negotiate_prompt_tuple_with_password_and_login() -> None:
    """on_trust_prompt tuple result passes password/login and uses token mode."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": "/x.pem", "password": "pw"}]
    cert_info = CertInfo(cert_fingerprint="new")
    sentinel = MagicMock()
    with (
        patch.object(security, "_try_plain_grpc_channel", return_value=None),
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
        patch.object(security, "_build_creds_from_entry", return_value=object()) as build,
        patch.object(security, "_secure_channel", return_value=sentinel),
    ):
        result = _auto_negotiate_channel(
            "url:5000",
            store,
            lambda h, i: (True, "pw", ""),
            require_tls=False,
            deadline=time.time() + 10,
            timeout=10,
        )
    assert result is sentinel
    store.trust.assert_called_once_with("url:5000", cert_info, password="pw", login=None)
    build.assert_called_once_with({"cert_path": "/x.pem", "password": "pw"}, "token")


def test_auto_negotiate_prompt_false_raises_unknown() -> None:
    """on_trust_prompt returning falsy raises TekUnknownInstrument."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="new")
    with (
        patch.object(security, "_try_plain_grpc_channel", return_value=None),
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
    ):
        with pytest.raises(TekUnknownInstrument):
            _auto_negotiate_channel(
                "url:5000",
                store,
                lambda h, i: False,
                require_tls=False,
                deadline=time.time() + 10,
                timeout=10,
            )


def test_auto_negotiate_trust_saved_but_missing_cert_path_raises() -> None:
    """After trusting, missing cert_path in the store raises TekUnknownInstrument."""
    store = MagicMock(spec=TekHSICredentialStore)
    store.get.side_effect = [None, {"cert_path": None}]
    cert_info = CertInfo(cert_fingerprint="new")
    with (
        patch.object(security, "_try_plain_grpc_channel", return_value=None),
        patch.object(security, "_fetch_server_cert", return_value=cert_info),
    ):
        with pytest.raises(TekUnknownInstrument):
            _auto_negotiate_channel(
                "url:5000",
                store,
                lambda h, i: True,
                require_tls=False,
                deadline=time.time() + 10,
                timeout=10,
            )


# ---------------------------------------------------------------------------
# TekHSICredentials
# ---------------------------------------------------------------------------


def test_tekhsi_credentials_tls_use_store_when_no_path() -> None:
    """tls() with no path defers to the credential store."""
    creds = TekHSICredentials.tls()
    assert creds._use_store is True
    assert creds._store_mode == "tls"


def test_tekhsi_credentials_tls_with_cert_path(tmp_path: Path) -> None:
    """tls(path) reads the cert and builds channel credentials directly."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"root-cert-bytes")
    creds = TekHSICredentials.tls(str(cert_path))
    assert creds._use_store is False
    assert isinstance(creds._grpc_credentials(), grpc.ChannelCredentials)


def test_tekhsi_credentials_token_use_store_when_no_args() -> None:
    """token() with no args defers to the credential store."""
    creds = TekHSICredentials.token()
    assert creds._use_store is True
    assert creds._store_mode == "token"


@pytest.mark.parametrize(
    ("cert_path", "token"),
    [("some/path.pem", None), (None, "sometoken")],
)
def test_tekhsi_credentials_token_partial_args_raises(
    cert_path: str | None, token: str | None
) -> None:
    """token() requires both ca_cert_path and token, or neither."""
    with pytest.raises(ValueError, match="requires both"):
        TekHSICredentials.token(ca_cert_path=cert_path, token=token)


def test_tekhsi_credentials_token_with_cert_and_token(tmp_path: Path) -> None:
    """token(path, token) builds composite creds with a Basic-auth callback."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"root-cert-bytes")

    captured: dict[str, Any] = {}

    def fake_metadata_call_credentials(cb: Any) -> MagicMock:
        captured["cb"] = cb
        return MagicMock()

    with patch.object(
        security.grpc, "metadata_call_credentials", side_effect=fake_metadata_call_credentials
    ):
        creds = TekHSICredentials.token(
            ca_cert_path=str(cert_path), token="mytoken", username="myuser"
        )
    assert creds._grpc_credentials() is not None

    recorder = MagicMock()
    captured["cb"](None, recorder)
    (metadata, error), _ = recorder.call_args
    assert error is None
    assert metadata[0][0] == "authorization"


def test_tekhsi_credentials_token_default_username(tmp_path: Path) -> None:
    """token() without username uses DEFAULT_MODE3_USERNAME."""
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(b"root-cert-bytes")

    captured: dict[str, Any] = {}

    def fake_metadata_call_credentials(cb: Any) -> MagicMock:
        captured["cb"] = cb
        return MagicMock()

    with patch.object(
        security.grpc, "metadata_call_credentials", side_effect=fake_metadata_call_credentials
    ):
        TekHSICredentials.token(ca_cert_path=str(cert_path), token="mytoken")

    recorder = MagicMock()
    captured["cb"](None, recorder)
    (metadata, _), _ = recorder.call_args

    decoded = base64.b64decode(metadata[0][1].split(" ", 1)[1]).decode()
    assert decoded == "Tektronix:mytoken"


def test_grpc_credentials_returns_stored_value() -> None:
    """_grpc_credentials returns the stored channel credentials."""
    creds = grpc.local_channel_credentials()
    wrapper = TekHSICredentials(creds)
    assert wrapper._grpc_credentials() is creds


def test_grpc_credentials_none_raises() -> None:
    """_grpc_credentials raises ValueError when store-based creds aren't resolved."""
    wrapper = TekHSICredentials(None)
    with pytest.raises(ValueError, match="must be resolved"):
        wrapper._grpc_credentials()
