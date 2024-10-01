"""Command & control using tm_devices, but retrieving waveform data using TekHSI."""

from tm_data_types import AnalogWaveform
from tm_devices import DeviceManager
from tm_devices.drivers import MSO6B

from tekhsi import TekHSIConnect

addr = "192.168.0.1"  # Replace with the IP address of your instrument

with DeviceManager(verbose=True) as device_manager:
    scope: MSO6B = device_manager.add_scope(f"{addr}")
    idn_response = scope.commands.idn.query()
    print(idn_response)
    # Make the waveform display OFF
    scope.commands.display.waveform.write("OFF")
    # Set the Horizontal mode to Manual
    scope.commands.horizontal.mode.write("OFF")
    # Set the horizontal Record Length
    scope.commands.horizontal.mode.recordlength.write("2500")

    # time.sleep(2) # Optional delay
    # Connect to instrument via TekHSI, select channel 1
    with TekHSIConnect(f"{scope.ip_address}:5000", ["ch1"]) as connect:
        # Save data from 10 acquisitions
        for i in range(10):
            with connect.access_data():
                waveform: AnalogWaveform = connect.get_data("ch1")
                print(f"{waveform.source_name}_{i}:{waveform.record_length}")

    # Make the waveform display ON
    scope.commands.display.waveform.write("ON")
