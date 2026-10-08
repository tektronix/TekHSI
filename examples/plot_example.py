"""An example script for connecting to a scope, retrieving waveform data, and plotting it."""

import matplotlib.pyplot as plt
import numpy as np

from tm_data_types import AnalogWaveform

from tekhsi import AcqWaitOn, TekHSIConnect

source = "ch1"
address = "192.168.0.1"  # Replace with the IP address of your instrument

with TekHSIConnect(f"{address}:5000", [source]) as connection:
    # Get one data set to set up plot
    with connection.access_data(AcqWaitOn.NewData):
        waveform: AnalogWaveform = connection.get_data(source)

    # Get data from data set need to setup plot
    horizontal_data = waveform.normalized_horizontal_values
    vertical_data = waveform.normalized_vertical_values

    min_val = np.min(vertical_data)
    max_val = np.max(vertical_data)

    # Add 5% of amplitude boundary to top/bottom of plot
    extra = (max_val - min_val) * 0.05

    # Set up the plot
    fig, ax = plt.subplots()

    # Add Title & Labels to plot
    plt.title(f"{source}")
    plt.xlabel(f"{waveform.x_axis_units}")
    plt.ylabel(f"{waveform.y_axis_units}")

    ax.set_ylim(min_val - extra, max_val + extra)
    ax.set_xlim(np.min(horizontal_data), np.max(horizontal_data))
    (line,) = ax.plot(horizontal_data, vertical_data)

    # Display the plot
    plt.show(block=False)

    # loop until user closes plot
    while plt.get_fignums() is not None and len(plt.get_fignums()) > 0:
        # Wait for next new data set
        with connection.access_data(AcqWaitOn.NextAcq):
            waveform = connection.get_data(source)

        # plot newly arrived data
        line.set_ydata(waveform.normalized_vertical_values)
        fig.canvas.draw()
        fig.canvas.flush_events()
