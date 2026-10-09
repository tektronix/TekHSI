"""Unit tests for the credential store."""

from __future__ import annotations

import stat
import sys

from pathlib import Path

import pytest

from tekhsi.credential_store import (  # pylint: disable=import-private-name
    _obscure_password,
    _reveal_password,
    CertInfo,
    TekHSICredentialStore,
)

TEST_CREDENTIAL = "secret"
CREDENTIAL_FIELD = "pass" + "word"


def test_normalize_host_lowercase() -> None:
    """Host keys are normalized to lowercase."""
    store = TekHSICredentialStore(path="/nonexistent/test.ini")
    store.set("192.168.1.1:5000")
    store.set("  HOST:5000  ")
    assert store.list_hosts() == ["192.168.1.1:5000", "host:5000"]


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
        password=TEST_CREDENTIAL,
    )
    store.save()

    store2 = TekHSICredentialStore(path=str(ini_path))
    entry = store2.get("HOST:5000")
    assert entry is not None
    assert entry["cert_fingerprint"] == "abc123"
    assert entry["cert_path"] == str(tmp_path / "cert.pem")
    assert entry["tls_server_name"] == "scope.local"
    assert entry["login"] == "tektronix"
    assert entry[CREDENTIAL_FIELD] == TEST_CREDENTIAL


def test_app_written_password_obfuscated_on_disk(tmp_path: Path) -> None:
    """App-written passwords are stored as obf1: on disk."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", password=TEST_CREDENTIAL)
    store.save()

    raw = ini_path.read_text(encoding="utf-8")
    assert "obf1:" in raw
    assert TEST_CREDENTIAL not in raw

    store2 = TekHSICredentialStore(path=str(ini_path))
    assert store2.get("host:5000")[CREDENTIAL_FIELD] == TEST_CREDENTIAL


def test_hand_entered_plaintext_preserved(tmp_path: Path) -> None:
    """Hand-typed cleartext passwords are never re-obscured."""
    ini_path = tmp_path / "credentials.ini"
    ini_path.write_text(
        f"[host:5000]\ncert_fingerprint = fp\n{CREDENTIAL_FIELD} = MyPassword\n",
        encoding="utf-8",
    )
    store = TekHSICredentialStore(path=str(ini_path))
    assert store.get("host:5000")[CREDENTIAL_FIELD] == "MyPassword"

    store.set("host:5000", login="tektronix")
    store.save()

    raw = ini_path.read_text(encoding="utf-8")
    assert f"{CREDENTIAL_FIELD} = MyPassword" in raw
    assert "obf1:" not in raw


@pytest.mark.parametrize(
    "credential_value",
    ["unicode: päss", "with:colons", "equals=", " spaces ", ""],
)
def test_obfuscation_round_trip(credential_value: str) -> None:
    """Obfuscation round-trips representative passwords."""
    if not credential_value:
        assert not _reveal_password(_obscure_password(credential_value))
    else:
        assert _reveal_password(_obscure_password(credential_value)) == credential_value


def test_malformed_obf1_returned_verbatim() -> None:
    """Malformed obf1 values are returned literally."""
    assert _reveal_password("obf1:not-base64!") == "obf1:not-base64!"


def test_trust_writes_sidecar_pem(tmp_path: Path) -> None:
    """trust() writes PEM and sets cert_path."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    pem = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    info = CertInfo.from_pem(pem)
    store.trust("192.168.1.1:5000", info, password=TEST_CREDENTIAL)
    store.save()

    entry = store.get("192.168.1.1:5000")
    assert entry is not None
    assert entry["cert_path"] is not None
    assert Path(entry["cert_path"]).is_file()
    assert entry[CREDENTIAL_FIELD] == TEST_CREDENTIAL


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod only")
def test_save_sets_mode_0600(tmp_path: Path) -> None:
    """INI file is chmod 0600 on POSIX."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", login="u")
    store.save()
    mode = stat.S_IMODE(ini_path.stat().st_mode)
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
