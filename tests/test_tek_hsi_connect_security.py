"""Unit tests for TekHSIConnect security helpers (Mode 3 upgrade path)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tekhsi import tek_hsi_connect as thc
from tekhsi.credential_store import CertInfo
from tekhsi.security import (
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekSecurityError,
)
from tekhsi.tek_hsi_connect import TekHSIConnect

# ---------- _parse_auth_prompt_result (static) ----------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ((True, "pw"), ("pw", None)),
        ((True, "pw", "user"), ("pw", "user")),
        ((True, "pw", ""), ("pw", None)),  # empty login normalized to None
        ([True, "pw", "user"], ("pw", "user")),  # list also accepted
    ],
)
def test_parse_auth_prompt_result_valid(result: Any, expected: tuple[str, str | None]) -> None:
    """Valid prompt results yield the expected (password, login) tuple."""
    assert TekHSIConnect._parse_auth_prompt_result(result, "host") == expected


@pytest.mark.parametrize(
    "result",
    [True, (True,), (True, None), (True, ""), False, (False,), None, 0, "no"],
)
def test_parse_auth_prompt_result_declined_or_no_password(result: Any) -> None:
    """Declined prompts or missing passwords raise TekAuthenticationFailed."""
    with pytest.raises(TekAuthenticationFailed):
        TekHSIConnect._parse_auth_prompt_result(result, "host")


# ---------- _upgrade_channel_with_token_after_unauthenticated ----------


def _make_bare_client() -> TekHSIConnect:
    """Build a TekHSIConnect instance without running __init__ (no gRPC)."""
    client = TekHSIConnect.__new__(TekHSIConnect)
    client.url = "host:5000"
    client.clientname = "test-client"
    client.channel = MagicMock()
    client.connection = MagicMock()
    client.native = MagicMock()
    client._credential_store_ref = None
    client._on_trust_ref = None
    return client


def test_upgrade_missing_store_or_callback_raises() -> None:
    """Upgrade fails when no credential store or trust callback is configured."""
    client = _make_bare_client()
    with pytest.raises(TekAuthenticationFailed, match="Authentication required"):
        client._upgrade_channel_with_token_after_unauthenticated()


def test_upgrade_missing_cert_path_raises() -> None:
    """Upgrade fails when the store has no stored cert_path for the host."""
    client = _make_bare_client()
    client._credential_store_ref = MagicMock()
    client._credential_store_ref.get.return_value = None
    client._on_trust_ref = lambda *_a, **_k: True
    with pytest.raises(TekAuthenticationFailed, match="no stored certificate"):
        client._upgrade_channel_with_token_after_unauthenticated()


def test_upgrade_fingerprint_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upgrade raises TekCertificateMismatch when live cert fingerprint differs from stored."""
    client = _make_bare_client()
    client._credential_store_ref = MagicMock()
    client._credential_store_ref.get.return_value = {
        "cert_path": "/tmp/x.pem",
        "cert_fingerprint": "stored-fp",
    }
    client._on_trust_ref = lambda *_a, **_k: True
    monkeypatch.setattr(
        thc, "_fetch_server_cert", MagicMock(return_value=CertInfo(cert_fingerprint="live-fp"))
    )
    with pytest.raises(TekCertificateMismatch):
        client._upgrade_channel_with_token_after_unauthenticated()


def test_upgrade_declined_prompt_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upgrade raises TekAuthenticationFailed when the trust prompt declines."""
    client = _make_bare_client()
    client._credential_store_ref = MagicMock()
    client._credential_store_ref.get.return_value = {
        "cert_path": "/tmp/x.pem",
        "cert_fingerprint": "fp",
    }
    client._on_trust_ref = lambda *_a, **_k: False
    monkeypatch.setattr(
        thc, "_fetch_server_cert", MagicMock(return_value=CertInfo(cert_fingerprint="fp"))
    )
    with pytest.raises(TekAuthenticationFailed):
        client._upgrade_channel_with_token_after_unauthenticated()


def test_upgrade_success_swaps_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful upgrade persists credentials and swaps in the new secure channel."""
    client = _make_bare_client()
    old_channel = client.channel
    store = MagicMock()
    entry = {"cert_path": "/tmp/x.pem", "cert_fingerprint": "fp"}
    # First get() for pre-check, second get() after store.set/save
    store.get.side_effect = [entry, entry]
    client._credential_store_ref = store
    client._on_trust_ref = lambda *_a, **_k: (True, "pw", "alice")

    monkeypatch.setattr(
        thc, "_fetch_server_cert", MagicMock(return_value=CertInfo(cert_fingerprint="fp"))
    )
    monkeypatch.setattr(thc, "_build_creds_from_entry", MagicMock(return_value=object()))
    new_channel = MagicMock(name="new_channel")
    monkeypatch.setattr(thc, "_secure_channel", MagicMock(return_value=new_channel))
    monkeypatch.setattr(thc, "ConnectStub", MagicMock())
    monkeypatch.setattr(thc, "NativeDataStub", MagicMock())

    client._upgrade_channel_with_token_after_unauthenticated()

    store.set.assert_called_once()
    _, kwargs = store.set.call_args
    assert kwargs["password"] == "pw"
    assert kwargs["login"] == "alice"
    store.save.assert_called_once()
    old_channel.close.assert_called()
    assert client.channel is new_channel


def test_upgrade_store_lost_entry_raises_security_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade raises TekSecurityError when the store entry disappears after save."""
    client = _make_bare_client()
    store = MagicMock()
    entry = {"cert_path": "/tmp/x.pem", "cert_fingerprint": "fp"}
    # After save, second get() returns None to trigger "Store update failed".
    store.get.side_effect = [entry, None]
    client._credential_store_ref = store
    client._on_trust_ref = lambda *_a, **_k: (True, "pw")

    monkeypatch.setattr(
        thc, "_fetch_server_cert", MagicMock(return_value=CertInfo(cert_fingerprint="fp"))
    )

    with pytest.raises(TekSecurityError, match="Store update failed"):
        client._upgrade_channel_with_token_after_unauthenticated()
