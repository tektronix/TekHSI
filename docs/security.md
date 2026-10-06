# Security and Authentication

TekHSI supports legacy plaintext connections as well as TLS-secured connections with optional HTTP Basic authentication.

## Connection modes

- **Plain gRPC:** the legacy mode used when no security options are provided.
- **TLS:** certificate-authenticated transport without a password.
- **TLS + Basic authentication:** certificate-authenticated transport with a username and password.
    Secure connections require the `cryptography` dependency, which is installed automatically with TekHSI.

## Explicit TLS credentials

Use `TekHSICredentials.tls()` when the scope certificate is available as a PEM file:

```python
from tekhsi import TekHSIConnect, TekHSICredentials

credentials = TekHSICredentials.tls("scope-cert.pem")
with TekHSIConnect("scope-host:5000", credentials=credentials) as scope:
    with scope.access_data():
        waveform = scope.get_data("ch1")
```

For TLS plus HTTP Basic authentication, use `TekHSICredentials.token()`:

```python
credentials = TekHSICredentials.token(
    "scope-cert.pem",
    "scope-password",
)
with TekHSIConnect("scope-host:5000", credentials=credentials) as scope:
    with scope.access_data():
        waveform = scope.get_data("ch1")
```

Do not commit passwords or private certificates to source control. Prefer environment variables or a protected credential store for production applications.

## Credential store and trust-on-first-use

`TekHSICredentialStore` persists trusted certificate information and credentials for reuse:

```python
from tekhsi import TekHSIConnect, TekHSICredentialStore

store = TekHSICredentialStore()


def trust_scope(host, certificate, authentication_required=False):
    if authentication_required:
        return True, "scope-password"
    return True


with TekHSIConnect(
    "scope-host:5000",
    credential_store=store,
    on_trust_prompt=trust_scope,
) as scope:
    with scope.access_data():
        waveform = scope.get_data("ch1")
```

The first connection can use `on_trust_prompt` to approve the scope certificate. The certificate fingerprint and credentials are then stored for later connections. A changed certificate raises a certificate-mismatch error rather than silently trusting a different endpoint.
The default store locations are:

| Platform                                                                                                                                      | Location                                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Windows                                                                                                                                       | `%APPDATA%\tektronix\credentials.ini`                     |
| Linux                                                                                                                                         | `~/.tektronix/credentials.ini`                            |
| macOS                                                                                                                                         | `~/Library/Application Support/tektronix/credentials.ini` |
| The store also maintains a `certs/` directory. Protect both the INI file and certificate directory using normal operating-system permissions. |                                                           |

## Authentication errors

- `TekUnknownInstrument`: the endpoint is not trusted and no trust callback accepted it.
- `TekCertificateMismatch`: the endpoint certificate differs from the trusted fingerprint.
- `TekAuthenticationFailed`: the scope rejected the supplied password or authentication negotiation.
- `TekSecurityError`: secure-channel setup failed for another security reason.

## Live-scope validation

Manual hardware tests are disabled unless explicitly enabled:

```powershell
$env:TEKHSI_RUN_MANUAL_SCOPE = "1"
$env:TEKHSI_SCOPE_URL = "scope-host:5000"
$env:TEKHSI_SCOPE_CHANNEL = "ch1"
$env:TEKHSI_SCOPE_PASSWORD = "<scope-password>"
python -m pytest tests/manual/test_scope_fastframe_auth.py -v -s
```

The test discovers the scope security mode, authenticates, reads a stopped FastFrame capture, and reports record length, frame count, summary-frame state, and transfer timing. Never commit a real scope address or password to the repository.

## FastFrame and authentication together

Authentication is independent of waveform type. After a secure connection is established, use `access_stopped_data()` to read a stopped FastFrame acquisition:

```python
from tekhsi import TekHSIConnect, TekHSICredentials
from tm_data_types import FastFrameAnalogWaveform

credentials = TekHSICredentials.token("scope-cert.pem", "scope-password")
with TekHSIConnect("scope-host:5000", credentials=credentials) as scope:
    with scope.access_stopped_data():
        waveform = scope.get_data("ch1")
if not isinstance(waveform, FastFrameAnalogWaveform):
    raise RuntimeError("FastFrame data was not returned")
print(waveform.num_frames)
print(waveform.data_frame_count)
print(waveform.summary_frame_index)
```

The manual integration test in `tests/manual/test_scope_fastframe_auth.py` validates security negotiation and a stopped FastFrame read in the same run. It does not change scope settings.

## Troubleshooting

| Symptom                                                             | Recommended action                                                                                        |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `UNAUTHENTICATED`                                                   | Confirm the scope is in the expected security mode and verify the password.                               |
| Certificate mismatch                                                | Remove the stale stored certificate only after verifying the new certificate, then trust it deliberately. |
| No active channel                                                   | Enable the channel on the scope and check `TEKHSI_SCOPE_CHANNEL`.                                         |
| A regular waveform is returned instead of `FastFrameAnalogWaveform` | Confirm FastFrame is enabled and the scope is stopped.                                                    |
| `num_frames` is zero                                                | Check the scope FastFrame frame-count and acquisition settings.                                           |
| `summary_frame_index is None`                                       | A summary frame may be disabled for the current acquisition mode.                                         |
| Plain connection works but TLS fails                                | Verify the PEM path, certificate fingerprint, and TLS server name.                                        |
| Credentials are not reused                                          | Check the credential-store path, file permissions, and the exact `host:port` value.                       |
| `cryptography` cannot be imported                                   | Reinstall the project dependencies from `pyproject.toml`.                                                 |
| Digital frame data is unexpected                                    | Check the source width and preserve the digital bitmask metadata when writing waveform files.             |

## Related API reference

The generated API reference documents the implementation details for:

- [`TekHSIConnect`][tekhsi.tek_hsi_connect.TekHSIConnect]
- [`TekHSICredentials`][tekhsi.security.TekHSICredentials]
- [`TekHSICredentialStore`][tekhsi.credential_store.TekHSICredentialStore]
- [`TekAuthenticationFailed`][tekhsi.security.TekAuthenticationFailed]
- [`TekCertificateMismatch`][tekhsi.security.TekCertificateMismatch]
- [`TekSecurityError`][tekhsi.security.TekSecurityError]
- `FastFrameLoadTiming` (the compatibility alias for [`WaveformTransferTiming`][tekhsi.load_timing.WaveformTransferTiming])
- `FastFrameDigitalWaveform` from `tm_data_types`
