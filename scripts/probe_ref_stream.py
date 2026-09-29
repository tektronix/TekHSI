#!/usr/bin/env python3
"""Compare FastFrame stream behavior for live digital vs ref digital."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tekhsi import TekHSIConnect
from tekhsi._tek_highspeed_server_pb2 import WfmReplyStatus
from tekhsi.credential_store import TekHSICredentialStore


def trust(*_args, **_kwargs):
    return True


def probe(channel: str) -> None:
    store = str(Path(tempfile.gettempdir()) / "tekhsi_probe_credentials.ini")
    print(f"=== {channel} ===")
    with TekHSIConnect(
        "169.254.6.254:5000",
        [channel],
        on_trust_prompt=trust,
        credential_store=TekHSICredentialStore(path=store),
    ) as conn:
        conn.force_sequence()
        conn._wait_for_data_access()
        try:
            header = conn._read_header(channel)
            print(
                f"header name={header.sourcename!r} wfmtype={header.wfmtype} "
                f"frames={header.num_frames} samples={header.noofsamples} "
                f"hasdata={header.hasdata} bitmask=0x{header.bitmask:08x}"
            )
            request = conn._waveform_request_for_header(header)
            iterator = conn.native.GetWaveform(request, timeout=30)
            chunks = boundaries = total_bytes = 0
            last_i = -1
            for last_i, response in enumerate(iterator):
                if not conn._is_wfm_data_status(response.status):
                    continue
                if response.HasField("frame_boundary"):
                    boundaries += 1
                if response.headerordata.WhichOneof("value") == "chunk":
                    chunk = response.headerordata.chunk.data
                    if chunk:
                        chunks += 1
                        total_bytes += len(chunk)
                if last_i < 8:
                    which = response.headerordata.WhichOneof("value")
                    chunk_len = (
                        len(response.headerordata.chunk.data) if which == "chunk" else 0
                    )
                    print(
                        f"  [{last_i}] status={WfmReplyStatus.Name(response.status)} "
                        f"oneof={which} bytes={chunk_len} "
                        f"boundary={response.HasField('frame_boundary')}"
                    )
            print(
                f"  totals: messages={last_i + 1}, chunks={chunks}, "
                f"boundaries={boundaries}, bytes={total_bytes}"
            )
            iterator.cancel()
        finally:
            conn._finished_with_data_access()


if __name__ == "__main__":
    for symbol in sys.argv[1:] or ["ch2_dall", "ref2_dall"]:
        probe(symbol.lower())
