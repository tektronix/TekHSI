#!/usr/bin/env python3
"""HSI FastFrame transfer sweep for Excel graphing.

Sweeps total sample count (record_length x num_frames) toward 100M,
picking at least three diverse (record_length, frames) factorizations per total
so Excel scatter plots can compare record length vs frame count at the same total.

Primary Y metrics for graphing:
  - transfer_time_ms  (gRPC receive + publish; data arrived -> available)
  - transfer_rate_Mbps

CSV is UTF-8 BOM, sorted by total_samples then record_length then num_frames.

For isolated frame-count vs record-length sweeps (raw, no averaging), see:
  scripts/hsi_diagnostic_benchmark.py
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import statistics
import sys
import tempfile
import time
import traceback

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPTS))

from tm_data_types import FastFrameAnalogWaveform

from scope_visa import (
    arm_sequence_acquisition,
    close_visa,
    configure_fastframe,
    configure_record_length,
    setup_scope_via_visa,
    start_scope_acquisition,
    wait_for_acquisition_complete,
)
from tekhsi import TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.helpers.logging import configure_logging, LoggingLevels
from tekhsi_conn import build_connect_kwargs, build_credentials, detect_server_mode

# Default total sample counts: ~x2.5 steps toward 100M.
# Smallest totals need rl>=2500 and frames>=2, so 15_000 is the first with 3+ layouts.
DEFAULT_TOTAL_SAMPLES: list[int] = [
    15_000,
    25_000,
    100_000,
    250_000,
    1_000_000,
    2_500_000,
    10_000_000,
    25_000_000,
    100_000_000,
]

# Record lengths commonly used on 5/6/7 Series scopes for factorization.
PREFERRED_RECORD_LENGTHS: list[int] = [
    2_500,
    10_000,
    100_000,
    1_000_000,
    10_000_000,
]

CSV_FIELDS: list[str] = [
    "total_samples",
    "record_length",
    "num_frames",
    "layout",
    "transfer_time_ms",
    "transfer_rate_Mbps",
    "grpc_transfer_ms",
    "grpc_publish_ms",
    "app_wait_ms",
    "acq_wait_s",
    "total_bytes",
    "bytes_per_sample",
    "status",
    "scope_ip",
    "channel",
    "repeats",
    "server_mode",
    "notes",
]


@dataclass(frozen=True)
class SweepPoint:
    """One (record_length, num_frames) configuration at a target total."""

    total_samples: int
    record_length: int
    num_frames: int
    layout: str


@dataclass
class SweepResult:
    point: SweepPoint
    transfer_time_ms: float
    transfer_rate_mbps: float
    grpc_transfer_ms: float | None
    grpc_publish_ms: float | None
    app_wait_ms: float
    acq_wait_s: float
    total_bytes: int
    bytes_per_sample: int
    status: str
    notes: str
    repeats: int


def _auto_trust_prompt(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD", "")
        return True, password
    return True


def default_total_samples(min_total: int, max_total: int) -> list[int]:
    return [t for t in DEFAULT_TOTAL_SAMPLES if min_total <= t <= max_total]


def _layout_label(num_frames: int) -> str:
    if num_frames <= 10:
        return "few_frames"
    if num_frames >= 100:
        return "many_frames"
    return "mid_frames"


MIN_FRAMES = 2
MIN_RECORD_LENGTH = 2_500  # typical minimum per-frame record length on 5/6/7 Series
MIN_COMBOS_PER_TOTAL = 3  # at least this many rl x frames layouts per total_samples


def _all_valid_pairs(total_samples: int) -> list[tuple[int, int]]:
    """Every (record_length, num_frames) whose product equals total_samples."""
    pairs: list[tuple[int, int]] = []
    max_frames = total_samples // MIN_RECORD_LENGTH
    for num_frames in range(MIN_FRAMES, max_frames + 1):
        if total_samples % num_frames != 0:
            continue
        record_length = total_samples // num_frames
        if record_length >= MIN_RECORD_LENGTH:
            pairs.append((record_length, num_frames))
    return pairs


def _evenly_spaced_indices(length: int, count: int) -> list[int]:
    if count <= 0 or length <= 0:
        return []
    if count >= length:
        return list(range(length))
    if count == 1:
        return [0]
    step = (length - 1) / (count - 1)
    return sorted({min(length - 1, round(i * step)) for i in range(count)})


def _layout_for_rank(rank: int, count: int, num_frames: int) -> str:
    if count == 1:
        return _layout_label(num_frames)
    if rank == 0:
        return "fewest_frames"
    if rank == count - 1:
        return "most_frames"
    return "mid_frames"


def _select_diverse_pairs(
    valid: list[tuple[int, int]],
    preferred_record_lengths: list[int],
    min_combos: int = MIN_COMBOS_PER_TOTAL,
) -> list[tuple[int, int]]:
    """Pick at least min_combos layouts, spread across frame counts when possible."""
    valid = sorted(set(valid), key=lambda x: (x[1], x[0]))
    if len(valid) <= min_combos:
        return valid

    indices = _evenly_spaced_indices(len(valid), min_combos)
    selected = [valid[i] for i in indices]

    for record_length in preferred_record_lengths:
        match = next((pair for pair in valid if pair[0] == record_length), None)
        if match is None or match in selected:
            continue
        replace_at = min(
            range(len(selected)),
            key=lambda i: abs(selected[i][1] - match[1]),
        )
        selected[replace_at] = match

    return sorted(set(selected), key=lambda x: (x[1], x[0]))


def factorizations(
    total_samples: int,
    record_lengths: list[int],
    max_record_length: int | None = None,
) -> list[SweepPoint]:
    """Return diverse (record_length, num_frames) pairs whose product equals total_samples."""
    valid = _all_valid_pairs(total_samples)
    if max_record_length is not None:
        valid = [(rl, nf) for rl, nf in valid if rl <= max_record_length]
    chosen = _select_diverse_pairs(valid, record_lengths)
    points: list[SweepPoint] = []
    for rank, (record_length, num_frames) in enumerate(chosen):
        points.append(
            SweepPoint(
                total_samples=total_samples,
                record_length=record_length,
                num_frames=num_frames,
                layout=_layout_for_rank(rank, len(chosen), num_frames),
            )
        )
    return points


def build_sweep_plan(
    totals: list[int],
    record_lengths: list[int],
    max_record_length: int | None,
    max_total_samples: int | None,
) -> tuple[list[SweepPoint], list[str]]:
    plan: list[SweepPoint] = []
    warnings: list[str] = []
    for total in totals:
        if max_total_samples is not None and total > max_total_samples:
            continue
        valid = _all_valid_pairs(total)
        if max_record_length is not None:
            valid = [(rl, nf) for rl, nf in valid if rl <= max_record_length]
        if not valid:
            warnings.append(
                f"total={total:,}: no valid rl x frames (need rl>={MIN_RECORD_LENGTH:,}, "
                f"frames>={MIN_FRAMES}"
                + (f", rl<={max_record_length:,}" if max_record_length else "")
                + ")"
            )
            continue
        if len(valid) < MIN_COMBOS_PER_TOTAL:
            warnings.append(
                f"total={total:,}: only {len(valid)} valid combo(s), need "
                f"{MIN_COMBOS_PER_TOTAL} for record-length vs frame comparison"
            )
        plan.extend(factorizations(total, record_lengths, max_record_length))
    return plan, warnings


def probe_scope_limits(visa_scope) -> tuple[int | None, str]:
    """Find the largest record length the scope accepts without clamping."""
    notes: list[str] = []
    max_seen: int | None = None
    for candidate in (100_000_000, 50_000_000, 10_000_000, 1_000_000, 250_000, 10_000, 2_500):
        actual = configure_record_length(visa_scope, candidate)
        if actual is None:
            continue
        max_seen = actual if max_seen is None else max(max_seen, actual)
        if actual < candidate:
            notes.append(f"rec_len clamped at {candidate:,} -> {actual:,}")
            break
    note = "; ".join(notes) if notes else ""
    return max_seen, note


def _run_one_acquisition(
    conn: TekHSIConnect,
    visa_scope,
    channel: str,
    acq_timeout_s: float = 120.0,
) -> tuple[float, float, float | None, float | None, float, float, int, int, int, str]:
    """Return timing metrics and optional error text from one stopped-data read."""
    acq_wait_s = 0.0
    acq_before = conn._acqcount  # noqa: SLF001

    if visa_scope is not None:
        t_acq_start = time.perf_counter()
        start_scope_acquisition(visa_scope)
        ok, reason = wait_for_acquisition_complete(visa_scope, timeout_s=acq_timeout_s)
        acq_wait_s = time.perf_counter() - t_acq_start
        if not ok:
            return 0.0, 0.0, None, None, 0.0, acq_wait_s, 0, 0, 0, reason

    t_app_start = time.perf_counter()
    with conn.access_stopped_data():
        waveform: FastFrameAnalogWaveform | None = conn.get_data(channel)
    app_wait_ms = (time.perf_counter() - t_app_start) * 1000.0

    if waveform is None:
        return 0.0, 0.0, None, None, app_wait_ms, acq_wait_s, 0, 0, 0, "no waveform from get_data"

    if conn._acqcount <= acq_before:  # noqa: SLF001
        return (
            0.0,
            0.0,
            None,
            None,
            app_wait_ms,
            acq_wait_s,
            0,
            0,
            0,
            "no new acquisition (stale cache)",
        )

    timing = waveform.load_timing
    if timing is not None:
        return (
            timing.total_ms,
            timing.transfer_mbps,
            timing.transfer_ms,
            timing.publish_ms,
            app_wait_ms,
            acq_wait_s,
            timing.total_raw_bytes,
            timing.bytes_per_sample,
            timing.num_frames,
            "",
        )

    bps = int(waveform.y_axis_values.dtype.itemsize)
    frames = waveform.num_frames or 0
    total_bytes = waveform.record_length * frames * bps
    rate = (total_bytes * 8 / 1_000_000) / (app_wait_ms / 1000) if app_wait_ms > 0 else 0.0
    return (
        app_wait_ms,
        rate,
        None,
        None,
        app_wait_ms,
        acq_wait_s,
        total_bytes,
        bps,
        frames,
        "no load_timing",
    )


def measure_point(
    conn: TekHSIConnect,
    visa_scope,
    channel: str,
    point: SweepPoint,
    repeats: int,
) -> SweepResult:
    notes: list[str] = []
    actual_rl = point.record_length
    actual_frames = point.num_frames

    if visa_scope is not None:
        rl = configure_record_length(visa_scope, point.record_length)
        if rl is None:
            return SweepResult(
                point=point,
                transfer_time_ms=0.0,
                transfer_rate_mbps=0.0,
                grpc_transfer_ms=None,
                grpc_publish_ms=None,
                app_wait_ms=0.0,
                acq_wait_s=0.0,
                total_bytes=0,
                bytes_per_sample=0,
                status="skipped",
                notes="VISA record length configure failed",
                repeats=0,
            )
        if rl != point.record_length:
            notes.append(f"rec_len clamped {point.record_length:,}->{rl:,}")
            return SweepResult(
                point=point,
                transfer_time_ms=0.0,
                transfer_rate_mbps=0.0,
                grpc_transfer_ms=None,
                grpc_publish_ms=None,
                app_wait_ms=0.0,
                acq_wait_s=0.0,
                total_bytes=0,
                bytes_per_sample=0,
                status="failed",
                notes=f"record length clamped {point.record_length:,}->{rl:,}",
                repeats=0,
            )
        actual_rl = rl

        arm_sequence_acquisition(visa_scope, 1)
        ff = configure_fastframe(visa_scope, point.num_frames)
        if ff is None:
            return SweepResult(
                point=point,
                transfer_time_ms=0.0,
                transfer_rate_mbps=0.0,
                grpc_transfer_ms=None,
                grpc_publish_ms=None,
                app_wait_ms=0.0,
                acq_wait_s=0.0,
                total_bytes=0,
                bytes_per_sample=0,
                status="skipped",
                notes="VISA FastFrame configure failed",
                repeats=0,
            )
        if ff != point.num_frames:
            notes.append(f"frames clamped {point.num_frames:,}->{ff:,}")
            return SweepResult(
                point=point,
                transfer_time_ms=0.0,
                transfer_rate_mbps=0.0,
                grpc_transfer_ms=None,
                grpc_publish_ms=None,
                app_wait_ms=0.0,
                acq_wait_s=0.0,
                total_bytes=0,
                bytes_per_sample=0,
                status="failed",
                notes=f"frames clamped {point.num_frames:,}->{ff:,}",
                repeats=0,
            )
        actual_frames = ff

    actual_total = actual_rl * actual_frames
    if actual_total != point.total_samples:
        notes.append(f"actual_total={actual_total:,} (target {point.total_samples:,})")

    transfer_times: list[float] = []
    transfer_rates: list[float] = []
    grpc_transfer: list[float] = []
    grpc_publish: list[float] = []
    app_waits: list[float] = []
    acq_waits: list[float] = []
    total_bytes = 0
    bytes_per_sample = 0
    errors: list[str] = []

    for _ in range(repeats):
        (
            transfer_time_ms,
            transfer_rate,
            grpc_t_ms,
            grpc_p_ms,
            app_wait_ms,
            acq_wait_s,
            tbytes,
            bps,
            _frames,
            err,
        ) = _run_one_acquisition(conn, visa_scope, channel)
        if err:
            errors.append(err)
            continue
        transfer_times.append(transfer_time_ms)
        transfer_rates.append(transfer_rate)
        if grpc_t_ms is not None:
            grpc_transfer.append(grpc_t_ms)
        if grpc_p_ms is not None:
            grpc_publish.append(grpc_p_ms)
        app_waits.append(app_wait_ms)
        acq_waits.append(acq_wait_s)
        total_bytes = tbytes
        bytes_per_sample = bps

    if not transfer_times:
        return SweepResult(
            point=point,
            transfer_time_ms=0.0,
            transfer_rate_mbps=0.0,
            grpc_transfer_ms=None,
            grpc_publish_ms=None,
            app_wait_ms=0.0,
            acq_wait_s=0.0,
            total_bytes=0,
            bytes_per_sample=0,
            status="failed",
            notes="; ".join(notes + errors) or "no successful repeats",
            repeats=0,
        )

    return SweepResult(
        point=point,
        transfer_time_ms=statistics.mean(transfer_times),
        transfer_rate_mbps=statistics.mean(transfer_rates),
        grpc_transfer_ms=statistics.mean(grpc_transfer) if grpc_transfer else None,
        grpc_publish_ms=statistics.mean(grpc_publish) if grpc_publish else None,
        app_wait_ms=statistics.mean(app_waits),
        acq_wait_s=statistics.mean(acq_waits) if acq_waits else 0.0,
        total_bytes=total_bytes,
        bytes_per_sample=bytes_per_sample,
        status="ok",
        notes="; ".join(notes),
        repeats=len(transfer_times),
    )


def result_to_csv_row(result: SweepResult, scope_ip: str, channel: str, server_mode: str) -> dict:
    p = result.point
    return {
        "total_samples": p.total_samples,
        "record_length": p.record_length,
        "num_frames": p.num_frames,
        "layout": p.layout,
        "transfer_time_ms": round(result.transfer_time_ms, 3),
        "transfer_rate_Mbps": round(result.transfer_rate_mbps, 2),
        "grpc_transfer_ms": ""
        if result.grpc_transfer_ms is None
        else round(result.grpc_transfer_ms, 3),
        "grpc_publish_ms": ""
        if result.grpc_publish_ms is None
        else round(result.grpc_publish_ms, 3),
        "app_wait_ms": round(result.app_wait_ms, 3),
        "acq_wait_s": round(result.acq_wait_s, 6),
        "total_bytes": result.total_bytes,
        "bytes_per_sample": result.bytes_per_sample,
        "status": result.status,
        "scope_ip": scope_ip,
        "channel": channel,
        "repeats": result.repeats,
        "server_mode": server_mode,
        "notes": result.notes,
    }


def write_csv(rows: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"hsi_transfer_sweep_{timestamp}.csv"
    sorted_rows = sorted(
        rows,
        key=lambda r: (r["total_samples"], r["record_length"], r["num_frames"]),
    )
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(sorted_rows)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ip", default="169.254.6.254")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--channel", default="ch1")
    parser.add_argument(
        "--repeats", type=int, default=2, help="Acquisitions averaged per sweep point"
    )
    parser.add_argument("--min-total", type=int, default=15_000)
    parser.add_argument("--max-total", type=int, default=100_000_000)
    parser.add_argument(
        "--totals",
        type=int,
        nargs="*",
        help="Explicit total sample counts (default: built-in 1K..100M progression)",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Single point only: use --record-length and --num-frames instead of sweep",
    )
    parser.add_argument("--record-length", type=int, default=2500)
    parser.add_argument("--num-frames", type=int, default=100)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results",
        help="Directory for Excel CSV (default: results/)",
    )
    parser.add_argument("--no-visa", action="store_true")
    args = parser.parse_args()

    configure_logging(log_console_level=LoggingLevels.WARNING)
    logging.getLogger("tekhsi").setLevel(logging.WARNING)

    url = f"{args.ip}:{args.port}"
    channel = args.channel.lower()

    totals = args.totals or default_total_samples(args.min_total, args.max_total)

    print("=" * 72)
    print("HSI FastFrame transfer sweep (Excel CSV)")
    print("=" * 72)
    print("Graph in Excel: scatter total_samples (X) vs transfer_time_ms (Y)")
    print("  Series/color by: record_length, num_frames, or layout")
    print()
    print(f"  scope       : {url}")
    print(f"  channel     : {channel}")
    print(f"  repeats     : {args.repeats} per point")
    print(f"  total range : {min(totals):,} .. {max(totals):,} samples")
    print(f"  output_dir  : {args.output_dir}")
    print("=" * 72)

    visa_scope = None
    visa_rm = None
    max_record_length: int | None = None
    probe_note = ""

    if not args.no_visa:
        print("\n[setup] VISA connect + probe limits...")
        visa_scope, visa_rm = setup_scope_via_visa(args.ip)
        if visa_scope is None:
            print("  VISA unavailable - sweep will use requested configs without SCPI setup.")
        else:
            max_record_length, probe_note = probe_scope_limits(visa_scope)
            if max_record_length is not None:
                print(f"  Max record length (probed): {max_record_length:,}")
            if probe_note:
                print(f"  {probe_note}")

    if args.single:
        total = args.record_length * args.num_frames
        plan = [
            SweepPoint(
                total_samples=total,
                record_length=args.record_length,
                num_frames=args.num_frames,
                layout=_layout_label(args.num_frames),
            )
        ]
    else:
        plan, plan_warnings = build_sweep_plan(
            totals,
            PREFERRED_RECORD_LENGTHS,
            max_record_length=max_record_length,
            max_total_samples=args.max_total,
        )

    if plan_warnings:
        print("\n[plan] warnings:")
        for warning in plan_warnings:
            print(f"  {warning}")

    if not plan:
        print("\nNo sweep points in plan (check --max-total or scope limits).")
        return 1

    print(
        f"\n[plan] {len(plan)} sweep points ({MIN_COMBOS_PER_TOTAL}+ layouts per total when possible):"
    )
    per_total = Counter(p.total_samples for p in plan)
    for total in sorted(per_total):
        print(f"  total={total:>12,}: {per_total[total]} layout(s)")
    print()
    for point in plan:
        print(
            f"  total={point.total_samples:>12,}  "
            f"rl={point.record_length:>10,}  frames={point.num_frames:>8,}  ({point.layout})"
        )

    print("\n[setup] TekHSI server mode...")
    needs_enc, needs_pwd, cert, pem_path, mode_str = detect_server_mode(url)
    print(f"  {mode_str}")

    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_repro_credentials.ini")
    credential_store = TekHSICredentialStore(path=store_path)
    if needs_enc or needs_pwd:
        credentials = build_credentials(
            url,
            None,
            needs_encryption=needs_enc,
            needs_password=needs_pwd,
            cert=cert,
            pem_path=pem_path,
        )
    else:
        credentials = None
    connect_kwargs = build_connect_kwargs(
        credentials,
        channel,
        on_trust_prompt=_auto_trust_prompt,
        credential_store=credential_store,
    )

    csv_rows: list[dict] = []

    try:
        print("\n[run] Sweep...")
        with TekHSIConnect(url, **connect_kwargs) as conn:
            for index, point in enumerate(plan, start=1):
                print(
                    f"\n  [{index}/{len(plan)}] total={point.total_samples:,}  "
                    f"rl={point.record_length:,}  frames={point.num_frames:,}  ({point.layout})"
                )
                result = measure_point(conn, visa_scope, channel, point, args.repeats)
                row = result_to_csv_row(result, args.ip, channel, mode_str)
                csv_rows.append(row)

                if result.status == "ok":
                    print(
                        f"    transfer_time={result.transfer_time_ms:.2f} ms  "
                        f"rate={result.transfer_rate_mbps:.2f} Mbps  "
                        f"(repeats={result.repeats})"
                    )
                else:
                    print(f"    {result.status}: {result.notes}")

    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if visa_scope is not None:
            close_visa(visa_scope, visa_rm)

    ok_rows = [r for r in csv_rows if r["status"] == "ok"]
    if not ok_rows:
        print("\nNo successful measurements.")
        if csv_rows:
            write_csv(csv_rows, args.output_dir)
        return 1

    csv_path = write_csv(csv_rows, args.output_dir)
    print("\n" + "=" * 72)
    print(f"Done: {len(ok_rows)} ok / {len(csv_rows)} points")
    print(f"CSV:  {csv_path.resolve()}")
    print()
    print("Excel tips:")
    print("  - Insert > Scatter: X=total_samples, Y=transfer_time_ms")
    print("  - Add record_length and num_frames as series names or data labels")
    print("  - Use log scale on X if totals span 1K..100M")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
