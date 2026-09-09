# Troubleshooting

## Pyright reports `pytest` import/member errors in tests

If your type-check environment does not install test dependencies, Pyright may report:

- `Import "pytest" could not be resolved`
- `Type of "fixture"/"mark"/"raises" is unknown`

Use the existing test pattern in this repo:

```python
from typing import Any
import pytest as _pytest  # pyright: ignore[reportMissingImports]

pytest: Any = _pytest
```

This keeps runtime test behavior unchanged while avoiding false-positive type errors.

## `pytest -q` appears stuck on `wait_for_data_access`

Some tests may wait for instrument/network state and can take longer than expected.
To identify the exact test currently running:

```powershell
python -m pytest -vv -s --maxfail=1
```

To run a quicker local suite without slow/docs tests:

```powershell
python -m pytest -q -k "not slow and not docs"
```

## Docs tests fail due to missing tools

`tests/test_docs.py` requires `mkdocs` and `linkchecker`.
Install project/dev dependencies (for example via `poetry install`) and re-run:

```powershell
python -m pytest tests/test_docs.py -q --maxfail=1
```

## Packaging output location

Build artifacts are written to `dist/`:

```powershell
python -m build
Get-ChildItem .\dist\*.whl
```

Install a locally built wheel:

```powershell
python -m pip install .\dist\tekhsi-<version>-py3-none-any.whl
```
