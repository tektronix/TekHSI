# Troubleshooting

This page lists common problems encountered when developing, testing, and building the
documentation for TekHSI, grouped by category. Each entry gives the symptom you will see and the
recommended fix.

## Static Analysis

### Pyright reports `pytest` import/member errors in tests

**Symptom:** If your type-check environment does not install test dependencies, Pyright may
report:

- `Import "pytest" could not be resolved`
- `Type of "fixture"/"mark"/"raises" is unknown`

**Solution:** Use the existing test pattern in this repo:

```python
from typing import Any
import pytest as _pytest  # pyright: ignore[reportMissingImports]

pytest: Any = _pytest
```

This keeps runtime test behavior unchanged while avoiding false-positive type errors.

## Running Tests

### `pytest -q` appears stuck on `wait_for_data_access`

**Symptom:** The test run appears to hang with no visible progress.

**Solution:** Some tests may wait for instrument/network state and can take longer than expected.
To identify the exact test currently running:

```powershell
python -m pytest -vv -s --maxfail=1
```

To run a quicker local suite without slow/docs tests:

```powershell
python -m pytest -q -k "not slow and not docs"
```

### Docs tests fail due to missing tools

**Symptom:** `tests/test_docs.py` fails with errors about missing `mkdocs` or `linkchecker`.

**Solution:** Install project/dev dependencies (for example via `poetry install`) and re-run:

```powershell
python -m pytest tests/test_docs.py -q --maxfail=1
```

## Building & Packaging

### Packaging output location

Build artifacts are written to `dist/`:

```powershell
python -m build
Get-ChildItem .\dist\*.whl
```

Install a locally built wheel:

```powershell
python -m pip install .\dist\tekhsi-<version>-py3-none-any.whl
```

## Still Stuck?

If none of the above resolves your issue, search the
[existing GitHub issues](https://github.com/tektronix/TekHSI/issues) and open a new one if needed,
including the command you ran, the full error output, and your Python/OS version.
