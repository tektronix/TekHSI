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

---

## v1.1.0 (2026-02-27)

### Merged Pull Requests

- fix: update access_data() attributes to use AcqWaitOn.NewData ([#126](https://github.com/tektronix/TekHSI/pull/126))
- chore: Update documentation dependencies ([#123](https://github.com/tektronix/TekHSI/pull/123))
- chore: Update Mermaid library source to use CDN ([#99](https://github.com/tektronix/TekHSI/pull/99))
- Drop support for Python 3.8 and 3.9, add support for Python 3.13, and improve handling of gRPC errors ([#85](https://github.com/tektronix/TekHSI/pull/85))
- gh-actions(deps): bump tektronix/python-package-ci-cd ([#32](https://github.com/tektronix/TekHSI/pull/32))
- fix: removed serial keyword from mkdocs.yml file. ([#55](https://github.com/tektronix/TekHSI/pull/55))
- python-deps(deps-dev): update twine requirement from ^5.0.0 to ^6.0.1 in the python-dependencies group ([#49](https://github.com/tektronix/TekHSI/pull/49))
- docs: Remove section of contribution guide that duplicates a later section ([#50](https://github.com/tektronix/TekHSI/pull/50))
- feat: Add insiders documentation features. ([#48](https://github.com/tektronix/TekHSI/pull/48))
- Switch from print to logging ([#46](https://github.com/tektronix/TekHSI/pull/46))
- python-deps(deps-dev): update wheel requirement from ^0.44 to ^0.45 in the python-dependencies group ([#44](https://github.com/tektronix/TekHSI/pull/44))
- chore: Update pyright dependency and use more reliable method of installing local nodejs for it ([#43](https://github.com/tektronix/TekHSI/pull/43))
- python-deps(deps-dev): update pyright requirement from 1.1.386 to 1.1.387 in the python-dependencies group ([#42](https://github.com/tektronix/TekHSI/pull/42))
- python-deps(deps-dev): update pyright requirement from 1.1.383 to 1.1.386 in the python-dependencies group across 1 directory ([#41](https://github.com/tektronix/TekHSI/pull/41))
- ci: Skip updating the mdformat repo during the dependency updater workflow ([#40](https://github.com/tektronix/TekHSI/pull/40))
- docs: Update documentation templates and macros ([#38](https://github.com/tektronix/TekHSI/pull/38))
- ci: Remove pre-commit hook that no longer works on Python 3.8 and replace with one that does ([#35](https://github.com/tektronix/TekHSI/pull/35))
- python-deps(deps-dev): update pyright requirement from 1.1.382.post1 to 1.1.383 in the python-dependencies group ([#33](https://github.com/tektronix/TekHSI/pull/33))
- docs: Update basic usage documentation page ([#31](https://github.com/tektronix/TekHSI/pull/31))
- python-deps(deps-dev): update pyright requirement from 1.1.381 to 1.1.382.post1 in the python-dependencies group ([#29](https://github.com/tektronix/TekHSI/pull/29))
- test: Ignore googletagmanager links during doctests ([#27](https://github.com/tektronix/TekHSI/pull/27))
- python-deps(deps-dev): update pyright requirement from 1.1.380 to 1.1.381 in the python-dependencies group ([#26](https://github.com/tektronix/TekHSI/pull/26))
- docs: updated development status in toml file. ([#25](https://github.com/tektronix/TekHSI/pull/25))

### Removed

- Python 3.8 and 3.9 support has been removed from the package. The minimum supported version is now Python 3.10.

### Added

- Added support for Python 3.13.
- Added an installation section to the main README.

### Changed

- Updated project dependencies to ensure compatibility with supported Python versions.
- Updated CI configuration to reflect the supported Python version matrix (Python 3.10–3.13).
- Improved exception handling in `tek_hsi_client.py` to provide clearer handling of gRPC errors.
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
