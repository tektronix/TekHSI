"""Digital waveform .wfm metadata helpers.

TekHSI populates ``digital_bitmask`` from ``WaveformHeader.bitmask`` (bit *n* set
means digital line *n* is present in the packed byte stream). The standard WFM
tekmeta block does not define a dedicated bitmask field, but it does carry
``d0``-``d7`` digital-probe state keys. We persist the integer bitmask in
tekmeta ``extended_metadata`` under ``digital_bitmask`` and mirror active lines
into ``digital_probe_*_state`` for scope/ref compatibility.
"""

from __future__ import annotations

from tm_data_types import DigitalWaveform, read_file, write_file
from tm_data_types.datum.waveforms.digital_waveform import (  # pylint: disable=import-error
    DigitalWaveformMetaInfo,
)
from tm_data_types.datum.waveforms.fastframe_digital_waveform import (  # pylint: disable=import-error
    FastFrameDigitalWaveform,
)

DIGITAL_BITMASK_META_KEY = "digital_bitmask"
_ACTIVE_PROBE_STATE = b"0x01"
_INACTIVE_PROBE_STATE = b"0x00"


def _ensure_digital_meta_info(
    waveform: DigitalWaveform | FastFrameDigitalWaveform,
) -> DigitalWaveformMetaInfo:
    if waveform.meta_info is None:
        waveform.meta_info = DigitalWaveformMetaInfo()
    elif not isinstance(waveform.meta_info, DigitalWaveformMetaInfo):
        waveform.meta_info = DigitalWaveformMetaInfo(**waveform.meta_info.operable_metainfo())
    return waveform.meta_info


def _bitmask_from_probe_states(meta_info: DigitalWaveformMetaInfo) -> int | None:
    states = [getattr(meta_info, f"digital_probe_{bit}_state", None) for bit in range(8)]
    if all(state is None for state in states):
        return None
    bitmask = 0
    for bit, state in enumerate(states):
        if state in {None, b"", b"0", b"0x00", b"0x0", "0", "0x00", "0x0"}:
            continue
        bitmask |= 1 << bit
    return bitmask


def stamp_digital_bitmask_meta(waveform: DigitalWaveform | FastFrameDigitalWaveform) -> None:
    """Write ``digital_bitmask`` into WFM tekmeta before ``write_file()``."""
    meta_info = _ensure_digital_meta_info(waveform)
    bitmask = int(waveform.digital_bitmask)
    meta_info.set_custom_metadata(**{DIGITAL_BITMASK_META_KEY: bitmask})
    for bit in range(8):
        state = _ACTIVE_PROBE_STATE if bitmask & (1 << bit) else _INACTIVE_PROBE_STATE
        setattr(meta_info, f"digital_probe_{bit}_state", state)


def restore_digital_bitmask_from_meta(waveform: DigitalWaveform | FastFrameDigitalWaveform) -> int:
    """Restore ``digital_bitmask`` on a waveform after ``read_file()``."""
    bitmask: int | None = None
    if waveform.meta_info is not None:
        extended = waveform.meta_info.extended_metadata or {}
        if DIGITAL_BITMASK_META_KEY in extended:
            bitmask = int(extended[DIGITAL_BITMASK_META_KEY])
        elif hasattr(waveform.meta_info, DIGITAL_BITMASK_META_KEY):
            bitmask = int(getattr(waveform.meta_info, DIGITAL_BITMASK_META_KEY))
        elif isinstance(waveform.meta_info, DigitalWaveformMetaInfo):
            bitmask = _bitmask_from_probe_states(waveform.meta_info)

    if bitmask is None:
        bitmask = int(waveform.digital_bitmask)
    waveform.digital_bitmask = bitmask
    return bitmask


def write_digital_wfm(path: str, waveform: DigitalWaveform | FastFrameDigitalWaveform) -> None:
    """Save a digital waveform, preserving ``digital_bitmask`` in tekmeta."""
    stamp_digital_bitmask_meta(waveform)
    write_file(path, waveform)


def read_digital_wfm(path: str) -> DigitalWaveform | FastFrameDigitalWaveform:
    """Load a digital waveform and restore ``digital_bitmask`` from tekmeta."""
    waveform = read_file(path)
    if not isinstance(waveform, (DigitalWaveform, FastFrameDigitalWaveform)):
        msg = f"expected a digital waveform, got {type(waveform).__name__}"
        raise TypeError(msg)
    restore_digital_bitmask_from_meta(waveform)
    return waveform
