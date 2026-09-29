#!/usr/bin/env python3
"""Validate scope reference waveforms against saved .wfm files."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import FastFrameAnalogWaveform, FastFrameDigitalWaveform, TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.wfm_digital import read_digital_wfm
from tm_data_types import AnalogWaveform, DigitalWaveform, read_file


def _auto_trust_prompt(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            print("Password required but TEKHSI_PASSWORD is not set.")
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


def _print_waveform_summary(label: str, wfm) -> None:
    print(f"\n=== {label} ===")
    print(f"  type={type(wfm).__name__} source={getattr(wfm, 'source_name', None)!r}")
    if isinstance(wfm, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
        print(
            f"  record_length={wfm.record_length} num_frames={wfm.num_frames} "
            f"summary_frame_index={wfm.summary_frame_index}"
        )
        data = wfm.frame_data(0)
        print(f"  frame[0] len={len(data)} raw[0]={int(data[0])} raw[-1]={int(data[-1])}")
        if isinstance(wfm, FastFrameDigitalWaveform):
            print(f"  digital_bitmask=0x{wfm.digital_bitmask:08x}")
    elif isinstance(wfm, AnalogWaveform):
        y = wfm.y_axis_values
        print(f"  samples={len(y)} raw[0]={int(y[0])} raw[-1]={int(y[-1])}")
    elif isinstance(wfm, DigitalWaveform):
        y = wfm.y_axis_byte_values
        print(f"  samples={len(y)} digital_bitmask=0x{wfm.digital_bitmask:08x}")


def _frame_count(wfm) -> int:
    if isinstance(wfm, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
        return wfm.num_frames
    return 1


def _record_length(wfm) -> int:
    if isinstance(wfm, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
        return wfm.record_length
    if isinstance(wfm, AnalogWaveform):
        return len(wfm.y_axis_values)
    if isinstance(wfm, DigitalWaveform):
        return len(wfm.y_axis_byte_values)
    raise TypeError(type(wfm).__name__)


def _frame_data(wfm, index: int) -> np.ndarray:
    if isinstance(wfm, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
        return np.asarray(wfm.frame_data(index))
    if index != 0:
        raise IndexError(f"single-frame waveform has no frame {index}")
    if isinstance(wfm, AnalogWaveform):
        return np.asarray(wfm.y_axis_values)
    if isinstance(wfm, DigitalWaveform):
        return np.asarray(wfm.y_axis_byte_values)
    raise TypeError(type(wfm).__name__)


def _compare_waveforms(expected, actual, pair_label: str) -> tuple[list[str], list[str]]:
    data_issues: list[str] = []
    meta_issues: list[str] = []

    if type(expected) is not type(actual):
        meta_issues.append(f"type: expected {type(expected).__name__}, scope {type(actual).__name__}")

    exp_frames = _frame_count(expected)
    act_frames = _frame_count(actual)
    if exp_frames != act_frames:
        data_issues.append(f"frame count: expected {exp_frames}, scope {act_frames}")

    exp_len = _record_length(expected)
    act_len = _record_length(actual)
    if exp_len != act_len:
        data_issues.append(f"record_length: expected {exp_len}, scope {act_len}")

    if isinstance(expected, FastFrameDigitalWaveform) and isinstance(actual, FastFrameDigitalWaveform):
        if expected.digital_bitmask != actual.digital_bitmask:
            meta_issues.append(
                f"digital_bitmask: expected 0x{expected.digital_bitmask:08x}, "
                f"scope 0x{actual.digital_bitmask:08x}"
            )

    frames = min(exp_frames, act_frames)
    for index in range(frames):
        exp = _frame_data(expected, index)
        act = _frame_data(actual, index)
        if exp.shape != act.shape:
            data_issues.append(f"frame[{index}] shape: expected {exp.shape}, scope {act.shape}")
            continue
        if not np.array_equal(exp, act):
            diff = int(np.max(np.abs(exp.astype(np.int64) - act.astype(np.int64))))
            mismatches = int(np.count_nonzero(exp != act))
            data_issues.append(
                f"frame[{index}] mismatch: {mismatches}/{exp.size} samples differ, max diff={diff}"
            )

        if isinstance(expected, FastFrameDigitalWaveform) and isinstance(actual, FastFrameDigitalWaveform):
            exp_bits = expected.frame(index).get_nth_bitstream(0)
            act_bits = actual.frame(index).get_nth_bitstream(0)
            if not np.array_equal(exp_bits, act_bits):
                bit_diff = int(np.count_nonzero(exp_bits != act_bits))
                data_issues.append(
                    f"frame[{index}] bitstream mismatch: {bit_diff}/{len(exp_bits)} bits differ"
                )

    return data_issues, meta_issues


def _load_expected_wfm(path: Path, digital: bool):
    if digital:
        return read_digital_wfm(str(path))
    return read_file(str(path))


def main() -> int:
    default_dir = ROOT / "sample_waveforms" / "fastframe_roundtrip"
    parser = argparse.ArgumentParser(description="Compare scope refs to saved .wfm files")
    parser.add_argument("--url", default="169.254.6.254:5000")
    parser.add_argument("--ref-analog", default="ref1")
    parser.add_argument("--ref-digital", default="ref2_dall")
    parser.add_argument("--wfm-analog", type=Path, default=default_dir / "CH1.wfm")
    parser.add_argument("--wfm-digital", type=Path, default=default_dir / "CH2_DALL.wfm")
    args = parser.parse_args()

    ref_specs = [
        (args.ref_analog.lower(), args.wfm_analog, False, "analog"),
        (args.ref_digital.lower(), args.wfm_digital, True, "digital"),
    ]

    for _, wfm_path, _, kind in ref_specs:
        if not wfm_path.is_file():
            print(f"ERROR: missing {kind} reference file: {wfm_path}")
            return 1

    expected: dict[str, object] = {}
    for _, wfm_path, is_digital, kind in ref_specs:
        expected[kind] = _load_expected_wfm(wfm_path, is_digital)
        _print_waveform_summary(f"expected {kind} ({wfm_path.name})", expected[kind])

    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    scope_data: dict[str, object] = {}

    print(f"\nConnecting to {args.url} ...", flush=True)
    for ref_symbol, wfm_path, _, kind in ref_specs:
        print(f"\n--- Reading {ref_symbol} from scope ---", flush=True)
        try:
            with TekHSIConnect(
                args.url,
                activesymbols=[ref_symbol],
                on_trust_prompt=_auto_trust_prompt,
                credential_store=TekHSICredentialStore(path=store_path),
            ) as conn:
                with conn.access_stopped_data():
                    print(f"available_symbols={conn.available_symbols}", flush=True)
                    wfm = conn.get_data(ref_symbol)
                    if wfm is None:
                        print(f"ERROR: no waveform for {ref_symbol}")
                        scope_data[kind] = None
                        continue
                    scope_data[kind] = wfm
                    _print_waveform_summary(f"scope {ref_symbol}", wfm)
        except Exception as exc:
            print(f"ERROR reading {ref_symbol}: {exc}")
            scope_data[kind] = None

    all_ok = True
    print("\n--- Comparison ---")
    for ref_symbol, wfm_path, _, kind in ref_specs:
        if scope_data.get(kind) is None:
            all_ok = False
            print(f"\nDATA FAIL {ref_symbol} vs {wfm_path.name}: could not read waveform from scope")
            continue
        data_issues, meta_issues = _compare_waveforms(expected[kind], scope_data[kind], kind)
        if data_issues:
            all_ok = False
            print(f"\nDATA FAIL {ref_symbol} vs {wfm_path.name}:")
            for issue in data_issues:
                print(f"  - {issue}")
        else:
            frames = _frame_count(expected[kind])
            print(f"\nDATA PASS {ref_symbol} vs {wfm_path.name} — all {frames} frame(s) match")
        if meta_issues:
            print(f"  metadata note(s) for {ref_symbol}:")
            for issue in meta_issues:
                print(f"  - {issue}")

    if all_ok:
        print("\nOverall: PASS — scope refs match saved .wfm files")
        return 0
    print("\nOverall: FAIL — scope refs differ from saved .wfm files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
