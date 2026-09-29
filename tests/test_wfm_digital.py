"""Tests for digital_bitmask WFM tekmeta helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tekhsi.wfm_digital import (
    DIGITAL_BITMASK_META_KEY,
    read_digital_wfm,
    restore_digital_bitmask_from_meta,
    stamp_digital_bitmask_meta,
    write_digital_wfm,
)
from tm_data_types.datum.waveforms.fastframe_digital_waveform import FastFrameDigitalWaveform


def test_digital_bitmask_wfm_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "digital_ff.wfm"
    original = FastFrameDigitalWaveform.create_fastframe(3, 128, dtype=np.int8)
    original.digital_bitmask = 0x05
    original.x_axis_spacing = 2e-10
    for index in range(3):
        original.fill_frame(index, np.full(128, index, dtype=np.int8))

    write_digital_wfm(str(path), original)
    loaded = read_digital_wfm(str(path))

    assert isinstance(loaded, FastFrameDigitalWaveform)
    assert loaded.digital_bitmask == 0x05
    assert loaded.meta_info is not None
    assert loaded.meta_info.extended_metadata[DIGITAL_BITMASK_META_KEY] == 0x05
    for index in range(3):
        assert np.array_equal(loaded.frame_data(index), original.frame_data(index))


def test_restore_prefers_explicit_meta_key() -> None:
    waveform = FastFrameDigitalWaveform.create_fastframe(1, 4, dtype=np.int8)
    waveform.digital_bitmask = 0x05
    stamp_digital_bitmask_meta(waveform)
    waveform.digital_bitmask = 0
    assert restore_digital_bitmask_from_meta(waveform) == 0x05
