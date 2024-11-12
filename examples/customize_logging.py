"""A script demonstrating how to customize the logging that happens during runtime."""

from tm_data_types import AnalogWaveform, write_file

from tekhsi import configure_logging, LoggingLevels, TekHSIConnect

addr = "192.168.0.1"  # Replace with the IP address of your instrument

configure_logging(
    log_console_level=LoggingLevels.NONE,  # completely disable console logging
    log_file_level=LoggingLevels.DEBUG,  # log everything to the file
    log_file_directory="./log_files",  # save the log file in the "./log_files" directory
    log_file_name="custom_log_filename.log",  # customize the filename
)

# Connect to instrument, select channel 1
with TekHSIConnect(f"{addr}:5000", ["ch1"]) as connect:
    # Save data from 10 acquisitions as a set of CSV files
    for i in range(10):
        with connect.access_data():
            wfm: AnalogWaveform = connect.get_data("ch1")

        # Save the waveform to a file
        write_file(f"{wfm.source_name}_{i}.csv", wfm)
