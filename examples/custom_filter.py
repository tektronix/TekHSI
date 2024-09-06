"""An example script to connect to a scope, apply a custom filter to waveform data, and save to files."""

from tekhsi import TekHSIConnect, WaveformHeader
from tm_data_types import AnalogWaveform, write_file
from typing import Dict, List

addr = "192.168.0.1"  # Replace with the IP address of your instrument


def custom_filter(prevheader: Dict[WaveformHeader], currentheader: List[WaveformHeader]):
    """A custom criterion for deciding when to consider an acquisition for acceptance."""
    for key, cur in currentheader.items():
        if key not in prevheader:
            return True
        prev = prevheader[key]
        if prev is not None and (
            prev.verticalspacing != cur.verticalspacing
            or prev.horizontalspacing != cur.horizontalspacing
        ):
            return True
    return False


# Connect to instrument, select channel 1
with TekHSIConnect(f"{addr}:5000", ["ch1"]) as connect:
    connect.instrumentation_enabled = True

    connect.set_acq_filter(custom_filter)

    for i in range(10):
        connect.wait_for_data()
        wfm: AnalogWaveform = connect.get_data("ch1")
        connect.done_with_data()

        # Do something with the waveform
        write_file(f"{wfm.source_name}_{i}.csv", wfm)
