from tm_data_types import AnalogWaveform

from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    # Request access to data
    with connection.access_data():
        # Access granted
        ch1: AnalogWaveform = connection.get_data("ch1")
        ch3: AnalogWaveform = connection.get_data("ch3")
