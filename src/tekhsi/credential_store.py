"""File-based credential store for TekHSI TLS trust and Basic auth."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import stat
import sys
import tempfile

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME

try:
    from cryptography import x509 as _x509
    from cryptography.x509.oid import ExtensionOID as _ExtensionOID
    from cryptography.x509.oid import NameOID as _NameOID

    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - optional dependency
    _x509 = None  # type: ignore[assignment]
    _ExtensionOID = None  # type: ignore[assignment]
    _NameOID = None  # type: ignore[assignment]
    _HAS_CRYPTOGRAPHY = False

_OBFUSCATION_PREFIX = "obf1:"
_OBFUSCATION_KEY = b"tekhsi-credstore-v1"


def tls_server_name_from_pem(cert_pem: bytes) -> str | None:
    """Return TLS verification name from server cert PEM (SAN DNS, else CN)."""
    if not _HAS_CRYPTOGRAPHY:
        return None
    try:
        cert = _x509.load_pem_x509_certificate(cert_pem)
    except ValueError:
        return None
    try:
        san = cert.extensions.get_extension_for_oid(_ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        for name in san:
            if isinstance(name, _x509.DNSName):
                return str(name.value)
    except _x509.ExtensionNotFound:
        pass
    if attrs := cert.subject.get_attributes_for_oid(_NameOID.COMMON_NAME):
        return str(attrs[0].value)
    return None


def _default_store_path() -> str:
    r"""Default path per platform (Tektronix shared store).

    Linux:   ~/.tektronix/credentials.ini
    Windows: %APPDATA%\tektronix\credentials.ini
    macOS:   ~/Library/Application Support/tektronix/credentials.ini
    """
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(home)))
        return str(base / "tektronix" / "credentials.ini")
    if sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / "tektronix" / "credentials.ini")
    return str(home / ".tektronix" / "credentials.ini")


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _obscure_password(plain: str) -> str:
    """Reversible obfuscation (XOR + base64) for app-written passwords.

    Deters shoulder-surfing only; trivially reversible with this source. NOT encryption.
    """
    raw = _xor_bytes(plain.encode("utf-8"), _OBFUSCATION_KEY)
    return _OBFUSCATION_PREFIX + base64.b64encode(raw).decode("ascii")


def _reveal_password(stored: str | None) -> str | None:
    """Return usable cleartext.

    Untagged values are treated as hand-entered plaintext and returned verbatim,
    so a user can add a password to credentials.ini by typing it directly.
    """
    if stored is None:
        return None
    if not stored.startswith(_OBFUSCATION_PREFIX):
        return stored
    b64 = stored[len(_OBFUSCATION_PREFIX) :]
    try:
        raw = base64.b64decode(b64, validate=True)
        return _xor_bytes(raw, _OBFUSCATION_KEY).decode("utf-8")
    except ValueError:
        return stored


@dataclass
class CertInfo:
    """Certificate fingerprint and optional PEM for trust-on-first-use."""

    cert_fingerprint: str
    cert_pem: bytes | None = None
    tls_server_name: str | None = None

    @property
    def fingerprint(self) -> str:
        """Alias for cert_fingerprint (API doc naming)."""
        return self.cert_fingerprint

    @staticmethod
    def from_pem(cert_pem: bytes) -> CertInfo:
        """Build CertInfo from certificate PEM bytes (e.g. from TLS handshake)."""
        digest = hashlib.sha256(cert_pem).hexdigest()
        tls_name = tls_server_name_from_pem(cert_pem)
        return CertInfo(cert_fingerprint=digest, cert_pem=cert_pem, tls_server_name=tls_name)


class TekHSICredentialStore:
    """INI-backed store for per-host TLS trust and Basic-auth credentials."""

    def __init__(self, path: str | None = None) -> None:
        """Initialize store. Loads existing file if present, otherwise starts empty."""
        self._path = path or _default_store_path()
        self._data: dict[str, dict[str, str]] = {}
        self._certs_dir = str(Path(self._path).parent / "certs")
        self.load()

    def _normalize_host(self, host: str) -> str:
        """Normalize host for section key (e.g. ensure port if present)."""
        return host.strip().lower()

    def load(self) -> None:
        """Load store from file. No-op if file does not exist."""
        self._data = {}
        path = Path(self._path)
        if not path.is_file():
            return
        parser = ConfigParser()
        try:
            with path.open(encoding="utf-8") as f:
                parser.read_file(f)
        except OSError:
            return
        for section in parser.sections():
            host = self._normalize_host(section)
            self._data[host] = dict(parser[section])

    def save(self) -> None:
        """Write store atomically (temp + rename). Creates parent directory if needed."""
        target = Path(self._path)
        dirpath = target.parent
        if str(dirpath):
            dirpath.mkdir(parents=True, exist_ok=True)
        parser = ConfigParser()
        for host, opts in sorted(self._data.items()):
            parser[host] = opts
        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".ini.tmp",
            dir=str(dirpath) or ".",
            text=True,
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                parser.write(f)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(target)
        except OSError:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise
        if os.name != "nt":
            with contextlib.suppress(OSError):
                target.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def get(self, host: str) -> dict[str, str | None] | None:
        """Return entry for host or None if not found."""
        key = self._normalize_host(host)
        if not (raw := self._data.get(key)):
            return None
        return {
            "cert_fingerprint": raw.get("cert_fingerprint") or None,
            "cert_path": raw.get("cert_path") or None,
            "tls_server_name": raw.get("tls_server_name") or None,
            "login": raw.get("login") or None,
            "password": _reveal_password(raw.get("password") or None),
        }

    def set(
        self,
        host: str,
        cert_fingerprint: str | None = None,
        cert_path: str | None = None,
        tls_server_name: str | None = None,
        login: str | None = None,
        password: str | None = None,
    ) -> None:
        """Write or update entry for host. Omitted keys left unchanged; explicit None clears."""
        if (key := self._normalize_host(host)) not in self._data:
            self._data[key] = {}
        entry = self._data[key]
        if cert_fingerprint is not None:
            entry["cert_fingerprint"] = cert_fingerprint
        if cert_path is not None:
            entry["cert_path"] = cert_path
        if tls_server_name is not None:
            entry["tls_server_name"] = tls_server_name
        if login is not None:
            entry["login"] = login
        if password is not None:
            entry["password"] = _obscure_password(password) if password else ""
        for k in list(entry):
            if not entry[k]:
                del entry[k]

    def trust(
        self,
        host: str,
        cert_info: CertInfo,
        password: str | None = None,
        login: str | None = None,
    ) -> None:
        """Record trust for host: fingerprint, optional cert file, password, and optional login."""
        if password and login is None:
            login = DEFAULT_MODE3_USERNAME
        key = self._normalize_host(host)
        self.set(
            host,
            cert_fingerprint=cert_info.cert_fingerprint,
            tls_server_name=cert_info.tls_server_name,
            password=password or None,
            login=login,
        )
        if cert_info.cert_pem:
            certs_dir = Path(self._certs_dir)
            certs_dir.mkdir(parents=True, exist_ok=True)
            safe_name = key.replace(":", "_").replace("/", "_")
            cert_path = certs_dir / f"{safe_name}.pem"
            with cert_path.open("wb") as f:
                f.write(cert_info.cert_pem)
            self.set(host, cert_path=str(cert_path))

    def list_hosts(self) -> list[str]:
        """Return all stored host keys."""
        return sorted(self._data.keys())

    def remove(self, host: str) -> None:
        """Remove entry for host."""
        key = self._normalize_host(host)
        self._data.pop(key, None)


TekCredentialStore = TekHSICredentialStore
