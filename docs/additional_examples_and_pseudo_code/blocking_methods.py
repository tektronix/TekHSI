from tm_data_types import AnalogWaveform, DigitalWaveform, IQWaveform

from tekhsi import AcqWaitOn, TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    with connection.access_data(AcqWaitOn.NewData):
        ch1: AnalogWaveform = connection.get_data("ch1")
        ch3: AnalogWaveform = connection.get_data("ch3")
        ch1_iq: IQWaveform = connection.get_data("ch1_iq")
        ch4_dall: DigitalWaveform = connection.get_data("ch4_DAll")
