import matplotlib.pyplot as plt
import numpy as np

from tm_data_types import DigitalWaveform

from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    # Get one data set to setup plot
    with connection.access_data():
        waveform: DigitalWaveform = connection.get_data("ch4_DAll")

    # Digital retrieval of bit 3 in the digital array
    vd = waveform.get_nth_bitstream(3).astype(np.float32)

    # Horizontal Times - returns an array of times
    # that corresponds to the time at each index in
    # vertical array
    hd = waveform.normalized_horizontal_values

    # Simple Plot Example
    _, ax = plt.subplots()
    ax.plot(hd, vd)
    ax.set(xlabel=waveform.x_axis_units, ylabel=waveform.y_axis_units, title="Simple Plot")
    plt.show()
