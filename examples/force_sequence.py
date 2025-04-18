"""A script demonstrating a way to use force_sequence to save a wfm locally"""

from tm_data_types import AnalogWaveform, write_file
from tekhsi import TekHSIConnect

addr = "192.168.0.1"  # Replace with the IP address of your instrument

# Connect to instrument
with TekHSIConnect(f"{addr}:5000") as connect:
    # Save a single acquisition that was made prior to connecting
        connect.force_sequence()
        with connect.access_data():
            wfm: AnalogWaveform = connect.get_data("ch1")
        
        # Save the waveform to a file
        write_file(f"{wfm.source_name}.csv", wfm)
