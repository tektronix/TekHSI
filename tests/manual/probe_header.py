#!/usr/bin/env python3
"""Print FastFrame header metadata without reading waveform bytes."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore


def _auto_trust(host: str, cert_info, auth_required: bool = False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "Tektronix")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="169.254.6.254:5000")
    parser.add_argument("channel", default="ch2_DAll", nargs="?")
    args = parser.parse_args()

    store_path = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    channel = args.channel.lower()

    print(f"Connecting to {args.url} ...", flush=True)
    t0 = time.perf_counter()
    with TekHSIConnect(
        args.url,
        activesymbols=[channel],
        on_trust_prompt=_auto_trust,
        credential_store=TekHSICredentialStore(path=store_path),
        timeout=15.0,
    ) as conn:
        print(f"connected in {(time.perf_counter() - t0) * 1000:.0f} ms", flush=True)
        print(f"available_symbols={conn.available_symbols}", flush=True)
        with conn.access_stopped_data():
            header = conn._read_header(channel)
            print(
                f"header: sourcename={header.sourcename!r} wfmtype={header.wfmtype} "
                f"num_frames={header.num_frames} noofsamples={header.noofsamples} "
                f"sourcewidth={header.sourcewidth} hasdata={header.hasdata} "
                f"bitmask=0x{header.bitmask:08x}",
                flush=True,
            )
            if header.frame_info:
                for info in header.frame_info[:3]:
                    print(
                        f"  frame_info[{info.frame_index}]: summary={info.is_summary_frame} "
                        f"duration={info.frame_duration_sec}",
                        flush=True,
                    )
                if len(header.frame_info) > 3:
                    print(f"  ... {len(header.frame_info)} frame_info entries total", flush=True)
    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
