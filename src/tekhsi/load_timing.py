"""TekHSI-specific FastFrame load instrumentation."""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOL_VERSION_V2 = 200
CAPABILITY_FASTFRAME = 0x0001


@dataclass(frozen=True)
class FastFrameLoadTiming:
    """Timing for loading raw digitizer samples into a FastFrameAnalogWaveform."""

    transfer_ms: float
    """gRPC stream receive plus assembly into per-frame raw sample arrays."""

    publish_ms: float
    """Assign raw arrays into the FastFrame wrapper (no normalization)."""

    num_frames: int
    samples_per_frame: int
    bytes_per_sample: int

    @property
    def total_samples(self) -> int:
        """Total raw digitizer samples across all frames."""
        return self.num_frames * self.samples_per_frame

    @property
    def total_ms(self) -> float:
        return self.transfer_ms + self.publish_ms

    @property
    def total_raw_bytes(self) -> int:
        return self.total_samples * self.bytes_per_sample

    @property
    def data_frame_count(self) -> int:
        """Individual acquisition frames (excludes the average frame)."""
        if self.num_frames <= 1:
            return self.num_frames
        return self.num_frames - 1

    @property
    def transfer_mbps(self) -> float:
        if self.transfer_ms <= 0:
            return 0.0
        return (self.total_raw_bytes * 8 / 1e6) / (self.transfer_ms / 1000)

    def format_summary(self) -> str:
        """Human-readable size and timing summary."""
        mib = self.total_raw_bytes / (1024 * 1024)
        if self.num_frames > 1:
            frame_desc = (
                f"{self.data_frame_count} data frames + 1 average frame "
                f"= {self.num_frames} total"
            )
        else:
            frame_desc = f"{self.num_frames} frame"
        return (
            f"{frame_desc}, {self.samples_per_frame:,} samples/frame "
            f"= {self.total_samples:,} total samples; "
            f"{self.total_samples:,} samples x {self.bytes_per_sample} bytes "
            f"= {self.total_raw_bytes:,} bytes ({mib:.1f} MiB); "
            f"transfer {self.transfer_ms:.3f} ms, publish {self.publish_ms:.3f} ms, "
            f"total {self.total_ms:.3f} ms, {self.transfer_mbps:.2f} Mbit/s"
        )
