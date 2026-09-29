# TekHSI Security: TLS, Certificates, and Authentication

This guide explains how `TekHSIConnect` secures its connection to an instrument: how TLS certificates are trusted, how passwords are handled, and how to configure it for each scenario. It is written for users of the library, not implementers.

> **Requirements.** The security features depend on the `cryptography` package, which is installed automatically with TekHSI. On minimal or air-gapped environments where you install dependencies by hand, ensure `cryptography` (>= 42.0.0) is present, or certificate handling for IP/`.local` instrument addresses will not work.

## Quick orientation

By default, `TekHSIConnect` behaves exactly as it always has — a plain, unencrypted connection:

```python
from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.1.50:5000") as scope:
    print(scope.available_symbols)
```

Security is **opt-in**. You enable it by passing one or more security parameters (`credentials`, `credential_store`, `on_trust_prompt`, or `require_tls`). If you pass none of them, nothing changes from prior behavior. Passing `timeout` alone does **not** enable security.

## The three connection modes

| Mode | Transport | Client authentication | When it's used |
|------|-----------|----------------------|----------------|
| **1 — Plain** | Unencrypted gRPC | None | Default; or when a plaintext probe succeeds and TLS isn't required. |
| **2 — TLS** | Encrypted (TLS) | None | Server presents a certificate you trust; no password needed. |
| **3 — TLS + Password** | Encrypted (TLS) | HTTP Basic (username + password) | Server requires a password in addition to TLS. |

The library negotiates the appropriate mode automatically based on what the server offers and what you've configured. You don't pick a mode by name; you provide credentials/trust settings and the right mode follows.

## How certificate trust works (trust-on-first-use)

Instruments typically present **self-signed** certificates, so there's no public certificate authority to validate against. TekHSI uses a **trust-on-first-use (TOFU)** model, the same approach SSH uses for host keys:

1. The **first** time you connect to an instrument over TLS, the library fetches the server's certificate and computes its SHA-256 fingerprint.
2. You decide whether to trust it (via the `on_trust_prompt` callback, below). If you trust it, the fingerprint and certificate are saved to your **credential store**.
3. On **every subsequent** connection, the library re-fetches the live certificate and compares its fingerprint to the stored one. If they match, the connection proceeds. If they **differ**, the connection is refused with `TekCertificateMismatch` — this is what protects you against a man-in-the-middle or a swapped instrument.

Because trust is pinned to the exact certificate, the connection trusts *only* that instrument's certificate — not the system trust store, and not any other CA-signed certificate.

> **Security note.** The first connection is the moment of trust. To verify you're trusting the right instrument, confirm the fingerprint shown in your trust prompt against the fingerprint reported by the instrument itself (out of band) before accepting it. After that, the pinning protects every later connection automatically.

## The trust prompt callback

When the library encounters an instrument it hasn't trusted yet (or a server that demands a password), it calls the function you pass as `on_trust_prompt`. Your callback decides what to do and returns one of these:

| Return value | Meaning |
|--------------|---------|
| `True` | Trust the certificate. Use **Mode 2** (TLS, no password). *(During a password upgrade — `auth_required=True` — bare `True` is treated as a decline; see below.)* |
| `(True, password)` | Trust the certificate **and** store this password. Username defaults to `tektronix`. Use **Mode 3**. |
| `(True, password, login)` | Trust the certificate, store the password with an explicit username. Use **Mode 3**. |
| `False` (or anything else) | Decline. The connection is refused — `TekUnknownInstrument` during first-time trust (`auth_required=False`), or `TekAuthenticationFailed` during a password upgrade (`auth_required=True`). |

Your callback receives the host and a `CertInfo` object so you can show the fingerprint to the user before deciding:

```python
def trust_prompt(host, cert_info, auth_required=False):
    print(f"Instrument {host} presented certificate:")
    print(f"  Fingerprint: {cert_info.fingerprint}")
    if auth_required:
        # Server requires a password (Mode 3). Returning just True is not enough here.
        pw = input("Password: ")
        return (True, pw)
    # First-time trust (Mode 2). Approve the certificate.
    answer = input("Trust this instrument? [y/N] ")
    return answer.strip().lower() == "y"
```

The third argument, `auth_required`, is `True` when the server has accepted the TLS certificate but is now demanding a password (the Mode-2 → Mode-3 upgrade). In that case returning bare `True` is insufficient — you must return `(True, password)`. If you decline at this stage (return `False`, or return bare `True` without a password), the connection fails with `TekAuthenticationFailed` rather than `TekUnknownInstrument`, because the certificate was already trusted and only the password was missing.

> Your callback can take either `(host, cert_info)` or `(host, cert_info, auth_required)`. The library adapts to whichever signature you provide.

## Usage scenarios

### A. Plain connection (default)

No changes. No certificate, no password.

```python
with TekHSIConnect("192.168.1.50:5000") as scope:
    ...
```

### B. First connection to a secure instrument (trust-on-first-use)

Provide a credential store and a trust prompt. The first run trusts and remembers; later runs are silent.

```python
from tekhsi import TekHSIConnect, TekHSICredentialStore

store = TekHSICredentialStore()  # default platform location (see below)

def trust_prompt(host, cert_info, auth_required=False):
    print(f"Fingerprint for {host}: {cert_info.fingerprint}")
    if auth_required:
        return (True, input("Password: "))
    return input("Trust? [y/N] ").strip().lower() == "y"

with TekHSIConnect(
    "192.168.1.50:5000",
    credential_store=store,
    on_trust_prompt=trust_prompt,
) as scope:
    ...
```

After the first successful connect, the certificate (and password, if any) are saved. Subsequent connections with the same `credential_store` need no prompt.

> **Important — a remembered certificate does not by itself force encryption.** When a store entry exists but you have *not* set `require_tls=True`, the library first tries a plain (unencrypted) connection; if the server accepts it, that plaintext channel is used and the stored certificate is never exercised. The stored cert is only *required* when the server refuses plaintext or when you set `require_tls=True`. **If you want every connection after trust to be encrypted, pass `require_tls=True`** (see Scenario E). Without it, "I trusted this instrument" means "I have its cert on file," not "I will only talk to it over TLS."

> **Mode-3 servers may prompt twice on the first connect.** If the instrument requires a password, the first connect can call your prompt once for certificate trust (`auth_required=False`) and again for the password (`auth_required=True`). To answer both in one step, return `(True, password)` from the *first* call instead of bare `True` — that supplies the password up front and avoids the second prompt.

### C. Explicit certificate file (Mode 2)

If you already have the instrument's certificate as a PEM file, point at it directly — no prompt, no store needed:

```python
from tekhsi import TekHSIConnect, TekHSICredentials

creds = TekHSICredentials.tls("instrument.pem")
with TekHSIConnect("192.168.1.50:5000", credentials=creds) as scope:
    ...
```

### D. Explicit certificate + password (Mode 3)

```python
creds = TekHSICredentials.token("instrument.pem", "my-password")
# Or with an explicit username:
creds = TekHSICredentials.token("instrument.pem", "my-password", username="operator")

with TekHSIConnect("192.168.1.50:5000", credentials=creds) as scope:
    ...
```

### E. Require TLS (refuse to fall back to plaintext)

Set `require_tls=True` to ensure the connection is encrypted or fails — never silently plaintext. You must also give the library a way to establish trust. That can be either a populated store / trust prompt (the auto-negotiation path shown below), **or** explicit credentials such as `TekHSICredentials.tls("instrument.pem")`:

```python
with TekHSIConnect(
    "192.168.1.50:5000",
    credential_store=store,
    on_trust_prompt=trust_prompt,
    require_tls=True,
) as scope:
    ...
```

Equivalently, with an explicit certificate and no store:

```python
creds = TekHSICredentials.tls("instrument.pem")
with TekHSIConnect("192.168.1.50:5000", credentials=creds, require_tls=True) as scope:
    ...
```

If TLS can't be established (unknown instrument, no prompt, no credentials), the connection raises `TekSecurityError` rather than falling back.

### F. Store-backed explicit credentials

`TekHSICredentials.tls()` and `.token()` can be called **with no arguments** to mean "resolve the certificate (and, for `.token()`, the password) from the credential store" rather than from a PEM file. This pairs an explicit-credentials call with a store:

```python
# Resolve cert from the store; TLS only (Mode 2):
creds = TekHSICredentials.tls()
with TekHSIConnect("192.168.1.50:5000", credentials=creds,
                   credential_store=store, on_trust_prompt=trust_prompt) as scope:
    ...

# Resolve cert + password from the store (Mode 3):
creds = TekHSICredentials.token()
with TekHSIConnect("192.168.1.50:5000", credentials=creds,
                   credential_store=store, on_trust_prompt=trust_prompt) as scope:
    ...
```

A no-argument `TekHSICredentials.tls()` / `.token()` **requires** a `credential_store=` to be passed, since that's where the certificate comes from.

### Other parameters and imports

| Item | Notes |
|------|-------|
| `timeout` (default `10.0`) | Seconds allowed for security negotiation. Only applies when a security path is active; has no effect on a plain default connection, and passing it alone does not enable security. |
| `TekCredentialStore` | Alias for `TekHSICredentialStore` (both are exported). Either name works. |
| `CertInfo` | Importable for typing your trust-prompt callback: `from tekhsi import CertInfo`. |
| Host-key normalization | Store section keys are lowercased and stripped, so `192.168.1.50:5000` and any mixed-case variant map to the same entry. |

## The credential store

Trusted certificates and passwords are stored in an INI file plus a `certs/` folder for the certificate PEMs.

### Default location

| Platform | Path |
|----------|------|
| Linux | `~/.tektronix/credentials.ini` |
| Windows | `%APPDATA%\tektronix\credentials.ini` |
| macOS | `~/Library/Application Support/tektronix/credentials.ini` |

Use a custom path by constructing the store explicitly:

```python
store = TekHSICredentialStore("/path/to/my/credentials.ini")
```

> **Heads-up:** passing `on_trust_prompt` *without* a `credential_store` causes the library to create and use the **default** store at the path above. If you want an isolated or temporary store, pass one explicitly.

### File format

Each instrument is one INI section, keyed by `host:port`:

```ini
[192.168.1.50:5000]
cert_fingerprint = 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
cert_path = /home/you/.tektronix/certs/192.168.1.50_5000.pem
tls_server_name = MSO58B-ABC123
login = tektronix
password = obf1:Bx5eX1tcWw==
```

| Key | Meaning |
|-----|---------|
| `cert_fingerprint` | SHA-256 of the trusted certificate. Checked on every connect. |
| `cert_path` | Path to the saved certificate PEM. |
| `tls_server_name` | Name used for TLS verification (handles IP / `.local` addressing). |
| `login` | Username for Basic auth (Mode 3). Defaults to `tektronix` if absent. |
| `password` | Password for Basic auth (Mode 3). See obfuscation below. |

On non-Windows systems the file is written with owner-only permissions (`0600`). On Windows it relies on your user account's `%APPDATA%` isolation.

### Adding a password by hand

If an instrument's certificate is already trusted and you want to enable Mode 3, you can edit the INI directly and type the password in **plain text** — no special encoding needed:

```ini
[192.168.1.50:5000]
cert_fingerprint = 9f86d081...
cert_path = /home/you/.tektronix/certs/192.168.1.50_5000.pem
tls_server_name = MSO58B-ABC123
login = tektronix
password = MyServerPassword
```

On the next connection the library reads your plaintext password, authenticates, and **leaves your entry exactly as you wrote it** — it does not rewrite or re-encode it. (To use a username other than `tektronix`, add or edit the `login` line.)

To create an entirely new entry by hand, you must also provide a valid `cert_path` pointing to the instrument's certificate PEM (and ideally its `cert_fingerprint`), since a secure connection needs the certificate.

### About password obfuscation

Passwords that the **library** writes are stored in a lightly obfuscated form, tagged `obf1:`. This is **not encryption** — it only prevents a password from sitting in plainly readable form in the file, deterring casual shoulder-surfing. It is trivially reversible by anyone with access to the file and the library.

**The real protection for stored credentials is operating-system file permissions** (owner-only on Linux/macOS, user-account isolation on Windows). Treat the credential store as sensitive, and don't share `credentials.ini` between machines expecting the obfuscated passwords to be portable — they're tied to this library, and hand-typed plaintext passwords aren't obfuscated at all.

## Exceptions

All security errors derive from `TekSecurityError`, so you can catch the whole category:

```python
from tekhsi import TekSecurityError, TekCertificateMismatch

try:
    with TekHSIConnect("192.168.1.50:5000", credential_store=store,
                       on_trust_prompt=trust_prompt) as scope:
        ...
except TekCertificateMismatch as e:
    print("The instrument's certificate changed — possible MITM or reconfigured device.")
except TekSecurityError as e:
    print(f"Security negotiation failed: {e}")
```

| Exception | Raised when |
|-----------|-------------|
| `TekSecurityError` | Base class for all of the below; also raised on negotiation timeout or when TLS is required but can't be established. |
| `TekUnknownInstrument` | The instrument isn't trusted and no prompt was provided (or the prompt declined). Carries the `cert_info` so you can inspect the fingerprint. |
| `TekCertificateMismatch` | The live certificate's fingerprint doesn't match the stored one. Carries both fingerprints. |
| `TekAuthenticationFailed` | The password was missing or rejected by the server, or the trust prompt declined to supply a password during a Mode-2 → Mode-3 upgrade (`auth_required=True`). |

### Handling a certificate mismatch

A `TekCertificateMismatch` means the instrument is presenting a different certificate than the one you trusted. This is intentional protection — investigate before overriding. If the change is legitimate (the instrument was reconfigured or its certificate regenerated), remove the stored entry and persist the change, then reconnect to re-trigger trust-on-first-use:

```python
store.remove("192.168.1.50:5000")  # drops the in-memory entry
store.save()                        # required to persist the removal to disk
# then reconnect to re-trust the new certificate
```

> `remove()` deletes the INI entry but does **not** delete the certificate PEM saved under `certs/`. The orphaned PEM is harmless (it's just a public certificate and is no longer referenced), but you may delete it manually if you want to tidy up.

## Programmatic store management

```python
from tekhsi import TekHSICredentialStore

store = TekHSICredentialStore()

# Inspect a stored entry (password is returned in usable cleartext):
entry = store.get("192.168.1.50:5000")

# List all trusted hosts:
hosts = store.list_hosts()

# Remove a host (e.g., to force re-trust):
store.remove("192.168.1.50:5000")
store.save()
```

## Summary

- Security is opt-in; the default connection is unchanged.
- Trust is established once per instrument (trust-on-first-use), then pinned and checked on every connect.
- Passwords are requested only when the server requires them, stored once, and reused silently thereafter.
- The credential store can be edited by hand; plaintext passwords you type are accepted and left untouched.
- Stored-credential confidentiality rests on OS file permissions — the `obf1:` obfuscation is convenience, not security.
