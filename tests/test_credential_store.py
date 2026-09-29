"""Unit tests for the credential store."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from tekhsi.credential_store import (
    CertInfo,
    TekHSICredentialStore,
    _obscure_password,
    _reveal_password,
)


def test_normalize_host_lowercase() -> None:
    """Host keys are normalized to lowercase."""
    store = TekHSICredentialStore(path="/nonexistent/test.ini")
    assert store._normalize_host("192.168.1.1:5000") == "192.168.1.1:5000"
    assert store._normalize_host("  HOST:5000  ") == "host:5000"


def test_set_get_save_load_round_trip(tmp_path: Path) -> None:
    """All five keys survive save/load."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set(
        "host:5000",
        cert_fingerprint="abc123",
        cert_path=str(tmp_path / "cert.pem"),
        tls_server_name="scope.local",
        login="tektronix",
        password="secret",
    )
    store.save()

    store2 = TekHSICredentialStore(path=str(ini_path))
    entry = store2.get("HOST:5000")
    assert entry is not None
    assert entry["cert_fingerprint"] == "abc123"
    assert entry["cert_path"] == str(tmp_path / "cert.pem")
    assert entry["tls_server_name"] == "scope.local"
    assert entry["login"] == "tektronix"
    assert entry["password"] == "secret"


def test_app_written_password_obfuscated_on_disk(tmp_path: Path) -> None:
    """App-written passwords are stored as obf1: on disk."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", password="secret")
    store.save()

    raw = ini_path.read_text(encoding="utf-8")
    assert "obf1:" in raw
    assert "secret" not in raw

    store2 = TekHSICredentialStore(path=str(ini_path))
    assert store2.get("host:5000")["password"] == "secret"


def test_hand_entered_plaintext_preserved(tmp_path: Path) -> None:
    """Hand-typed cleartext passwords are never re-obscured."""
    ini_path = tmp_path / "credentials.ini"
    ini_path.write_text(
        "[host:5000]\ncert_fingerprint = fp\npassword = MyPassword\n",
        encoding="utf-8",
    )
    store = TekHSICredentialStore(path=str(ini_path))
    assert store.get("host:5000")["password"] == "MyPassword"

    store.set("host:5000", login="tektronix")
    store.save()

    raw = ini_path.read_text(encoding="utf-8")
    assert "password = MyPassword" in raw
    assert "obf1:" not in raw


@pytest.mark.parametrize(
    "password",
    ["unicode: päss", "with:colons", "equals=", " spaces ", ""],
)
def test_obfuscation_round_trip(password: str) -> None:
    """Obfuscation round-trips representative passwords."""
    if password == "":
        assert _reveal_password(_obscure_password(password)) == ""
    else:
        assert _reveal_password(_obscure_password(password)) == password


def test_malformed_obf1_returned_verbatim() -> None:
    """Malformed obf1 values are returned literally."""
    assert _reveal_password("obf1:not-base64!") == "obf1:not-base64!"


def test_trust_writes_sidecar_pem(tmp_path: Path) -> None:
    """trust() writes PEM and sets cert_path."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    pem = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    info = CertInfo.from_pem(pem)
    store.trust("192.168.1.1:5000", info, password="pw")
    store.save()

    entry = store.get("192.168.1.1:5000")
    assert entry is not None
    assert entry["cert_path"] is not None
    assert Path(entry["cert_path"]).is_file()
    assert entry["password"] == "pw"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod only")
def test_save_sets_mode_0600(tmp_path: Path) -> None:
    """INI file is chmod 0600 on POSIX."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", login="u")
    store.save()
    mode = stat.S_IMODE(os.stat(ini_path).st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_list_hosts_and_remove(tmp_path: Path) -> None:
    """list_hosts and remove behave as expected."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("b:1")
    store.set("a:2")
    assert store.list_hosts() == ["a:2", "b:1"]
    store.remove("b:1")
    assert store.list_hosts() == ["a:2"]
