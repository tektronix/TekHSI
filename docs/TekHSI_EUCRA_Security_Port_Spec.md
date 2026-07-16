# TekHSI EUCRA — Security (Auth + Cert + Credential Store) Port Specification

**Status:** Implementation-ready
**Source of truth:** `TekHSI_v2` (working code on `C:\Users\keith\Desktop\TekHSI_v2\`)
**Target:** `tekhsi_github_EUCRA` (`D:\Repo\tekhsi_github_EUCRA`, package root `src/tekhsi/`)
**Scope:** Port *only* the TLS/certificate trust, credential store, and HTTP-Basic ("token") authentication subsystem from v2 into EUCRA. Explicitly **exclude** all other v2 changes (capability negotiation, lazy stubs, parallel reads, additional data-plane stubs, etc.).

---

## 0. Why this document exists

The v2 client works and its security model is solid, but in v2 the auth/cert code is interleaved with experimental, unrelated features inside `connect.py`. This spec extracts the *security-only* surface so it can be dropped into EUCRA cleanly, with the entangled experimental code identified and excluded.

Everything in §3–§7 is verbatim working code lifted from v2 via the code index. Where v2's code is mixed with non-security features, §8 calls out exactly what to strip.

---

## 1. The three security modes (reference)

The ported subsystem must support the same three modes v2 supports:

1. **Mode 1 — Plain.** `grpc.insecure_channel` when a plaintext probe succeeds and policy allows (`require_tls=False`).
2. **Mode 2 — TLS only.** `grpc.ssl_channel_credentials` with a stored or explicit PEM. **No** `authorization` metadata.
3. **Mode 3 — TLS + HTTP Basic ("token").** TLS plus an `authorization: Basic <b64>` header. Store mode `"token"` or `TekHSICredentials.token(...)`.

Trust storage is **file-based INI + sidecar PEM only**. There is no OS keychain in this codebase.

**Naming convention (decision — resolve before coding):** In all *new* code, the secret is the **password** carried via HTTP **Basic** auth. The word **`token`** is preserved only in the existing public API (`TekHSICredentials.token(...)`, store mode `"token"`) for backward compatibility. Do not introduce new "token" vocabulary in helpers, logs, or variables.

This creates a deliberate tension with the verbatim v2 copies below, which *do* contain legacy "token" naming — the method `_upgrade_channel_with_token_after_unauthenticated` and the error string `"Server requires a token; ..."` (§8.4). **Recommended resolution:** keep the public API name `TekHSICredentials.token()` (callers depend on it) and keep the internal method name `_upgrade_channel_with_token_after_unauthenticated` (private, aids v2 traceability), but **reword user-facing log/error strings** that say "token" to "password" since those are what end users read. Whichever way you decide, decide it explicitly — the inline `PORT CHANGE`/verbatim markers tell you which strings are v2-original so you can find and reword them. Implementers should not be left guessing.

---

## 2. Files to create vs. modify in EUCRA

| Action | Path (EUCRA) | Contents |
|--------|--------------|----------|
| **Create** | `src/tekhsi/auth_basic.py` | §3 — Basic-auth value builder/parser + `DEFAULT_MODE3_USERNAME` |
| **Create** | `src/tekhsi/credential_store.py` | §4 — `CertInfo`, `TekHSICredentialStore`, `tls_server_name_from_pem`, `_default_store_path` |
| **Create** | `src/tekhsi/security.py` *(recommended new home)* | §5 (exceptions), §6 (channel/negotiation helpers), §7 (`TekHSICredentials`). In v2 these live at the top of `connect.py`; isolating them in EUCRA keeps the security unit self-contained and avoids importing v2's other `connect.py` changes. |
| **Modify** | `src/tekhsi/tek_hsi_connect.py` | §8 — new `__init__` params + channel branch; `_connect` UNAUTHENTICATED upgrade; new method `_upgrade_channel_with_token_after_unauthenticated`; store `_credential_store_ref`/`_on_trust_ref`/`_auto_security` |
| **Modify** | `src/tekhsi/__init__.py` | §9 — export the public security symbols |

> **Import-path note.** v2 uses a flat `tekhsi` package. EUCRA's source lives under `src/tekhsi/` on disk but is installed/imported as the top-level package `tekhsi` (src-layout). So **file paths** in this spec are `src/tekhsi/...`, but **import statements** must use `tekhsi.*` (e.g. `from tekhsi.security import ...`), matching every existing import in EUCRA — *not* `src.tekhsi.*`, which would break at runtime and fail lint/type-check. The code bodies below are shown as they exist in v2; only the flat-vs-`tekhsi` import prefixes apply.

---

## 3. `auth_basic.py` (standalone — copy as-is)

Dependencies: `base64`, `binascii`, `typing`. No internal dependencies. This is the safest module to move.

```python
import base64
import binascii
from typing import Optional, Tuple

DEFAULT_MODE3_USERNAME = "tektronix"


def build_basic_authorization_value(username: str, password: str) -> str:
    """Return the full value for the ``authorization`` metadata key: ``Basic <b64>``."""
    pair = f"{username}:{password}".encode("utf-8")
    b64 = base64.b64encode(pair).decode("ascii")
    return f"Basic {b64}"


def parse_basic_authorization(header_value: str) -> Optional[Tuple[str, str]]:
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
```

| Symbol | Role |
|--------|------|
| `DEFAULT_MODE3_USERNAME` | `"tektronix"` — used when the store omits `login`, or a password is stored without a login. |
| `build_basic_authorization_value(username, password)` | Returns the **value only** (no key): `Basic <base64(UTF-8 "user:password")>`. This is the client send path. |
| `parse_basic_authorization(header_value)` | Server/test helper. **Not** used on the client send path; include it for symmetry/tests only. |

---

## 4. `credential_store.py` (standalone — copy as-is)

Dependencies: `os`, `sys`, `stat`, `hashlib`, `tempfile`, `configparser.ConfigParser`, `dataclasses`, `typing`, and **`cryptography`** (optional but required for TLS server-name extraction; see note). Imports `DEFAULT_MODE3_USERNAME` from `auth_basic`.

> **`cryptography` dependency.** `tls_server_name_from_pem` imports `cryptography.x509`. If `cryptography` is not installed it degrades gracefully (returns `None`), but TLS-name override for IP/.local hosts (§6) will not work — meaning TLS to an instrument addressed by IP (the common case) would fail hostname verification. **Add `cryptography` to EUCRA's `pyproject.toml` runtime dependencies (the `[project].dependencies` / `dependencies = [...]` array), not just dev/test extras.** It is not currently declared. Pin a minimum version consistent with what v2 was validated against.

### 4.1 `tls_server_name_from_pem` (module-level helper)

```python
def tls_server_name_from_pem(cert_pem: bytes) -> Optional[str]:
    """Return TLS verification name from server cert PEM (SAN DNS, else CN)."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID, NameOID
    except ImportError:
        return None
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except ValueError:
        return None
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        for name in san:
            if isinstance(name, x509.DNSName):
                return str(name.value)
    except x509.ExtensionNotFound:
        pass
    attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if attrs:
        return str(attrs[0].value)
    return None
```

### 4.2 `_default_store_path` (module-level helper)

```python
def _default_store_path() -> str:
    """Default path per platform (Tektronix shared store).

    Linux:   ~/.tektronix/credentials.ini
    Windows: %APPDATA%\\tektronix\\credentials.ini
    macOS:   ~/Library/Application Support/tektronix/credentials.ini
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "tektronix", "credentials.ini")
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "tektronix",
            "credentials.ini",
        )
    return os.path.join(os.path.expanduser("~"), ".tektronix", "credentials.ini")
```

### 4.2a Password obfuscation (module-level — PORT ADDITION, deviates from v2)

> **This is a deliberate deviation from working v2, which stores passwords as raw plaintext** (v2 doc §3.8 explicitly defers at-rest protection). This port obscures **app-written** passwords with a reversible XOR+base64 scheme.
>
> **Honesty label — this is obfuscation, not security.** The XOR pad is a fixed constant in the source. Anyone with the code (it's open) can reverse an `obf1:` value in seconds. This deters shoulder-surfing and keeps the password from sitting in literally-readable form in the INI; it provides **no** protection against an attacker who has the file *and* the library. Real at-rest protection requires an OS keystore (DPAPI / Keychain / Secret Service), which is out of scope here. The actual security boundary remains OS user isolation (`%APPDATA%` / `~/.tektronix` + `chmod 0600`).

```python
_OBFUSCATION_PREFIX = "obf1:"              # marks an APP-written (obscured) value
_OBFUSCATION_KEY = b"tekhsi-credstore-v1"  # fixed XOR pad; NOT a secret, NOT security


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _obscure_password(plain: str) -> str:
    """Reversible obfuscation (XOR + base64) for app-written passwords.

    Deters shoulder-surfing only; trivially reversible with this source. NOT encryption.
    """
    raw = _xor_bytes(plain.encode("utf-8"), _OBFUSCATION_KEY)
    return _OBFUSCATION_PREFIX + base64.b64encode(raw).decode("ascii")


def _reveal_password(stored: Optional[str]) -> Optional[str]:
    """Return usable cleartext.

    Untagged values are treated as hand-entered plaintext and returned verbatim,
    so a user can add a password to credentials.ini by typing it directly.
    """
    if stored is None:
        return None
    if not stored.startswith(_OBFUSCATION_PREFIX):
        return stored  # user typed it by hand — accept as-is
    b64 = stored[len(_OBFUSCATION_PREFIX):]
    try:
        raw = base64.b64decode(b64, validate=True)
        return _xor_bytes(raw, _OBFUSCATION_KEY).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return stored  # malformed tag — treat literally rather than lose the value
```

Add `import base64, binascii` to `credential_store.py`.

**Design contract (manual-edit friendly):**

- The **app** only ever writes obscured values (`set()` calls `_obscure_password`). App-written passwords appear as `password = obf1:...`.
- A **user** may hand-edit `credentials.ini` and type a password in **cleartext**. The store reads it (`get()` → `_reveal_password` returns it verbatim) and **never rewrites it**. The `obf1:` tag distinguishes the two; its *absence* means "human-entered plaintext."
- The store does **not** auto-convert a user's cleartext to `obf1:` on load or save. A hand-typed value only becomes obscured if the *app itself* later calls `set(password=...)` for that host — legitimately app-written data at that point. This honors "never touch what the user typed."

### 4.3 `CertInfo` (dataclass at line 63 in v2)

`CertInfo` is a dataclass. Its field set is fully constrained by the working call sites (`from_pem` passes all three; `_resolve_credentials_from_store` passes only `cert_fingerprint`, so the other two need defaults):

```python
@dataclass
class CertInfo:
    cert_fingerprint: str
    cert_pem: Optional[bytes] = None
    tls_server_name: Optional[str] = None
```

(Confirm the exact decorator/field metadata against v2 `credential_store.py:63–70` — see §12 note — but this is the only shape consistent with all callers.) The methods (verified verbatim):

```python
    @property
    def fingerprint(self) -> str:
        """Alias for cert_fingerprint (API doc naming)."""
        return self.cert_fingerprint

    @staticmethod
    def from_pem(cert_pem: bytes) -> "CertInfo":
        """Build CertInfo from certificate PEM bytes (e.g. from TLS handshake)."""
        digest = hashlib.sha256(cert_pem).hexdigest()
        tls_name = tls_server_name_from_pem(cert_pem)
        return CertInfo(cert_fingerprint=digest, cert_pem=cert_pem, tls_server_name=tls_name)
```

Fingerprint is the **SHA-256 hex digest of the certificate PEM bytes**.

### 4.4 `TekHSICredentialStore`

Backed by `ConfigParser`, UTF-8, one INI section per host endpoint. Sidecar PEMs are written to a `certs/` directory next to the INI.

**Section keys** (`_normalize_host`): `host.strip().lower()` — the full `host:port` string as passed, lowercased.

**Per-section options:** `cert_fingerprint`, `cert_path`, `tls_server_name`, `login`, `password`.

```python
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or _default_store_path()
        self._data: Dict[str, Dict[str, str]] = {}
        self._certs_dir = os.path.join(os.path.dirname(self._path), "certs")
        self.load()

    def _normalize_host(self, host: str) -> str:
        """Normalize host for section key (e.g. ensure port if present)."""
        return host.strip().lower()

    def load(self) -> None:
        """Load store from file. No-op if file does not exist."""
        self._data = {}
        if not os.path.isfile(self._path):
            return
        parser = ConfigParser()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                parser.read_file(f)
        except OSError:
            return
        for section in parser.sections():
            host = self._normalize_host(section)
            self._data[host] = dict(parser[section])

    def save(self) -> None:
        """Write store atomically (temp + rename). Creates parent directory if needed."""
        dirpath = os.path.dirname(self._path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        parser = ConfigParser()
        for host, opts in sorted(self._data.items()):
            parser[host] = opts
        fd, tmp_path = tempfile.mkstemp(
            suffix=".ini.tmp",
            dir=dirpath or ".",
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                parser.write(f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        if os.name != "nt":
            try:
                os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    def get(self, host: str) -> Optional[Dict[str, Optional[str]]]:
        """Return entry for host (cert_fingerprint, cert_path, tls_server_name, login, password). None if not found.

        PORT CHANGE: password is revealed via _reveal_password so callers always
        receive usable cleartext, whether the stored value was app-obscured (obf1:)
        or hand-entered plaintext.
        """
        key = self._normalize_host(host)
        raw = self._data.get(key)
        if raw is None:
            return None
        return {
            "cert_fingerprint": raw.get("cert_fingerprint") or None,
            "cert_path": raw.get("cert_path") or None,
            "tls_server_name": raw.get("tls_server_name") or None,
            "login": raw.get("login") or None,
            "password": _reveal_password(raw.get("password") or None),  # PORT CHANGE
        }

    def set(
        self,
        host: str,
        cert_fingerprint: Optional[str] = None,
        cert_path: Optional[str] = None,
        tls_server_name: Optional[str] = None,
        login: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Write or update entry for host. Omitted keys left unchanged; explicit None clears.

        PORT CHANGE: a non-empty password (always app-written here) is stored obscured
        as obf1:... . Empty string still clears the key (unchanged from v2).
        """
        key = self._normalize_host(host)
        if key not in self._data:
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
            # PORT CHANGE: obscure app-written passwords; "" falls through to the
            # empty-clears loop below and deletes the key.
            entry["password"] = _obscure_password(password) if password != "" else ""
        for k in list(entry):
            if entry[k] == "":
                del entry[k]

    def trust(
        self,
        host: str,
        cert_info: CertInfo,
        password: Optional[str] = None,
        login: Optional[str] = None,
    ):
        """Record trust for host: fingerprint, optional cert file, password, and optional Basic-auth login."""
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
            os.makedirs(self._certs_dir, exist_ok=True)
            safe_name = key.replace(":", "_").replace("/", "_")
            cert_path = os.path.join(self._certs_dir, f"{safe_name}.pem")
            with open(cert_path, "wb") as f:
                f.write(cert_info.cert_pem)
            self.set(host, cert_path=cert_path)
```

Also present in v2 (verified verbatim) — copy for completeness:

```python
    def list_hosts(self) -> List[str]:
        """Return all stored host keys."""
        return sorted(self._data.keys())

    def remove(self, host: str) -> None:
        """Remove entry for host."""
        key = self._normalize_host(host)
        self._data.pop(key, None)
```

**Atomicity & permissions:** `save()` writes to a temp file, `fsync`s, then `os.replace` (atomic rename). On non-Windows it `chmod 0600`. PEMs and any hand-entered passwords are stored as written; app-written passwords are obscured (`obf1:`, §4.2a) — but obscuration is **not** a security control. On Windows, OS user isolation under `%APPDATA%` is the real boundary.

### 4.5 Example `credentials.ini`

App-written entry (password obscured by the library):

```ini
[192.168.1.50:5000]
cert_fingerprint = 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
cert_path = C:\Users\keith\AppData\Roaming\tektronix\certs\192.168.1.50_5000.pem
tls_server_name = MSO58B-ABC123
login = tektronix
password = obf1:Bx5eX1tcWw==
```

**Adding a password by hand.** A user who has already trusted an instrument's cert (so `cert_path`/`cert_fingerprint` exist) can enable Mode 3 by editing the section and typing the password in **cleartext** — no tag, no encoding:

```ini
[192.168.1.50:5000]
cert_fingerprint = 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
cert_path = C:\Users\keith\AppData\Roaming\tektronix\certs\192.168.1.50_5000.pem
tls_server_name = MSO58B-ABC123
login = tektronix
password = MyServerPassword
```

On the next connect the store reads the cleartext via `_reveal_password` (untagged ⇒ returned verbatim), `_auto_negotiate_channel` sees `entry["password"]` and builds Mode-3 credentials, and the connection authenticates. The store **leaves the hand-typed value exactly as written** — it is never re-obscured. (If the user wants to set `login` too, they add a `login = ...` line; if omitted, `DEFAULT_MODE3_USERNAME` = `tektronix` is used at send time.) To create a brand-new host section entirely by hand, the user must also supply a valid `cert_path` pointing to the server's PEM (and ideally `cert_fingerprint`), since Mode 2/3 channel build requires it.

---

## 5. Security exceptions (`security.py`)

From v2 `connect.py` lines 100–146. **Verified verbatim from working code.** `TekSecurityError` is a bare base; the three subclasses have real `__init__` bodies that set attributes and build formatted messages. Catching `TekSecurityError` catches all subclasses.

```python
class TekSecurityError(Exception):
    """Base class for all security-related errors."""
    pass


class TekUnknownInstrument(TekSecurityError):
    """Instrument not in credential store, no callback provided."""

    def __init__(self, host: str, cert_info: CertInfo) -> None:
        self.host = host
        self.cert_info = cert_info
        fp = cert_info.cert_fingerprint
        msg = (
            f"Unknown instrument {host}\n"
            f"  Fingerprint: {fp[:16]}...\n"
            f"  Provide on_trust_prompt callback or trust via TekCredentialStore."
            if fp
            else f"Unknown instrument {host}. Provide on_trust_prompt or TekCredentialStore."
        )
        super().__init__(msg)


class TekCertificateMismatch(TekSecurityError):
    """Stored fingerprint doesn't match server certificate."""

    def __init__(self, host: str, stored_fingerprint: str, current_fingerprint: str) -> None:
        self.host = host
        self.stored_fingerprint = stored_fingerprint
        self.current_fingerprint = current_fingerprint
        super().__init__(
            f"Certificate mismatch for {host}.\n"
            f"  Stored:  {stored_fingerprint[:24]}...\n"
            f"  Current: {current_fingerprint[:24]}...\n"
            f"  If the instrument was reconfigured, remove and re-trust it."
        )


class TekAuthenticationFailed(TekSecurityError):
    """Password rejected or missing."""

    def __init__(self, host: str, message: str) -> None:
        self.host = host
        super().__init__(f"{host}: {message}")
```

> **Public attributes:** `TekUnknownInstrument.cert_info` (a `CertInfo`, exposing `.fingerprint`/`.cert_fingerprint`), `TekCertificateMismatch.stored_fingerprint`/`.current_fingerprint`, and `.host` on all three.

---

## 6. Channel + negotiation helpers (`security.py`)

These module-level functions are the heart of the subsystem. Copy verbatim. Dependencies: `ssl`, `socket`, `ipaddress`, `uuid`, `time`, `grpc`, plus `ConnectStub`/`ConnectRequest` from EUCRA's generated gRPC modules, and the store/exception/auth symbols above.

### 6.1 Host parsing & TLS-name resolution

```python
def _parse_host_port(host_port: str) -> Tuple[str, int]:
    s = host_port.strip()
    if s.startswith("["):
        end = s.index("]")
        host = s[1:end]
        if len(s) > end + 1 and s[end + 1] == ":":
            return host, int(s[end + 2 :])
        return host, 5000
    if ":" in s:
        host, port_str = s.rsplit(":", 1)
        return host, int(port_str)
    return s, 5000


def _is_ip_literal(host: str) -> bool:
    """True if host is an IPv4 or IPv6 address literal (not a DNS name)."""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def _tls_server_name_for_entry(entry: Dict[str, Optional[str]]) -> Optional[str]:
    name = entry.get("tls_server_name")
    if name:
        return name
    cert_path = entry.get("cert_path")
    if not cert_path:
        return None
    try:
        with open(cert_path, "rb") as f:
            return tls_server_name_from_pem(f.read())
    except OSError:
        return None


def _tls_channel_options(connect_host: str, tls_server_name: Optional[str]) -> Tuple[Tuple[str, str], ...]:
    """gRPC channel options when URL host differs from the cert name (IP or .local)."""
    if not tls_server_name:
        return ()
    cert_name = tls_server_name.strip()
    host = connect_host.strip()
    host_lower = host.lower()
    cert_lower = cert_name.lower()
    if host_lower == cert_lower:
        return ()
    if host_lower == cert_lower + ".local":
        return (("grpc.ssl_target_name_override", cert_name),)
    if host_lower.endswith(".local") and host_lower[: -len(".local")] == cert_lower:
        return (("grpc.ssl_target_name_override", cert_name),)
    if _is_ip_literal(host):
        return (("grpc.ssl_target_name_override", cert_name),)
    if host_lower != cert_lower:
        return (("grpc.ssl_target_name_override", cert_name),)
    return ()
```

### 6.2 Secure channel construction

```python
def _secure_channel(
    url: str,
    creds: grpc.ChannelCredentials,
    entry: Optional[Dict[str, Optional[str]]] = None,
    tls_server_name: Optional[str] = None,
) -> grpc.Channel:
    host, _ = _parse_host_port(url)
    if tls_server_name is None and entry is not None:
        tls_server_name = _tls_server_name_for_entry(entry)
    opts = _tls_channel_options(host, tls_server_name)
    if opts:
        return grpc.secure_channel(url, creds, options=opts)
    return grpc.secure_channel(url, creds)
```

### 6.3 Credentials from a store entry (Mode 2 / Mode 3)

```python
def _build_creds_from_entry(entry: Dict[str, Optional[str]], mode: str) -> grpc.ChannelCredentials:
    """Build gRPC credentials from a store entry (must have cert_path)."""
    ca_path = entry.get("cert_path")
    if not ca_path:
        raise ValueError("Store entry missing cert_path")
    with open(ca_path, "rb") as f:
        root = f.read()
    if mode == "token":
        password = entry.get("password") or ""
        login = entry.get("login") or DEFAULT_MODE3_USERNAME
        ssl_creds = grpc.ssl_channel_credentials(root_certificates=root)
        def meta_cb(ctx, cb):
            val = build_basic_authorization_value(login, password)
            cb((("authorization", val),), None)
        return grpc.composite_channel_credentials(ssl_creds, grpc.metadata_call_credentials(meta_cb))
    return grpc.ssl_channel_credentials(root_certificates=root)
```

### 6.4 TOFU cert fetch + plaintext probe

```python
def _fetch_server_cert(host: str, port: int, timeout: float = 5.0) -> CertInfo:
    """Connect via TLS without verification and return server cert info (for TOFU)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
    if not der:
        raise ConnectionError("Server did not present a certificate")
    pem = ssl.DER_cert_to_PEM_cert(der)
    return CertInfo.from_pem(pem.encode() if isinstance(pem, str) else pem)


def _try_plain_grpc_channel(url: str, deadline: float) -> Optional[grpc.Channel]:
    """If the server accepts plain gRPC Connect, return a new insecure channel; else None.

    Used so Mode 1 (plain) still works when the credential store has a stale TLS entry
    for the same host:port (otherwise we would TLS-handshake a plaintext port and get
    SSL WRONG_VERSION_NUMBER).
    """
    ch = grpc.insecure_channel(url)
    probe = str(uuid.uuid4())
    try:
        rem = max(0.5, deadline - time.time())
        if rem <= 0:
            try:
                ch.close()
            except Exception:
                pass
            return None
        stub = ConnectStub(ch)
        stub.Connect(ConnectRequest(name=probe), timeout=rem)
        try:
            stub.Disconnect(ConnectRequest(name=probe), timeout=min(rem, 3.0))
        except grpc.RpcError:
            pass
    except grpc.RpcError:
        try:
            ch.close()
        except Exception:
            pass
        return None
    except Exception:
        try:
            ch.close()
        except Exception:
            pass
        return None
    else:
        try:
            ch.close()
        except Exception:
            pass
        return grpc.insecure_channel(url)
```

### 6.5 TOFU callback invocation

The `on_trust_prompt` callback supports two signatures — `(host, cert_info)` or `(host, cert_info, auth_required)` — dispatched by arity:

```python
def _call_on_trust(cb: Callable[..., Any], host_port: str, cert_info: CertInfo, auth_required: bool):
    """Invoke on_trust_prompt with (host, cert_info) or (host, cert_info, auth_required)."""
    import inspect
    try:
        sig = inspect.signature(cb)
        if len(sig.parameters) >= 3:
            return cb(host_port, cert_info, auth_required)
    except TypeError:
        pass
    return cb(host_port, cert_info)
```

**Return shapes** (`auth_required=False`, first trust / TOFU):

| Return | Meaning |
|--------|---------|
| `True` | Trust cert, Mode 2 (no password). |
| `(True, password)` | Trust cert + store password; login defaults to `tektronix`. Mode 3. |
| `(True, password, login)` | Trust cert + store password + explicit login. Mode 3. |
| `False` / anything else | Decline → `TekUnknownInstrument`. |

When `auth_required=True` (server returned `UNAUTHENTICATED` on an already-trusted TLS cert), only the `(True, password[, login])` shapes are meaningful; returning `True` alone or declining raises `TekAuthenticationFailed`.

### 6.6 Store resolution (explicit store-based credentials)

```python
def _resolve_credentials_from_store(
    host_port: str,
    store: "TekHSICredentialStore",
    mode: str,
    on_trust_prompt: Optional[Callable[..., Union[bool, Tuple[bool, Optional[str]]]]],
    deadline: float,
):
    """Resolve gRPC credentials from store or TOFU."""
    host, port = _parse_host_port(host_port)
    if time.time() > deadline:
        raise TekSecurityError(
            f"Connection to {host_port} timed out during security negotiation."
        )
    entry = store.get(host_port)
    if entry and entry.get("cert_path"):
        tmo = max(0.5, min(5.0, deadline - time.time()))
        live = _fetch_server_cert(host, port, tmo)
        fp = entry.get("cert_fingerprint")
        if fp and live.cert_fingerprint != fp:
            raise TekCertificateMismatch(host_port, fp, live.cert_fingerprint)
        return _build_creds_from_entry(entry, mode)
    try:
        tmo = max(0.5, min(5.0, deadline - time.time()))
        cert_info = _fetch_server_cert(host, port, tmo)
    except Exception as e:
        raise TekUnknownInstrument(host_port, CertInfo(cert_fingerprint="")) from e
    if on_trust_prompt:
        result = _call_on_trust(on_trust_prompt, host_port, cert_info, False)
        if result is True:
            store.trust(host_port, cert_info, password=None)
            store.save()
        elif isinstance(result, (list, tuple)) and len(result) >= 1 and result[0]:
            password = result[1] if len(result) > 1 else None
            login = result[2] if len(result) > 2 else None
            if login == "":
                login = None
            store.trust(host_port, cert_info, password=password, login=login)
            store.save()
        else:
            raise TekUnknownInstrument(host_port, cert_info)
    else:
        raise TekUnknownInstrument(host_port, cert_info)
    entry = store.get(host_port)
    if not entry or not entry.get("cert_path"):
        raise TekUnknownInstrument(host_port, cert_info)
    return _build_creds_from_entry(entry, mode)
```

### 6.7 Auto-negotiation (`credentials=None`)

```python
def _auto_negotiate_channel(
    url: str,
    store: "TekHSICredentialStore",
    on_trust_prompt: Optional[Callable[..., Any]],
    require_tls: bool,
    deadline: float,
    timeout: float,
):
    """Pick insecure or TLS channel when credentials=None (auto-negotiation)."""
    host, port = _parse_host_port(url)
    entry = store.get(url)

    if entry and entry.get("cert_path"):
        if not require_tls:
            plain = _try_plain_grpc_channel(url, deadline)
            if plain is not None:
                return plain
        tmo = max(0.5, min(8.0, deadline - time.time()))
        live = _fetch_server_cert(host, port, tmo)
        fp = entry.get("cert_fingerprint")
        if fp and live.cert_fingerprint != fp:
            raise TekCertificateMismatch(url, fp, live.cert_fingerprint)
        if entry.get("password"):
            return _secure_channel(url, _build_creds_from_entry(entry, "token"), entry=entry)
        return _secure_channel(url, _build_creds_from_entry(entry, "tls"), entry=entry)

    if not require_tls:
        plain = _try_plain_grpc_channel(url, deadline)
        if plain is not None:
            return plain
        rem = max(0.5, deadline - time.time())
        if rem <= 0:
            raise TekSecurityError(
                f"Connection to {url} timed out during security negotiation ({timeout}s)."
            )
    else:
        if not on_trust_prompt:
            raise TekSecurityError(
                f"TLS required but cannot establish secure connection to {url}. "
                f"Instrument not in credential store. Use on_trust_prompt or populate the store."
            )

    if time.time() > deadline:
        raise TekSecurityError(
            f"Connection to {url} timed out during security negotiation ({timeout}s)."
        )
    tmo = max(0.5, min(8.0, deadline - time.time()))
    cert_info = _fetch_server_cert(host, port, tmo)
    if not on_trust_prompt:
        raise TekUnknownInstrument(url, cert_info)
    result = _call_on_trust(on_trust_prompt, url, cert_info, False)
    if result is True:
        store.trust(url, cert_info, password=None)
        store.save()
    elif isinstance(result, (list, tuple)) and len(result) >= 1 and result[0]:
        pwd = result[1] if len(result) > 1 else None
        login = result[2] if len(result) > 2 else None
        if login == "":
            login = None
        store.trust(url, cert_info, password=pwd, login=login)
        store.save()
    else:
        raise TekUnknownInstrument(url, cert_info)
    entry = store.get(url)
    if not entry or not entry.get("cert_path"):
        raise TekUnknownInstrument(url, cert_info)
    if entry.get("password"):
        return _secure_channel(url, _build_creds_from_entry(entry, "token"), entry=entry)
    return _secure_channel(url, _build_creds_from_entry(entry, "tls"), entry=entry)
```

---

## 7. `TekHSICredentials` (explicit API, `security.py`)

The user-facing builder. `tls()`/`token()` are static factory methods; with no args they return a deferred "use the store" marker that `TekHSIConnect.__init__` resolves.

```python
class TekHSICredentials:
    def __init__(
        self,
        channel_credentials: Optional[grpc.ChannelCredentials] = None,
        _use_store: bool = False,
        _store_mode: str = "tls",
        _tls_server_name: Optional[str] = None,
    ):
        self._channel_credentials = channel_credentials
        self._use_store = _use_store
        self._store_mode = _store_mode
        self._tls_server_name = _tls_server_name

    @staticmethod
    def tls(ca_cert_path: Optional[str] = None) -> "TekHSICredentials":
        """Build credentials for Mode 2 (TLS only).

        With ca_cert_path: trust the server using that CA/server cert.
        With no args: resolve from credential_store (use with TekHSIConnect(
        credential_store=..., on_trust_prompt=...)).
        """
        if ca_cert_path is None:
            return TekHSICredentials(None, _use_store=True, _store_mode="tls")
        with open(ca_cert_path, "rb") as f:
            root_certificates = f.read()
        creds = grpc.ssl_channel_credentials(root_certificates=root_certificates)
        tls_name = tls_server_name_from_pem(root_certificates)
        return TekHSICredentials(creds, _tls_server_name=tls_name)

    @staticmethod
    def token(
        ca_cert_path: Optional[str] = None,
        token: Optional[str] = None,
        username: Optional[str] = None,
    ):
        """Build credentials for Mode 3 (TLS + HTTP Basic client auth).

        With ca_cert_path and token: Basic auth with ``username`` (default: tektronix) and password ``token``.
        With no args: resolve cert, login, and password from credential_store.
        """
        if ca_cert_path is None and token is None:
            return TekHSICredentials(None, _use_store=True, _store_mode="token")
        if ca_cert_path is None or token is None:
            raise ValueError("token() requires both ca_cert_path and token, or neither (use store)")
        with open(ca_cert_path, "rb") as f:
            root_certificates = f.read()
        ssl_creds = grpc.ssl_channel_credentials(root_certificates=root_certificates)
        user = username if username is not None else DEFAULT_MODE3_USERNAME

        def metadata_cb(context, callback):
            callback(
                (("authorization", build_basic_authorization_value(user, token)),),
                None,
            )

        auth_creds = grpc.metadata_call_credentials(metadata_cb)
        composite = grpc.composite_channel_credentials(ssl_creds, auth_creds)
        tls_name = tls_server_name_from_pem(root_certificates)
        return TekHSICredentials(composite, _tls_server_name=tls_name)

    def _grpc_credentials(self) -> grpc.ChannelCredentials:
        """Return the underlying gRPC channel credentials (for TekHSIConnect)."""
        if self._channel_credentials is None:
            raise ValueError("Store-based credentials must be resolved via credential_store")
        return self._channel_credentials
```

### 7.1 gRPC metadata pattern (Mode 3) — exact requirements

- Use `grpc.metadata_call_credentials` with a `meta_cb(context, callback)` that calls `callback(((key, value),), None)`.
- The **first arg** to `callback` is a **tuple of tuples**, each `(metadata_key, metadata_value)` — both `str`. Do **not** pass a list.
- The metadata key **must be lowercase** `"authorization"`.
- The **second arg** to `callback` is `None`.
- `composite_channel_credentials` order is **TLS first, then metadata**: `grpc.composite_channel_credentials(ssl_creds, grpc.metadata_call_credentials(meta_cb))`.

---

## 8. Wiring into EUCRA's `TekHSIConnect` (`tek_hsi_connect.py`)

This is the only real integration work. EUCRA's current `__init__` (line 114) hardcodes `self.channel = grpc.insecure_channel(url)`; `_connect` (line 666) does a single unconditional `Connect`.

### 8.1 New `__init__` signature

Add five parameters after the existing `data_filter`:

```python
def __init__(
    self,
    url: str,
    activesymbols: list[str] | None = None,
    callback: Callable | None = None,
    data_filter: Callable | None = None,
    credentials: Optional[Union[grpc.ChannelCredentials, TekHSICredentials]] = None,
    credential_store: Optional[TekHSICredentialStore] = None,
    on_trust_prompt: Optional[Callable[..., Union[bool, Tuple[bool, Optional[str]]]]] = None,
    require_tls: bool = False,
    timeout: float = 10.0,
):
```

### 8.2 Replace the channel-construction line

EUCRA today:

```python
self.channel = grpc.insecure_channel(url)
```

Replace with the negotiation block below, **wrapped in the legacy guard from §8.6(b)** so it only runs for security-opted-in callers (drop in **before** `self.clientname = ...`). Note: EUCRA's class lacks the `TekCredentialStore` alias used in v2; either import `TekHSICredentialStore` under that name or substitute directly. The `else:` branch shown here is the `else` of the §8.6(b) `if _legacy_plain:` guard:

```python
deadline = time.time() + max(1.0, float(timeout))
store_for_auto = credential_store if credential_store is not None else TekHSICredentialStore()

if credentials is not None:
    if isinstance(credentials, TekHSICredentials) and getattr(credentials, "_use_store", False):
        if credential_store is None:
            raise ValueError("credential_store is required when credentials use the store")
        creds = _resolve_credentials_from_store(
            url, credential_store, credentials._store_mode, on_trust_prompt, deadline
        )
        entry = credential_store.get(url)
        self.channel = _secure_channel(url, creds, entry=entry)
        self._credential_store_ref = credential_store
        self._on_trust_ref = on_trust_prompt
        self._auto_security = True
    else:
        if isinstance(credentials, TekHSICredentials):
            creds = credentials._grpc_credentials()
        else:
            creds = credentials
        tls_name = (
            credentials._tls_server_name
            if isinstance(credentials, TekHSICredentials)
            else None
        )
        self.channel = _secure_channel(url, creds, tls_server_name=tls_name)
        self._credential_store_ref = store_for_auto
        self._on_trust_ref = None
        self._auto_security = False
else:
    self.channel = _auto_negotiate_channel(
        url, store_for_auto, on_trust_prompt, require_tls, deadline, timeout
    )
    self._credential_store_ref = store_for_auto
    self._on_trust_ref = on_trust_prompt
    self._auto_security = True
```

The three instance attributes `_credential_store_ref`, `_on_trust_ref`, `_auto_security` are consumed by the `_connect` upgrade path (§8.3).

### 8.3 `_connect` — UNAUTHENTICATED upgrade

EUCRA's current `_connect`:

```python
def _connect(self) -> None:
    """Request connect to the gRCP server."""
    _logger.debug("connect")
    request = ConnectRequest(name=self.clientname)
    self.connection.Connect(request)
```

Replace the body with the retry/upgrade loop. **STRIP the capability-capture lines** (`self._protocol_version`, `self._capabilities` and the associated logging) — those belong to v2's *experimental capability-negotiation feature*, which is out of scope for this port:

```python
def _connect(self) -> None:
    """Connect to the gRPC server, upgrading to Mode 3 if the server demands auth."""
    _logger.debug("connect")
    request = ConnectRequest(name=self.clientname)
    upgrade_done = False
    while True:
        try:
            self.connection.Connect(request)
        except grpc.RpcError as e:
            if (
                e.code() == grpc.StatusCode.UNAUTHENTICATED
                and getattr(self, "_auto_security", False)
                and not upgrade_done
            ):
                self._upgrade_channel_with_token_after_unauthenticated()
                upgrade_done = True
                continue
            if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                detail = (e.details() or "").strip() or "UNAUTHENTICATED"
                if upgrade_done:
                    detail = (
                        f"{detail} "
                        "(Check Mode 3 password matches the server's --password; "
                        f"Basic username defaults to {DEFAULT_MODE3_USERNAME}.)"
                    )
                raise TekAuthenticationFailed(self.url, detail) from e
            raise
        return
```

> After upgrade, both `self.connection` (ConnectStub) **and** `self.native` (NativeDataStub) are rebound to the new authenticated channel inside `_upgrade_channel_with_token_after_unauthenticated` (§8.4), so the `continue` retries `Connect` on the upgraded channel and later data-plane RPCs also carry the Basic-auth metadata.
>
> **Init-ordering safety (holds in EUCRA today):** `_connect()` is called inside `__init__` *before* `_available_symbols()` and *before* the background `_run` thread is started. So the entire upgrade — including the channel/stub rebind — completes before any other code touches `self.channel`/`self.native`. Preserve that ordering: keep the `self._connect()` call where EUCRA has it (after stub construction, before `_available_symbols()` and `thread.start()`). If you ever move stub creation or symbol enumeration earlier, re-check that they don't run against the pre-upgrade channel.

### 8.4 New method `_upgrade_channel_with_token_after_unauthenticated`

Copy verbatim into the `TekHSIConnect` class:

```python
def _upgrade_channel_with_token_after_unauthenticated(self) -> None:
    """After Connect returns UNAUTHENTICATED on TLS (cert-only), prompt for token and retry channel."""
    store = self._credential_store_ref
    cb = self._on_trust_ref
    if store is None or cb is None:
        raise TekAuthenticationFailed(
            self.url,
            "Authentication required; provide on_trust_prompt or store password for this host.",
        )
    entry = store.get(self.url)
    if not entry or not entry.get("cert_path"):
        raise TekAuthenticationFailed(
            self.url,
            "Authentication required but no stored certificate for this host.",
        )
    host, port = _parse_host_port(self.url)
    live = _fetch_server_cert(host, port, timeout=8.0)
    fp = entry.get("cert_fingerprint")
    if fp and live.cert_fingerprint != fp:
        raise TekCertificateMismatch(self.url, fp, live.cert_fingerprint)
    result = _call_on_trust(cb, self.url, live, True)
    password: Optional[str] = None
    login: Optional[str] = None
    if isinstance(result, (list, tuple)):
        if len(result) >= 1 and result[0]:
            password = result[1] if len(result) > 1 else None
            login = result[2] if len(result) > 2 else None
            if login == "":
                login = None
    elif result is True:
        password = None
    else:
        raise TekAuthenticationFailed(self.url, "Authentication declined in on_trust_prompt.")
    if not password:
        raise TekAuthenticationFailed(
            self.url,
            "Server requires a token; when auth_required is True, return (True, password) or "
            "(True, password, login) from on_trust_prompt.",
        )
    store.set(
        self.url,
        password=password,
        login=login if login is not None else DEFAULT_MODE3_USERNAME,
    )
    store.save()
    entry2 = store.get(self.url)
    if not entry2 or not entry2.get("cert_path"):
        raise TekSecurityError("Store update failed after authentication prompt.")
    try:
        self.channel.close()
    except Exception:
        pass
    self.channel = _secure_channel(self.url, _build_creds_from_entry(entry2, "token"), entry=entry2)
    self.connection = ConnectStub(self.channel)
    # EUCRA DEVIATION FROM v2 — REQUIRED. v2 uses lazy stubs (_get_native_stub
    # builds NativeDataStub from self.channel on first use, AFTER any upgrade),
    # so v2 only rebinds self.connection here. EUCRA binds self.native eagerly in
    # __init__ (§8.2 keeps that), so the eager native stub still points at the
    # pre-upgrade TLS-only channel and would send waveform RPCs WITHOUT the Basic
    # auth metadata. Rebind it to the upgraded channel.
    self.native = NativeDataStub(self.channel)
```

> **Why this line is not in the v2 source (and must be added for EUCRA).** v2 made data-plane stubs lazy (`_get_native_stub`, `connect.py:1145`), so at upgrade time no native stub exists yet — it's later created from the already-authenticated `self.channel`, and rebinding only `self.connection` is sufficient *there*. EUCRA's model is eager: `__init__` does `self.native = NativeDataStub(self.channel)` up front (and §10 deliberately keeps EUCRA's eager construction rather than porting v2's lazy stubs). Under eager binding, `self.native` is captured against the pre-upgrade TLS-only channel; without the rebind above, `GetHeader`/`GetWaveform` would run over a channel carrying no `authorization` header and Mode 3 would fail after the upgrade. This is a genuine architecture mismatch, not a v2 bug — the rebind is the correct EUCRA-side fix. (If EUCRA binds any *other* data-plane stub eagerly in `__init__`, rebind those here too, by the same reasoning.)

### 8.5 Required imports & module symbols in `tek_hsi_connect.py`

Add to the top of the file:

```python
import time
from typing import Optional, Union, Tuple, Callable

from tekhsi.security import (
    TekHSICredentials,
    TekSecurityError,
    TekUnknownInstrument,
    TekCertificateMismatch,
    TekAuthenticationFailed,
    _secure_channel,
    _auto_negotiate_channel,
    _resolve_credentials_from_store,
    _build_creds_from_entry,
    _fetch_server_cert,
    _parse_host_port,
    _call_on_trust,
)
from tekhsi.credential_store import TekHSICredentialStore, CertInfo
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
```

(Confirm whether `ConnectStub`/`ConnectRequest` are already imported in EUCRA — they are, since the existing `_connect` uses them; the security module also needs them, so import them there too.)

### 8.6 Backward compatibility (REQUIRED behavior contract)

This port must not change behavior for existing callers or tests that don't opt into security. Three properties to preserve, and one hazard to neutralize:

**(a) Signature compatibility — preserved by construction.** The five new params are appended *after* the original four (`url, activesymbols, callback, data_filter`) and all default to a no-op (`credentials=None, credential_store=None, on_trust_prompt=None, require_tls=False, timeout=10.0`). Existing positional calls (`TekHSIConnect(url)`, `TekHSIConnect(url, syms, cb, filt)`) and keyword calls are unaffected. EUCRA's current `__init__` has no `credentials`/`timeout`/etc. param, so there is no name collision.

**(b) Default channel behavior — HAZARD, must be neutralized.** v2's `credentials=None` path does **not** reproduce EUCRA's current `self.channel = grpc.insecure_channel(url)`. Instead it builds a default store and calls `_auto_negotiate_channel`, which (i) instantiates `TekHSICredentialStore()` and reads `~/.tektronix/credentials.ini`, and (ii) runs `_try_plain_grpc_channel` — a real probe `Connect`/`Disconnect` round-trip — before returning an insecure channel. For existing EUCRA tests this is a behavior change: tests that mock `grpc.insecure_channel`, assert on `self.channel`, or count Connect RPCs may break, and a stale on-disk `credentials.ini` entry for the test host could divert a plaintext test toward TLS.

> **Required mitigation — preserve the legacy fast path.** When `credentials is None` **and** `credential_store is None` **and** `on_trust_prompt is None` **and** `require_tls is False` (i.e. a pre-port call site), skip auto-negotiation entirely and use the original line, so existing behavior and tests are byte-for-byte preserved:
>
> ```python
> _legacy_plain = (
>     credentials is None
>     and credential_store is None
>     and on_trust_prompt is None
>     and not require_tls
> )
> if _legacy_plain:
>     # Preserve pre-security behavior exactly (existing tests rely on this).
>     self.channel = grpc.insecure_channel(url)
>     self._credential_store_ref = None
>     self._on_trust_ref = None
>     self._auto_security = False
> else:
>     # ... the §8.2 negotiation block ...
> ```
>
> This keeps auto-negotiation (probe + default store + TOFU) strictly **opt-in** — it runs only when a caller passes a store, a prompt, or `require_tls`. It does not weaken the "prompt only if the server requires it" goal: with `_auto_security=False`, the `_connect` upgrade branch in §8.3 is skipped, so a legacy plaintext caller behaves exactly as today. The trade-off: a legacy caller hitting a *new* auth-required server gets the raw `UNAUTHENTICATED` `RpcError` (same as pre-port), rather than an auto-prompt — correct, because they supplied no `on_trust_prompt` to prompt with.

**(c) `_connect` compatibility.** The new `_connect` (§8.3) still issues the same `ConnectRequest(name=self.clientname)` and, on success with no auth challenge, returns after a single `Connect` — identical observable behavior to today. The retry loop only diverges on `UNAUTHENTICATED` **and** `_auto_security=True`; with the §8.6(b) mitigation, legacy callers have `_auto_security=False`, so they never enter the upgrade branch. Remember to **strip** the v2 `protocol_version`/`capabilities` capture (§10) — leaving it in would add new instance attributes and ConnectReply field reads that EUCRA's proto/tests may not expect.

### 8.7 Credential-lifecycle validation (the "once, only if required, no leak" goals)

Confirmed against the working v2 control flow:

- **Only if the server requires it.** A password is requested *only* inside `_connect`'s `except grpc.RpcError` branch, gated on `grpc.StatusCode.UNAUTHENTICATED`. Mode 1 (plain) and Mode 2 (TLS-only) servers never reach that branch, so no prompt occurs. The prompt mechanism is the caller-supplied `on_trust_prompt`; a caller who never meets an auth-required server never has to implement it.
- **Exactly once, then silent.** On the first `UNAUTHENTICATED`, `_upgrade_channel_with_token_after_unauthenticated` obtains the password (via `on_trust_prompt` with `auth_required=True`), then `store.set(url, password=..., login=...)` + `store.save()`. Every later connect finds `entry.get("password")` in `_auto_negotiate_channel` and builds Mode-3 creds directly — **no re-prompt**. The `upgrade_done` flag prevents a second prompt within one connect.
- **No leak via the connect object.** The password is never assigned to a `TekHSIConnect` attribute. The only security state on the object is `_credential_store_ref` (store handle), `_on_trust_ref` (callback), and `_auto_security` (bool). The secret exists only transiently inside the `meta_cb` closure that constructs the per-RPC `authorization: Basic <b64>` header (sent over TLS), and persisted in the credential store.
- **At-rest scope (state explicitly).** "No leak" applies to the **connect API surface**, not to disk. App-written passwords are obscured in the INI (`obf1:`, §4.2a); hand-entered passwords remain cleartext by the user's choice. Obscuration deters shoulder-surfing but is trivially reversible with the source — it is **not** a security control. The real at-rest boundary is OS user isolation (`save()` applies `chmod 0600` on POSIX; `%APPDATA%` ACLs on Windows). This is a deliberate deviation from v2 (which stored raw plaintext); it does not claim cryptographic protection.

---

## 9. `__init__.py` exports

Add the public security surface to `src/tekhsi/__init__.py`, **including the two aliases that v2 exposes** (the v2 `__init__` block in §8.2 references `TekCredentialStore` by name, so this alias is load-bearing, not cosmetic):

```python
from tekhsi.security import (
    TekHSICredentials,
    TekSecurityError,
    TekUnknownInstrument,
    TekCertificateMismatch,
    TekAuthenticationFailed,
)
from tekhsi.credential_store import TekHSICredentialStore, CertInfo

# Aliases exposed by v2 (preserve for compatibility)
TekCredentialStore = TekHSICredentialStore
TekHSIUnknownInstrument = TekUnknownInstrument
```

**Extend `__all__`.** EUCRA's `__init__.py` currently lists only `TekHSIConnect`, `AcqWaitOn`, etc. in `__all__`. Add every new public symbol so re-exports, `from tekhsi import *`, and doc generation pick them up:

```python
__all__ += [
    "TekHSICredentials",
    "TekHSICredentialStore",
    "TekCredentialStore",          # alias
    "CertInfo",
    "TekSecurityError",
    "TekUnknownInstrument",
    "TekHSIUnknownInstrument",     # alias
    "TekCertificateMismatch",
    "TekAuthenticationFailed",
]
```

Define the aliases wherever is cleanest — either in `__init__.py` as above, or next to the class definitions in `credential_store.py` / `security.py`. If you keep the §8.2 wiring block exactly as v2 wrote it (`store_for_auto = ... else TekCredentialStore()`), the alias must be importable in `tek_hsi_connect.py`; the simplest path is to alias `TekCredentialStore = TekHSICredentialStore` at the bottom of `credential_store.py` and import that name. (Alternatively, substitute `TekHSICredentialStore()` directly in the wiring block and skip the alias — your call.)

Keep the private helpers (`_secure_channel`, etc.) unexported.

---

## 10. What to EXCLUDE (v2 code that is NOT part of this port)

When copying from v2's `connect.py` and `__init__`, do **not** bring across the following — they are unrelated experimental features that happen to live in the same files:

1. **Capability negotiation.** `self._protocol_version`, `self._capabilities`, the `protocol_version`/`capabilities` capture in `_connect`, and the "Connected: protocol vN" logging. (Tracked separately in v2's `TekHSI_v2_Capability_Amendment.md`.)
2. **Lazy data-plane stubs.** v2's `__init__` initializes `self._native_stub`, `self._normalized_stub`, `self._measurement_stub`, `self._control_stub`, `self._state_stub` to `None`. EUCRA keeps its existing eager `NativeDataStub`/`ConnectStub` construction — leave it alone.
3. **Parallel reads.** Any `_parallel_reads_*`, `_read_executor`, `TEKHSI_USE_PARALLEL_READS` logic is EUCRA-side experimental and unrelated to security; not touched by this port.
4. **Additional v2 stubs/services** (Measurement, InstrumentControl, InstrumentState) — out of scope.

The clean test that a line belongs in this port: it must touch TLS, certificates, the credential store, Basic auth, or the `UNAUTHENTICATED` handshake. Everything else stays.

---

## 11. Verification checklist

- [ ] **Mode 1 (plain):** Connect to a plaintext server with no `credentials`, empty store → `_try_plain_grpc_channel` succeeds, insecure channel used.
- [ ] **Mode 2 (TLS, explicit):** `credentials=TekHSICredentials.tls("server.pem")` → secure channel, no auth metadata.
- [ ] **Mode 2 (TLS, store/TOFU):** `credentials=TekHSICredentials.tls()` + `credential_store=...` + `on_trust_prompt` returning `True` → cert fetched, fingerprint stored, PEM written to `certs/`, secure channel.
- [ ] **Mode 3 (explicit):** `credentials=TekHSICredentials.token("server.pem", "pw")` → composite creds, `authorization: Basic` header present.
- [ ] **Mode 3 (auto-upgrade):** trusted TLS host, server returns `UNAUTHENTICATED` → `_connect` triggers `_upgrade_channel_with_token_after_unauthenticated`, prompt returns `(True, password)`, retry succeeds. **Then assert a data-plane RPC (`GetHeader`/`GetWaveform`) succeeds over the upgraded channel** — this is what proves `self.native` was rebound (§8.4); a test that only checks `Connect` would miss the missing-metadata bug.
- [ ] **Cert mismatch:** stored fingerprint ≠ live cert → `TekCertificateMismatch` raised.
- [ ] **require_tls=True, unknown host, no prompt:** → `TekSecurityError`.
- [ ] **Store round-trip:** `save()` then fresh `load()` preserves all five keys; INI is `chmod 0600` on POSIX.
- [ ] **App password obscured:** after `trust(..., password="pw")` + `save()`, the on-disk `password` value starts with `obf1:` and is not equal to `"pw"`; a fresh `load()` + `get()` returns `"pw"`.
- [ ] **Hand-entered cleartext accepted:** write a section by hand with `password = pw` (no tag) → `get()` returns `"pw"`, Mode 3 connects.
- [ ] **Hand-entered cleartext preserved:** after the app updates a *different* field for that host and `save()`s, the user's `password` line is still the original cleartext (never rewritten to `obf1:`).
- [ ] **Round-trip both forms:** `_reveal_password(_obscure_password(s)) == s` for representative passwords (unicode, `:`, `=`, spaces); untagged input returns unchanged.
- [ ] **Malformed tag tolerated:** a value like `obf1:not-base64!` is returned literally by `get()` rather than raising.
- [ ] **IP/.local host:** TLS connection to an IP literal with a CN/SAN cert sets `grpc.ssl_target_name_override`.
- [ ] **No capability/parallel-read symbols** leaked into EUCRA from the port.

**Backward compatibility (must pass before merge):**

- [ ] **Legacy plain call unchanged:** `TekHSIConnect(url)` and `TekHSIConnect(url, syms, cb, filt)` with no security args → `_legacy_plain` true → `self.channel = grpc.insecure_channel(url)`, **no** store read, **no** probe RPC, `_auto_security is False`. Existing tests that mock `grpc.insecure_channel` or assert channel type pass unmodified.
- [ ] **Existing test suite green with no `credentials.ini` present** AND **with a stale `credentials.ini` entry for the test host present** — the legacy fast path must ignore the store entirely, so both runs are identical.
- [ ] **Legacy caller vs. auth-required server:** `TekHSIConnect(url)` (no prompt) against a server that returns `UNAUTHENTICATED` → raises the raw `grpc.RpcError` (pre-port behavior), not an auto-prompt.

**Credential lifecycle (the stated goals):**

- [ ] **Prompt only when required:** plain/TLS-only server → `on_trust_prompt`'s `auth_required=True` branch is **never** invoked.
- [ ] **Prompt exactly once:** first connect to a Mode-3 server prompts once and persists; second `TekHSIConnect` to the same host (fresh process, same store) connects with **zero** prompts.
- [ ] **No object-level leak:** after a Mode-3 connect, assert the password string is not present in any `TekHSIConnect` instance attribute (only `_credential_store_ref`/`_on_trust_ref`/`_auto_security`).

---

## 12. Source provenance

All code bodies in §3–§8 were extracted from the indexed `TekHSI_v2` project (`C:\Users\keith\Desktop\TekHSI_v2\`):

| Symbol | v2 file:line |
|--------|--------------|
| `build_basic_authorization_value`, `parse_basic_authorization`, `DEFAULT_MODE3_USERNAME` | `tekhsi/auth_basic.py:13,20` |
| `tls_server_name_from_pem` | `tekhsi/credential_store.py:17` |
| `_default_store_path` | `tekhsi/credential_store.py:41` |
| `CertInfo`, `.fingerprint`, `.from_pem` | `tekhsi/credential_store.py:63,71,76` |
| `TekHSICredentialStore` (all methods) | `tekhsi/credential_store.py:83–221` |
| **Password obfuscation** (`_obscure_password`, `_reveal_password`, `_xor_bytes`, `obf1:` handling in `get`/`set`) | **PORT ADDITION — not in v2.** §4.2a. v2 stores raw plaintext; v2 doc §3.8 defers at-rest protection. |
| `TekSecurityError` & subclasses | `tekhsi/connect.py:100,109,130,145` |
| `_parse_host_port`, `_is_ip_literal`, `_tls_server_name_for_entry`, `_tls_channel_options` | `tekhsi/connect.py:150,164,176,190` |
| `_secure_channel` | `tekhsi/connect.py:211` |
| `_try_plain_grpc_channel` | `tekhsi/connect.py:227` |
| `_fetch_server_cert`, `_call_on_trust` | `tekhsi/connect.py:270,284` |
| `_build_creds_from_entry` | `tekhsi/connect.py:302` |
| `_resolve_credentials_from_store` | `tekhsi/connect.py:320` |
| `_auto_negotiate_channel` | `tekhsi/connect.py:368` |
| `TekHSICredentials` (all methods) | `tekhsi/connect.py:477–544` |
| `TekHSIConnect.__init__` (security block) | `tekhsi/connect.py:568` |
| `_upgrade_channel_with_token_after_unauthenticated` | `tekhsi/connect.py:1230` |
| `TekHSIConnect._connect` | `tekhsi/connect.py:1285` |
| EUCRA target `__init__` / `_connect` | `tekhsi_github_EUCRA/src/tekhsi/tek_hsi_connect.py:114,666` |

The authoritative narrative reference in v2 is `client_security_changes.md` (29 sections); the exception hierarchy is documented in `archive/TekHSI_Security_Python_API.md` §6.

> **Verification status:** All function and method bodies in §3–§8, **including the four exception classes (§5)**, were confirmed verbatim against the working v2 index — **except** `get()` and `set()`, which carry a port modification for password obfuscation (§4.2a, clearly marked `PORT CHANGE` inline), and the obfuscation helpers themselves, which are new and not from v2. The store keys, the five-key `get()` return, and the `TekCredentialStore`/`TekHSIUnknownInstrument` aliases were cross-checked against the code (where the older `client_security_changes.md` doc disagreed — e.g. it claims "four option names" — the **working code wins**: `get()`/`set()` handle five keys including `tls_server_name`).
>
> **One item determined by usage rather than pulled verbatim:** the `CertInfo` dataclass *field declarations* (`credential_store.py:63–70`). The index exposes attributes only through methods, not raw field lines. The field set and defaults are nonetheless fully constrained by confirmed call sites: `from_pem` builds `CertInfo(cert_fingerprint=digest, cert_pem=cert_pem, tls_server_name=tls_name)`, and `_resolve_credentials_from_store` builds `CertInfo(cert_fingerprint="")` — so the declaration must be:
> ```python
> @dataclass
> class CertInfo:
>     cert_fingerprint: str
>     cert_pem: Optional[bytes] = None
>     tls_server_name: Optional[str] = None
> ```
> Confirm the decorator and any field metadata against the live file, but the shape above is the only one consistent with all working call sites.

---

## 13. Test plan (required for CI — `fail_under = 67`)

§11 is a behavioral checklist; EUCRA CI enforces coverage, so the new modules need unit tests landed *with* the implementation, not after. The existing test server (`tests/server/`) is **plaintext-only**, so TLS/Mode-2/Mode-3 integration needs new fixtures.

**Unit tests (no server needed):**
- `auth_basic`: `build_basic_authorization_value` round-trips with `parse_basic_authorization`; edge cases — empty password, `:` in password, non-ASCII (UTF-8), malformed/short/non-base64 headers return `None`, missing `Basic ` prefix.
- `credential_store`: `set`/`get`/`save`/`load` round-trip preserving all five keys; `_normalize_host` lowercasing; atomic-write leaves no `.tmp` on success; POSIX `chmod 0600`; `trust()` writes the sidecar PEM and sets `cert_path`.
- **Obfuscation:** `_reveal_password(_obscure_password(s)) == s` over the representative set (unicode, `:`, `=`, spaces, empty); app-written value is `obf1:`-tagged and ≠ plaintext on disk; untagged (hand-entered) value returned verbatim and **never rewritten** after an unrelated `set()`+`save()`; malformed `obf1:` returned literally, no raise.
- Helpers: `_parse_host_port` (host, host:port, bracketed IPv6, default-port fallback); `_is_ip_literal`; `_tls_channel_options` (matching name → no override; IP/.local → override); the four exception classes' `.host`/fingerprint attributes and message text.

**Wiring tests (mock gRPC / channel):**
- **`_legacy_plain` guard** — the load-bearing one: `TekHSIConnect(url)` with no security args makes **no** store read and **no** probe RPC, sets `self.channel = grpc.insecure_channel(url)` and `_auto_security is False`. Assert via mock that `TekHSICredentialStore` is never constructed and `_try_plain_grpc_channel` is never called on this path.
- Run the existing suite twice — with no `credentials.ini` and with a stale entry for the test host — and confirm identical results (the guard must ignore the store).

**Integration tests (new infra required):**
- A TLS-enabled mock server (self-signed cert) to exercise: TOFU first-trust → fingerprint pinned; cert-mismatch → `TekCertificateMismatch`; Mode 3 `UNAUTHENTICATED` → upgrade → authenticated `GetHeader`/`GetWaveform` succeed (this is the test that would have caught the §8.4 `self.native` rebind bug — assert a data-plane RPC works *after* upgrade, not just `Connect`).
- These need a cert fixture and a server that can demand Basic auth; budget for standing this up since `tests/server/` can't.

## 14. Behavior contract & docs (for the public API and CHANGELOG)

Decisions the review surfaced that callers must be able to discover — put these in the `TekHSIConnect.__init__` docstring and the release notes, not just this spec:

- **Security negotiation is opt-in.** Auto-negotiation (default-store read + plaintext probe + TOFU) activates only when at least one of `credential_store`, `on_trust_prompt`, or `require_tls=True` is passed. Passing `timeout=` **alone does not** enable it — a legacy `TekHSIConnect(url, timeout=30)` stays on the plain fast path. Document this so the timeout param isn't mistaken for a security switch.
- **Partial opt-in creates a default store.** Passing `on_trust_prompt` without `credential_store` causes the wiring to instantiate `TekHSICredentialStore()` at the **default platform path** (`~/.tektronix/credentials.ini` etc.) and read/write it. Callers expecting an ephemeral session should know a persistent INI is touched; pass an explicit store (e.g. a temp path) to avoid it.
- **Error-type contract for security-enabled callers.** With `_auto_security=True`, a server `UNAUTHENTICATED` surfaces as `TekAuthenticationFailed`, not raw `grpc.RpcError`. Legacy callers (guard path) still get raw `RpcError`. State this in the CHANGELOG as the behavioral contract.
- **Obfuscation is not cross-client.** `obf1:` passwords are EUCRA-only on disk. EUCRA reads a v2-written plaintext INI fine (untagged ⇒ accepted), but **v2 cannot read an EUCRA-written `obf1:` value**. If a credentials.ini is meant to be shared between v2 and EUCRA clients, either keep passwords hand-entered (plaintext) or don't share the file. Call this out wherever store portability is documented.
- **`TekHSICredentials` accepts a raw `grpc.ChannelCredentials`.** The `Union[grpc.ChannelCredentials, TekHSICredentials]` type lets advanced callers pass gRPC creds directly, bypassing `TekHSICredentials` — but then `_tls_server_name` handling is skipped and the caller must set `grpc.ssl_target_name_override` themselves for IP/.local hosts. One-line docstring note is enough.

## 15. Known spec/source nits (carry into review, not blockers)

- **Duplicate-ish numbering:** the obfuscation helpers are labeled §4.2a (inserted between `_default_store_path` at §4.2 and `CertInfo` at §4.3) to avoid renumbering verbatim blocks; not a true collision but renumber on a docs pass if desired.
- **`_tls_channel_options` redundancy:** the final `if host_lower != cert_lower:` branch overlaps earlier cases. Harmless and copied verbatim from working v2; leave as-is for traceability, simplify only with a test in hand.
- **Provenance tree availability:** §12 references `C:\Users\keith\Desktop\TekHSI_v2\`. If that tree is on the implementing machine, spot-check the `CertInfo` field metadata (the one usage-inferred item) directly.
- **OSS-release surface not covered here:** mkdocs pages, CHANGELOG entry, and any API-comparison workflow for the Tektronix release are out of this spec's scope but will be needed — §14's contract notes are the raw material for them.
