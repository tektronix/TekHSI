"""Backward-compatible re-exports for HTTP Basic auth helpers.

Some callers import from ``tekhsi.auth.basic`` while internal code imports from
``tekhsi.auth_basic``. Keep both paths valid.
"""

from tekhsi.auth_basic import (
    build_basic_authorization_value,
    DEFAULT_MODE3_USERNAME,
    parse_basic_authorization,
)

__all__ = [
    "DEFAULT_MODE3_USERNAME",
    "build_basic_authorization_value",
    "parse_basic_authorization",
]
