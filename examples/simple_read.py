"""An example script for demonstrating reading waveform files and plotting the data."""

from tm_data_types import read_file, AnalogWaveform, IQWaveform, DigitalWaveform
import matplotlib.pyplot as plt
import numpy as np

# Read the waveform file
file = read_file("sample_waveforms/test_sine.wfm")

y_axis = ""

# Check the type of waveform and extract data accordingly
if isinstance(file, AnalogWaveform):
    waveform: AnalogWaveform = file
    vertical_data = waveform.normalized_vertical_values
    y_axis = waveform.y_axis_units
elif isinstance(file, IQWaveform):
    waveform: IQWaveform = file
    vertical_data = waveform.normalized_vertical_values.real
    y_axis = waveform.iq_axis_units
elif isinstance(file, DigitalWaveform):
    waveform: DigitalWaveform = file
    vertical_data = waveform.get_nth_bitstream(3).astype(np.float32)
else:
    raise TypeError("Unsupported waveform type")

horizontal_data = waveform.normalized_horizontal_values
min_val = np.min(vertical_data)
max_val = np.max(vertical_data)
# Add 5% of amplitude boundary to top/bottom of plot
extra = (max_val - min_val) * 0.05

# Set up the plot
fig, ax = plt.subplots()

# Add Title & Labels to plot
plt.title(f"{waveform.source_name}")
plt.xlabel(f"{waveform.x_axis_units}")
plt.ylabel(f"{y_axis}")

ax.set_ylim(min_val - extra, max_val + extra)
ax.set_xlim(np.min(horizontal_data), np.max(horizontal_data))
(line,) = ax.plot(horizontal_data, vertical_data)

# Display the plot
plt.show()
