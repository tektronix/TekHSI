"""Unit tests for tekhsi.auth_basic."""

from __future__ import annotations

import base64

import pytest

from tekhsi.auth_basic import (
    build_basic_authorization_value,
    DEFAULT_MODE3_USERNAME,
    parse_basic_authorization,
)


def test_build_basic_authorization_value_ascii() -> None:
    """Test that building a Basic Authorization header value works for ASCII characters."""
    expected = "Basic " + base64.b64encode(b"tektronix:pw").decode("ascii")
    assert build_basic_authorization_value("tektronix", "pw") == expected


def test_build_and_parse_round_trip_unicode() -> None:
    """Test round-trip build/parse of a Basic Authorization header with Unicode characters."""
    value = build_basic_authorization_value("user", "pässwörd")
    assert parse_basic_authorization(value) == ("user", "pässwörd")


def test_parse_basic_authorization_valid_case_insensitive_prefix() -> None:
    """Test that the prefix is case-insensitive."""
    value = "bAsIc " + base64.b64encode(b"user:pw").decode("ascii")
    assert parse_basic_authorization(value) == ("user", "pw")


def test_parse_basic_authorization_strips_whitespace() -> None:
    """Test that leading and trailing whitespace is stripped from the header value."""
    inner = base64.b64encode(b"user:pw").decode("ascii")
    assert parse_basic_authorization(f"  Basic {inner}  ") == ("user", "pw")


def test_parse_basic_authorization_password_contains_colon() -> None:
    """Test that a password containing colons is parsed correctly."""
    value = "Basic " + base64.b64encode(b"user:pw:with:colons").decode("ascii")
    assert parse_basic_authorization(value) == ("user", "pw:with:colons")


@pytest.mark.parametrize("bad", ["Bearer xxx", "Bas", "", "     "])
def test_parse_basic_authorization_invalid_prefix(bad: str) -> None:
    """Test that invalid prefixes return None."""
    assert parse_basic_authorization(bad) is None


def test_parse_basic_authorization_empty_b64() -> None:
    """Test that an empty base64 string returns None."""
    assert parse_basic_authorization("Basic    ") is None


def test_parse_basic_authorization_invalid_base64() -> None:
    """Test that a non-base64 string returns None."""
    assert parse_basic_authorization("Basic !!!not_b64!!!") is None


def test_parse_basic_authorization_non_utf8() -> None:
    """Test that a base64 string that decodes to non-UTF-8 returns None."""
    value = "Basic " + base64.b64encode(b"\xff\xfe:pw").decode("ascii")
    assert parse_basic_authorization(value) is None


def test_parse_basic_authorization_missing_colon() -> None:
    """Test that a base64 string without a colon returns None."""
    value = "Basic " + base64.b64encode(b"nocolon").decode("ascii")
    assert parse_basic_authorization(value) is None


def test_default_username_constant() -> None:
    """Test that the default username constant is as expected."""
    assert DEFAULT_MODE3_USERNAME == "tektronix"
