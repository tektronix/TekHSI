"""Use TekHSI to read a stopped FastFrame capture from the scope."""

import os

from tekhsi import TekHSIConnect
from tekhsi.credential_store import CertInfo, TekHSICredentialStore
from tm_data_types import FastFrameAnalogWaveform


def auto_trust(
    _host: str,
    _cert_info: CertInfo,
    auth_required: bool = False,  # noqa: FBT001, FBT002
) -> bool | tuple[bool, str, str]:
    """Accept the scope certificate (set TEKHSI_PASSWORD if auth is required)."""
    if auth_required:
        if not (password := os.environ.get("TEKHSI_PASSWORD")):
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "Tektronix")
    return True


addr = "192.168.0.1:5000"  # Replace with your instrument TekHSI address

with TekHSIConnect(
    addr,
    activesymbols=["ch1"],
    on_trust_prompt=auto_trust,
    credential_store=TekHSICredentialStore(),
) as connection:
    # FastFrame captures on a stopped scope require force_sequence + AnyAcq.
    with connection.access_stopped_data():
        waveform = connection.get_data("ch1")

if waveform is None:
    message = "No waveform returned for ch1"
    raise RuntimeError(message)

if not isinstance(waveform, FastFrameAnalogWaveform):
    print(f"Expected FastFrameAnalogWaveform, got {type(waveform).__name__}")
else:
    print(f"source={waveform.source_name}")
    print(f"record_length={waveform.record_length}")
    print(f"data_frames={waveform.data_frame_count}, total_frames={waveform.num_frames}")
    print(f"current_frame={waveform.current_frame_index}")
    print(f"summary_frame={waveform.summary_frame_index}")

    # Raw digitizer codes (no normalization). Use frame_array() for volts.
    frame0 = waveform.frame_data(0)
    print(f"frame 0: {len(frame0)} samples, raw[0]={int(frame0[0])}")

    if waveform.get_summary_frame() is not None:
        summary_samples = waveform.frame_data(waveform.summary_frame_index)
        print(f"summary frame: raw[0]={int(summary_samples[0])}")
    else:
        print("summary frame: not present (disabled on scope or not declared in header)")

    if waveform.load_timing is not None:
        print(waveform.load_timing.format_summary())
