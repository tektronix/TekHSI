"""A script for connecting to a scope, retrieving waveform data, and saving it to a file."""

from tm_data_types import AnalogWaveform, write_file

from tekhsi import AcqWaitOn, TekHSIConnect

addr = "192.168.0.1"  # Replace with the IP address of your instrument

# Connect to instrument, select channel 1
with TekHSIConnect(f"{addr}:5000", ["ch1"]) as connect:
    # Save data from 10 acquisitions as a set of CSV files
    for i in range(10):
        # Use AcqWaitOn.NextAcq to wait for the next new acquisition
        with connect.access_data(AcqWaitOn.NextAcq):
            wfm: AnalogWaveform = connect.get_data("ch1")

        # Save the waveform to a file
        write_file(f"{wfm.source_name}_{i}.csv", wfm)
