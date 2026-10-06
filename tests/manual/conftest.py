"""Reusable fixtures for manual live-scope integration tests."""

from __future__ import annotations

import os

from abc import ABC
from pathlib import Path

import pytest

from tm_data_types import Waveform

PROJECT_ROOT_DIR = Path(__file__).parent.parent


class DerivedWaveform(Waveform, ABC):
    """Provide the shared test waveform type when this conftest shadows the root module."""

    @property
    def _measured_data(self) -> str:
        """Implement the abstract waveform property for tests."""
        return "measured data"


class DerivedWaveformHandler:
    """Provide the shared test waveform handler when this conftest is imported as ``conftest``."""

    @staticmethod
    def data_arrival(waveforms: list[DerivedWaveform]) -> None:
        """Process waveforms for client tests."""
        for _ in waveforms:
            print("Processing waveform")


@pytest.fixture
def manual_scope_enabled_fixture() -> None:
    """Skip the test unless manual scope testing is explicitly enabled."""
    if os.environ.get("TEKHSI_RUN_MANUAL_SCOPE") != "1":
        pytest.skip("Set TEKHSI_RUN_MANUAL_SCOPE=1 to run against a real scope.")


@pytest.fixture
def scope_url(  # pylint: disable=redefined-outer-name
    manual_scope_enabled_fixture: None,
) -> str:
    """Return the instrument's TekHSI address, skipping if it isn't configured.

    There is intentionally no default - tests must be pointed at a real
    instrument via ``TEKHSI_SCOPE_URL``. Depends on ``manual_scope_enabled``
    so the enable/disable gate always runs first.
    """
    del manual_scope_enabled_fixture  # gate only; value is unused
    url = os.environ.get("TEKHSI_SCOPE_URL")
    if not url:
        pytest.skip("Set TEKHSI_SCOPE_URL to the instrument's TekHSI address (host:port).")
    return url


@pytest.fixture
def scope_channel() -> str:
    """Return the scope channel to exercise, defaulting to ``ch1``."""
    return os.environ.get("TEKHSI_SCOPE_CHANNEL", "ch1")
