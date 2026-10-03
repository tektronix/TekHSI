"""Unit tests for WaveformTransferTiming (src/tekhsi/load_timing.py)."""

from __future__ import annotations

from tekhsi.load_timing import (
    CAPABILITY_FASTFRAME,
    FastFrameLoadTiming,
    PROTOCOL_VERSION_V2,
    REPLY_CONTENT_MASK_FRAME_METADATA,
    WaveformTransferTiming,
)


def test_constants() -> None:
    """Protocol constants have their expected values."""
    assert PROTOCOL_VERSION_V2 == 200
    assert CAPABILITY_FASTFRAME == 0x0001
    assert REPLY_CONTENT_MASK_FRAME_METADATA == 0x0001


def test_fastframe_load_timing_is_alias() -> None:
    """FastFrameLoadTiming is a backward-compatible alias."""
    assert FastFrameLoadTiming is WaveformTransferTiming


def test_single_frame_properties() -> None:
    """A single-frame (non-FastFrame) timing computes basic derived properties."""
    timing = WaveformTransferTiming(
        kind="analog",
        transfer_ms=10.0,
        publish_ms=2.0,
        record_length=1000,
        bytes_per_sample=2,
        num_frames=1,
    )
    assert timing.fastframe is False
    assert timing.total_samples == 1000
    assert timing.total_ms == 12.0
    assert timing.total_raw_bytes == 2000
    assert timing.data_frame_count == 1
    assert timing.transfer_mbps > 0


def test_transfer_ms_zero_yields_zero_mbps() -> None:
    """transfer_mbps returns 0.0 when transfer_ms is non-positive (avoids div-by-zero)."""
    timing = WaveformTransferTiming(
        kind="analog",
        transfer_ms=0.0,
        publish_ms=1.0,
        record_length=100,
        bytes_per_sample=1,
        num_frames=1,
    )
    assert timing.transfer_mbps == 0.0

    negative = WaveformTransferTiming(
        kind="analog",
        transfer_ms=-5.0,
        publish_ms=1.0,
        record_length=100,
        bytes_per_sample=1,
        num_frames=1,
    )
    assert negative.transfer_mbps == 0.0


def test_fastframe_properties_and_data_frame_count() -> None:
    """FastFrame timing (num_frames > 1) reports fastframe True and correct data-frame count."""
    timing = WaveformTransferTiming(
        kind="digital",
        transfer_ms=5.0,
        publish_ms=1.0,
        record_length=128,
        bytes_per_sample=1,
        num_frames=4,
        summary_frame_count=1,
    )
    assert timing.fastframe is True
    assert timing.total_samples == 512
    assert timing.data_frame_count == 3


def test_format_summary_single_frame() -> None:
    """format_summary describes a single-frame capture with 'byte/sample' (singular)."""
    timing = WaveformTransferTiming(
        kind="analog",
        transfer_ms=1.0,
        publish_ms=0.5,
        record_length=4,
        bytes_per_sample=1,
        num_frames=1,
    )
    summary = timing.format_summary()
    assert "analog single-frame" in summary
    assert "1 frame" in summary
    assert "byte/sample" in summary
    assert "bytes/sample" not in summary


def test_format_summary_fastframe_no_summary_frame() -> None:
    """format_summary describes FastFrame captures without a summary frame."""
    timing = WaveformTransferTiming(
        kind="analog",
        transfer_ms=1.0,
        publish_ms=0.5,
        record_length=10,
        bytes_per_sample=2,
        num_frames=3,
        summary_frame_count=0,
    )
    summary = timing.format_summary()
    assert "FastFrame" in summary
    assert "3 data frames (no summary frame)" in summary
    assert "bytes/sample" in summary


def test_format_summary_fastframe_single_summary_frame() -> None:
    """format_summary uses singular 'summary frame' when summary_frame_count == 1."""
    timing = WaveformTransferTiming(
        kind="digital",
        transfer_ms=1.0,
        publish_ms=0.5,
        record_length=10,
        bytes_per_sample=1,
        num_frames=4,
        summary_frame_count=1,
    )
    summary = timing.format_summary()
    assert "3 data frames + 1 summary frame = 4 total" in summary


def test_format_summary_fastframe_multiple_summary_frames() -> None:
    """format_summary uses plural 'summary frames' when summary_frame_count > 1."""
    timing = WaveformTransferTiming(
        kind="iq",
        transfer_ms=1.0,
        publish_ms=0.5,
        record_length=10,
        bytes_per_sample=4,
        num_frames=6,
        summary_frame_count=2,
    )
    summary = timing.format_summary()
    assert "4 data frames + 2 summary frames = 6 total" in summary
