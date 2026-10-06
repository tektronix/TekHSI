"""Tests for digital_bitmask WFM tekmeta helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tekhsi import wfm_digital
from tekhsi.wfm_digital import (
    _bitmask_from_probe_states,
    _ensure_digital_meta_info,
    DIGITAL_BITMASK_META_KEY,
    read_digital_wfm,
    restore_digital_bitmask_from_meta,
    stamp_digital_bitmask_meta,
    write_digital_wfm,
)
from tm_data_types.datum.waveforms.digital_waveform import DigitalWaveformMetaInfo
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


def test_ensure_digital_meta_info_creates_new_when_none() -> None:
    """_ensure_digital_meta_info creates a DigitalWaveformMetaInfo when missing."""
    obj = SimpleNamespace(meta_info=None)
    result = _ensure_digital_meta_info(obj)  # type: ignore[arg-type]
    assert isinstance(result, DigitalWaveformMetaInfo)
    assert obj.meta_info is result


def test_ensure_digital_meta_info_replaces_wrong_type() -> None:
    """_ensure_digital_meta_info converts a non-digital meta_info via operable_metainfo()."""

    class _FakeMeta:  # pylint: disable=too-few-public-methods
        """Stand-in meta_info exposing only operable_metainfo()."""

        def operable_metainfo(self) -> dict:
            """Return an empty operable metadata mapping."""
            return {}

    obj = SimpleNamespace(meta_info=_FakeMeta())
    result = _ensure_digital_meta_info(obj)  # type: ignore[arg-type]
    assert isinstance(result, DigitalWaveformMetaInfo)


def test_bitmask_from_probe_states_all_none() -> None:
    """No probe-state attributes set returns None."""
    meta = DigitalWaveformMetaInfo()
    for bit in range(8):
        setattr(meta, f"digital_probe_{bit}_state", None)
    assert _bitmask_from_probe_states(meta) is None


def test_bitmask_from_probe_states_mixed() -> None:
    """Active/inactive probe states combine into the correct bitmask."""
    meta = DigitalWaveformMetaInfo()
    for bit in range(8):
        setattr(meta, f"digital_probe_{bit}_state", b"0x00")
    meta.digital_probe_0_state = b"0x01"
    meta.digital_probe_3_state = b"0x01"
    assert _bitmask_from_probe_states(meta) == 0b1001


def test_restore_digital_bitmask_derives_from_probe_states() -> None:
    """restore_digital_bitmask_from_meta falls back to probe-state derivation."""
    meta = DigitalWaveformMetaInfo()
    for bit in range(8):
        setattr(meta, f"digital_probe_{bit}_state", b"0x00")
    meta.digital_probe_1_state = b"0x01"
    obj = SimpleNamespace(meta_info=meta, digital_bitmask=0)
    result = restore_digital_bitmask_from_meta(obj)  # type: ignore[arg-type]
    assert result == 0b10
    assert obj.digital_bitmask == 0b10


def test_restore_digital_bitmask_no_meta_info_uses_existing() -> None:
    """restore_digital_bitmask_from_meta keeps existing value when meta_info is None."""
    obj = SimpleNamespace(meta_info=None, digital_bitmask=7)
    result = restore_digital_bitmask_from_meta(obj)  # type: ignore[arg-type]
    assert result == 7
    assert obj.digital_bitmask == 7


def test_read_digital_wfm_raises_type_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_digital_wfm raises TypeError for non-digital waveform types."""
    monkeypatch.setattr(wfm_digital, "read_file", lambda _path: object())
    with pytest.raises(TypeError, match="expected a digital waveform"):
        read_digital_wfm("dummy.wfm")
