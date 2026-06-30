"""Use TekHSI to plot an analog waveform."""

import matplotlib.pyplot as plt

from tm_data_types import AnalogWaveform

from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    # Get one data set to setup plot
    with connection.access_data():
        waveform: AnalogWaveform = connection.get_data("ch1")

    # Data converted into vertical units
    # This is the usual way to access the data
    vd = waveform.normalized_vertical_values

    # Horizontal Times - returns an array of times
    # that corresponds to the time at each index in
    # vertical array
    hd = waveform.normalized_horizontal_values

    # Simple Plot Example
    _, ax = plt.subplots()
    ax.plot(hd, vd)
    ax.set(xlabel=waveform.x_axis_units, ylabel=waveform.y_axis_units, title="Simple Plot")
    plt.show()
