"""An example script for creating a sine waveform and saving it to a file."""

import math

import numpy as np

from tm_data_types import AnalogWaveform, write_file

length = 1000  # Record length of the waveform
frequency = 40.0e-10  # Frequency of the sinewave
cycles = 10  # Number of cycles of the sinewave in the waveform
amplitude = 1  # Amplitude of the waveform
offset = 0  # Offset of the waveform in vertical units (probably volts)

waveform = AnalogWaveform()
waveform.source_name = "sinwave_test"
waveform.x_axis_spacing = (1 / frequency) * cycles / length
waveform.trigger_index = 0
waveform.y_axis_offset = offset

x_points = np.zeros(length, dtype=np.float32)
for i in range(length):
    x_points[i] = math.sin((i / (length / cycles)) * 2 * math.pi) * amplitude / 2.0
waveform.y_axis_values = x_points

# List comprehension way of creating data
# waveform.y_axis_values = np.array([math.sin((i/(length/cycles))*2*math.pi)*amplitude/2.0 for i in range(length)])

# Numpy vector approach to creating the data (much faster) - both np.float32 and np.float64 work but np.float32 is
# recommended.
# x_points = np.linspace(0, cycles, length, dtype=np.float32)
# waveform.y_axis_values = np.sin(2 * np.pi
# * x_points) * amplitude / 2.0

write_file("sample_waveforms/test_sine.wfm", waveform)
