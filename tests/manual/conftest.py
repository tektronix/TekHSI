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


@pytest.fixture(autouse=True)
def manual_scope_enabled_fixture() -> None:
    """Skip the test unless a real scope address is configured."""
    if not os.environ.get("TEKHSI_SCOPE_URL"):
        pytest.skip("Set TEKHSI_SCOPE_URL to the instrument's TekHSI address (host:port).")


@pytest.fixture
def scope_url() -> str:
    """Return the configured instrument's TekHSI address.

    There is intentionally no default - tests must be pointed at a real
    instrument via ``TEKHSI_SCOPE_URL``. The autouse gate validates that the
    address is configured before this fixture runs.
    """
    return os.environ["TEKHSI_SCOPE_URL"]


@pytest.fixture
def scope_channel() -> str:
    """Return the scope channel to exercise, defaulting to ``ch1``."""
    return os.environ.get("TEKHSI_SCOPE_CHANNEL", "ch1")
