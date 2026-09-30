"""TekHSI waveform transfer timing instrumentation."""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOL_VERSION_V2 = 200
CAPABILITY_FASTFRAME = 0x0001
REPLY_CONTENT_MASK_FRAME_METADATA = 0x0001


@dataclass(frozen=True)
class WaveformTransferTiming:
    """Timing for gRPC sample transfer and client-side assembly."""

    kind: str
    """Waveform class: ``analog``, ``digital``, or ``iq``."""

    transfer_ms: float
    """gRPC stream receive plus assembly into sample arrays."""

    publish_ms: float
    """Assign raw arrays into the waveform object (FastFrame only)."""

    record_length: int
    """Samples per frame (or total samples for a single-frame capture)."""

    bytes_per_sample: int
    num_frames: int
    summary_frame_count: int = 0

    @property
    def fastframe(self) -> bool:
        """True if this transfer captured more than one frame."""
        return self.num_frames > 1

    @property
    def total_samples(self) -> int:
        """Total samples across all frames."""
        return self.num_frames * self.record_length

    @property
    def total_ms(self) -> float:
        """Total client-observed time: transfer plus publish."""
        return self.transfer_ms + self.publish_ms

    @property
    def total_raw_bytes(self) -> int:
        """Total raw sample bytes across all frames."""
        return self.total_samples * self.bytes_per_sample

    @property
    def data_frame_count(self) -> int:
        """Number of non-summary (data) frames."""
        return self.num_frames - self.summary_frame_count

    @property
    def transfer_mbps(self) -> float:
        """Effective transfer throughput in megabits/second."""
        if self.transfer_ms <= 0:
            return 0.0
        return (self.total_raw_bytes * 8 / 1e6) / (self.transfer_ms / 1000)

    def format_summary(self) -> str:
        """Human-readable size and timing summary."""
        mib = self.total_raw_bytes / (1024 * 1024)
        ff = "FastFrame" if self.fastframe else "single-frame"
        if self.fastframe:
            if self.summary_frame_count:
                summary_label = (
                    "summary frame" if self.summary_frame_count == 1 else "summary frames"
                )
                frame_desc = (
                    f"{self.data_frame_count} data frames + {self.summary_frame_count} "
                    f"{summary_label} = {self.num_frames} total"
                )
            else:
                frame_desc = f"{self.num_frames} data frames (no summary frame)"
        else:
            frame_desc = "1 frame"
        bps_label = "byte/sample" if self.bytes_per_sample == 1 else "bytes/sample"
        return (
            f"{self.kind} {ff}: {frame_desc}, {self.record_length:,} samples/frame, "
            f"{self.bytes_per_sample} {bps_label} "
            f"= {self.total_samples:,} total samples ({self.total_raw_bytes:,} bytes, {mib:.1f} MiB); "
            f"transfer {self.transfer_ms:.3f} ms, publish {self.publish_ms:.3f} ms, "
            f"total {self.total_ms:.3f} ms, {self.transfer_mbps:.2f} Mbit/s"
        )


# Backward-compatible alias used by FastFrame paths and existing docs.
FastFrameLoadTiming = WaveformTransferTiming
