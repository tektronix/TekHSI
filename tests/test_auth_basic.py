"""Unit tests for auth_basic helpers."""

import base64

from tekhsi.auth_basic import (
    build_basic_authorization_value,
    DEFAULT_MODE3_USERNAME,
    parse_basic_authorization,
)


def test_build_and_parse_round_trip() -> None:
    """Basic auth value round-trips through parse."""
    value = build_basic_authorization_value("user", "secret")
    assert value.startswith("Basic ")
    parsed = parse_basic_authorization(value)
    assert parsed == ("user", "secret")


def test_empty_password() -> None:
    """Empty password is preserved in round-trip."""
    value = build_basic_authorization_value("user", "")
    assert parse_basic_authorization(value) == ("user", "")


def test_colon_in_password() -> None:
    """Password containing colon splits on first colon only."""
    value = build_basic_authorization_value("user", "a:b:c")
    assert parse_basic_authorization(value) == ("user", "a:b:c")


def test_non_ascii_password() -> None:
    """UTF-8 passwords round-trip."""
    value = build_basic_authorization_value("user", "päss")
    assert parse_basic_authorization(value) == ("user", "päss")


def test_parse_invalid_inputs() -> None:
    """Malformed headers return None."""
    assert parse_basic_authorization("") is None
    assert parse_basic_authorization("Bearer xyz") is None
    assert parse_basic_authorization("Basic") is None
    assert parse_basic_authorization("Basic !!!") is None
    assert parse_basic_authorization("Basic dGVzdA==") is None  # no colon in decoded


def test_parse_empty_base64_after_prefix() -> None:
    """Whitespace-only payload after 'Basic ' is treated as empty and invalid."""
    assert parse_basic_authorization("Basic    ") is None


def test_parse_invalid_utf8_decoded_payload() -> None:
    """Valid base64 that decodes to non-UTF-8 bytes returns None."""
    b64 = base64.b64encode(b"\xff\xfe\xfd").decode("ascii")
    assert parse_basic_authorization(f"Basic {b64}") is None


def test_default_username_constant() -> None:
    """Default Mode 3 username is tektronix."""
    assert DEFAULT_MODE3_USERNAME == "Tektronix"
