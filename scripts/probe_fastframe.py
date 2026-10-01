"""Probe FastFrame support on a live TekHSI scope."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import FastFrameAnalogWaveform, TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore


def _auto_trust_prompt(
    host: str, cert_info: Any, auth_required: bool = False
) -> bool | tuple[bool, str | None]:
    fp = getattr(cert_info, "cert_fingerprint", "") or ""
    fp_short = fp[:16] + "..." if len(fp) >= 16 else fp or "(none)"
    print(f"  [TRUST] host={host!r} auth_required={auth_required} fingerprint={fp_short}")
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            print("  Password required but TEKHSI_PASSWORD is not set.")
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


def _connect_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    if args.legacy:
        return {}
    store_path = args.store_path
    if store_path is None and not args.no_store:
        store_path = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    kw: dict[str, Any] = {"on_trust_prompt": _auto_trust_prompt}
    if store_path:
        kw["credential_store"] = TekHSICredentialStore(path=store_path)
    if args.require_tls:
        kw["require_tls"] = True
    return kw


def _print_load_timing(waveform: FastFrameAnalogWaveform) -> None:
    timing = waveform.load_timing
    if timing is None:
        print("load_timing: unavailable")
        return
    print("load_timing (raw digitizer levels, no normalization):")
    print(f"  {timing.format_summary()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe FastFrame on a TekHSI scope")
    parser.add_argument("--url", default="169.254.6.254:5000", help="Scope TekHSI address")
    parser.add_argument("--channel", default="ch1", help="Channel symbol")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Plain TekHSIConnect (no TLS auto-negotiation)",
    )
    parser.add_argument(
        "--require-tls",
        action="store_true",
        help="Refuse plaintext fallback during auto-negotiation",
    )
    parser.add_argument(
        "--store-path",
        default=None,
        help="Credential store INI path (default: temp file for probe trust pinning)",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Use platform default store instead of an isolated temp store",
    )
    parser.add_argument(
        "--list-frames",
        action="store_true",
        help="Print raw digitizer level for the first sample of every frame",
    )
    args = parser.parse_args()

    print(f"Connecting to {args.url} ...", flush=True)
    connect_kw = _connect_kwargs(args)
    with TekHSIConnect(
        args.url,
        activesymbols=[args.channel],
        callback=None,
        **connect_kw,
    ) as conn:
        conn.verbose = True
        print(
            f"protocol_version={conn.protocol_version} "
            f"capabilities=0x{conn.capabilities:04x} "
            f"fastframe_capable={conn.fastframe_capable}",
            flush=True,
        )

        with conn.access_stopped_data():
            waveform = conn.get_data(args.channel)

        if waveform is None:
            print("No waveform returned from cache.")
            return 1

        print(f"type={type(waveform).__name__} source={waveform.source_name}")
        if isinstance(waveform, FastFrameAnalogWaveform):
            print(f"samples_per_frame={waveform.record_length}")
            if waveform.summary_frame_index is None:
                print(f"{waveform.num_frames} data frames (no summary frame)")
            else:
                print(
                    f"{waveform.data_frame_count} data frames + "
                    f"{waveform.num_frames - waveform.data_frame_count} summary frame(s) "
                    f"= {waveform.num_frames} total"
                )
            print(f"current_frame_index={waveform.current_frame_index}")
            print(f"summary_frame_index={waveform.summary_frame_index}")
            _print_load_timing(waveform)
            if args.list_frames and waveform.all_frames_loaded:
                for index in range(waveform.data_frame_count):
                    samples = waveform.frame_data(index)
                    print(f"  frame {index:3d} (data): raw[0]={int(samples[0])}")
                summary_index = waveform.summary_frame_index
                if summary_index is not None:
                    summary_samples = waveform.frame_data(summary_index)
                    print(
                        f"  frame {summary_index:3d} (summary): "
                        f"raw[0]={int(summary_samples[0])} len={len(summary_samples)}"
                    )
        else:
            print("Waveform is a plain AnalogWaveform (single frame or no FastFrame metadata).")

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
