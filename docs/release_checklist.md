# Release Checklist

Use this checklist before publishing a new version.

## 1) Update versioning and release notes

- Update `tool.poetry.version` in `pyproject.toml`.
- Add release notes to the `Unreleased` section in `CHANGELOG.md`.
- Mirror the same notes in `docs/CHANGELOG.md`.

## 2) Run focused validation

```powershell
python -m pytest tests/test_docs.py -q --maxfail=1
python -m pytest tests/test_security.py -q --maxfail=1
python -m pytest tests/test_wfm_digital.py -q --maxfail=1
```

## 3) Run broader validation (recommended)

```powershell
python -m pytest -q --maxfail=1
```

If local hardware/integration tests are long-running, use:

```powershell
python -m pytest -q -k "not slow and not docs"
```

## 4) Build distribution artifacts

```powershell
python -m build
```

Expected output files in `dist/`:

- `tekhsi-<version>.tar.gz`
- `tekhsi-<version>-py3-none-any.whl`

## 5) Smoke install from wheel (recommended)

```powershell
python -m pip install --force-reinstall .\dist\tekhsi-<version>-py3-none-any.whl
python -c "import tekhsi; print(tekhsi.__version__)"
```

## 6) Documentation navigation and links

- Ensure new/updated docs pages are linked from `README.md` and `mkdocs.yml`.
- Verify docs link checks pass through `tests/test_docs.py`.
