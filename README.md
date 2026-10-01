<div markdown="1" class="custom-badge-table">

|                   |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Testing**       | [![Code testing status](https://github.com/tektronix/TekHSI/actions/workflows/test-code.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/test-code.yml) [![Docs testing status](https://github.com/tektronix/TekHSI/actions/workflows/test-docs.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/test-docs.yml) [![Coverage status](https://codecov.io/gh/tektronix/TekHSI/branch/main/graph/badge.svg)](https://codecov.io/gh/tektronix/TekHSI)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Code Quality**  | [![CodeQL status](https://github.com/tektronix/TekHSI/actions/workflows/codeql-analysis.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/codeql-analysis.yml) [![CodeFactor grade](https://www.codefactor.io/repository/github/tektronix/TekHSI/badge)](https://www.codefactor.io/repository/github/tektronix/TekHSI) [![pre-commit status](https://results.pre-commit.ci/badge/github/tektronix/TekHSI/main.svg)](https://results.pre-commit.ci/latest/github/tektronix/TekHSI/main)                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **Package**       | [![PyPI: Package status](https://img.shields.io/pypi/status/TekHSI?logo=pypi)](https://pypi.org/project/TekHSI/) [![PyPI: Latest release version](https://img.shields.io/pypi/v/TekHSI?logo=pypi)](https://pypi.org/project/TekHSI/) [![PyPI: Supported Python versions](https://img.shields.io/pypi/pyversions/TekHSI?logo=python)](https://pypi.org/project/TekHSI/) [![PyPI: Downloads](https://static.pepy.tech/badge/TekHSI)](https://pepy.tech/project/TekHSI) [![License: Apache 2.0](https://img.shields.io/pypi/l/tekhsi)](https://github.com/tektronix/TekHSI/blob/main/LICENSE.md) [![Package build status](https://github.com/tektronix/TekHSI/actions/workflows/package-build.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/package-build.yml) [![PyPI upload status](https://github.com/tektronix/TekHSI/actions/workflows/package-release.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/package-release.yml) |
| **Documentation** | [![ReadtheDocs Status](https://img.shields.io/readthedocs/tekhsi/stable?logo=readthedocs)](https://tekhsi.readthedocs.io)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **Code Style**    | [![Test style: pytest](https://img.shields.io/badge/test%20style-pytest-blue)](https://github.com/pytest-dev/pytest) [![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-black)](https://docs.astral.sh/ruff/formatter/) [![Docstring style: google](https://img.shields.io/badge/docstring%20style-google-tan)](https://google.github.io/styleguide/pyguide.html)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Linting**       | [![pre-commit enabled](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit) [![Docstring formatter: docformatter](https://img.shields.io/badge/docstring%20formatter-docformatter-tan)](https://github.com/PyCQA/docformatter)[![Linter: pylint](https://img.shields.io/badge/linter-pylint-purple)](https://github.com/pylint-dev/pylint)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

</div>

---

# TekHSI: Tektronix High Speed Interface

**FastFrame build v1.2.0** — extends upstream TekHSI with multi-frame capture, load timing, and
benchmark tooling. Requires **`tm_data_types>=0.5.0,<0.6.0`** and **`protobuf>=7.35,<8.0`**.
See [FastFrame demo guide](docs/DEMO_README.md).

`TekHSI` is a Python library that provides a low latency, high-speed data link between Tektronix
scopes and host computer using gRPC. This library is designed to provide a reliable and efficient
way to transfer data between devices, especially when dealing with large amounts of data.

With `TekHSI`, you can easily connect your Tektronix scope to other devices, such as host computers
or other test equipment, and transmit data quickly and efficiently. This library is especially
useful for applications that require real-time data acquisition and analysis, such as in the
fields of electronics, telecommunications, and signal processing.

`TekHSI` uses gRPC, a high-performance, open-source framework that provides a platform-independent
way to communicate between applications. This means you can use `TekHSI` with any platform
supporting gRPC, including Windows, Linux, and macOS.

> [!NOTE]
> **FastFrame stream status quirk:** On live scopes, `GetWaveform` data chunks often arrive with
> `WFMREPLYSTATUS_UNSPECIFIED` rather than `WFMREPLYSTATUS_SUCCESS`. Only the final (often empty)
> stream message may report `SUCCESS`. Clients must treat both statuses as valid when reading chunk
> data; filtering on `SUCCESS` alone drops every frame and breaks FastFrame reads (notably digital
> captures such as `ch2_DAll`). TekHSI accepts `UNSPECIFIED` and `SUCCESS` in its stream parsers.

## Key Features

1. Low latency - `TekHSI` provides a fast and efficient data link between devices, with minimal
    delay between data transmission and reception.
2. High speed - `TekHSI` can transfer large amounts of data quickly and efficiently.
3. Easy to use - `TekHSI` is designed to be easy to use, with a simple and intuitive API that makes
    it easy to connect your Tektronix scope.
4. Consistent sets - `TekHSI` guarantees that data arrives in "consistent sets." This means that
    data is all from the same acquisition. This is true when the instrument is stopped and when it
    is running. When using SCPI commands, this is only guaranteed when the instrument is stopped.
5. Richer Synchronization - `TekHSI` allows a rich set of synchronization options. This includes
    accepting any arriving acquisition, accepting acquisitions with vertical or horizontal changes,
    or only accepting acquisitions after a certain time.
6. **FastFrame** - Multi-frame stopped captures stream into `FastFrameAnalogWaveform` /
    `FastFrameDigitalWaveform` with per-frame timing metadata and `waveform.load_timing` transfer metrics.

In summary, if you need a reliable and efficient way to transfer data between your Tektronix scope
and host computer, `TekHSI` is the library for you. With its low latency, high speed, and
easy-to-use API, `TekHSI` provides a powerful solution for data acquisition and analysis.

## Installation

> [!IMPORTANT]
> `TekHSI` requires a 64-bit Python installation due to its external dependencies.

### This FastFrame build (local wheel)

Bump the project version in `pyproject.toml` when preparing a new release, rebuild, then install:

```shell
python -m pip install build
python -m build --wheel --outdir dist
python -m pip install dist/tekhsi-1.2.0-py3-none-any.whl
```

The wheel filename matches the version in `pyproject.toml` (currently **1.2.0**).

### PyPI (upstream TekHSI)

```shell
pip install tekhsi
```

## Device Support

<div markdown="1" class="custom-table-center-cells device-support-table">

| Type   | Series/Model          |
| ------ | --------------------- |
| Scopes | **4 Series B MSO**    |
|        | **5 Series MSO**      |
|        | **5 Series B MSO**    |
|        | **5 Series MSO (LP)** |
|        | **6 Series MSO**      |
|        | **6 Series B MSO**    |
|        | **6 Series LPD**      |

</div>

## Live test status

Results from a live scope at **169.254.6.254:5000** (TekHSI v2, stopped FastFrame captures).
Transfer rates are **10-run averages** in **Mbit/s** from
[`scripts/measure_transfer_rate.py`](scripts/measure_transfer_rate.py) (`--iterations 10`).

### v1.1.1 diagnostic sweep (2026-07-24)

Isolated frame-count vs record-length sweeps (66 configs, 3 repeats each, randomized order) were
captured with `scripts/hsi_diagnostic_benchmark.py`.
Cross-check at RL=100K, N=10: **~9.4 ms** gRPC transfer in both sweeps. Re-run with:

```shell
python scripts/hsi_diagnostic_benchmark.py --ip 169.254.6.254 --repeats 3 --acq-timeout 120
```

Excel-friendly total-sample sweeps: [`scripts/reproduce_benchmark_issue.py`](scripts/reproduce_benchmark_issue.py).

### Transfer rate table

| Record length | Frames | Width | Ch1 analog data rate (Mbit/s) | Ch2 digital data rate (Mbit/s) |
| ------------- | ------ | ----- | ----------------------------- | ------------------------------ |
| 1,000         | 100    | 1     | 96.6                          | 94.2                           |
| 10,000        | 100    | 1     | 471                           | 813                            |
| 100,000       | 100    | 1     | 801                           | 931                            |
| 1,000,000     | 100    | 1     | 899                           | 940                            |
| 5,000,000     | 100    | 1     | 940                           | 941                            |

Throughput increases with record length and plateaus near **~940 Mbit/s** on large captures.
Small record lengths are dominated by fixed gRPC/setup overhead.

### FastFrame → .wfm → read-back

[`scripts/fastframe_wfm_roundtrip.py`](scripts/fastframe_wfm_roundtrip.py) — capture **ch1** and
**ch2_dall**, save to `.wfm`, re-read, and compare:

| Channel  | Capture          | Result                                       |
| -------- | ---------------- | -------------------------------------------- |
| ch1      | 100 × 5M samples | **PASS** — all 100 frames bit-accurate       |
| ch2_dall | 100 × 5M samples | **PASS** — all 100 frames + bitstreams match |

Saved files (local, gitignored): `sample_waveforms/fastframe_roundtrip/CH1.wfm`, `CH2_DALL.wfm`.

### Scope reference validation

[`scripts/validate_scope_refs.py`](scripts/validate_scope_refs.py) — compare scope refs loaded
from those `.wfm` files against the on-disk originals:

| Scope ref | Source file  | Result                                                                                     |
| --------- | ------------ | ------------------------------------------------------------------------------------------ |
| ref1      | CH1.wfm      | **PASS** — all 100 frames match                                                            |
| ref2_dall | CH2_DALL.wfm | **FAIL** — header reports 100 frames and `hasdata=True`, but `GetWaveform` returns 0 bytes |

Analog FastFrame refs load and stream correctly. Digital FastFrame refs appear in
`available_symbols` with a valid header, but TekHSI cannot pull waveform bytes from the scope
after loading from `.wfm`.

See also [scripts/README.md](scripts/README.md) for usage details on the benchmark and validation scripts.

### v1.2.0 library changes (summary)

- `access_stopped_data()` waits on **`NewData`** (not `AnyAcq`) so stopped FastFrame reads do not reuse stale cache.
- Background acquisition thread **always runs**; there is no `background_thread=False` mode.
- Pending/empty headers are retried; IQ reads fixed (`self.native` in `_read_waveform()`).
- Full list: [CHANGELOG v1.2.0](docs/CHANGELOG.md).

## Testing and Packaging Quick Checks

Use these commands as a practical pre-release gate:

```powershell
python -m pytest "tests/test_docs.py" -q --maxfail=1
python -m pytest -q --maxfail=1
python -m build
```

If your full test run is long-running due to instrument/network waits (for example repeated `wait_for_data_access` logs), run a quicker local pass and then targeted suites:

```powershell
python -m pytest -q -k "not slow and not docs"
python -m pytest "tests/test_security.py" -q --maxfail=1
python -m pytest "tests/test_wfm_digital.py" -q --maxfail=1
```

Build artifacts are written to `dist/` (wheel + sdist).

## Documentation

See the full documentation at <https://TekHSI.readthedocs.io>, or in this repository:

- [FastFrame demo guide](docs/DEMO_README.md)
- [Scripts usage](scripts/README.md)
- [Basic usage](docs/basic_usage.md)
- [EUCRA secure connections](docs/EUCRA_USAGE.md)
- [Release checklist](docs/release_checklist.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Changelog](docs/CHANGELOG.md)

## Maintainers

Before reaching out to any maintainers directly, please first check if
your issue or question is already covered by any [open
issues](https://github.com/tektronix/TekHSI/issues). If the issue or
question you have is not already covered, please [file a new
issue](https://github.com/tektronix/TekHSI/issues/new/choose) or
start a
[discussion](https://github.com/tektronix/TekHSI/discussions) and
the maintainers will review and respond there.

- <opensource@tektronix.com> - For open-source policy and license
    questions.

## Contributing

Interested in contributing? Check out the [contributing guidelines](docs/CONTRIBUTING.md). Please
note that this project is released with a [Code of Conduct](docs/CODE_OF_CONDUCT.md). By
contributing to this project, you agree to abide by its terms.

## License

`TekHSI` was created by Tektronix. It is licensed under the terms of
the [Apache License 2.0](docs/LICENSE.md).

## Security

The signatures of the files uploaded to [PyPI](https://pypi.org/project/TekHSI/) and each
[GitHub Release](https://github.com/tektronix/TekHSI/releases) can be verified using
the [GitHub CLI `attestation verify` command](https://cli.github.com/manual/gh_attestation_verify).
The artifact attestations can also be directly downloaded from the
[GitHub repo attestations page](https://github.com/tektronix/TekHSI/attestations) if desired.

```shell
gh attestation verify --owner tektronix <file>
```
