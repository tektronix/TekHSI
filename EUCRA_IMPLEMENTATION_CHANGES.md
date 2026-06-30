# EUCRA implementation changes vs upstream TekHSI

**Baseline:** [tektronix/TekHSI](https://github.com/tektronix/TekHSI) `main` (v1.1.0)  
**This tree:** EUCRA security port — TLS, certificate trust, and HTTP Basic authentication for `TekHSIConnect`.

This document covers **core library implementation only** (source under `src/tekhsi/` and the runtime dependency added in `pyproject.toml`). It does not cover CI, docs site, release automation, or other repository infrastructure.

---

## Summary

| Area | Upstream | EUCRA |
|------|----------|-------|
| Default connect | Always `grpc.insecure_channel(url)` | Unchanged when no security parameters are passed |
| Secure connect | Not supported | Opt-in: TLS (Mode 2), TLS + Basic auth (Mode 3), auto-negotiation |
| Certificate trust | N/A | Trust-on-first-use (TOFU) with pinned SHA-256 fingerprints |
| Stored credentials | N/A | Platform INI store + sidecar PEM files |
| New runtime dependency | — | `cryptography>=42.0.0` |

**Unchanged from upstream:** gRPC/protobuf stubs (`_tek_highspeed_server_pb2*.py`), helpers, waveform acquisition/read path, parallel-read experimental code, and the pre-existing `close()` registry-cleanup defect (still present; not part of this port).

---

## `pyproject.toml`

**Runtime dependency added:**

```toml
cryptography>=42.0.0
```

Used for TLS certificate parsing (SAN/CN extraction), fingerprinting, and secure-channel setup. Installed automatically with the wheel.

*(Other `pyproject.toml` edits in this tree — pytest `manual` marker, ruff ignores for `tests/manual/**` — are test-harness configuration, not library behavior.)*

---

## New module: `src/tekhsi/auth_basic.py`

HTTP Basic authentication helpers for Mode 3 client auth.

| Symbol | Purpose |
|--------|---------|
| `DEFAULT_MODE3_USERNAME` | Default Basic auth username (`"tektronix"`) |
| `build_basic_authorization_value()` | Builds `Basic <base64>` for gRPC metadata |
| `parse_basic_authorization()` | Parses a Basic header (used in tests) |

---

## New module: `src/tekhsi/credential_store.py`

INI-backed credential store for per-instrument TLS trust and passwords.

| Symbol | Purpose |
|--------|---------|
| `CertInfo` | Server certificate fingerprint, PEM bytes, TLS server name; `fingerprint` property alias |
| `TekHSICredentialStore` | Load/save `credentials.ini`, trust hosts, store passwords |
| `TekCredentialStore` | Alias for `TekHSICredentialStore` |
| `tls_server_name_from_pem()` | Extract verification name from cert (SAN DNS, else CN) |

**Default store paths:**

| Platform | Path |
|----------|------|
| Linux | `~/.tektronix/credentials.ini` |
| Windows | `%APPDATA%\tektronix\credentials.ini` |
| macOS | `~/Library/Application Support/tektronix/credentials.ini` |

**Behavior notes:**

- Sidecar PEM files written under a `certs/` directory next to the INI.
- Passwords the library writes are tagged `obf1:` (reversible obfuscation, not encryption).
- Hand-typed plaintext passwords in the INI are accepted and left unchanged.
- Non-Windows INI files are written mode `0600`.

---

## New module: `src/tekhsi/security.py`

TLS channel negotiation, credential builders, and security exceptions.

### Public exceptions

| Exception | When raised |
|-----------|-------------|
| `TekSecurityError` | Base class; negotiation timeout; TLS required but unavailable |
| `TekUnknownInstrument` | Unknown host, no trust prompt, or prompt declined at TOFU |
| `TekHSIUnknownInstrument` | Alias for `TekUnknownInstrument` |
| `TekCertificateMismatch` | Live cert fingerprint ≠ stored fingerprint |
| `TekAuthenticationFailed` | Missing/rejected password; prompt declined during Mode 3 upgrade |

### Public credentials builder

| API | Purpose |
|-----|---------|
| `TekHSICredentials.tls(pem_path)` | Mode 2 — TLS with pinned CA/server cert PEM |
| `TekHSICredentials.tls()` | Mode 2 — resolve cert from `credential_store` |
| `TekHSICredentials.token(pem_path, password, username=…)` | Mode 3 — TLS + HTTP Basic |
| `TekHSICredentials.token()` | Mode 3 — resolve cert + password from store |

### Internal negotiation (used by `TekHSIConnect`)

| Function | Role |
|----------|------|
| `_auto_negotiate_channel()` | Plaintext probe, then TLS/TOFU when security params are set |
| `_try_plain_grpc_channel()` | Tests whether server accepts unencrypted gRPC Connect |
| `_fetch_server_cert()` | TLS handshake without verification; returns `CertInfo` for TOFU |
| `_secure_channel()` | Builds `grpc.secure_channel` with cert pinning and optional name override |
| `_build_creds_from_entry()` | Builds gRPC credentials from store entry (`tls` or `token` mode) |
| `_resolve_credentials_from_store()` | Store lookup, fingerprint check, TOFU via `on_trust_prompt` |
| `_call_on_trust()` | Invokes callback with 2- or 3-argument signature |
| `_parse_host_port()` | Parses `host:port`, IPv6, default port 5000 |
| `_tls_channel_options()` | Sets `grpc.ssl_target_name_override` for IP / `.local` mismatches |

**Connection modes (client view):**

| Mode | Transport | Client auth |
|------|-----------|-------------|
| 1 | Plain gRPC | None |
| 2 | TLS | None (pinned server cert) |
| 3 | TLS | HTTP Basic (username + password) |

---

## Modified: `src/tekhsi/__init__.py`

Exports added to the public API (`__all__`):

- `CertInfo`
- `TekCredentialStore`, `TekHSICredentialStore`
- `TekHSICredentials`
- `TekAuthenticationFailed`, `TekCertificateMismatch`, `TekSecurityError`
- `TekUnknownInstrument`, `TekHSIUnknownInstrument`

---

## Modified: `src/tekhsi/tek_hsi_connect.py`

Main integration point. **~174 lines added, 3 removed** (security wiring only; data-plane logic unchanged).

### `TekHSIConnect.__init__` — new optional parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `credentials` | `None` | `TekHSICredentials` or raw `grpc.ChannelCredentials` |
| `credential_store` | `None` | `TekHSICredentialStore` for trust/password persistence |
| `on_trust_prompt` | `None` | TOFU / password callback |
| `require_tls` | `False` | Refuse plaintext fallback during auto-negotiation |
| `timeout` | `10.0` | Security negotiation timeout (seconds) |

### Legacy plain guard

When **all** of the following are absent/false, behavior is **identical to upstream**:

```python
credentials is None
credential_store is None
on_trust_prompt is None
require_tls is False
```

→ `grpc.insecure_channel(url)` with no store access and no security probe.

Passing `timeout` alone does **not** enable security.

### Channel creation (when security is active)

1. **Explicit credentials** — `_secure_channel()` with PEM or store-resolved creds.
2. **Auto-negotiation** — `_auto_negotiate_channel()` when any security parameter is set but `credentials` is omitted.
3. **Instance state** — `_credential_store_ref`, `_on_trust_ref`, `_auto_security` track negotiation context for Connect upgrade.

### `_connect()` — Mode 3 upgrade loop

**Upstream:**

```python
self.connection.Connect(request)
```

**EUCRA:**

- Retry loop on `Connect` RPC.
- On `UNAUTHENTICATED` with `_auto_security=True`, calls `_upgrade_channel_with_token_after_unauthenticated()` once, then retries.
- Wraps persistent auth failures in `TekAuthenticationFailed` (auto-security path).
- Legacy plain path re-raises raw `grpc.RpcError` on `UNAUTHENTICATED`.

### `_upgrade_channel_with_token_after_unauthenticated()` (new)

After TLS Connect is rejected for lack of client credentials:

1. Requires `credential_store` and `on_trust_prompt`.
2. Re-fetches live cert; checks fingerprint against store (`TekCertificateMismatch` on mismatch).
3. Calls `on_trust_prompt(..., auth_required=True)` for password.
4. Saves password to store; rebuilds channel with Mode 3 credentials.
5. **Rebinds** `self.connection` and `self.native` stubs on the new channel (required for data-plane RPCs after upgrade).

### Unchanged in this file

- Waveform read/cache/background thread logic
- `access_data()`, `get_data()`, acquisition filters
- Parallel read executor (experimental)
- `close()` registry cleanup block (upstream defect; still references `_available_symbols` instead of `_connections`)

---

## Files not changed

Under `src/tekhsi/`, these match upstream TekHSI v1.1.0:

- `_tek_highspeed_server_pb2.py`, `_tek_highspeed_server_pb2_grpc.py`
- `helpers/` (logging, enums, etc.)
- All waveform and instrumentation logic outside the security hooks above

---

## Behavioral contract (quick reference)

```python
# Unchanged upstream usage
with TekHSIConnect("169.254.6.254:5000") as scope:
    ...

# Secure usage (examples)
with TekHSIConnect(url, credential_store=store, on_trust_prompt=prompt) as scope:
    ...

with TekHSIConnect(url, credentials=TekHSICredentials.tls("instrument.pem")) as scope:
    ...

with TekHSIConnect(url, require_tls=True, credential_store=store, on_trust_prompt=prompt) as scope:
    ...
```

See `EUCRA_USAGE.md` for full user-facing documentation.

---

## Line-count reference

| File | Status | Lines (approx.) |
|------|--------|-----------------|
| `auth_basic.py` | New | 38 |
| `credential_store.py` | New | 257 |
| `security.py` | New | 412 |
| `tek_hsi_connect.py` | Modified | +174 / −3 vs upstream |
| `__init__.py` | Modified | +18 lines |

*Compared to [tektronix/TekHSI](https://github.com/tektronix/TekHSI) `main` as of the EUCRA port baseline (release 1.1.0).*
