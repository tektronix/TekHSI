#!/usr/bin/env python3
"""Measure TekHSI waveform gRPC transfer rate on a live scope."""

from __future__ import annotations

import argparse
import logging
import os
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import TekHSIConnect, WaveformTransferTiming
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.helpers.logging import LoggingLevels, configure_logging
from tm_data_types import Waveform


def _auto_trust_prompt(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


def _timing_from_waveform(wfm: Waveform) -> WaveformTransferTiming | None:
    timing = getattr(wfm, "load_timing", None)
    if isinstance(timing, WaveformTransferTiming):
        return timing
    return None


def _print_header() -> None:
    cols = (
        ("Run", 4),
        ("Channel", 12),
        ("Kind", 8),
        ("FastFrame", 9),
        ("RecLen", 8),
        ("Bytes/Sample", 12),
        ("Frames", 7),
        ("RawBytes", 10),
        ("Transfer", 10),
        ("Publish", 9),
        ("Mbit/s", 8),
    )
    print(" ".join(f"{title:<{width}}" for title, width in cols))
    print("-" * 102)


def _print_row(run: int, channel: str, timing: WaveformTransferTiming) -> None:
    ff = "yes" if timing.fastframe else "no"
    print(
        f"{run:<4} "
        f"{channel:<12} "
        f"{timing.kind:<8} "
        f"{ff:<9} "
        f"{timing.record_length:<8} "
        f"{timing.bytes_per_sample:<12} "
        f"{timing.num_frames:<7} "
        f"{timing.total_raw_bytes:<10} "
        f"{timing.transfer_ms:>8.3f} ms "
        f"{timing.publish_ms:>7.3f} ms "
        f"{timing.transfer_mbps:>7.2f}"
    )


def _average_mbps(timing: WaveformTransferTiming, transfer_ms: float) -> float:
    if transfer_ms <= 0:
        return 0.0
    return (timing.total_raw_bytes * 8 / 1e6) / (transfer_ms / 1000)


def _print_average(channel: str, timings: list[WaveformTransferTiming]) -> None:
    if not timings:
        return
    ref = timings[0]
    transfer_ms = statistics.mean(t.transfer_ms for t in timings)
    publish_ms = statistics.mean(t.publish_ms for t in timings)
    ff = "yes" if ref.fastframe else "no"
    print(
        f"{'avg':<4} "
        f"{channel:<12} "
        f"{ref.kind:<8} "
        f"{ff:<9} "
        f"{ref.record_length:<8} "
        f"{ref.bytes_per_sample:<12} "
        f"{ref.num_frames:<7} "
        f"{ref.total_raw_bytes:<10} "
        f"{transfer_ms:>8.3f} ms "
        f"{publish_ms:>7.3f} ms "
        f"{_average_mbps(ref, transfer_ms):>7.2f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure TekHSI waveform transfer rates")
    parser.add_argument("--url", default="169.254.6.254:5000")
    parser.add_argument(
        "channels",
        nargs="*",
        default=["ch1"],
        help="Channel symbols (e.g. ch1 ch2 ch1_iq)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Stopped-scope reads per channel (force_sequence between runs when > 1)",
    )
    args = parser.parse_args()

    configure_logging(log_console_level=LoggingLevels.WARNING)
    logging.getLogger("tekhsi").setLevel(logging.WARNING)

    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    channels = [c.lower() for c in args.channels]

    with TekHSIConnect(
        args.url,
        activesymbols=channels,
        on_trust_prompt=_auto_trust_prompt,
        credential_store=TekHSICredentialStore(path=store_path),
    ) as conn:
        conn.verbose = False
        results: dict[str, list[WaveformTransferTiming]] = {ch: [] for ch in channels}
        _print_header()
        for run in range(1, args.iterations + 1):
            if run > 1:
                conn.force_sequence()
            with conn.access_stopped_data():
                for channel in channels:
                    wfm = conn.get_data(channel)
                    if wfm is None:
                        print(f"{run:<4} {channel:<12} (no data)")
                        continue
                    timing = _timing_from_waveform(wfm)
                    if timing is None:
                        print(f"{run:<4} {channel:<12} (no transfer timing metadata)")
                        continue
                    results[channel].append(timing)
                    _print_row(run, channel, timing)

        if args.iterations > 1:
            print("-" * 102)
            for channel in channels:
                if results[channel]:
                    _print_average(channel, results[channel])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
