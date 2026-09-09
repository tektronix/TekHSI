"""HTTP Basic authorization helpers for TekHSI Mode 3 client auth."""

from __future__ import annotations

import base64

DEFAULT_MODE3_USERNAME = "tektronix"

# Length of the "Basic " scheme prefix (including the trailing space).
_BASIC_PREFIX_LEN = 6


def build_basic_authorization_value(username: str, password: str) -> str:
    """Return the full value for the ``authorization`` metadata key: ``Basic <b64>``."""
    pair = f"{username}:{password}".encode()
    b64 = base64.b64encode(pair).decode("ascii")
    return f"Basic {b64}"


def parse_basic_authorization(header_value: str) -> tuple[str, str] | None:
    """Parse ``Basic <b64>``; return ``(username, password)`` or ``None`` if invalid."""
    s = header_value.strip()
    if len(s) < _BASIC_PREFIX_LEN or s[:_BASIC_PREFIX_LEN].lower() != "basic ":
        return None
    if not (b64 := s[_BASIC_PREFIX_LEN:].strip()):
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except ValueError:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if ":" not in decoded:
        return None
    user, pw = decoded.split(":", 1)
    return user, pw
