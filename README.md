<div markdown="1" class="custom-badge-table">

|                   |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Testing**       | [![Code testing status](https://github.com/tektronix/TekHSI/actions/workflows/test-code.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/test-code.yml) [![Docs testing status](https://github.com/tektronix/TekHSI/actions/workflows/test-docs.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/test-docs.yml) [![Coverage status](https://codecov.io/gh/tektronix/TekHSI/branch/main/graph/badge.svg)](https://codecov.io/gh/tektronix/TekHSI)                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **Code Quality**  | [![CodeQL status](https://github.com/tektronix/TekHSI/actions/workflows/codeql-analysis.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/codeql-analysis.yml) [![CodeFactor grade](https://www.codefactor.io/repository/github/tektronix/TekHSI/badge)](https://www.codefactor.io/repository/github/tektronix/TekHSI) [![pre-commit status](https://results.pre-commit.ci/badge/github/tektronix/TekHSI/main.svg)](https://results.pre-commit.ci/latest/github/tektronix/TekHSI/main)                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **Package**       | [![PyPI: Package status](https://img.shields.io/pypi/status/TekHSI?logo=pypi)](https://pypi.org/project/TekHSI/) [![PyPI: Latest release version](https://img.shields.io/pypi/v/TekHSI?logo=pypi)](https://pypi.org/project/TekHSI/) [![PyPI: Supported Python versions](https://img.shields.io/pypi/pyversions/TekHSI?logo=python)](https://pypi.org/project/TekHSI/) [![PyPI: Downloads](https://pepy.tech/badge/TekHSI)](https://pepy.tech/project/TekHSI) [![License: Apache 2.0](https://img.shields.io/pypi/l/tekhsi)](https://github.com/tektronix/TekHSI/blob/main/LICENSE.md) [![Package build status](https://github.com/tektronix/TekHSI/actions/workflows/package-build.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/package-build.yml) [![PyPI upload status](https://github.com/tektronix/TekHSI/actions/workflows/package-release.yml/badge.svg?branch=main)](https://github.com/tektronix/TekHSI/actions/workflows/package-release.yml) |
| **Documentation** | [![ReadtheDocs Status](https://img.shields.io/readthedocs/tekhsi/stable?logo=readthedocs)](https://tekhsi.readthedocs.io)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Code Style**    | [![Test style: pytest](https://img.shields.io/badge/test%20style-pytest-blue)](https://github.com/pytest-dev/pytest) [![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-black)](https://docs.astral.sh/ruff/formatter/) [![Docstring style: google](https://img.shields.io/badge/docstring%20style-google-tan)](https://google.github.io/styleguide/pyguide.html)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **Linting**       | [![pre-commit enabled](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit) [![Docstring formatter: docformatter](https://img.shields.io/badge/docstring%20formatter-docformatter-tan)](https://github.com/PyCQA/docformatter)[![Linter: pylint](https://img.shields.io/badge/linter-pylint-purple)](https://github.com/pylint-dev/pylint)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

</div>

---

# TekHSI: Tektronix High Speed Interface

`TekHSI` is a Python library that provides a low latency, high-speed data link between Tektronix scopes and host computer using gRPC. This library is designed to provide a reliable and efficient way to transfer data between devices, especially when dealing with large amounts of data.

With `TekHSI`, you can easily connect your Tektronix scope to other devices, such as host computers or other test equipment, and transmit data quickly and efficiently. This library is especially useful for applications that require real-time data acquisition and analysis, such as in the fields of electronics, telecommunications, and signal processing.

`TekHSI` uses gRPC, a high-performance, open-source framework that provides a platform-independent way to communicate between applications. This means you can use `TekHSI` with any platform supporting gRPC, including Windows, Linux, and macOS.

## Some of the key features of `TekHSI` include:

1. Low latency - `TekHSI` provides a fast and efficient data link between devices, with minimal delay between data transmission and reception.
2. High speed - `TekHSI` can transfer large amounts of data quickly and efficiently.
3. Easy to use - `TekHSI` is designed to be easy to use, with a simple and intuitive API that makes it easy to connect your Tektronix scope.
4. Consistent sets - `TekHSI` guarantees that data arrives in "consistent sets." This means that data is all from the same acquisition. This is true when the instrument is stopped and when it is running. When using SCPI commands, this is only guaranteed when the instrument is stopped.
5. Richer Synchronization - `TekHSI` allows a rich set of synchronization options. This includes accepting any arriving acquisition, accepting acquisitions with vertical or horizontal changes, or only accepting acquisitions after a certain time.

In summary, if you need a reliable and efficient way to transfer data between your Tektronix scope and host computer, `TekHSI` is the library for you. With its low latency, high speed, and easy-to-use API, `TekHSI` provides a powerful solution for data acquisition and analysis.

## Devices with TekHSI support

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

<div markdown="1" class="custom-table-center-cells device-support-table">

</div>

## Documentation

See the full documentation at <https://TekHSI.readthedocs.io>

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

Interested in contributing? Check out the [contributing guidelines](https://github.com/tektronix/TekHSI/blob/main/CONTRIBUTING.md). Please
note that this project is released with a [Code of Conduct](https://github.com/tektronix/TekHSI/blob/main/CODE_OF_CONDUCT.md). By
contributing to this project, you agree to abide by its terms.

## License

`TekHSI` was created by Tektronix. It is licensed under the terms of
the [Apache License 2.0](https://github.com/tektronix/TekHSI/blob/main/LICENSE.md).

## Security

The signatures of the files uploaded to [PyPI](https://pypi.org/project/TekHSI/) and each
[GitHub Release](https://github.com/tektronix/TekHSI/releases) can be verified using
the [GitHub CLI `attestation verify` command](https://cli.github.com/manual/gh_attestation_verify).
The artifact attestations can also be directly downloaded from the
[GitHub repo attestations page](https://github.com/tektronix/TekHSI/attestations) if desired.

```shell
gh attestation verify --owner tektronix <file>
```
