#!/usr/bin/env python3
"""Retrieve FastFrame captures, save to .wfm, re-read, and compare for accuracy."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tm_data_types import read_file, write_file
from tm_data_types.datum.waveforms.fastframe_common import FrameTimingInfo

from tekhsi import FastFrameAnalogWaveform, FastFrameDigitalWaveform, TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.wfm_digital import read_digital_wfm, write_digital_wfm


def _auto_trust_prompt(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            print("Password required but TEKHSI_PASSWORD is not set.")
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


def _safe_filename(source_name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in source_name)


def _print_fastframe_info(
    label: str, wfm: FastFrameAnalogWaveform | FastFrameDigitalWaveform
) -> None:
    print(f"\n=== {label} ===")
    print(f"  type={type(wfm).__name__}")
    print(f"  source={wfm.source_name!r}")
    print(f"  record_length={wfm.record_length}")
    print(f"  num_frames={wfm.num_frames} data_frames={wfm.data_frame_count}")
    print(
        f"  current_frame_index={wfm.current_frame_index} "
        f"summary_frame_index={wfm.summary_frame_index}"
    )
    print(f"  summary_frame_type={wfm.summary_frame_type.name}")
    print(f"  all_frames_loaded={wfm.all_frames_loaded}")
    print(f"  x_axis_spacing={wfm.x_axis_spacing} x_axis_units={wfm.x_axis_units!r}")
    if isinstance(wfm, FastFrameAnalogWaveform):
        print(
            f"  y_axis_spacing={wfm.y_axis_spacing} y_axis_offset={wfm.y_axis_offset} "
            f"y_axis_units={wfm.y_axis_units!r}"
        )
    if isinstance(wfm, FastFrameDigitalWaveform):
        print(f"  digital_bitmask=0x{wfm.digital_bitmask:08x}")
    print(f"  frame_info entries={len(wfm.frame_info)}")
    for info in wfm.frame_info[:3]:
        print(
            f"    frame[{info.frame_index}]: tt={info.time_offset:.6g}s "
            f"summary={info.is_summary_frame}"
        )
    if len(wfm.frame_info) > 3:
        print(f"    ... ({len(wfm.frame_info) - 3} more)")
    frame0 = wfm.frame_data(0)
    print(f"  frame[0]: len={len(frame0)} raw[0]={int(frame0[0])} raw[-1]={int(frame0[-1])}")
    if isinstance(wfm, FastFrameDigitalWaveform):
        bits = wfm.frame(0).get_nth_bitstream(0)
        print(f"  frame[0] bitstream[0]={int(bits[0])} len={len(bits)}")


def _normalize_units(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return str(value)


def _compare_scalar(
    name: str,
    left,
    right,
    rtol: float = 0.0,
    atol: float = 0.0,
    *,
    optional: bool = False,
) -> list[str]:
    if optional and (left is None or right is None):
        return []
    if left is None and right is None:
        return []
    if isinstance(left, float) or isinstance(right, float):
        if not np.isclose(left, right, rtol=rtol, atol=atol, equal_nan=True):
            return [f"{name}: {left!r} != {right!r}"]
        return []
    if left != right:
        return [f"{name}: {left!r} != {right!r}"]
    return []


def _compare_frame_info(left: list[FrameTimingInfo], right: list[FrameTimingInfo]) -> list[str]:
    issues: list[str] = []
    if len(left) != len(right):
        issues.append(f"frame_info count: {len(left)} != {len(right)}")
        return issues
    for li, ri in zip(left, right):
        prefix = f"frame_info[{li.frame_index}]"
        issues.extend(_compare_scalar(f"{prefix}.frame_index", li.frame_index, ri.frame_index))
        issues.extend(
            _compare_scalar(f"{prefix}.time_offset", li.time_offset, ri.time_offset, atol=1e-9)
        )
        issues.extend(_compare_scalar(f"{prefix}.gmt_sec", li.gmt_sec, ri.gmt_sec))
        issues.extend(
            _compare_scalar(f"{prefix}.fract_sec", li.fract_sec, ri.fract_sec, atol=1e-12)
        )
        issues.extend(
            _compare_scalar(
                f"{prefix}.real_point_offset", li.real_point_offset, ri.real_point_offset
            )
        )
        issues.extend(
            _compare_scalar(
                f"{prefix}.frame_duration_sec",
                li.frame_duration_sec,
                ri.frame_duration_sec,
                atol=1e-12,
            )
        )
        issues.extend(
            _compare_scalar(f"{prefix}.is_summary_frame", li.is_summary_frame, ri.is_summary_frame)
        )
    return issues


def _compare_fastframe(
    original: FastFrameAnalogWaveform | FastFrameDigitalWaveform,
    loaded: FastFrameAnalogWaveform | FastFrameDigitalWaveform,
) -> tuple[list[str], list[str]]:
    """Return (data_issues, metadata_issues)."""
    data_issues: list[str] = []
    meta_issues: list[str] = []
    if type(original) is not type(loaded):
        data_issues.append(f"type: {type(original).__name__} != {type(loaded).__name__}")
        return data_issues, meta_issues

    meta_issues.extend(
        _compare_scalar("record_length", original.record_length, loaded.record_length)
    )
    meta_issues.extend(_compare_scalar("num_frames", original.num_frames, loaded.num_frames))
    meta_issues.extend(
        _compare_scalar(
            "summary_frame_index", original.summary_frame_index, loaded.summary_frame_index
        )
    )
    meta_issues.extend(
        _compare_scalar(
            "summary_frame_type", original.summary_frame_type, loaded.summary_frame_type
        )
    )
    meta_issues.extend(
        _compare_scalar("x_axis_spacing", original.x_axis_spacing, loaded.x_axis_spacing)
    )
    meta_issues.extend(
        _compare_scalar(
            "x_axis_units",
            _normalize_units(original.x_axis_units),
            _normalize_units(loaded.x_axis_units),
        )
    )
    meta_issues.extend(
        _compare_scalar("source_name", original.source_name, loaded.source_name, optional=True)
    )

    if isinstance(original, FastFrameAnalogWaveform):
        meta_issues.extend(
            _compare_scalar("y_axis_spacing", original.y_axis_spacing, loaded.y_axis_spacing)
        )
        meta_issues.extend(
            _compare_scalar("y_axis_offset", original.y_axis_offset, loaded.y_axis_offset)
        )
        meta_issues.extend(
            _compare_scalar(
                "y_axis_units",
                _normalize_units(original.y_axis_units),
                _normalize_units(loaded.y_axis_units),
            )
        )

    if isinstance(original, FastFrameDigitalWaveform):
        meta_issues.extend(
            _compare_scalar("digital_bitmask", original.digital_bitmask, loaded.digital_bitmask)
        )

    if len(original.frame_info) == len(loaded.frame_info):
        meta_issues.extend(_compare_frame_info(original.frame_info, loaded.frame_info))
    elif original.frame_info and loaded.frame_info:
        meta_issues.append(
            f"frame_info count: scope={len(original.frame_info)} file={len(loaded.frame_info)} "
            f"(WFM stores per-frame timing; TekHSI may return fewer entries)"
        )
        orig_by_index = {info.frame_index: info for info in original.frame_info}
        for info in loaded.frame_info:
            if info.frame_index in orig_by_index:
                meta_issues.extend(_compare_frame_info([orig_by_index[info.frame_index]], [info]))
    else:
        meta_issues.append(
            f"frame_info count: scope={len(original.frame_info)} file={len(loaded.frame_info)}"
        )

    if original.num_frames != loaded.num_frames:
        data_issues.append(f"num_frames: {original.num_frames} != {loaded.num_frames}")
        return data_issues, meta_issues

    for index in range(original.num_frames):
        orig_data = original.frame_data(index)
        load_data = loaded.frame_data(index)
        if orig_data.shape != load_data.shape:
            data_issues.append(f"frame[{index}] shape: {orig_data.shape} != {load_data.shape}")
            continue
        if not np.array_equal(orig_data, load_data):
            diff = int(np.max(np.abs(orig_data.astype(np.int64) - load_data.astype(np.int64))))
            mismatches = int(np.count_nonzero(orig_data != load_data))
            data_issues.append(
                f"frame[{index}] data mismatch: {mismatches}/{orig_data.size} samples differ, max diff={diff}"
            )

        if isinstance(original, FastFrameDigitalWaveform):
            orig_bits = original.frame(index).get_nth_bitstream(0)
            load_bits = loaded.frame(index).get_nth_bitstream(0)
            if not np.array_equal(orig_bits, load_bits):
                bit_diff = int(np.count_nonzero(orig_bits != load_bits))
                data_issues.append(
                    f"frame[{index}] bitstream mismatch: {bit_diff}/{len(orig_bits)} bits differ"
                )

    return data_issues, meta_issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FastFrame scope capture → .wfm save → read-back comparison",
    )
    parser.add_argument("--url", default="169.254.6.254:5000")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "sample_waveforms" / "fastframe_roundtrip",
        help="Directory for saved .wfm files",
    )
    parser.add_argument(
        "channels",
        nargs="*",
        default=["ch1", "ch2_dall"],
        help="Channel symbols (default: ch1 ch2_dall)",
    )
    args = parser.parse_args()

    channels = [c.lower() for c in args.channels]
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    captured: dict[str, FastFrameAnalogWaveform | FastFrameDigitalWaveform] = {}
    saved_paths: dict[str, Path] = {}

    print(f"Connecting to {args.url} ...", flush=True)
    with (
        TekHSIConnect(
            args.url,
            activesymbols=channels,
            on_trust_prompt=_auto_trust_prompt,
            credential_store=TekHSICredentialStore(path=store_path),
        ) as conn,
        conn.access_stopped_data(),
    ):
        print(f"available_symbols={conn.available_symbols}", flush=True)
        for channel in channels:
            print(f"\n--- Reading {channel} from scope ---", flush=True)
            wfm = conn.get_data(channel)
            if wfm is None:
                print(f"ERROR: no waveform for {channel}")
                return 1
            if not isinstance(wfm, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
                print(
                    f"ERROR: {channel} is {type(wfm).__name__}, expected a FastFrame capture "
                    f"(num_frames > 1 on a stopped scope)"
                )
                return 1
            captured[channel] = wfm
            _print_fastframe_info(f"scope {channel}", wfm)

            path = output_dir / f"{_safe_filename(wfm.source_name)}.wfm"
            print(f"  saving -> {path}")
            if isinstance(wfm, FastFrameDigitalWaveform):
                write_digital_wfm(str(path), wfm)
            else:
                write_file(str(path), wfm)
            saved_paths[channel] = path

    print("\n--- Reading back saved .wfm files ---")
    all_data_ok = True
    for channel, path in saved_paths.items():
        original = captured[channel]
        if isinstance(original, FastFrameDigitalWaveform):
            loaded = read_digital_wfm(str(path))
        else:
            loaded = read_file(str(path))
        _print_fastframe_info(f"file {path.name}", loaded)

        if not isinstance(loaded, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
            print(
                f"FAIL {channel}: read_file returned {type(loaded).__name__}, expected FastFrame type"
            )
            all_data_ok = False
            continue

        data_issues, meta_issues = _compare_fastframe(original, loaded)
        if data_issues:
            all_data_ok = False
            print(f"\nDATA FAIL {channel} ({path.name}) — {len(data_issues)} issue(s):")
            for issue in data_issues:
                print(f"  - {issue}")
        else:
            print(f"\nDATA PASS {channel} ({path.name}) — all {original.num_frames} frames match")

        if meta_issues:
            print(f"  metadata note(s) for {channel}:")
            for issue in meta_issues:
                print(f"  - {issue}")

    print(f"\nSaved files in {output_dir.resolve()}")
    if all_data_ok:
        print("Overall: DATA PASS — sample arrays match after .wfm round-trip")
        return 0
    print("Overall: DATA FAIL — see differences above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
