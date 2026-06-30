"""An example script for connecting to a scope, retrieving waveform data from multiple channels, and plotting it."""

import matplotlib.pyplot as plt

from tm_data_types import AnalogWaveform

from tekhsi import AcqWaitOn, TekHSIConnect

address = "192.168.0.1"  # Replace with the IP address of your instrument

# Open connection to the instrument
with TekHSIConnect(f"{address}:5000", ["ch1", "ch3"]) as connection:
    # Request access to data, waiting for new data
    with connection.access_data(AcqWaitOn.NewData):
        ch1: AnalogWaveform = connection.get_data("ch1")
        ch3: AnalogWaveform = connection.get_data("ch3")

# Define a Plot. This works best if the channels are not too large.
fig, subplot = plt.subplots(2)

# Note that channels return None if they are turned off
if ch1 is not None:
    subplot[0].set_title(ch1.source_name)
    subplot[0].plot(ch1.normalized_horizontal_values, ch1.normalized_vertical_values)

if ch3 is not None:
    subplot[1].set_title(ch3.source_name)
    subplot[1].plot(ch3.normalized_horizontal_values, ch3.normalized_vertical_values)

# Display the Plot
plt.show()
