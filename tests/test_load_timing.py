"""Unit tests for WaveformTransferTiming."""

from __future__ import annotations

from tekhsi.load_timing import FastFrameLoadTiming, WaveformTransferTiming


def _timing(**overrides: str | float) -> WaveformTransferTiming:
    base: dict[str, str | float | int] = {
        "kind": "analog",
        "transfer_ms": 10.0,
        "publish_ms": 2.0,
        "record_length": 1000,
        "bytes_per_sample": 2,
        "num_frames": 1,
        "summary_frame_count": 0,
    }
    base.update(overrides)
    return WaveformTransferTiming(**base)  # type: ignore[arg-type]


def test_fastframe_property_single_frame() -> None:
    """num_frames == 1 is not FastFrame."""
    assert _timing(num_frames=1).fastframe is False


def test_fastframe_property_multi_frame() -> None:
    """num_frames > 1 is FastFrame."""
    assert _timing(num_frames=5).fastframe is True


def test_total_samples() -> None:
    """total_samples multiplies frames by record length."""
    assert _timing(num_frames=4, record_length=100).total_samples == 400


def test_total_ms() -> None:
    """total_ms sums transfer and publish."""
    assert _timing(transfer_ms=10.0, publish_ms=2.5).total_ms == 12.5


def test_total_raw_bytes() -> None:
    """total_raw_bytes multiplies samples by bytes_per_sample."""
    t = _timing(num_frames=2, record_length=100, bytes_per_sample=2)
    assert t.total_raw_bytes == 400


def test_data_frame_count() -> None:
    """data_frame_count subtracts summary frames from total."""
    t = _timing(num_frames=10, summary_frame_count=2)
    assert t.data_frame_count == 8


def test_transfer_mbps_zero_when_no_transfer_time() -> None:
    """transfer_mbps is 0.0 when transfer_ms <= 0."""
    assert _timing(transfer_ms=0.0).transfer_mbps == 0.0
    assert _timing(transfer_ms=-1.0).transfer_mbps == 0.0


def test_transfer_mbps_nonzero() -> None:
    """transfer_mbps computes a positive rate for real transfer time."""
    t = _timing(transfer_ms=8.0, num_frames=1, record_length=1_000_000, bytes_per_sample=1)
    assert t.transfer_mbps > 0.0


def test_format_summary_single_frame() -> None:
    """format_summary describes a single-frame capture."""
    summary = _timing(num_frames=1).format_summary()
    assert "1 frame" in summary
    assert "analog" in summary


def test_format_summary_fastframe_with_summary_frame() -> None:
    """format_summary reports data + summary frame breakdown."""
    summary = _timing(num_frames=5, summary_frame_count=1).format_summary()
    assert "4 data frames + 1 summary frame" in summary
    assert "5 total" in summary


def test_format_summary_fastframe_with_multiple_summary_frames() -> None:
    """format_summary pluralizes 'summary frames' when count > 1."""
    summary = _timing(num_frames=10, summary_frame_count=3).format_summary()
    assert "summary frames" in summary


def test_format_summary_fastframe_without_summary_frame() -> None:
    """format_summary reports plain data frame count with no summary frame."""
    summary = _timing(num_frames=5, summary_frame_count=0).format_summary()
    assert "5 data frames (no summary frame)" in summary


def test_format_summary_singular_byte_label() -> None:
    """bytes_per_sample == 1 uses singular 'byte/sample'."""
    summary = _timing(bytes_per_sample=1).format_summary()
    assert "byte/sample" in summary
    assert "bytes/sample" not in summary


def test_format_summary_plural_byte_label() -> None:
    """bytes_per_sample != 1 uses plural 'bytes/sample'."""
    summary = _timing(bytes_per_sample=2).format_summary()
    assert "bytes/sample" in summary


def test_fastframe_load_timing_alias() -> None:
    """FastFrameLoadTiming is a backward-compatible alias."""
    assert FastFrameLoadTiming is WaveformTransferTiming
