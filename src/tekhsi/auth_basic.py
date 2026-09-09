"""HTTP Basic authorization helpers for TekHSI Mode 3 client auth."""

from __future__ import annotations

import base64
import binascii

DEFAULT_MODE3_USERNAME = "tektronix"


def build_basic_authorization_value(username: str, password: str) -> str:
    """Return the full value for the ``authorization`` metadata key: ``Basic <b64>``."""
    pair = f"{username}:{password}".encode()
    b64 = base64.b64encode(pair).decode("ascii")
    return f"Basic {b64}"


def parse_basic_authorization(header_value: str) -> tuple[str, str] | None:
    """Parse ``Basic <b64>``; return ``(username, password)`` or ``None`` if invalid."""
    s = header_value.strip()
    if len(s) < 6 or s[:6].lower() != "basic ":
        return None
    b64 = s[6:].strip()
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if ":" not in decoded:
        return None
    user, pw = decoded.split(":", 1)
    return user, pw
