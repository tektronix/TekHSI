#!/usr/bin/env python3
"""Raw HSI diagnostic benchmark for frame-count vs record-length isolation.

Protocol (run in order):
  1. Link verification (ethtool / ip -s link) — abort sweeps if link bad
  2. Sweep A: RL=100K fixed, vary num_frames
  3. Sweep B: N=10 fixed, vary record_length
  4. Per-frame arrival dump (falloff config)
  5. tcpdump during falloff transfer
  6. ss -ti every 100ms during one long + one falloff transfer

Raw numbers only — no averaging, no modeling. Three repeats per config,
randomized execution order. Does not modify tekhsi core; uses existing APIs
and private stream hooks like scripts/probe_stream.py.

Deliverables under --output-dir/<timestamp>/:
  link_verification.txt
  link_verification_after_transfer.txt
  sweep_a.csv
  sweep_b.csv
  per_frame_arrivals.csv
  ss_long_transfer.txt
  ss_falloff_transfer.txt
  falloff_capture.pcap (when tcpdump available)
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import shutil
import sys
import tempfile
import time
import traceback

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPTS))

from hsi_network_diagnostics import (
    LinkCheckResult,
    record_link_after_transfer,
    resolve_iface_for_host,
    SsSampler,
    verify_link_before_sweeps,
)
from scope_visa import (
    arm_sequence_acquisition,
    close_visa,
    configure_fastframe,
    configure_record_length,
    DEFAULT_ACQ_WAIT_TIMEOUT_S,
    disable_fastframe,
    setup_scope_via_visa,
    start_scope_acquisition,
    wait_for_acquisition_complete,
)
from tekhsi import TekHSIConnect
from tekhsi._tek_highspeed_server_pb2 import WfmReplyStatus
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.helpers.logging import configure_logging, LoggingLevels
from tekhsi_conn import build_connect_kwargs, build_credentials, detect_server_mode
from tm_data_types import FastFrameAnalogWaveform

SWEEP_A_RL = 100_000
SWEEP_A_FRAMES = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500]

SWEEP_B_FRAMES = 10
SWEEP_B_RL = [
    1_000,
    2_500,
    5_000,
    10_000,
    25_000,
    50_000,
    100_000,
    250_000,
    1_000_000,
    2_500_000,
    10_000_000,
]

FALLOFF_RL = 2_500
FALLOFF_FRAMES = 4_000
LONG_RL = 10_000_000
LONG_FRAMES = 10

SWEEP_CSV_FIELDS = [
    "sweep",
    "run_index",
    "exec_order",
    "record_length",
    "num_frames",
    "total_samples",
    "grpc_transfer_ms",
    "client_publish_ms",
    "wall_ms",
    "status",
    "notes",
    "scope_ip",
    "channel",
    "timestamp_utc",
]

FRAME_ARRIVAL_FIELDS = [
    "record_length",
    "num_frames",
    "message_index",
    "frame_index",
    "is_frame_boundary",
    "chunk_bytes",
    "cumulative_bytes",
    "arrival_ms",
    "delta_ms",
    "status",
]


@dataclass(frozen=True)
class BenchConfig:
    sweep: str
    record_length: int
    num_frames: int
    run_index: int

    @property
    def total_samples(self) -> int:
        return self.record_length * self.num_frames


def _auto_trust_prompt(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD", "")
        return True, password
    return True


def build_run_list(repeats: int, seed: int | None) -> list[BenchConfig]:
    configs: list[BenchConfig] = []
    for nf in SWEEP_A_FRAMES:
        for run_index in range(1, repeats + 1):
            configs.append(BenchConfig("A", SWEEP_A_RL, nf, run_index))
    for rl in SWEEP_B_RL:
        for run_index in range(1, repeats + 1):
            configs.append(BenchConfig("B", rl, SWEEP_B_FRAMES, run_index))
    rng = random.Random(seed)
    rng.shuffle(configs)
    return configs


def configure_scope(
    visa_scope,
    record_length: int,
    num_frames: int,
    *,
    fail_on_clamp: bool = True,
) -> tuple[int, int]:
    """Configure scope; raise if clamped when ``fail_on_clamp`` is True."""
    rl = configure_record_length(visa_scope, record_length)
    if rl is None:
        raise RuntimeError("record length configure failed")
    if fail_on_clamp and rl != record_length:
        raise RuntimeError(f"record length clamped {record_length:,} -> {rl:,}")

    if num_frames < 2:
        if not disable_fastframe(visa_scope):
            raise RuntimeError("disable_fastframe failed")
        actual_frames = 1
        if fail_on_clamp and num_frames != 1:
            raise RuntimeError(f"expected single-frame capture, requested {num_frames}")
    else:
        arm_sequence_acquisition(visa_scope, 1)
        ff = configure_fastframe(visa_scope, num_frames)
        if ff is None:
            raise RuntimeError("fastframe configure failed")
        if fail_on_clamp and ff != num_frames:
            raise RuntimeError(f"frame count clamped {num_frames:,} -> {ff:,}")
        actual_frames = ff

    return rl, actual_frames


def run_acquisition_and_read(
    conn: TekHSIConnect,
    visa_scope,
    channel: str,
    expected_rl: int,
    expected_nf: int,
    acq_timeout_s: float,
) -> tuple[float, float | None, float | None, float, str]:
    acq_before = conn._acqcount

    if visa_scope is not None:
        start_scope_acquisition(visa_scope)
        ok, reason = wait_for_acquisition_complete(visa_scope, timeout_s=acq_timeout_s)
        if not ok:
            return 0.0, None, None, 0.0, reason

    wall_start = time.perf_counter()
    with conn.access_stopped_data():
        waveform: FastFrameAnalogWaveform | None = conn.get_data(channel)
    wall_ms = (time.perf_counter() - wall_start) * 1000.0

    if waveform is None:
        return wall_ms, None, None, wall_ms, "no waveform from get_data"

    if conn._acqcount <= acq_before:
        return wall_ms, None, None, wall_ms, "no new acquisition (stale cache)"

    timing = waveform.load_timing
    if timing is None:
        return wall_ms, None, None, wall_ms, "no load_timing"

    if timing.record_length != expected_rl:
        return (
            wall_ms,
            timing.transfer_ms,
            timing.publish_ms,
            wall_ms,
            f"record_length mismatch expected {expected_rl:,} got {timing.record_length:,}",
        )
    if timing.num_frames != expected_nf:
        return (
            wall_ms,
            timing.transfer_ms,
            timing.publish_ms,
            wall_ms,
            f"num_frames mismatch expected {expected_nf:,} got {timing.num_frames:,}",
        )

    return wall_ms, timing.transfer_ms, timing.publish_ms, wall_ms, ""


def measure_config(
    conn: TekHSIConnect,
    visa_scope,
    channel: str,
    config: BenchConfig,
    acq_timeout_s: float,
) -> dict:
    notes: list[str] = []
    status = "ok"
    rl = config.record_length
    nf = config.num_frames
    try:
        if visa_scope is not None:
            rl, nf = configure_scope(visa_scope, config.record_length, config.num_frames)
        else:
            notes.append("no_visa")

        wall_ms, grpc_ms, publish_ms, _, err = run_acquisition_and_read(
            conn,
            visa_scope,
            channel,
            expected_rl=rl,
            expected_nf=nf,
            acq_timeout_s=acq_timeout_s,
        )
        if err:
            status = "failed"
            notes.append(err)
    except Exception as exc:
        status = "failed"
        notes.append(str(exc))
        wall_ms = 0.0
        grpc_ms = None
        publish_ms = None

    return {
        "sweep": config.sweep,
        "run_index": config.run_index,
        "exec_order": "",
        "record_length": rl,
        "num_frames": nf,
        "total_samples": rl * nf,
        "grpc_transfer_ms": "" if grpc_ms is None else grpc_ms,
        "client_publish_ms": "" if publish_ms is None else publish_ms,
        "wall_ms": wall_ms,
        "status": status,
        "notes": "; ".join(notes),
        "scope_ip": "",
        "channel": channel,
        "timestamp_utc": datetime.now().astimezone().isoformat(timespec="milliseconds"),
    }


def _is_wfm_data_status(status: int) -> bool:
    name = WfmReplyStatus.Name(status)
    return name not in ("WFMREPLYSTATUS_UNSPECIFIED", "WFMREPLYSTATUS_REJECTED")


def dump_per_frame_arrivals(
    url: str,
    connect_kwargs: dict,
    visa_scope,
    channel: str,
    record_length: int,
    num_frames: int,
    output_path: Path,
    acq_timeout_s: float,
) -> list[dict]:
    """Stream per-message arrival times on a fresh connection (after long sweep)."""
    rows: list[dict] = []
    if visa_scope is not None:
        configure_scope(visa_scope, record_length, num_frames)
        start_scope_acquisition(visa_scope)
        ok, reason = wait_for_acquisition_complete(visa_scope, timeout_s=acq_timeout_s)
        if not ok:
            raise RuntimeError(reason)

    with TekHSIConnect(url, **connect_kwargs) as conn, conn.access_stopped_data():
        header = conn._read_header(channel)
        request = conn._waveform_request_for_header(header)
        expected_bytes = int(header.num_frames) * int(header.noofsamples) * int(header.sourcewidth)
        timeout_sec = min(120.0, max(15.0, expected_bytes / (5 * 1024 * 1024)))
        iterator = conn.native.GetWaveform(request, timeout=timeout_sec)

        t0 = time.perf_counter()
        cumulative = 0
        prev_arrival = 0.0
        frame_index = -1

        try:
            for message_index, response in enumerate(iterator):
                arrival_ms = (time.perf_counter() - t0) * 1000.0
                delta_ms = arrival_ms - prev_arrival if message_index else 0.0
                prev_arrival = arrival_ms

                is_boundary = response.HasField("frame_boundary")
                chunk_bytes = 0
                if response.headerordata.WhichOneof("value") == "chunk":
                    chunk_bytes = len(response.headerordata.chunk.data)
                    cumulative += chunk_bytes

                if is_boundary:
                    frame_index = int(response.frame_boundary.frame_info.frame_index)

                rows.append(
                    {
                        "record_length": record_length,
                        "num_frames": num_frames,
                        "message_index": message_index,
                        "frame_index": frame_index if is_boundary else "",
                        "is_frame_boundary": int(is_boundary),
                        "chunk_bytes": chunk_bytes,
                        "cumulative_bytes": cumulative,
                        "arrival_ms": round(arrival_ms, 6),
                        "delta_ms": round(delta_ms, 6),
                        "status": WfmReplyStatus.Name(response.status),
                    }
                )

                if not _is_wfm_data_status(response.status):
                    continue
                if cumulative >= expected_bytes and is_boundary:
                    if frame_index >= int(header.num_frames) - 1:
                        break
        finally:
            import contextlib

            with contextlib.suppress(Exception):
                iterator.cancel()

    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FRAME_ARRIVAL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def run_transfer_with_ss(
    conn: TekHSIConnect,
    visa_scope,
    channel: str,
    host: str,
    port: int,
    record_length: int,
    num_frames: int,
    acq_timeout_s: float,
) -> str:
    sampler = SsSampler(host, port, interval_s=0.1)
    sampler.start()
    try:
        if visa_scope is not None:
            configure_scope(visa_scope, record_length, num_frames)
        run_acquisition_and_read(
            conn,
            visa_scope,
            channel,
            expected_rl=record_length,
            expected_nf=num_frames,
            acq_timeout_s=acq_timeout_s,
        )
    finally:
        result = sampler.stop()
    return result


def write_sweep_csv(path: Path, rows: list[dict], sweep_label: str) -> None:
    filtered = [r for r in rows if r["sweep"] == sweep_label]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SWEEP_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(
            sorted(
                filtered,
                key=lambda r: (int(r["record_length"]), int(r["num_frames"]), int(r["run_index"])),
            )
        )


def large_link_test_transfer(
    conn: TekHSIConnect,
    visa_scope,
    channel: str,
    max_rl: int | None,
) -> BenchConfig:
    rl = min(LONG_RL, max_rl) if max_rl else LONG_RL
    return BenchConfig("link_test", rl, LONG_FRAMES, 1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ip", default="169.254.6.254")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--channel", default="ch1")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--seed", type=int, default=None, help="Random order seed (default: random)"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--no-visa", action="store_true")
    parser.add_argument("--skip-link-check", action="store_true")
    parser.add_argument("--skip-pcap", action="store_true")
    parser.add_argument("--skip-ss", action="store_true")
    parser.add_argument("--skip-frame-dump", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--acq-timeout",
        type=float,
        default=DEFAULT_ACQ_WAIT_TIMEOUT_S,
        help="Seconds to wait for scope acquisition to complete (default: 120)",
    )
    args = parser.parse_args()

    configure_logging(log_console_level=LoggingLevels.WARNING)
    logging.getLogger("tekhsi").setLevel(logging.WARNING)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.output_dir / f"diagnostic_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    url = f"{args.ip}:{args.port}"
    channel = args.channel.lower()
    run_list = build_run_list(args.repeats, args.seed)

    print("=" * 72)
    print("HSI diagnostic benchmark (raw)")
    print("=" * 72)
    print(f"  scope      : {url}")
    print(f"  channel    : {channel}")
    print(f"  repeats    : {args.repeats} per config (all rows kept)")
    print(f"  configs    : Sweep A={len(SWEEP_A_FRAMES)}, Sweep B={len(SWEEP_B_RL)}")
    print(f"  total runs  : {len(run_list)}")
    print(f"  output      : {run_dir}")
    print(f"  acq timeout : {args.acq_timeout:.0f}s (timeouts fail the row)")
    print(f"  cross-check : RL={SWEEP_A_RL}, N={SWEEP_B_FRAMES} appears in both sweeps")
    print("=" * 72)

    if args.dry_run:
        for idx, cfg in enumerate(run_list, start=1):
            print(
                f"  [{idx:>3}] sweep={cfg.sweep} run={cfg.run_index} "
                f"rl={cfg.record_length:,} frames={cfg.num_frames:,} total={cfg.total_samples:,}"
            )
        return 0

    link: LinkCheckResult | None = None
    if not args.skip_link_check:
        print("\n[1/7] Link verification (before)...")
        link = verify_link_before_sweeps(args.ip, run_dir)
        for msg in link.messages:
            print(f"  {msg}")
        if not link.ok:
            print("\nABORT: link verification failed. Fix link before sweeps.")
            print(f"See {run_dir / 'link_verification.txt'}")
            return 2

    visa_scope = None
    visa_rm = None
    max_rl: int | None = None
    if not args.no_visa:
        print("\n[setup] VISA...")
        visa_scope, visa_rm = setup_scope_via_visa(args.ip)
        if visa_scope is not None:
            actual = configure_record_length(visa_scope, LONG_RL)
            max_rl = actual

    print("\n[setup] TekHSI...")
    needs_enc, needs_pwd, cert, pem_path, mode_str = detect_server_mode(url)
    print(f"  {mode_str}")
    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_diagnostic_credentials.ini")
    credential_store = TekHSICredentialStore(path=store_path)
    credentials = (
        build_credentials(
            url,
            None,
            needs_encryption=needs_enc,
            needs_password=needs_pwd,
            cert=cert,
            pem_path=pem_path,
        )
        if needs_enc or needs_pwd
        else None
    )
    connect_kwargs = build_connect_kwargs(
        credentials,
        channel,
        on_trust_prompt=_auto_trust_prompt,
        credential_store=credential_store,
    )

    all_rows: list[dict] = []

    try:
        with TekHSIConnect(url, **connect_kwargs) as conn:
            if link is not None and not args.skip_link_check:
                print("\n[1b/7] Large transfer for link counter delta...")
                lt = large_link_test_transfer(conn, visa_scope, channel, max_rl)
                row = measure_config(conn, visa_scope, channel, lt, args.acq_timeout)
                row["scope_ip"] = args.ip
                link = record_link_after_transfer(args.ip, run_dir, link)
                for msg in link.messages:
                    print(f"  {msg}")
                if not link.ok:
                    print("\nABORT: link errors after large transfer.")
                    return 2

            print("\n[2/7] Sweeps A + B (randomized order)...")
            for exec_order, config in enumerate(run_list, start=1):
                print(
                    f"  [{exec_order}/{len(run_list)}] sweep={config.sweep} run={config.run_index} "
                    f"rl={config.record_length:,} frames={config.num_frames:,}"
                )
                row = measure_config(conn, visa_scope, channel, config, args.acq_timeout)
                row["exec_order"] = exec_order
                row["scope_ip"] = args.ip
                all_rows.append(row)
                if row["status"] != "ok":
                    print(f"    FAILED: {row['notes']}")

            if not args.skip_frame_dump:
                print(
                    f"\n[3/7] Per-frame arrival dump (RL={FALLOFF_RL:,}, N={FALLOFF_FRAMES:,})..."
                )
                dump_per_frame_arrivals(
                    url,
                    connect_kwargs,
                    visa_scope,
                    channel,
                    FALLOFF_RL,
                    FALLOFF_FRAMES,
                    run_dir / "per_frame_arrivals.csv",
                    args.acq_timeout,
                )

            iface = resolve_iface_for_host(args.ip) if link else None

            if not args.skip_pcap and iface:
                print(f"\n[4/7] tcpdump during falloff transfer ({iface})...")
                pcap_path = run_dir / "falloff_capture.pcap"
                pcap_notes: list[str] = []
                if shutil.which("tcpdump"):
                    import subprocess

                    filter_expr = f"host {args.ip} and port {args.port}"
                    proc = subprocess.Popen(
                        ["tcpdump", "-i", iface, "-w", str(pcap_path), filter_expr],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    try:
                        if visa_scope is not None:
                            configure_scope(visa_scope, FALLOFF_RL, FALLOFF_FRAMES)
                        run_acquisition_and_read(
                            conn,
                            visa_scope,
                            channel,
                            FALLOFF_RL,
                            FALLOFF_FRAMES,
                            args.acq_timeout,
                        )
                    finally:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        if proc.stderr:
                            pcap_notes.append(proc.stderr.read())
                    if pcap_path.exists():
                        pcap_notes.append(
                            f"pcap written: {pcap_path} ({pcap_path.stat().st_size} bytes)"
                        )
                    else:
                        pcap_notes.append("tcpdump ended without pcap file")
                else:
                    pcap_notes.append("tcpdump not available")
                (run_dir / "falloff_capture.txt").write_text(
                    "\n".join(pcap_notes) + "\n", encoding="utf-8"
                )
            elif not args.skip_pcap:
                (run_dir / "falloff_capture.txt").write_text(
                    "pcap skipped: no iface\n", encoding="utf-8"
                )

            if not args.skip_ss:
                print("\n[5/7] ss -ti during long transfer...")
                long_rl = min(LONG_RL, max_rl) if max_rl else LONG_RL
                ss_long = run_transfer_with_ss(
                    conn,
                    visa_scope,
                    channel,
                    args.ip,
                    args.port,
                    long_rl,
                    LONG_FRAMES,
                    args.acq_timeout,
                )
                (run_dir / "ss_long_transfer.txt").write_text(ss_long + "\n", encoding="utf-8")

                print("[6/7] ss -ti during falloff transfer...")
                ss_falloff = run_transfer_with_ss(
                    conn,
                    visa_scope,
                    channel,
                    args.ip,
                    args.port,
                    FALLOFF_RL,
                    FALLOFF_FRAMES,
                    args.acq_timeout,
                )
                (run_dir / "ss_falloff_transfer.txt").write_text(
                    ss_falloff + "\n", encoding="utf-8"
                )

    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if visa_scope is not None:
            close_visa(visa_scope, visa_rm)

    for row in all_rows:
        row.setdefault("scope_ip", args.ip)

    write_sweep_csv(run_dir / "sweep_a.csv", all_rows, "A")
    write_sweep_csv(run_dir / "sweep_b.csv", all_rows, "B")

    manifest = [
        f"timestamp={timestamp}",
        f"scope={url}",
        f"channel={channel}",
        f"repeats={args.repeats}",
        f"sweep_a_rows={sum(1 for r in all_rows if r['sweep'] == 'A')}",
        f"sweep_b_rows={sum(1 for r in all_rows if r['sweep'] == 'B')}",
        f"cross_point_A: rl={SWEEP_A_RL} frames=10",
        f"cross_point_B: rl={SWEEP_A_RL} frames={SWEEP_B_FRAMES}",
        "files:",
        "  link_verification.txt",
        "  link_verification_after_transfer.txt",
        "  sweep_a.csv",
        "  sweep_b.csv",
        "  per_frame_arrivals.csv",
        "  ss_long_transfer.txt",
        "  ss_falloff_transfer.txt",
        "  falloff_capture.pcap",
    ]
    (run_dir / "manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    ok = sum(1 for r in all_rows if r["status"] == "ok")
    print("\n" + "=" * 72)
    print(f"Done: {ok}/{len(all_rows)} sweep rows ok")
    print(f"Output: {run_dir.resolve()}")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
