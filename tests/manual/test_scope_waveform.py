"""Manual scope integration test — skipped unless TEKHSI_RUN_MANUAL_SCOPE=1.

Run against real hardware::

    set TEKHSI_RUN_MANUAL_SCOPE=1
    set TEKHSI_SCOPE_URL=<instrument-ip>:5000
    pytest tests/manual/test_scope_waveform.py -v -s

Prefer the script for scenario sweeps::

    python scripts/manual_scope_waveform.py --list-scenarios
    python scripts/manual_scope_waveform.py --scenario auto --url <instrument-ip>:5000
"""

from __future__ import annotations

import os
import sys

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

manual_scope_waveform = pytest.importorskip("manual_scope_waveform")
run_scenario = manual_scope_waveform.run_scenario


@pytest.mark.manual
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("legacy", id="legacy"),
        pytest.param("auto-isolated-store", id="auto-isolated-store"),
        pytest.param("token-store", id="token-store"),
    ],
)
def test_scope_waveform_scenario(
    scenario: str, tmp_path: Path, scope_url: str, scope_channel: str
) -> None:
    """Connect to a real scope and pull one waveform (manual hardware test)."""
    store_path = tmp_path / "credentials.ini"
    report = run_scenario(
        scenario,
        url=scope_url,
        channel=scope_channel,
        password=os.environ.get("TEKHSI_SCOPE_PASSWORD", "tek"),
        login=os.environ.get("TEKHSI_SCOPE_LOGIN", "Tektronix"),
        store_path=store_path if scenario != "legacy" else None,
        timeout=float(os.environ.get("TEKHSI_SCOPE_TIMEOUT", "15")),
        log_dir=PROJECT_ROOT / "tests" / "manual" / "logs",
    )
    assert not report.failed_steps(), report.failed_steps()
