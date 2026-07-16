#!/usr/bin/env python3
"""Inspect raw FastFrame stream messages for a channel."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import TekHSIConnect
from tekhsi._tek_highspeed_server_pb2 import WfmReplyStatus
from tekhsi.credential_store import TekHSICredentialStore


def trust(host, cert_info, auth_required=False):
    if auth_required:
        pw = os.environ.get("TEKHSI_PASSWORD")
        if not pw:
            return False
        return True, pw, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="169.254.6.254:5000")
    parser.add_argument("channel", default="ch2_DAll", nargs="?")
    parser.add_argument("--max", type=int, default=15)
    args = parser.parse_args()

    store = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    channel = args.channel.lower()

    with TekHSIConnect(
        args.url,
        [channel],
        on_trust_prompt=trust,
        credential_store=TekHSICredentialStore(path=store),
        background_thread=False,
    ) as conn:
        with conn.access_stopped_data():
            header = conn._read_header(channel)
            print(
                f"header wfmtype={header.wfmtype} num_frames={header.num_frames} "
                f"samples={header.noofsamples} width={header.sourcewidth}",
                flush=True,
            )
            request = conn._waveform_request_for_header(header)
            print(f"request stream_all={request.stream_all_frames} mask=0x{request.reply_content_mask:x}", flush=True)
            it = conn.native.GetWaveform(request, timeout=30)
            for i, response in enumerate(it):
                if i >= args.max:
                    print(f"... stopping after {args.max} messages", flush=True)
                    break
                which = response.headerordata.WhichOneof("value")
                chunk_len = 0
                if which == "chunk":
                    chunk_len = len(response.headerordata.chunk.data)
                boundary = response.HasField("frame_boundary")
                print(
                    f"[{i}] status={WfmReplyStatus.Name(response.status)} "
                    f"oneof={which} chunk_bytes={chunk_len} boundary={boundary}",
                    flush=True,
                )
            with __import__("contextlib").suppress(Exception):
                it.cancel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
