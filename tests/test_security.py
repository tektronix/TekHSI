"""Unit tests for security helpers and exceptions."""

from tekhsi.credential_store import CertInfo
from tekhsi.security import (
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekSecurityError,
    TekUnknownInstrument,
    _is_ip_literal,
    _parse_host_port,
    _tls_channel_options,
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
