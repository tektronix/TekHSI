# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com), and this
project adheres to [Semantic Versioning](https://semver.org).

Valid subsections within a version are:

- Added
- Changed
- Deprecated
- Removed
- Fixed
- Security

---

## Unreleased

Things to be included in the next release go here.

### Added

- Added an installation section to the main README.
- Added support for Python 3.13.

### Removed

- Python 3.8 support has been removed from the package. The minimum supported version is now Python 3.9.

### Changed

- Updated the documentation by moving portions from the Basic Usage page to the API docs.
- Switched from using standard `print()` calls to using the `logging` module for all logging in the `tekhsi` package.
    - A configuration function provides the ability to set different logging levels for stdout and file logging.
    - By default, a log file is created with every debug message logged to it.

### Removed

- _**<span style="color:orange">minor breaking change</span>**_: Removed the `print_with_timestamp()` function since this functionality is now handled by the `logging` module.
- _**<span style="color:orange">minor breaking change</span>**_: Removed the `get_timestamp_string()` function since this functionality is now handled by the `logging` module.

---

## v1.0.0 (2024-09-20)

### Merged Pull Requests

- Updated Documentation to include usage of PyVISA and tm_devices along with TekHSI. ([#24](https://github.com/tektronix/TekHSI/pull/24))
- python-deps(deps): bump the python-dependencies group across 1 directory with 4 updates ([#23](https://github.com/tektronix/TekHSI/pull/23))
- test: enabled doctest in test-docs.yml ([#22](https://github.com/tektronix/TekHSI/pull/22))
- fix: Remove corrupted requirements file ([#21](https://github.com/tektronix/TekHSI/pull/21))
- ci: Update tektronix/python-package-ci-cd workflows to v1.4.0 ([#20](https://github.com/tektronix/TekHSI/pull/20))

### Added

- Updated documentation to include examples illustrating usage of `PyVISA` and `tm_devices`.
- Updated documentation requirements.

---

## v0.1.1 (2024-09-11)

### Merged Pull Requests

- Update documentation and add missing dependencies ([#19](https://github.com/tektronix/TekHSI/pull/19))

### Fixed

- Added missing dependencies to `pyproject.toml`.

### Changed

- Updated all documentation links to use the proper URLs and fixed Readme badges.

---

## v0.1.0 (2024-09-11)

### Merged Pull Requests

- chore: Update dependencies and remove unneeded dependencies ([#18](https://github.com/tektronix/TekHSI/pull/18))
- fix: Updated project description in pyproject.toml ([#14](https://github.com/tektronix/TekHSI/pull/14))
- Static Code Analysis changes ([#12](https://github.com/tektronix/TekHSI/pull/12))
- tests: Update test_client.py for tests to run efficiently on tox. ([#8](https://github.com/tektronix/TekHSI/pull/8))
- fix: Resolved some security issues flagged by CodeQL ([#4](https://github.com/tektronix/TekHSI/pull/4))
- build: Update dependencies to temporarily use the GitHub repo for tm_data_types ([#2](https://github.com/tektronix/TekHSI/pull/2))
- fix: Updated line endings in known_words.txt ([#1](https://github.com/tektronix/TekHSI/pull/1))

### Added

- First release of `TekHSI`!
