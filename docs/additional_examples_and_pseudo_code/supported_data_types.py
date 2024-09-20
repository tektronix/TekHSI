import numpy as np

from tm_data_types import AnalogWaveform, DigitalWaveform, IQWaveform, read_file

data = read_file("Test.wfm")

# currently wfm files can be of three flavors
# AnalogWaveform, IQWaveform, or DigitalWaveform
# each can be explicitly checked for as follows.
if isinstance(data, AnalogWaveform):
    wfm: AnalogWaveform = data
    # returns the sampled values in vertical units
    vd = wfm.normalized_vertical_values
    y_axis = wfm.y_axis_units
elif isinstance(data, IQWaveform):
    wfm: IQWaveform = data
    # Returns the real portion of the iq data for plotting.
    # Note that 'normalized_vertical_values' is a complex array.
    vd = wfm.normalized_vertical_values.real
    y_axis = wfm.y_axis_units
elif isinstance(data, DigitalWaveform):
    wfm: DigitalWaveform = data
    # Returns bit 3 as a float stream for plotting.
    vd = wfm.get_nth_bitstream(3).astype(np.float32)
