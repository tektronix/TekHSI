# Scripts

Repository management utilities. These scripts help contributors set up their environment and
keep generated code in sync — they are not tests and do not require a live instrument.

| Script                                         | Purpose                                                             |
| ---------------------------------------------- | ------------------------------------------------------------------- |
| [`contributor_setup.py`](contributor_setup.py) | Set up a local environment for contributing (see `CONTRIBUTING.md`) |
| [`generate_protos.py`](generate_protos.py)     | Regenerate gRPC stubs from `normalizedvector.proto`                 |

## Usage

```shell
python scripts/contributor_setup.py
python scripts/generate_protos.py
```

Live-instrument diagnostics, benchmarks, and manual hardware test scripts live under
[`tests/manual/`](../tests/manual/README.md) since they require a reachable TekHSI-enabled
instrument and are not part of repository management.
