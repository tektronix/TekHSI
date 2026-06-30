#!/usr/bin/env python3
"""Confirm High Res FastFrame: last frame is the average of data frames."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import FastFrameAnalogWaveform, TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore


def trust(host: str, cert_info: Any, auth_required: bool = False) -> bool:
    print(f"TRUST {host} auth={auth_required}", flush=True)
    return True


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "169.254.6.254:5000"
    channel = sys.argv[2] if len(sys.argv) > 2 else "ch1"
    store = TekHSICredentialStore(path=str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini"))

    print(f"Connecting to {url} ...", flush=True)
    with TekHSIConnect(url, activesymbols=[channel], on_trust_prompt=trust, credential_store=store) as conn:
        with conn.access_stopped_data():
            wfm = conn.get_data(channel)

    if not isinstance(wfm, FastFrameAnalogWaveform):
        print(f"Not FastFrame: {type(wfm).__name__}")
        return 1

    if not wfm.all_frames_loaded:
        print("Frames not fully loaded.")
        return 1

    data_count = wfm.data_frame_count
    avg_index = wfm.summary_frame_index
    assert avg_index is not None

    data_arrays = [np.asarray(wfm.frame_data(i)) for i in range(data_count)]
    avg_array = np.asarray(wfm.frame_data(avg_index))

    print(f"samples_per_frame (header): {wfm.record_length}")
    print(f"data frames: {data_count}, average frame index: {avg_index}, total: {wfm.num_frames}")
    print(f"average frame length: {len(avg_array)}")
    print(f"data frame lengths: min={min(len(a) for a in data_arrays)} max={max(len(a) for a in data_arrays)}")

    # If all frames share length, compute mean of data frames and compare to last frame.
    lengths = {len(a) for a in data_arrays}
    if len(lengths) == 1 and len(avg_array) == lengths.pop():
        n = len(avg_array)
        stack = np.stack(data_arrays, axis=0).astype(np.float64)
        computed_mean = stack.mean(axis=0)
        last = avg_array.astype(np.float64)
        diff = last - computed_mean
        max_abs_diff = float(np.max(np.abs(diff)))
        rms_diff = float(np.sqrt(np.mean(diff * diff)))
        corr = float(np.corrcoef(last, computed_mean)[0, 1]) if n > 1 else 1.0

        print("\nComparison: last frame vs mean of data frames (raw digitizer levels)")
        print(f"  max abs difference : {max_abs_diff:.6g}")
        print(f"  RMS difference     : {rms_diff:.6g}")
        print(f"  correlation        : {corr:.6f}")

        # Heuristic thresholds on raw ADC codes
        if max_abs_diff < 1.0 and corr > 0.9999:
            print("\nRESULT: Last frame matches the average of data frames (High Res average confirmed).")
            return 0
        if corr > 0.99 and rms_diff < max(1.0, 0.01 * float(np.std(last))):
            print("\nRESULT: Last frame is very close to the mean of data frames (likely High Res average).")
            return 0
        print("\nRESULT: Last frame does NOT match the mean of data frames.")
        print("  (Either High Res average is computed differently, or last frame is not an average.)")
        return 2

    print("\nRESULT: Data and average frames have different lengths; cannot compare sample-by-sample.")
    print("  Inspect lengths above to see how the scope structured the capture.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
