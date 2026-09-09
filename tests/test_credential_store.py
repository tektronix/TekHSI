"""Unit tests for tekhsi.credential_store."""

from __future__ import annotations

import hashlib
import sys

from pathlib import Path

import pytest

from tekhsi import credential_store as cs
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import (  # pylint: disable=import-private-name
    _default_store_path,
    _obscure_password,
    _reveal_password,
    CertInfo,
    TekHSICredentialStore,
    tls_server_name_from_pem,
)

# ---------- tls_server_name_from_pem ----------


def test_tls_server_name_from_pem_san_dns(self_signed_pem) -> None:
    """Test that tls_server_name_from_pem returns the first SAN DNS name if present."""
    cert_pem, _ = self_signed_pem(common_name="scope", san_dns=["scope.local"])
    assert tls_server_name_from_pem(cert_pem) == "scope.local"


def test_tls_server_name_from_pem_cn_fallback(self_signed_pem) -> None:
    """Test that tls_server_name_from_pem falls back to CN if no SAN is present."""
    cert_pem, _ = self_signed_pem(common_name="mycn", san_dns=None)
    assert tls_server_name_from_pem(cert_pem) == "mycn"


def test_tls_server_name_from_pem_invalid_bytes() -> None:
    """Test that tls_server_name_from_pem returns None for invalid bytes."""
    assert tls_server_name_from_pem(b"not a pem") is None


def test_tls_server_name_from_pem_no_san_no_cn(self_signed_pem) -> None:
    """Test that tls_server_name_from_pem returns None if the cert has no SAN and no CN."""
    cert_pem, _ = self_signed_pem(include_cn=False, san_dns=None)
    assert tls_server_name_from_pem(cert_pem) is None


def test_tls_server_name_from_pem_no_cryptography(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that tls_server_name_from_pem returns None when cryptography is unavailable."""
    monkeypatch.setattr(cs, "_HAS_CRYPTOGRAPHY", False)
    assert tls_server_name_from_pem(b"anything") is None


# ---------- _default_store_path ----------


def test_default_store_path_win32(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that the default store path is correct on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = _default_store_path()
    assert p.endswith("credentials.ini")
    assert "tektronix" in p


def test_default_store_path_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the default store path is correct on macOS."""
    monkeypatch.setattr(sys, "platform", "darwin")
    p = _default_store_path()
    assert p.endswith("credentials.ini")
    assert "Library" in p and "tektronix" in p


def test_default_store_path_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the default store path is correct on Linux."""
    monkeypatch.setattr(sys, "platform", "linux")
    p = _default_store_path()
    assert p.endswith("credentials.ini")
    assert ".tektronix" in p


# ---------- obscure / reveal ----------


def test_obscure_reveal_round_trip() -> None:
    """Test that obscuring and revealing a password round-trips correctly."""
    stored = _obscure_password("s3cret!")
    assert stored.startswith("obf1:")
    assert _reveal_password(stored) == "s3cret!"


def test_reveal_password_none_returns_none() -> None:
    """Test that revealing a None value returns None."""
    assert _reveal_password(None) is None


def test_reveal_password_plaintext_passthrough() -> None:
    """Test that a stored value without the "obf1:" prefix is returned verbatim."""
    assert _reveal_password("hand-entered") == "hand-entered"


def test_reveal_password_invalid_b64_returns_stored_verbatim() -> None:
    """Test that a stored value that is not valid base64 returns the stored value verbatim."""
    bad = "obf1:!!!"
    assert _reveal_password(bad) == bad


# ---------- CertInfo ----------


def test_certinfo_from_pem_and_fingerprint_alias(self_signed_pem) -> None:
    """Test that CertInfo.from_pem correctly computes the fingerprint and that the alias works."""
    cert_pem, _ = self_signed_pem(common_name="scope", san_dns=["scope.local"])
    info = CertInfo.from_pem(cert_pem)
    assert info.cert_fingerprint == hashlib.sha256(cert_pem).hexdigest()
    assert info.fingerprint == info.cert_fingerprint
    assert info.cert_pem == cert_pem
    assert info.tls_server_name == "scope.local"


# ---------- TekHSICredentialStore ----------


def _store(tmp_path: Path) -> TekHSICredentialStore:
    return TekHSICredentialStore(path=str(tmp_path / "credentials.ini"))


def test_store_init_missing_file(tmp_path: Path) -> None:
    """Test that initializing the store with a missing file creates an empty store."""
    store = _store(tmp_path)
    assert store.list_hosts() == []


def test_store_get_missing_host(tmp_path: Path) -> None:
    """Test that getting a missing host returns None."""
    store = _store(tmp_path)
    assert store.get("nope:5000") is None


def test_store_set_and_get_reveals_password(tmp_path: Path) -> None:
    """Test that setting and getting an entry works and reveals the password."""
    store = _store(tmp_path)
    store.set(
        "Host:5000",
        cert_fingerprint="fp",
        cert_path="/tmp/x.pem",
        tls_server_name="scope",
        login="user",
        password="pw",
    )
    entry = store.get("host:5000")
    assert entry is not None
    assert entry["cert_fingerprint"] == "fp"
    assert entry["password"] == "pw"
    assert entry["login"] == "user"


def test_store_set_clears_empty_values(tmp_path: Path) -> None:
    """Test that setting a falsey value clears the key in the store."""
    store = _store(tmp_path)
    store.set("host", cert_fingerprint="fp", login="user")
    store.set("host", password="")  # falsey clears the key
    entry = store.get("host")
    assert entry is not None
    assert entry["password"] is None


def test_store_save_and_reload_round_trip(tmp_path: Path) -> None:
    """Test that saving and reloading the store preserves entries."""
    path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(path))
    store.set("host:5000", cert_fingerprint="fp", login="tektronix", password="pw")
    store.save()
    assert path.is_file()

    reloaded = TekHSICredentialStore(path=str(path))
    entry = reloaded.get("host:5000")
    assert entry is not None
    assert entry["cert_fingerprint"] == "fp"
    assert entry["login"] == "tektronix"
    assert entry["password"] == "pw"


def test_store_trust_writes_cert_and_defaults_login(tmp_path: Path, self_signed_pem) -> None:
    """Test that trust() writes the cert to a file and sets default login."""
    store = _store(tmp_path)
    cert_pem, _ = self_signed_pem(common_name="scope", san_dns=["scope.local"])
    info = CertInfo.from_pem(cert_pem)
    store.trust("host:5000", info, password="pw")
    entry = store.get("host:5000")
    assert entry is not None
    assert entry["login"] == DEFAULT_MODE3_USERNAME
    assert entry["cert_path"] is not None
    assert Path(entry["cert_path"]).is_file()


def test_store_list_hosts_sorted_and_remove(tmp_path: Path) -> None:
    """Test that list_hosts returns sorted hostnames and that remove works."""
    store = _store(tmp_path)
    store.set("b", cert_fingerprint="1")
    store.set("a", cert_fingerprint="2")
    assert store.list_hosts() == ["a", "b"]
    store.remove("a")
    assert store.list_hosts() == ["b"]
    # Removing missing host is silent
    store.remove("does-not-exist")
