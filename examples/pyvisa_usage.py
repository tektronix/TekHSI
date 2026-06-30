"""Command & control using PyVISA, but retrieving waveform data using TekHSI."""

import pyvisa

from tm_data_types import AnalogWaveform

from tekhsi import AcqWaitOn, TekHSIConnect

addr = "192.168.0.1"  # Replace with the IP address of your instrument

rm = pyvisa.ResourceManager("@py")

# write command to instrument sample using pyvisa
visa_scope = rm.open_resource(f"TCPIP0::{addr}::INSTR")

sample_query = visa_scope.query("*IDN?")
print(sample_query)
# Make the waveform display OFF
visa_scope.write("DISplay:WAVEform OFF")
# Set the Horizontal mode to Manual
visa_scope.write("HOR:MODE MAN")
# Set the horizontal Record Length
visa_scope.write("HOR:MODE:RECO 2500")

# time.sleep(2) # Optional delay
# Connect to instrument via TekHSI, select channel 1
with TekHSIConnect(f"{addr}:5000", ["ch1"]) as connect:
    # Save data from 10 acquisitions
    for i in range(10):
        with connect.access_data(AcqWaitOn.NextAcq):
            waveform: AnalogWaveform = connect.get_data("ch1")
            print(f"{waveform.source_name}_{i}:{waveform.record_length}")

visa_scope.write("DISplay:WAVEform ON")

# close visa connection
visa_scope.close()
