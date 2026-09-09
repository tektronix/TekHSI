"""Unit tests for tekhsi.security."""

from __future__ import annotations

import base64

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tekhsi import security as sec
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import CertInfo
from tekhsi.security import (  # pylint: disable=import-private-name
    _build_creds_from_entry,
    _call_on_trust,
    _is_ip_literal,
    _parse_host_port,
    _secure_channel,
    _tls_channel_options,
    _tls_server_name_for_entry,
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekHSICredentials,
    TekUnknownInstrument,
)

# ---------- Exceptions ----------


def test_tek_unknown_instrument_with_fingerprint() -> None:
    """Test that TekUnknownInstrument stores the correct attributes and formats the message."""
    info = CertInfo(cert_fingerprint="a" * 32)
    err = TekUnknownInstrument("host:5000", info)
    assert err.host == "host:5000"
    assert err.cert_info is info
    assert "Fingerprint:" in str(err)


def test_tek_unknown_instrument_empty_fingerprint() -> None:
    """Test that TekUnknownInstrument with an empty fingerprint omits it from the message."""
    info = CertInfo(cert_fingerprint="")
    err = TekUnknownInstrument("host:5000", info)
    assert "Fingerprint:" not in str(err)
    assert "host:5000" in str(err)


def test_tek_certificate_mismatch_attrs() -> None:
    """Test that TekCertificateMismatch stores the correct attributes and formats the message."""
    err = TekCertificateMismatch("host", "a" * 40, "b" * 40)
    assert err.host == "host"
    assert err.stored_fingerprint == "a" * 40
    assert err.current_fingerprint == "b" * 40
    assert "Certificate mismatch" in str(err)


def test_tek_authentication_failed_prefixes_host() -> None:
    """Test that TekAuthenticationFailed includes the host in the error message."""
    err = TekAuthenticationFailed("host:5000", "bad password")
    assert str(err).startswith("host:5000: ")


# ---------- _parse_host_port ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("host", ("host", 5000)),
        ("host:1234", ("host", 1234)),
        ("[::1]", ("::1", 5000)),
        ("[::1]:1234", ("::1", 1234)),
    ],
)
def test_parse_host_port(value: str, expected: tuple[str, int]) -> None:
    """Test that _parse_host_port correctly parses host and port."""
    assert _parse_host_port(value) == expected


# ---------- _is_ip_literal ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.2.3.4", True),
        ("::1", True),
        ("[::1]", True),
        ("example.com", False),
        ("scope.local", False),
    ],
)
def test_is_ip_literal(value: str, expected: bool) -> None:
    """Test that _is_ip_literal correctly identifies IP literals."""
    assert _is_ip_literal(value) is expected


# ---------- _tls_server_name_for_entry ----------


def test_tls_server_name_for_entry_explicit() -> None:
    """Test that if tls_server_name is present in the entry, it is returned."""
    assert _tls_server_name_for_entry({"tls_server_name": "n"}) == "n"


def test_tls_server_name_for_entry_from_cert(tmp_path: Path, self_signed_pem) -> None:
    """Test that if tls_server_name is missing, we derive it from the cert_path SAN."""
    cert_pem, _ = self_signed_pem(common_name="scope", san_dns=["scope.local"])
    p = tmp_path / "c.pem"
    p.write_bytes(cert_pem)
    assert _tls_server_name_for_entry({"cert_path": str(p)}) == "scope.local"


def test_tls_server_name_for_entry_missing_both() -> None:
    """Test that if both tls_server_name and cert_path are missing, we return None."""
    assert _tls_server_name_for_entry({}) is None


def test_tls_server_name_for_entry_oserror(tmp_path: Path) -> None:
    """Test that if the cert_path does not exist, we return None instead of raising an OSError."""
    assert _tls_server_name_for_entry({"cert_path": str(tmp_path / "nope.pem")}) is None


# ---------- _tls_channel_options ----------


@pytest.mark.parametrize(
    ("host", "name", "should_override"),
    [
        ("scope", None, False),  # no name
        ("scope", "scope", False),  # equal
        ("scope.local", "scope", True),  # .local suffix
        ("10.0.0.1", "scope", True),  # ip literal
        ("other", "scope", True),  # mismatch
    ],
)
def test_tls_channel_options(host: str, name: str | None, should_override: bool) -> None:
    """Test that _tls_channel_options returns the expected override based on host and name."""
    opts = _tls_channel_options(host, name)
    if should_override:
        assert opts and opts[0][0] == "grpc.ssl_target_name_override"
    else:
        assert not opts


# ---------- _secure_channel ----------


def test_secure_channel_without_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that if the host is not an IP literal, the channel options are not overridden."""
    sentinel = object()
    mock = MagicMock(return_value=sentinel)
    monkeypatch.setattr(sec.grpc, "secure_channel", mock)
    creds = MagicMock()
    result = _secure_channel("scope:5000", creds, tls_server_name="scope")
    assert result is sentinel
    _, kwargs = mock.call_args
    assert "options" not in kwargs


def test_secure_channel_with_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that if the host is an IP literal, the channel options are overridden."""
    sentinel = object()
    mock = MagicMock(return_value=sentinel)
    monkeypatch.setattr(sec.grpc, "secure_channel", mock)
    result = _secure_channel("10.0.0.1:5000", MagicMock(), tls_server_name="scope")
    assert result is sentinel
    _, kwargs = mock.call_args
    assert "options" in kwargs
    assert kwargs["options"][0][0] == "grpc.ssl_target_name_override"


def test_secure_channel_derives_tls_name_from_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that entry-derived tls_server_name overrides channel options for IP-literal hosts."""
    mock = MagicMock(return_value=object())
    monkeypatch.setattr(sec.grpc, "secure_channel", mock)
    _secure_channel("10.0.0.1:5000", MagicMock(), entry={"tls_server_name": "scope"})
    _, kwargs = mock.call_args
    assert "options" in kwargs  # ip literal + entry-derived name => override


# ---------- _build_creds_from_entry ----------


def test_build_creds_from_entry_missing_cert_path_raises() -> None:
    """Test that _build_creds_from_entry raises ValueError if cert_path is missing."""
    with pytest.raises(ValueError, match="cert_path"):
        _build_creds_from_entry({}, "tls")


def test_build_creds_from_entry_tls_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, self_signed_pem
) -> None:
    """Test that _build_creds_from_entry in tls mode builds a channel credential."""
    cert_pem, _ = self_signed_pem()
    p = tmp_path / "ca.pem"
    p.write_bytes(cert_pem)
    sentinel = object()
    monkeypatch.setattr(sec.grpc, "ssl_channel_credentials", MagicMock(return_value=sentinel))
    result = _build_creds_from_entry({"cert_path": str(p)}, "tls")
    assert result is sentinel


def test_build_creds_from_entry_token_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, self_signed_pem
) -> None:
    """Test _build_creds_from_entry token mode builds composite creds with an auth header."""
    cert_pem, _ = self_signed_pem()
    p = tmp_path / "ca.pem"
    p.write_bytes(cert_pem)

    ssl_sentinel = object()
    composite_sentinel = object()
    call_creds_sentinel = object()

    monkeypatch.setattr(sec.grpc, "ssl_channel_credentials", MagicMock(return_value=ssl_sentinel))
    captured: dict = {}

    def _cap_meta(cb):
        captured["cb"] = cb
        return call_creds_sentinel

    monkeypatch.setattr(sec.grpc, "metadata_call_credentials", _cap_meta)
    monkeypatch.setattr(
        sec.grpc, "composite_channel_credentials", MagicMock(return_value=composite_sentinel)
    )

    result = _build_creds_from_entry(
        {"cert_path": str(p), "password": "pw", "login": "u"},
        "token",
    )
    assert result is composite_sentinel

    # Invoke the captured meta_cb and confirm it emits an authorization header.
    received: dict = {}

    def _fake_cb(headers, err):  # noqa: ARG001
        received["headers"] = headers

    captured["cb"](None, _fake_cb)
    headers = dict(received["headers"])
    assert headers["authorization"].startswith("Basic ")


def test_build_creds_from_entry_token_mode_default_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, self_signed_pem
) -> None:
    """Test that if no login is stored, the default username is used in the authorization header."""
    cert_pem, _ = self_signed_pem()
    p = tmp_path / "ca.pem"
    p.write_bytes(cert_pem)

    monkeypatch.setattr(sec.grpc, "ssl_channel_credentials", MagicMock(return_value=object()))
    captured: dict = {}

    def _cap_meta(cb):
        captured["cb"] = cb
        return object()

    monkeypatch.setattr(sec.grpc, "metadata_call_credentials", _cap_meta)
    monkeypatch.setattr(sec.grpc, "composite_channel_credentials", MagicMock(return_value=object()))
    _build_creds_from_entry({"cert_path": str(p)}, "token")

    received: dict = {}

    def _fake_cb(headers, err):  # noqa: ARG001
        received["headers"] = headers

    captured["cb"](None, _fake_cb)
    # No login stored -> default username used

    expected = "Basic " + base64.b64encode(f"{DEFAULT_MODE3_USERNAME}:".encode()).decode("ascii")
    assert dict(received["headers"])["authorization"] == expected


# ---------- _call_on_trust ----------


def test_call_on_trust_two_arg_callback() -> None:
    """Test that a two-arg callback is called with host and cert_info."""

    def cb(h, c):  # noqa: ARG001
        return True

    assert _call_on_trust(cb, "h", CertInfo(cert_fingerprint=""), auth_required=True) is True


def test_call_on_trust_three_arg_callback_receives_auth_required() -> None:
    """Test that a three-arg callback receives the auth_required flag."""

    def cb(h, c, ar):  # noqa: ARG001
        return ar

    assert _call_on_trust(cb, "h", CertInfo(cert_fingerprint=""), auth_required=True) is True


def test_call_on_trust_typeerror_falls_back_to_two_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that if the callback raises TypeError on signature inspection, we fall back."""

    def cb(h, c):  # noqa: ARG001
        return "two-arg-result"

    monkeypatch.setattr(sec.inspect, "signature", MagicMock(side_effect=TypeError))
    assert (
        _call_on_trust(cb, "h", CertInfo(cert_fingerprint=""), auth_required=True)
        == "two-arg-result"
    )


# ---------- TekHSICredentials ----------


def test_credentials_tls_no_ca_uses_store() -> None:
    """Test that TekHSICredentials.tls() with no ca_cert_path uses the credential store."""
    creds = TekHSICredentials.tls()
    assert creds._use_store is True
    assert creds._store_mode == "tls"
    assert creds._channel_credentials is None
    with pytest.raises(ValueError, match="Store-based"):
        creds._grpc_credentials()


def test_credentials_tls_with_ca_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, self_signed_pem
) -> None:
    """Test that TekHSICredentials.tls() with a ca_cert_path builds a channel credential."""
    cert_pem, _ = self_signed_pem(common_name="scope", san_dns=["scope.local"])
    p = tmp_path / "ca.pem"
    p.write_bytes(cert_pem)
    sentinel = object()
    monkeypatch.setattr(sec.grpc, "ssl_channel_credentials", MagicMock(return_value=sentinel))
    creds = TekHSICredentials.tls(str(p))
    assert creds._channel_credentials is sentinel
    assert creds._tls_server_name == "scope.local"
    assert creds._grpc_credentials() is sentinel


def test_credentials_token_no_args_uses_store() -> None:
    """Test that TekHSICredentials.token() with no args uses the credential store."""
    creds = TekHSICredentials.token()
    assert creds._use_store is True
    assert creds._store_mode == "token"


def test_credentials_token_missing_one_arg_raises(tmp_path: Path) -> None:
    """Test TekHSICredentials.token() raises ValueError if only one of ca_cert_path/token given."""
    with pytest.raises(ValueError, match="requires both"):
        TekHSICredentials.token(ca_cert_path=str(tmp_path / "x"))
    with pytest.raises(ValueError, match="requires both"):
        TekHSICredentials.token(token="tok")


def test_credentials_token_full_args_builds_composite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, self_signed_pem
) -> None:
    """Test that TekHSICredentials.token() with all args builds a composite channel credential."""
    cert_pem, _ = self_signed_pem(common_name="scope", san_dns=["scope.local"])
    p = tmp_path / "ca.pem"
    p.write_bytes(cert_pem)
    monkeypatch.setattr(sec.grpc, "ssl_channel_credentials", MagicMock(return_value=object()))
    captured: dict = {}

    def _cap_meta(cb):
        captured["cb"] = cb
        return object()

    monkeypatch.setattr(sec.grpc, "metadata_call_credentials", _cap_meta)
    composite = object()
    monkeypatch.setattr(
        sec.grpc, "composite_channel_credentials", MagicMock(return_value=composite)
    )
    creds = TekHSICredentials.token(str(p), token="secret", username="alice")
    assert creds._channel_credentials is composite
    assert creds._tls_server_name == "scope.local"

    received: dict = {}

    def _fake_cb(headers, err):  # noqa: ARG001
        received["headers"] = headers

    captured["cb"](None, _fake_cb)

    expected = "Basic " + base64.b64encode(b"alice:secret").decode("ascii")
    assert dict(received["headers"])["authorization"] == expected
