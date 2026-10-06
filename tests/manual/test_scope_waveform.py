# Copyright (c) 2026 Tektronix, Inc.
"""Manual scope integration test — skipped unless TEKHSI_RUN_MANUAL_SCOPE=1.

Run against real hardware::

    set TEKHSI_RUN_MANUAL_SCOPE=1
    set TEKHSI_SCOPE_URL=169.254.6.254:5000
    pytest tests/manual/test_scope_waveform.py -v -s

Prefer the script for scenario sweeps::

    python scripts/manual_scope_waveform.py --list-scenarios
    python scripts/manual_scope_waveform.py --scenario auto --url 169.254.6.254:5000
"""

from __future__ import annotations

import os
import sys

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from manual_scope_waveform import run_scenario  # noqa: E402

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("TEKHSI_RUN_MANUAL_SCOPE") != "1",
        reason=(
            "Manual scope test — set TEKHSI_RUN_MANUAL_SCOPE=1 and TEKHSI_SCOPE_URL. "
            "Or run: python scripts/manual_scope_waveform.py"
        ),
    ),
]


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("legacy", id="legacy"),
        pytest.param("auto-isolated-store", id="auto-isolated-store"),
        pytest.param("token-store", id="token-store"),
    ],
)
def test_scope_waveform_scenario(scenario: str, tmp_path: Path) -> None:
    """Connect to a real scope and pull one waveform (manual hardware test)."""
    url = os.environ.get("TEKHSI_SCOPE_URL", "169.254.6.254:5000")
    store_path = tmp_path / "credentials.ini"
    report = run_scenario(
        scenario,
        url=url,
        channel=os.environ.get("TEKHSI_SCOPE_CHANNEL", "ch1"),
        password=os.environ.get("TEKHSI_SCOPE_PASSWORD", "tek"),
        login=os.environ.get("TEKHSI_SCOPE_LOGIN", "Tektronix"),
        store_path=store_path if scenario != "legacy" else None,
        timeout=float(os.environ.get("TEKHSI_SCOPE_TIMEOUT", "15")),
        log_dir=PROJECT_ROOT / "tests" / "manual" / "logs",
    )
    assert not report.failed_steps(), report.failed_steps()
