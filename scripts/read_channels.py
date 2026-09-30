#!/usr/bin/env python3
"""Read one or more channels from a live TekHSI scope."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import FastFrameAnalogWaveform, FastFrameDigitalWaveform, TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore
from tm_data_types import AnalogWaveform, DigitalWaveform


def _auto_trust_prompt(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            print("Password required but TEKHSI_PASSWORD is not set.")
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


def _describe_waveform(wfm) -> None:
    print(f"  type={type(wfm).__name__} source={wfm.source_name!r}")
    if isinstance(wfm, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
        print(f"  record_length={wfm.record_length}")
        print(f"  num_frames={wfm.num_frames} data_frames={wfm.data_frame_count}")
        print(
            f"  current_frame_index={wfm.current_frame_index} "
            f"summary_frame_index={wfm.summary_frame_index}"
        )
        if wfm.summary_frame_index is None:
            print("  summary frame: disabled (all frames are data frames)")
        print(f"  all_frames_loaded={wfm.all_frames_loaded}")
        bitmask = getattr(wfm, "digital_bitmask", None)
        if bitmask is not None:
            print(f"  digital_bitmask=0x{bitmask:08x}")
        samples = wfm.frame_data(0)
        print(f"  frame[0] raw[0]={int(samples[0])} len={len(samples)}")
        if isinstance(wfm, FastFrameDigitalWaveform):
            print(f"  frame[0] bitstream[0]={int(wfm.frame(0).get_nth_bitstream(0)[0])}")
        if wfm.load_timing:
            lt = wfm.load_timing
            print(f"  bytes_per_sample={lt.bytes_per_sample}")
            print(f"  {lt.format_summary()}")
    elif isinstance(wfm, AnalogWaveform):
        y = wfm.y_axis_values
        n = len(y) if y is not None else 0
        print(f"  samples={n} y_units={wfm.y_axis_units!r} x_spacing={wfm.x_axis_spacing}")
        if n:
            print(f"  raw[0]={int(y[0])} raw[-1]={int(y[-1])}")
        if getattr(wfm, "load_timing", None):
            lt = wfm.load_timing
            print(f"  bytes_per_sample={lt.bytes_per_sample}")
            print(f"  {lt.format_summary()}")
    elif isinstance(wfm, DigitalWaveform):
        y = wfm.y_axis_byte_values
        n = len(y) if y is not None else 0
        print(f"  samples={n} y_units={wfm.y_axis_units!r} x_spacing={wfm.x_axis_spacing}")
        if n:
            print(f"  raw[0]={int(y[0])} raw[-1]={int(y[-1])}")
        if getattr(wfm, "load_timing", None):
            lt = wfm.load_timing
            print(f"  bytes_per_sample={lt.bytes_per_sample}")
            print(f"  {lt.format_summary()}")
    else:
        print("  unexpected waveform type")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read channels from a TekHSI scope")
    parser.add_argument("--url", default="169.254.6.254:5000")
    parser.add_argument("channels", nargs="*", default=["ch1", "ref1"])
    args = parser.parse_args()

    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    channels = [c.lower() for c in args.channels]

    print(f"Connecting to {args.url} ...", flush=True)
    with TekHSIConnect(
        args.url,
        activesymbols=channels,
        callback=None,
        on_trust_prompt=_auto_trust_prompt,
        credential_store=TekHSICredentialStore(path=store_path),
    ) as conn:
        conn.verbose = True
        print(
            f"protocol_version={conn.protocol_version} "
            f"capabilities=0x{conn.capabilities:04x} "
            f"fastframe_capable={conn.fastframe_capable}"
        )
        print(f"activesymbols={conn.activesymbols}")

        with conn.access_stopped_data():
            print(f"available_symbols={conn.available_symbols}", flush=True)
            for channel in channels:
                print(f"\n--- {channel} ---", flush=True)
                wfm = conn.get_data(channel)
                if wfm is None:
                    print("  No waveform returned")
                    continue
                _describe_waveform(wfm)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
