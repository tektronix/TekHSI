"""An example script for connecting to a Tek instrument, retrieving IQ waveform data, and plotting it."""

from tekhsi import TekHSIConnect, AcqWaitOn
from tm_data_types import IQWaveform
import matplotlib.pyplot as plt
import numpy as np

source = "ch1_iq"
address = "192.168.0.1"  # Replace with the IP address of your instrument
decimate_count = 150

with TekHSIConnect(f"{address}:5000", [source]) as connection:
    # connection.instrumentation_enabled = True
    # Get one data set to setup plot
    with connection.access_data(AcqWaitOn.AnyAcq):
        waveform: IQWaveform = connection.get_data(source)

    iq_data = waveform.normalized_vertical_values
    i_data = waveform.normalized_vertical_values.imag
    q_data = waveform.normalized_vertical_values.real
    h_data = waveform.normalized_horizontal_values

    decimate = int(len(i_data) / decimate_count)

    fig = plt.figure()
    ax0 = fig.add_subplot(221)
    ax1 = fig.add_subplot(223)
    ax2 = fig.add_subplot(122, projection="3d")

    # print(waveform.metadata)

    ax0.psd(
        iq_data,
        NFFT=int(waveform.meta_info.iq_fft_length),
        Fc=waveform.meta_info.iq_center_frequency,
        Fs=waveform.meta_info.iq_sample_rate,
    )
    ax0.set_title("PSD")

    ax1.specgram(
        iq_data,
        NFFT=int(waveform.meta_info.iq_fft_length),
        Fc=waveform.meta_info.iq_center_frequency,
        Fs=waveform.meta_info.iq_sample_rate,
    )
    ax1.set_title("Spectrogram")

    ax2.scatter(h_data[::decimate], i_data[::decimate], q_data[::decimate], marker="+")
    ax2.set_title("IQ")
    ax2.set_xlabel("Time")
    ax2.set_ylabel("I")
    ax2.set_zlabel("Q")
    ax2.set_ylim(-1, 1)
    ax2.set_zlim(-1, 1)

    plt.show(block=False)

    # loop until user closes plot
    while plt.get_fignums() is not None and len(plt.get_fignums()) > 0:
        # Wait for next new data set
        with connection.access_data():
            waveform: IQWaveform = connection.get_data(source)

        iq_data = waveform.normalized_vertical_values
        i_data = np.real(iq_data)
        q_data = np.imag(iq_data)
        h_data = np.real(waveform.normalized_horizontal_values)
        decimate = int(len(i_data) / decimate_count)

        # plot newly arrived data
        ax0.clear()
        ax1.clear()
        ax2.clear()
        ax0.psd(
            iq_data,
            NFFT=int(waveform.meta_info.iq_fft_length),
            Fc=waveform.meta_info.iq_center_frequency,
            Fs=waveform.meta_info.iq_sample_rate,
        )
        ax0.set_title("PSD")
        ax1.specgram(
            iq_data,
            NFFT=int(waveform.meta_info.iq_fft_length),
            Fc=waveform.meta_info.iq_center_frequency,
            Fs=waveform.meta_info.iq_sample_rate,
        )
        ax1.set_title("Spectrogram")
        ax2.scatter(h_data[::decimate], i_data[::decimate], q_data[::decimate], marker="+")
        ax2.set_title("IQ")
        ax2.set_xlabel("Time")
        ax2.set_ylabel("I")
        ax2.set_zlabel("Q")
        ax2.set_ylim(-1, 1)
        ax2.set_zlim(-1, 1)
        fig.canvas.draw()
        fig.canvas.flush_events()
