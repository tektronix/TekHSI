"""Use TekHSI to plot an IQ waveform."""

import matplotlib.pyplot as plt

from tm_data_types import IQWaveform

from tekhsi import TekHSIConnect

with TekHSIConnect("169.254.3.12:5000") as connection:
    # Get one data set to setup plot
    with connection.access_data():
        waveform: IQWaveform = connection.get_data("ch1_iq")

    # IQ Data Access (Complex Array)
    iq_data = waveform.normalized_vertical_values

    # Simple Plot Example
    _, ax = plt.subplots()
    ax.specgram(
        iq_data,
        NFFT=int(waveform.meta_info.iq_fft_length),
        Fc=waveform.meta_info.iq_center_frequency,
        Fs=waveform.meta_info.iq_sample_rate,
    )
    ax.set_title("Spectrogram")
    plt.show()
