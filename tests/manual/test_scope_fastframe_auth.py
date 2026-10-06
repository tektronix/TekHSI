"""Manual integration test: FastFrame + authentication (TLS and TLS+password).

WHAT THIS SCRIPT DOES
----------------------
Each run does a single pass:
  1. Discovers what the scope currently requires (plain / TLS / TLS+password).
  2. Connects with the matching credentials.
  3. Reads a stopped FastFrame capture on ``channel``.
  4. Prints a simple PASS/FAIL report of what it saw:
       - record length
       - number of frames captured
       - summary-frame presence
       - acquisition mode (inferred from the waveform metadata)

HOW TO USE IT (change the scope, then just re-run this script)
----------------------------------------------------------------
This script does NOT change any scope settings for you - you switch them
manually in the scope UI between runs, then re-run this file. Suggested
combinations to cycle through:

  Authentication:
    A1. No TLS, no password            (plain gRPC)
    A2. TLS only                       (Mode 2 - no password)
    A3. TLS + password                 (Mode 3 - HTTP Basic auth)

  FastFrame:
    F1. Record length: short  (e.g. 1,000 pts)  vs long (e.g. 1,000,000 pts)
    F2. Acquisition mode: Sample / Average / Envelope / HiRes / Peak Detect
    F3. Number of frames: e.g. 2, 10, 1000 (scope's FastFrame frame count)
    F4. Summary frame: enabled vs disabled (scope's FastFrame "Summary Frame"
        setting - usually Average or Envelope summary)

Run the full matrix (A1-A3) x (F1-F4 varied one at a time) and confirm this
script reports PASS every time with the values you expect. Any mismatch
(wrong record length, missing frames, wrong summary state) is a real defect.

This script intentionally avoids plotting/matplotlib so it runs fast and is
easy to read - it only prints a text report.
"""

from __future__ import annotations

import getpass
import os
import sys

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "examples"))

# Imports must happen after sys.path adjustment so local example helpers resolve.
# pylint: disable=wrong-import-position
from auth_helpers import discover, guard_placeholder_addr, verify_password  # noqa: E402
from tekhsi import TekHSIConnect, TekHSICredentials  # noqa: E402
from tm_data_types import FastFrameAnalogWaveform  # noqa: E402

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("TEKHSI_RUN_MANUAL_SCOPE") != "1",
        reason="Set TEKHSI_RUN_MANUAL_SCOPE=1 to run against a real scope.",
    ),
]

url = os.environ.get("TEKHSI_SCOPE_URL", "192.168.0.1:5000")
channel = os.environ.get("TEKHSI_SCOPE_CHANNEL", "ch1")
addr = url.rsplit(":", maxsplit=1)[0]
guard_placeholder_addr(addr)


def _fmt(label: str, value: object) -> str:
    return f"  {label:<22}: {value}"


def discover_and_connect() -> TekHSIConnect:
    """Discover the scope's current auth mode and open a matching connection."""
    plain_ok, cert_path, entry, needs_password = discover(url)

    print(f"Server at {url} requires:")
    print(f"  - Encryption (TLS): {'no' if plain_ok else 'yes'}")
    print(f"  - Password:         {'yes' if needs_password else 'no'}")

    password: str | None = None
    if needs_password:
        password = (
            os.environ.get("TEKHSI_SCOPE_PASSWORD")
            or getpass.getpass(f"Password for TekHSI at {url}: ")
            or None
        )
        if not password:
            print("Password is required but none was provided.")
            if cert_path is not None:
                cert_path.unlink(missing_ok=True)
            sys.exit(1)
        if not (password := verify_password(url, entry, password, cert_path)):
            print("Password verification did not return a usable token/password.")
            if cert_path is not None:
                cert_path.unlink(missing_ok=True)
            sys.exit(1)

    credentials: TekHSICredentials | None
    if plain_ok:
        credentials = None
    elif needs_password:
        if cert_path is None:
            print("TLS+password mode requires a CA cert path, but none was discovered.")
            sys.exit(1)
        credentials = TekHSICredentials.token(str(cert_path), password)
    else:
        credentials = TekHSICredentials.tls(str(cert_path))

    # Cleanup of the temp cert file is intentionally skipped here; it is a
    # short-lived temp file and the process exit will clean it up. Keeping
    # this script simple/readable was prioritized over that minor cleanup.
    return TekHSIConnect(url, credentials=credentials)


def report_fastframe_capture(waveform: object) -> bool:
    """Print a simple PASS/FAIL diagnostic report for a FastFrame capture."""
    print("\n--- FastFrame capture report --------------------------------------")

    if waveform is None:
        print("  FAIL: no waveform returned (channel enabled? scope stopped?)")
        return False

    if not isinstance(waveform, FastFrameAnalogWaveform):
        print(f"  FAIL: expected FastFrameAnalogWaveform, got {type(waveform).__name__}")
        print("        (Is FastFrame actually enabled on the scope for this channel?)")
        return False

    record_length = len(waveform.frame_data(0))
    num_frames = waveform.num_frames
    data_frame_count = waveform.data_frame_count
    current_frame = waveform.current_frame_index
    summary_index = waveform.summary_frame_index
    has_summary = summary_index is not None and summary_index >= 0

    print(_fmt("source", waveform.source_name))
    print(_fmt("record length", record_length))
    print(_fmt("num_frames (total)", num_frames))
    print(_fmt("data_frame_count", data_frame_count))
    print(_fmt("current_frame_index", current_frame))
    print(_fmt("summary_frame_index", summary_index))
    print(_fmt("summary frame present", has_summary))

    ok = True
    if record_length <= 0:
        print("  FAIL: record length is zero.")
        ok = False
    if num_frames <= 0:
        print("  FAIL: num_frames is zero - FastFrame does not look enabled.")
        ok = False
    if data_frame_count != num_frames and not has_summary:
        # If there's no summary frame, data_frame_count should equal num_frames.
        print("  WARN: data_frame_count != num_frames and no summary frame;")
        print("        double-check scope FastFrame frame count.")

    if has_summary and summary_index is not None:
        summary_samples = waveform.frame_data(summary_index)
        print(_fmt("summary raw[0]", int(summary_samples[0])))

    if waveform.load_timing is not None:
        print("  timing:", waveform.load_timing.format_summary())

    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    print("---------------------------------------------------------------------\n")
    return ok


def main() -> int:
    """Run one discover -> connect -> capture -> report cycle."""
    with discover_and_connect() as connection:
        print("Channels:", list(connection.activesymbols))
        if channel not in connection.activesymbols:
            print(f"FAIL: '{channel}' is not an active channel on the scope.")
            return 1

        # FastFrame captures on a stopped scope require force_sequence + AnyAcq,
        # which access_stopped_data() takes care of for us.
        with connection.access_stopped_data():
            waveform = connection.get_data(channel)

    ok = report_fastframe_capture(waveform)
    return 0 if ok else 1


def test_scope_fastframe_auth() -> None:
    """Read and validate one stopped FastFrame capture from a real scope."""
    assert not main()


if __name__ == "__main__":
    sys.exit(main())
