"""Manual scope integration test — skipped unless TEKHSI_RUN_MANUAL_SCOPE=1.

Run against real hardware::

    set TEKHSI_RUN_MANUAL_SCOPE=1
    set TEKHSI_SCOPE_URL=169.254.6.254:5000
    pytest tests/manual/test_scope_waveform.py -v -s

Prefer the script for scenario sweeps::

    python tests/manual/manual_scope_waveform.py --list-scenarios
    python tests/manual/manual_scope_waveform.py --scenario auto --url 169.254.6.254:5000
"""

from __future__ import annotations

import os

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from manual_scope_waveform import (  # pylint: disable=import-error
    run_scenario,  # type: ignore
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [  # pyright: ignore[reportUnknownVariableType]
    pytest.mark.manual,  # pyright: ignore[reportUnknownMemberType]
    pytest.mark.skipif(  # pyright: ignore[reportUnknownMemberType]
        os.environ.get("TEKHSI_RUN_MANUAL_SCOPE") != "1",
        reason=(
            "Manual scope test — set TEKHSI_RUN_MANUAL_SCOPE=1 and TEKHSI_SCOPE_URL. "
            "Or run: python tests/manual/manual_scope_waveform.py"
        ),
    ),
]


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    "scenario",
    [
        pytest.param("legacy", id="legacy"),  # pyright: ignore[reportUnknownMemberType]
        pytest.param("auto-isolated-store", id="auto-isolated-store"),  # pyright: ignore[reportUnknownMemberType]
        pytest.param("token-store", id="token-store"),  # pyright: ignore[reportUnknownMemberType]
    ],
)
def test_scope_waveform_scenario(scenario: str, tmp_path: Path) -> None:
    """Connect to a real scope and pull one waveform (manual hardware test)."""
    url = os.environ.get("TEKHSI_SCOPE_URL", "169.254.6.254:5000")
    store_path = tmp_path / "credentials.ini"
    report = run_scenario(  # pyright: ignore[reportUnknownVariableType]
        scenario,
        url=url,
        channel=os.environ.get("TEKHSI_SCOPE_CHANNEL", "ch1"),
        password=os.environ.get("TEKHSI_SCOPE_PASSWORD", "tek"),
        login=os.environ.get("TEKHSI_SCOPE_LOGIN", "Tektronix"),
        store_path=store_path if scenario != "legacy" else None,
        timeout=float(os.environ.get("TEKHSI_SCOPE_TIMEOUT", "15")),
        log_dir=PROJECT_ROOT / "tests" / "manual" / "logs",
    )
    assert not report.failed_steps(), report.failed_steps()  # pyright: ignore[reportUnknownMemberType]
