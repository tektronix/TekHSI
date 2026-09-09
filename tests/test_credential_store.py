"""Unit tests for the credential store."""

from __future__ import annotations

import builtins
import os
import stat
import sys

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from tekhsi.credential_store import (
    _default_store_path,  # pyright: ignore[reportPrivateUsage]
    _obscure_password,  # pyright: ignore[reportPrivateUsage]
    _reveal_password,  # pyright: ignore[reportPrivateUsage]
    CertInfo,
    TekHSICredentialStore,
    tls_server_name_from_pem,
)


def test_normalize_host_lowercase() -> None:
    """Host keys are normalized to lowercase."""
    store = TekHSICredentialStore(path="/nonexistent/test.ini")
    assert store._normalize_host("192.168.1.1:5000") == "192.168.1.1:5000"  # pyright: ignore[reportPrivateUsage]
    assert store._normalize_host("  HOST:5000  ") == "host:5000"  # pyright: ignore[reportPrivateUsage]


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
    entry = store2.get("host:5000")
    assert entry is not None
    assert entry["password"] == "secret"


def test_hand_entered_plaintext_preserved(tmp_path: Path) -> None:
    """Hand-typed cleartext passwords are never re-obscured."""
    ini_path = tmp_path / "credentials.ini"
    ini_path.write_text(
        "[host:5000]\ncert_fingerprint = fp\npassword = MyPassword\n",
        encoding="utf-8",
    )
    store = TekHSICredentialStore(path=str(ini_path))
    entry = store.get("host:5000")
    assert entry is not None
    assert entry["password"] == "MyPassword"

    store.set("host:5000", login="tektronix")
    store.save()

    raw = ini_path.read_text(encoding="utf-8")
    assert "password = MyPassword" in raw
    assert "obf1:" not in raw


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
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
    cert_path = cast("str", entry["cert_path"])
    assert Path(cert_path).is_file()
    assert entry["password"] == "pw"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod only")  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
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


def test_get_unknown_host_returns_none(tmp_path: Path) -> None:
    """get() returns None for a host that has never been set."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    assert store.get("unknown:1") is None


def test_reveal_password_none_returns_none() -> None:
    """_reveal_password(None) returns None (no stored value)."""
    assert _reveal_password(None) is None


def test_set_empty_string_clears_existing_key(tmp_path: Path) -> None:
    """Setting a field to '' removes it from the stored entry."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", password="secret", login="tektronix")
    store.set("host:5000", password="")
    entry = store.get("host:5000")
    assert entry is not None
    assert entry["password"] is None
    assert entry["login"] == "tektronix"


def test_trust_without_password_skips_default_login(tmp_path: Path) -> None:
    """trust() without a password leaves login as None (default-login branch skipped)."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    info = CertInfo(cert_fingerprint="abc123")
    store.trust("192.168.1.1:5000", info)
    entry = store.get("192.168.1.1:5000")
    assert entry is not None
    assert entry["login"] is None
    assert entry["password"] is None


def test_trust_without_cert_pem_skips_sidecar_file(tmp_path: Path) -> None:
    """trust() with a fingerprint-only CertInfo does not write a sidecar PEM file."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    info = CertInfo(cert_fingerprint="abc123")
    store.trust("192.168.1.1:5000", info, password="pw")
    entry = store.get("192.168.1.1:5000")
    assert entry is not None
    assert entry["cert_path"] is None
    assert not os.path.isdir(store._certs_dir)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    ("platform", "env", "expected_parts"),
    [
        (
            "win32",
            {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"},
            ["tektronix", "credentials.ini"],
        ),
        ("darwin", {}, ["Library", "Application Support", "tektronix", "credentials.ini"]),
        ("linux", {}, [".tektronix", "credentials.ini"]),
    ],
)
def test_default_store_path_per_platform(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    env: dict,
    expected_parts: list,
) -> None:
    """_default_store_path builds the expected path for each supported platform."""
    monkeypatch.setattr(sys, "platform", platform)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    path = _default_store_path()
    for part in expected_parts:
        assert part in path


def test_tls_server_name_from_pem_import_error() -> None:
    """tls_server_name_from_pem returns None when the cryptography package is unavailable."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "cryptography" or name.startswith("cryptography."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with patch.object(builtins, "__import__", side_effect=fake_import):
        assert tls_server_name_from_pem(b"irrelevant") is None


def test_tls_server_name_from_pem_invalid_cert_returns_none() -> None:
    """tls_server_name_from_pem returns None for bytes that don't parse as a certificate."""
    assert tls_server_name_from_pem(b"not a real certificate") is None


def _generate_self_signed_cert(*, san_dns: str | None, common_name: str) -> bytes:
    """Build a minimal self-signed certificate PEM for SAN/CN branch testing."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, common_name)],
    )
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
        )
    )
    if san_dns:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(san_dns)]),
            critical=False,
        )
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM)


def test_tls_server_name_from_pem_uses_san_dns_name() -> None:
    """tls_server_name_from_pem prefers the SAN DNS name when present."""
    pytest.importorskip("cryptography")
    pem = _generate_self_signed_cert(san_dns="scope.example.com", common_name="fallback-cn")
    assert tls_server_name_from_pem(pem) == "scope.example.com"


def test_tls_server_name_from_pem_falls_back_to_common_name() -> None:
    """tls_server_name_from_pem falls back to the CN when there is no SAN extension."""
    pytest.importorskip("cryptography")
    pem = _generate_self_signed_cert(san_dns=None, common_name="scope-cn.example.com")
    assert tls_server_name_from_pem(pem) == "scope-cn.example.com"


def test_load_ignores_oserror(tmp_path: Path) -> None:
    """load() returns without raising if the store file cannot be opened."""
    ini_path = tmp_path / "credentials.ini"
    ini_path.write_text("[host:5000]\nlogin = u\n", encoding="utf-8")
    store = TekHSICredentialStore(path=str(ini_path))

    with patch("builtins.open", side_effect=OSError("boom")):
        store.load()
    assert store.list_hosts() == []


def test_save_with_no_directory_component(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """save() works when the store path has no directory component."""
    monkeypatch.chdir(tmp_path)
    store = TekHSICredentialStore(path="credentials_relative.ini")
    store.set("host:5000", login="u")
    store.save()
    assert (tmp_path / "credentials_relative.ini").is_file()


def test_save_cleans_up_temp_file_on_replace_error(tmp_path: Path) -> None:
    """save() removes the temp file and re-raises if os.replace() fails."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", login="u")

    with (
        patch("os.replace", side_effect=OSError("boom")),
        pytest.raises(OSError, match="boom"),
    ):
        store.save()
    # Only the (non-renamed) temp file(s) may remain; the target .ini must not exist.
    assert not ini_path.is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod only")  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def test_save_swallows_chmod_error(tmp_path: Path) -> None:
    """save() swallows OSError raised by os.chmod (e.g. unsupported filesystem)."""
    ini_path = tmp_path / "credentials.ini"
    store = TekHSICredentialStore(path=str(ini_path))
    store.set("host:5000", login="u")
    with patch("os.chmod", side_effect=OSError("boom")):
        store.save()  # Should not raise
    assert ini_path.is_file()
