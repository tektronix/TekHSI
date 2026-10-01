"""Tests for digital_bitmask WFM tekmeta helpers."""

# pyright: basic
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast, TYPE_CHECKING  # pylint: disable=unused-import

import numpy as np
import pytest  # pyright: ignore[reportMissingImports]

from tekhsi.wfm_digital import (
    _bitmask_from_probe_states,  # pyright: ignore[reportPrivateUsage]
    _ensure_digital_meta_info,  # pyright: ignore[reportPrivateUsage]
    DIGITAL_BITMASK_META_KEY,
    read_digital_wfm,
    restore_digital_bitmask_from_meta,
    stamp_digital_bitmask_meta,
    write_digital_wfm,
)
from tm_data_types import AnalogWaveform, DigitalWaveformMetaInfo, write_file

if TYPE_CHECKING:
    from tm_data_types import FastFrameDigitalWaveform  # type: ignore
else:
    try:
        from tm_data_types import FastFrameDigitalWaveform  # type: ignore
    except (ImportError, AttributeError):
        from tm_data_types import (
            DigitalWaveform as FastFrameDigitalWaveform,  # type: ignore  # pyright: ignore[reportAssignmentType]
        )


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
    assert loaded.digital_bitmask == 0x05  # type: ignore
    assert loaded.meta_info is not None
    extended = cast("dict", loaded.meta_info.extended_metadata)
    assert extended[DIGITAL_BITMASK_META_KEY] == 0x05
    for index in range(3):
        assert np.array_equal(loaded.frame_data(index), original.frame_data(index))  # type: ignore


def test_restore_prefers_explicit_meta_key() -> None:
    waveform = FastFrameDigitalWaveform.create_fastframe(1, 4, dtype=np.int8)
    waveform.digital_bitmask = 0x05
    stamp_digital_bitmask_meta(waveform)
    waveform.digital_bitmask = 0
    assert restore_digital_bitmask_from_meta(waveform) == 0x05


def test_ensure_digital_meta_info_creates_when_none() -> None:
    """_ensure_digital_meta_info creates a fresh DigitalWaveformMetaInfo when meta_info is None."""
    waveform = SimpleNamespace(meta_info=None)
    meta_info = _ensure_digital_meta_info(waveform)  # type: ignore[arg-type]
    assert type(meta_info).__name__ == "DigitalWaveformMetaInfo"
    assert waveform.meta_info is meta_info


def test_ensure_digital_meta_info_replaces_incompatible_meta_info() -> None:
    """_ensure_digital_meta_info attempts to rebuild meta_info lacking operable_metainfo."""

    class FakeMeta:  # pylint: disable=too-few-public-methods
        """Stand-in object without an operable_metainfo method."""

    waveform = SimpleNamespace(meta_info=FakeMeta())
    with pytest.raises(AttributeError):
        _ensure_digital_meta_info(waveform)  # type: ignore[arg-type]


def test_bitmask_from_probe_states_all_none_returns_none() -> None:
    """_bitmask_from_probe_states returns None when no probe state fields are set."""
    meta = DigitalWaveformMetaInfo()
    for bit in range(8):
        setattr(meta, f"digital_probe_{bit}_state", None)
    assert _bitmask_from_probe_states(meta) is None


def test_bitmask_from_probe_states_computes_bitmask() -> None:
    """_bitmask_from_probe_states ORs active bits and skips inactive/empty states."""
    meta = DigitalWaveformMetaInfo()
    for bit in range(8):
        setattr(meta, f"digital_probe_{bit}_state", None)
    meta.digital_probe_0_state = b"0x01"
    meta.digital_probe_1_state = b"0x00"
    meta.digital_probe_2_state = b"0x01"
    meta.digital_probe_3_state = b""
    assert _bitmask_from_probe_states(meta) == 0b101


def test_restore_from_meta_info_none_uses_waveform_attribute() -> None:
    """Falls back to the waveform attribute when meta_info is None."""
    waveform = SimpleNamespace(meta_info=None, digital_bitmask=0x03)
    assert restore_digital_bitmask_from_meta(waveform) == 0x03  # type: ignore[arg-type]
    assert waveform.digital_bitmask == 0x03


def test_restore_from_direct_meta_attribute() -> None:
    """restore_digital_bitmask_from_meta reads a direct digital_bitmask attribute on meta_info."""
    meta = SimpleNamespace(extended_metadata=None, digital_bitmask=7)
    waveform = SimpleNamespace(meta_info=meta, digital_bitmask=0)
    assert restore_digital_bitmask_from_meta(waveform) == 7  # type: ignore[arg-type]


def test_restore_from_probe_states_branch() -> None:
    """restore_digital_bitmask_from_meta falls back to probe-state derivation."""
    meta = DigitalWaveformMetaInfo()
    for bit in range(8):
        setattr(meta, f"digital_probe_{bit}_state", None)
    meta.digital_probe_0_state = b"0x01"
    waveform = SimpleNamespace(meta_info=meta, digital_bitmask=0)
    assert restore_digital_bitmask_from_meta(waveform) == 1  # type: ignore[arg-type]


def test_read_digital_wfm_wrong_type_raises(tmp_path: Path) -> None:
    """read_digital_wfm raises TypeError when the file contains a non-digital waveform."""
    path = tmp_path / "analog.wfm"
    waveform = AnalogWaveform()
    waveform.y_axis_values = cast("object", np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32))
    write_file(str(path), waveform)

    with pytest.raises(TypeError, match="expected a digital waveform"):
        read_digital_wfm(str(path))
