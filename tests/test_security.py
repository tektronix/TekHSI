"""Unit tests for security helpers and exceptions."""

from __future__ import annotations

import time

from pathlib import Path
from typing import Any, cast
from unittest.mock import ANY, MagicMock, patch

import grpc
import pytest as _pytest  # pyright: ignore[reportMissingImports]

pytest: Any = _pytest

from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import CertInfo
from tekhsi.security import (
    _auto_negotiate_channel,  # pyright: ignore[reportPrivateUsage]
    _basic_auth_call_credentials,  # pyright: ignore[reportPrivateUsage]
    _build_creds_from_entry,  # pyright: ignore[reportPrivateUsage]
    _call_on_trust,  # pyright: ignore[reportPrivateUsage]
    _fetch_server_cert,  # pyright: ignore[reportPrivateUsage]
    _is_ip_literal,  # pyright: ignore[reportPrivateUsage]
    _parse_host_port,  # pyright: ignore[reportPrivateUsage]
    _parse_trust_response,  # pyright: ignore[reportPrivateUsage]
    _resolve_credentials_from_store,  # pyright: ignore[reportPrivateUsage]
    _secure_channel,  # pyright: ignore[reportPrivateUsage]
    _tls_channel_options,  # pyright: ignore[reportPrivateUsage]
    _tls_server_name_for_entry,  # pyright: ignore[reportPrivateUsage]
    _try_plain_grpc_channel,  # pyright: ignore[reportPrivateUsage]
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


# --------------------------------------------------------------------------------------------
# _parse_trust_response
# --------------------------------------------------------------------------------------------
def test_parse_trust_response_true() -> None:
    """A bare True acceptance has no password or login."""
    assert _parse_trust_response(True) == (True, None, None)


def test_parse_trust_response_tuple_password_login() -> None:
    """A 3-tuple carries acceptance, password, and login."""
    assert _parse_trust_response((True, "pw", "user")) == (True, "pw", "user")


def test_parse_trust_response_list_password_only() -> None:
    """A 2-list carries acceptance and password only."""
    assert _parse_trust_response([True, "pw"]) == (True, "pw", None)


def test_parse_trust_response_empty_login_becomes_none() -> None:
    """An empty-string login normalizes to None."""
    assert _parse_trust_response((True, "pw", "")) == (True, "pw", None)


def test_parse_trust_response_non_string_password_ignored() -> None:
    """A non-string password entry is treated as absent."""
    assert _parse_trust_response((True, 123)) == (True, None, None)


def test_parse_trust_response_false_first_element() -> None:
    """A falsy first element rejects the trust prompt."""
    assert _parse_trust_response((False, "pw")) == (False, None, None)


def test_parse_trust_response_invalid_type_returns_false() -> None:
    """Non-tuple/list/True responses are treated as rejection."""
    assert _parse_trust_response(42) == (False, None, None)
    assert _parse_trust_response(None) == (False, None, None)


def test_parse_trust_response_empty_sequences_return_false() -> None:
    """Empty callback sequences are treated as rejected trust decisions."""
    assert _parse_trust_response(()) == (False, None, None)
    assert _parse_trust_response([]) == (False, None, None)
    assert _parse_trust_response((0, "pw")) == (False, None, None)
    assert _parse_trust_response(("", "pw")) == (False, None, None)


# --------------------------------------------------------------------------------------------
# _basic_auth_call_credentials
# --------------------------------------------------------------------------------------------
def test_basic_auth_call_credentials_invokes_metadata_callback() -> None:
    """The metadata callback injects a Basic Authorization header."""
    with patch("tekhsi.security.grpc.metadata_call_credentials") as mock_metadata:
        _basic_auth_call_credentials("user", "secret")

    mock_metadata.assert_called_once()
    meta_cb = mock_metadata.call_args[0][0]
    captured = {}

    def cb(metadata: object, error: object) -> None:
        captured["metadata"] = metadata
        captured["error"] = error

    meta_cb(None, cb)
    assert captured["metadata"][0][0] == "authorization"
    auth_value = cast("str", captured["metadata"][0][1])
    assert auth_value.startswith("Basic ")
    assert captured["error"] is None


def test_call_on_trust_supports_two_argument_callback() -> None:
    """Callbacks with the legacy two-argument signature remain supported."""
    callback = MagicMock(return_value=True)
    cert_info = CertInfo(cert_fingerprint="abc")

    assert _call_on_trust(callback, "scope:5000", cert_info, False) is True
    callback.assert_called_once_with("scope:5000", cert_info)


def test_call_on_trust_falls_back_when_signature_inspection_raises() -> None:
    """A callback whose signature cannot be inspected uses the legacy call shape."""
    callback = MagicMock(return_value=True)
    cert_info = CertInfo(cert_fingerprint="abc")
    with patch("inspect.signature", side_effect=TypeError):
        assert _call_on_trust(callback, "scope:5000", cert_info, False) is True
    callback.assert_called_once_with("scope:5000", cert_info)


# --------------------------------------------------------------------------------------------
# _tls_server_name_for_entry
# --------------------------------------------------------------------------------------------
def test_tls_server_name_for_entry_prefers_explicit_name() -> None:
    """An explicit tls_server_name short-circuits cert reading."""
    entry = {"tls_server_name": "scope.local", "cert_path": None}
    assert _tls_server_name_for_entry(entry) == "scope.local"


def test_tls_server_name_for_entry_no_cert_path_returns_none() -> None:
    """No tls_server_name and no cert_path yields None."""
    entry: dict[str, str | None] = {"tls_server_name": None, "cert_path": None}
    assert _tls_server_name_for_entry(entry) is None


def test_tls_server_name_for_entry_reads_cert_path(tmp_path: Path) -> None:
    """A cert_path is read and passed through tls_server_name_from_pem."""
    pem_path = tmp_path / "cert.pem"
    pem_path.write_bytes(b"fake")
    entry: dict[str, str | None] = {"tls_server_name": None, "cert_path": str(pem_path)}
    with patch("tekhsi.security.tls_server_name_from_pem", return_value="derived.local") as mock_fn:
        assert _tls_server_name_for_entry(entry) == "derived.local"
    mock_fn.assert_called_once()


def test_tls_server_name_for_entry_oserror_returns_none() -> None:
    """An unreadable cert_path returns None instead of raising."""
    entry = {"tls_server_name": None, "cert_path": "/nonexistent/path.pem"}
    assert _tls_server_name_for_entry(entry) is None


# --------------------------------------------------------------------------------------------
# _secure_channel
# --------------------------------------------------------------------------------------------
def test_secure_channel_no_options() -> None:
    """A matching tls_server_name yields no channel options."""
    creds = MagicMock()
    with patch("tekhsi.security.grpc.secure_channel") as mock_secure:
        _secure_channel("scope.local:5000", creds, tls_server_name="scope.local")
    mock_secure.assert_called_once_with("scope.local:5000", creds)


def test_secure_channel_with_options_from_entry() -> None:
    """An IP host with a differing cert name gets an override option."""
    creds = MagicMock()
    entry: dict[str, str | None] = {"tls_server_name": None, "cert_path": None}
    with patch("tekhsi.security.grpc.secure_channel") as mock_secure:
        _secure_channel("192.168.1.1:5000", creds, entry=entry, tls_server_name="MSO58B")
    mock_secure.assert_called_once_with(
        "192.168.1.1:5000", creds, options=(("grpc.ssl_target_name_override", "MSO58B"),)
    )


# --------------------------------------------------------------------------------------------
# _build_creds_from_entry
# --------------------------------------------------------------------------------------------
def test_build_creds_from_entry_missing_cert_path_raises() -> None:
    """A store entry without cert_path cannot build credentials."""
    with pytest.raises(ValueError, match="missing cert_path"):
        _build_creds_from_entry({}, "tls")


def test_build_creds_from_entry_tls_mode(tmp_path: Path) -> None:
    """TLS mode builds plain SSL channel credentials from the CA file."""
    cert_path = tmp_path / "ca.pem"
    cert_path.write_bytes(b"cert-bytes")
    entry: dict[str, str | None] = {"cert_path": str(cert_path)}
    with patch(
        "tekhsi.security.grpc.ssl_channel_credentials", return_value="ssl-creds"
    ) as mock_ssl:
        result = _build_creds_from_entry(entry, "tls")
    assert result == "ssl-creds"
    mock_ssl.assert_called_once_with(root_certificates=b"cert-bytes")


def test_build_creds_from_entry_token_mode(tmp_path: Path) -> None:
    """Token mode composes SSL creds with Basic-auth call credentials."""
    cert_path = tmp_path / "ca.pem"
    cert_path.write_bytes(b"cert-bytes")
    entry: dict[str, str | None] = {
        "cert_path": str(cert_path),
        "password": "secret",
        "login": "myuser",
    }
    with (
        patch("tekhsi.security.grpc.ssl_channel_credentials", return_value="ssl-creds"),
        patch(
            "tekhsi.security.grpc.composite_channel_credentials", return_value="composite"
        ) as mock_composite,
        patch(
            "tekhsi.security._basic_auth_call_credentials", return_value="auth-creds"
        ) as mock_auth,
    ):
        result = _build_creds_from_entry(entry, "token")
    assert result == "composite"
    mock_auth.assert_called_once_with("myuser", "secret")
    mock_composite.assert_called_once_with("ssl-creds", "auth-creds")


def test_try_plain_grpc_channel_returns_none_on_rpc_error() -> None:
    """A failed plaintext probe closes its temporary channel and returns None."""
    channel = MagicMock()
    with (
        patch("tekhsi.security.grpc.insecure_channel", return_value=channel),
        patch("tekhsi.security.ConnectStub") as stub_cls,
    ):
        stub_cls.return_value.Connect.side_effect = grpc.RpcError()
        result = _try_plain_grpc_channel("scope:5000", time.time() + 5.0)
    assert result is None
    channel.close.assert_called_once()


def test_try_plain_grpc_channel_returns_new_channel_on_success() -> None:
    """A successful plaintext probe closes the probe channel and creates a fresh one."""
    probe_channel = MagicMock()
    result_channel = MagicMock()
    with (
        patch(
            "tekhsi.security.grpc.insecure_channel",
            side_effect=[probe_channel, result_channel],
        ),
        patch("tekhsi.security.ConnectStub") as stub_cls,
    ):
        result = _try_plain_grpc_channel("scope:5000", time.time() + 5.0)
    assert result is result_channel
    stub_cls.return_value.Connect.assert_called_once()
    stub_cls.return_value.Disconnect.assert_called_once()
    probe_channel.close.assert_called_once()


def test_resolve_credentials_from_store_times_out() -> None:
    """Credential resolution rejects an already-expired negotiation deadline."""
    store = MagicMock()
    with pytest.raises(TekSecurityError, match="timed out"):
        _resolve_credentials_from_store("scope:5000", store, "tls", None, 0.0)
    store.get.assert_not_called()


def test_resolve_credentials_from_store_unknown_without_prompt() -> None:
    """An untrusted certificate without a callback raises the TOFU exception."""
    store = MagicMock()
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="fingerprint")
    with patch("tekhsi.security._fetch_server_cert", return_value=cert_info):
        with pytest.raises(TekUnknownInstrument) as exc_info:
            _resolve_credentials_from_store("scope:5000", store, "tls", None, time.time() + 5.0)
    assert exc_info.value.cert_info is cert_info


def test_resolve_credentials_from_store_prompt_declined() -> None:
    """A declined trust prompt does not add an instrument to the store."""
    store = MagicMock()
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="fingerprint")
    with patch("tekhsi.security._fetch_server_cert", return_value=cert_info):
        with pytest.raises(TekUnknownInstrument):
            _resolve_credentials_from_store(
                "scope:5000", store, "tls", lambda *_args: False, time.time() + 5.0
            )
    store.trust.assert_not_called()


def test_credentials_store_and_argument_validation() -> None:
    """Store-backed credential builders and invalid token arguments behave predictably."""
    assert TekHSICredentials.tls()._use_store is True  # pyright: ignore[reportPrivateUsage]
    assert TekHSICredentials.token()._use_store is True  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError, match="requires both"):
        TekHSICredentials.token(token="secret")
    with pytest.raises(ValueError, match="Store-based"):
        TekHSICredentials()._grpc_credentials()  # pyright: ignore[reportPrivateUsage]


def test_build_creds_from_entry_token_mode_defaults(tmp_path: Path) -> None:
    """Token mode falls back to the default username and empty password."""
    cert_path = tmp_path / "ca.pem"
    cert_path.write_bytes(b"cert-bytes")
    entry: dict[str, str | None] = {"cert_path": str(cert_path)}
    with (
        patch("tekhsi.security.grpc.ssl_channel_credentials", return_value="ssl-creds"),
        patch("tekhsi.security.grpc.composite_channel_credentials", return_value="composite"),
        patch(
            "tekhsi.security._basic_auth_call_credentials", return_value="auth-creds"
        ) as mock_auth,
    ):
        _build_creds_from_entry(entry, "token")
    mock_auth.assert_called_once_with(DEFAULT_MODE3_USERNAME, "")


# --------------------------------------------------------------------------------------------
# _fetch_server_cert
# --------------------------------------------------------------------------------------------
def _mock_ssl_socket(getpeercert_return: object) -> tuple[MagicMock, MagicMock]:
    """Build mocked socket/ssl-context objects wired for the `with` statements."""
    mock_ssock = MagicMock()
    mock_ssock.getpeercert.return_value = getpeercert_return
    mock_ssock.__enter__.return_value = mock_ssock
    mock_ssock.__exit__.return_value = False
    mock_context = MagicMock()
    mock_context.wrap_socket.return_value = mock_ssock
    mock_sock = MagicMock()
    mock_sock.__enter__.return_value = mock_sock
    mock_sock.__exit__.return_value = False
    return mock_sock, mock_context


def test_fetch_server_cert_success() -> None:
    """A successful TLS probe returns CertInfo built from the PEM bytes."""
    mock_sock, mock_context = _mock_ssl_socket(b"der-bytes")
    with (
        patch("tekhsi.security.socket.create_connection", return_value=mock_sock),
        patch("tekhsi.security.ssl.SSLContext", return_value=mock_context),
        patch(
            "tekhsi.security.ssl.DER_cert_to_PEM_cert",
            return_value="-----BEGIN CERTIFICATE-----\n",
        ),
    ):
        result = _fetch_server_cert("host", 5000, timeout=1.0)
    assert result.cert_pem == b"-----BEGIN CERTIFICATE-----\n"


def test_fetch_server_cert_no_cert_raises() -> None:
    """A peer that presents no certificate raises ConnectionError."""
    mock_sock, mock_context = _mock_ssl_socket(None)
    with (
        patch("tekhsi.security.socket.create_connection", return_value=mock_sock),
        patch("tekhsi.security.ssl.SSLContext", return_value=mock_context),
        pytest.raises(ConnectionError, match="did not present a certificate"),
    ):
        _fetch_server_cert("host", 5000)


# --------------------------------------------------------------------------------------------
# _try_plain_grpc_channel
# --------------------------------------------------------------------------------------------
def test_try_plain_grpc_channel_success() -> None:
    """A server that accepts plain Connect/Disconnect yields a fresh insecure channel."""
    mock_channel = MagicMock()
    mock_stub = MagicMock()
    with (
        patch("tekhsi.security.grpc.insecure_channel", return_value=mock_channel) as mock_insecure,
        patch("tekhsi.security.ConnectStub", return_value=mock_stub),
    ):
        result = _try_plain_grpc_channel("host:5000", deadline=time.time() + 5)
    assert result is mock_channel
    mock_stub.Connect.assert_called_once()
    assert mock_insecure.call_count == 2


def test_try_plain_grpc_channel_connect_rpc_error_returns_none() -> None:
    """An RpcError on Connect means the server is not plain gRPC."""
    mock_channel = MagicMock()
    mock_stub = MagicMock()
    mock_stub.Connect.side_effect = grpc.RpcError("boom")
    with (
        patch("tekhsi.security.grpc.insecure_channel", return_value=mock_channel),
        patch("tekhsi.security.ConnectStub", return_value=mock_stub),
    ):
        result = _try_plain_grpc_channel("host:5000", deadline=time.time() + 5)
    assert result is None


def test_try_plain_grpc_channel_disconnect_rpc_error_ignored() -> None:
    """An RpcError on the courtesy Disconnect call is swallowed."""
    mock_channel = MagicMock()
    mock_stub = MagicMock()
    mock_stub.Disconnect.side_effect = grpc.RpcError("boom")
    with (
        patch("tekhsi.security.grpc.insecure_channel", return_value=mock_channel),
        patch("tekhsi.security.ConnectStub", return_value=mock_stub),
    ):
        result = _try_plain_grpc_channel("host:5000", deadline=time.time() + 5)
    assert result is mock_channel


def test_try_plain_grpc_channel_generic_exception_returns_none() -> None:
    """A non-RpcError exception during the probe is also treated as failure."""
    mock_channel = MagicMock()
    mock_stub = MagicMock()
    mock_stub.Connect.side_effect = RuntimeError("boom")
    with (
        patch("tekhsi.security.grpc.insecure_channel", return_value=mock_channel),
        patch("tekhsi.security.ConnectStub", return_value=mock_stub),
    ):
        result = _try_plain_grpc_channel("host:5000", deadline=time.time() + 5)
    assert result is None


# --------------------------------------------------------------------------------------------
# _call_on_trust
# --------------------------------------------------------------------------------------------
def test_call_on_trust_two_param_callback() -> None:
    """A 2-parameter callback is invoked without auth_required."""

    def cb(_host: str, _cert_info: CertInfo) -> str:
        return "two-param"

    result = _call_on_trust(cb, "host:5000", CertInfo(cert_fingerprint="fp"), True)
    assert result == "two-param"


def test_call_on_trust_three_param_callback() -> None:
    """A 3-parameter callback receives auth_required."""

    def cb(_host: str, _cert_info: CertInfo, auth_required: bool) -> bool:
        return auth_required

    result = _call_on_trust(cb, "host:5000", CertInfo(cert_fingerprint="fp"), True)
    assert result is True


def test_call_on_trust_signature_typeerror_falls_back() -> None:
    """When signature inspection fails, fall back to the 2-argument call."""
    cb = MagicMock(return_value="ok")
    with patch("inspect.signature", side_effect=TypeError("no sig")):
        result = _call_on_trust(cb, "host:5000", CertInfo(cert_fingerprint="fp"), True)
    assert result == "ok"
    cb.assert_called_once_with("host:5000", ANY)


# --------------------------------------------------------------------------------------------
# _resolve_credentials_from_store
# --------------------------------------------------------------------------------------------
def test_resolve_credentials_deadline_exceeded() -> None:
    """An expired deadline raises TekSecurityError before any I/O."""
    store = MagicMock()
    with pytest.raises(TekSecurityError, match="timed out"):
        _resolve_credentials_from_store("host:5000", store, "tls", None, deadline=0.0)


def test_resolve_credentials_from_store_entry_matching_fingerprint() -> None:
    """A stored entry with a matching live fingerprint builds credentials."""
    store = MagicMock()
    store.get.return_value = {"cert_path": "/fake/path.pem", "cert_fingerprint": "abc"}
    live_cert = CertInfo(cert_fingerprint="abc")
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=live_cert),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds") as mock_build,
    ):
        result = _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 5)
    assert result == "creds"
    mock_build.assert_called_once()


def test_resolve_credentials_from_store_fingerprint_mismatch() -> None:
    """A stored entry with a mismatched live fingerprint raises TekCertificateMismatch."""
    store = MagicMock()
    store.get.return_value = {"cert_path": "/fake/path.pem", "cert_fingerprint": "abc"}
    live_cert = CertInfo(cert_fingerprint="different")
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=live_cert),
        pytest.raises(TekCertificateMismatch),
    ):
        _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 5)


def test_resolve_credentials_from_store_no_entry_no_prompt_raises_unknown() -> None:
    """No stored entry and no trust prompt raises TekUnknownInstrument."""
    store = MagicMock()
    store.get.return_value = None
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=CertInfo(cert_fingerprint="fp")),
        pytest.raises(TekUnknownInstrument),
    ):
        _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 5)


def test_resolve_credentials_from_store_fetch_fails_raises_unknown() -> None:
    """A failed cert fetch raises TekUnknownInstrument (chained from the underlying error)."""
    store = MagicMock()
    store.get.return_value = None
    with (
        patch("tekhsi.security._fetch_server_cert", side_effect=OSError("no route")),
        pytest.raises(TekUnknownInstrument),
    ):
        _resolve_credentials_from_store("host:5000", store, "tls", None, time.time() + 5)


def test_resolve_credentials_from_store_prompt_accepted_no_password() -> None:
    """Accepting the trust prompt without a password stores trust and builds creds."""
    store = MagicMock()
    store.get.side_effect = [None, {"cert_path": "/fake/path.pem"}]
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=True)
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds"),
    ):
        result = _resolve_credentials_from_store("host:5000", store, "tls", prompt, time.time() + 5)
    assert result == "creds"
    store.trust.assert_called_once_with("host:5000", cert_info, password=None)
    store.save.assert_called_once()


def test_resolve_credentials_from_store_prompt_accepted_with_password() -> None:
    """Accepting the trust prompt with a password/login passes both through to trust()."""
    store = MagicMock()
    store.get.side_effect = [None, {"cert_path": "/fake/path.pem"}]
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=(True, "secret", "user"))
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds"),
    ):
        result = _resolve_credentials_from_store(
            "host:5000", store, "token", prompt, time.time() + 5
        )
    assert result == "creds"
    store.trust.assert_called_once_with("host:5000", cert_info, password="secret", login="user")


def test_resolve_credentials_from_store_prompt_rejected_raises_unknown() -> None:
    """Rejecting the trust prompt raises TekUnknownInstrument."""
    store = MagicMock()
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=False)
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        pytest.raises(TekUnknownInstrument),
    ):
        _resolve_credentials_from_store("host:5000", store, "tls", prompt, time.time() + 5)


def test_resolve_credentials_from_store_trust_saved_but_entry_still_missing() -> None:
    """If the store still lacks a usable entry after trust()+save(), raise TekUnknownInstrument."""
    store = MagicMock()
    store.get.side_effect = [None, None]
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=True)
    with (
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        pytest.raises(TekUnknownInstrument),
    ):
        _resolve_credentials_from_store("host:5000", store, "tls", prompt, time.time() + 5)


# --------------------------------------------------------------------------------------------
# _auto_negotiate_channel
# --------------------------------------------------------------------------------------------
def test_auto_negotiate_channel_entry_plain_succeeds() -> None:
    """A stored entry with require_tls=False first tries a plain gRPC probe."""
    store = MagicMock()
    store.get.return_value = {"cert_path": "/fake/path.pem", "cert_fingerprint": "abc"}
    mock_channel = MagicMock()
    with patch("tekhsi.security._try_plain_grpc_channel", return_value=mock_channel):
        result = _auto_negotiate_channel(
            "host:5000", store, None, require_tls=False, deadline=time.time() + 5, timeout=5.0
        )
    assert result is mock_channel


def test_auto_negotiate_channel_entry_with_password_uses_token_mode() -> None:
    """A stored entry with a password builds token-mode secure credentials."""
    store = MagicMock()
    store.get.return_value = {
        "cert_path": "/fake/path.pem",
        "cert_fingerprint": "abc",
        "password": "secret",
    }
    live_cert = CertInfo(cert_fingerprint="abc")
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=live_cert),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds") as mock_build,
        patch("tekhsi.security._secure_channel", return_value="secure-channel") as mock_secure,
    ):
        result = _auto_negotiate_channel(
            "host:5000", store, None, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )
    assert result == "secure-channel"
    mock_build.assert_called_once_with(store.get.return_value, "token")
    mock_secure.assert_called_once()


def test_auto_negotiate_channel_entry_without_password_uses_tls_mode() -> None:
    """A stored entry without a password builds plain TLS credentials."""
    store = MagicMock()
    store.get.return_value = {"cert_path": "/fake/path.pem", "cert_fingerprint": "abc"}
    live_cert = CertInfo(cert_fingerprint="abc")
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=live_cert),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds") as mock_build,
        patch("tekhsi.security._secure_channel", return_value="secure-channel"),
    ):
        result = _auto_negotiate_channel(
            "host:5000", store, None, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )
    assert result == "secure-channel"
    mock_build.assert_called_once_with(store.get.return_value, "tls")


def test_auto_negotiate_channel_entry_fingerprint_mismatch() -> None:
    """A live-fingerprint mismatch against the stored entry raises TekCertificateMismatch."""
    store = MagicMock()
    store.get.return_value = {"cert_path": "/fake/path.pem", "cert_fingerprint": "abc"}
    live_cert = CertInfo(cert_fingerprint="different")
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=live_cert),
        pytest.raises(TekCertificateMismatch),
    ):
        _auto_negotiate_channel(
            "host:5000", store, None, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )


def test_auto_negotiate_channel_no_entry_plain_succeeds() -> None:
    """No stored entry, require_tls=False: a successful plain probe wins immediately."""
    store = MagicMock()
    store.get.return_value = None
    mock_channel = MagicMock()
    with patch("tekhsi.security._try_plain_grpc_channel", return_value=mock_channel):
        result = _auto_negotiate_channel(
            "host:5000", store, None, require_tls=False, deadline=time.time() + 5, timeout=5.0
        )
    assert result is mock_channel


def test_auto_negotiate_channel_no_entry_plain_fails_deadline_exceeded() -> None:
    """No stored entry, plain probe fails, and the deadline has passed: raises."""
    store = MagicMock()
    store.get.return_value = None
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        pytest.raises(TekSecurityError, match="timed out"),
    ):
        _auto_negotiate_channel(
            "host:5000", store, None, require_tls=False, deadline=0.0, timeout=5.0
        )


def test_auto_negotiate_channel_require_tls_no_prompt_raises() -> None:
    """require_tls=True with no stored entry and no on_trust_prompt raises immediately."""
    store = MagicMock()
    store.get.return_value = None
    with pytest.raises(TekSecurityError, match="TLS required"):
        _auto_negotiate_channel(
            "host:5000", store, None, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )


def test_auto_negotiate_channel_no_entry_no_prompt_after_plain_fails() -> None:
    """No stored entry, require_tls=False, plain fails, and no prompt: raises TekUnknownInstrument."""
    store = MagicMock()
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="fp")
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        pytest.raises(TekUnknownInstrument),
    ):
        _auto_negotiate_channel(
            "host:5000", store, None, require_tls=False, deadline=time.time() + 5, timeout=5.0
        )


def test_auto_negotiate_channel_prompt_accepted_with_password() -> None:
    """An accepted trust prompt with a password stores trust and returns a token-mode channel."""
    store = MagicMock()
    store.get.side_effect = [
        None,
        {"cert_path": "/fake/path.pem", "password": "secret"},
    ]
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=(True, "secret", "user"))
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds"),
        patch("tekhsi.security._secure_channel", return_value="secure-channel"),
    ):
        result = _auto_negotiate_channel(
            "host:5000", store, prompt, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )
    assert result == "secure-channel"
    store.trust.assert_called_once_with("host:5000", cert_info, password="secret", login="user")


def test_auto_negotiate_channel_prompt_accepted_no_password() -> None:
    """An accepted trust prompt without a password stores trust with password=None."""
    store = MagicMock()
    store.get.side_effect = [None, {"cert_path": "/fake/path.pem"}]
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=True)
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        patch("tekhsi.security._build_creds_from_entry", return_value="creds"),
        patch("tekhsi.security._secure_channel", return_value="secure-channel"),
    ):
        result = _auto_negotiate_channel(
            "host:5000", store, prompt, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )
    assert result == "secure-channel"
    store.trust.assert_called_once_with("host:5000", cert_info, password=None)


def test_auto_negotiate_channel_prompt_rejected_raises() -> None:
    """A rejected trust prompt raises TekUnknownInstrument."""
    store = MagicMock()
    store.get.return_value = None
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=False)
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        pytest.raises(TekUnknownInstrument),
    ):
        _auto_negotiate_channel(
            "host:5000", store, prompt, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )


def test_auto_negotiate_channel_deadline_exceeded_before_fetch() -> None:
    """require_tls=True with a prompt but an already-expired deadline raises before fetching."""
    store = MagicMock()
    store.get.return_value = None
    prompt = MagicMock(return_value=True)
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        pytest.raises(TekSecurityError, match="timed out"),
    ):
        _auto_negotiate_channel(
            "host:5000", store, prompt, require_tls=True, deadline=0.0, timeout=5.0
        )


def test_auto_negotiate_channel_trust_saved_but_entry_still_missing() -> None:
    """If store lookup still fails after trust()+save(), raise TekUnknownInstrument."""
    store = MagicMock()
    store.get.side_effect = [None, None]
    cert_info = CertInfo(cert_fingerprint="fp")
    prompt = MagicMock(return_value=True)
    with (
        patch("tekhsi.security._try_plain_grpc_channel", return_value=None),
        patch("tekhsi.security._fetch_server_cert", return_value=cert_info),
        pytest.raises(TekUnknownInstrument),
    ):
        _auto_negotiate_channel(
            "host:5000", store, prompt, require_tls=True, deadline=time.time() + 5, timeout=5.0
        )


# --------------------------------------------------------------------------------------------
# TekHSICredentials
# --------------------------------------------------------------------------------------------
def test_tekhsi_credentials_tls_default_uses_store() -> None:
    """TekHSICredentials.tls() with no path defers to the credential store."""
    creds = TekHSICredentials.tls()
    assert creds._use_store is True  # pyright: ignore[reportPrivateUsage]
    assert creds._store_mode == "tls"  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError, match="Store-based credentials"):
        creds._grpc_credentials()  # pyright: ignore[reportPrivateUsage]


def test_tekhsi_credentials_tls_with_cert_path(tmp_path: Path) -> None:
    """TekHSICredentials.tls(path) builds SSL creds and derives tls_server_name."""
    cert_path = tmp_path / "ca.pem"
    cert_path.write_bytes(b"cert-bytes")
    with (
        patch("tekhsi.security.grpc.ssl_channel_credentials", return_value="ssl-creds"),
        patch("tekhsi.security.tls_server_name_from_pem", return_value="scope.local"),
    ):
        creds = TekHSICredentials.tls(str(cert_path))
    assert creds._grpc_credentials() == "ssl-creds"  # pyright: ignore[reportPrivateUsage]
    assert creds._tls_server_name == "scope.local"  # pyright: ignore[reportPrivateUsage]


def test_tekhsi_credentials_token_default_uses_store() -> None:
    """TekHSICredentials.token() with no args defers to the credential store."""
    creds = TekHSICredentials.token()
    assert creds._use_store is True  # pyright: ignore[reportPrivateUsage]
    assert creds._store_mode == "token"  # pyright: ignore[reportPrivateUsage]


def test_tekhsi_credentials_token_requires_both_args() -> None:
    """Providing only one of ca_cert_path/token raises ValueError."""
    with pytest.raises(ValueError, match="requires both"):
        TekHSICredentials.token(ca_cert_path="somepath")
    with pytest.raises(ValueError, match="requires both"):
        TekHSICredentials.token(token="tok")


def test_tekhsi_credentials_token_with_cert_and_token(tmp_path: Path) -> None:
    """TekHSICredentials.token(path, token) composes SSL + Basic-auth credentials."""
    cert_path = tmp_path / "ca.pem"
    cert_path.write_bytes(b"cert-bytes")
    with (
        patch("tekhsi.security.grpc.ssl_channel_credentials", return_value="ssl-creds"),
        patch("tekhsi.security.grpc.composite_channel_credentials", return_value="composite"),
        patch("tekhsi.security.tls_server_name_from_pem", return_value="scope.local"),
    ):
        creds = TekHSICredentials.token(str(cert_path), "tok", username="myuser")
    assert creds._grpc_credentials() == "composite"  # pyright: ignore[reportPrivateUsage]
