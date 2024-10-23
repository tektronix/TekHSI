import os
import subprocess
import sys
import time

from abc import ABC
from io import StringIO
from pathlib import Path
from typing import List

import grpc
import psutil
import pytest

from tm_data_types import Waveform

from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.tek_hsi_connect import TekHSIConnect

from server.tekhsi_test_server import TEST_SERVER_ADDRESS, TEST_SERVER_PORT_NUMBER

PROJECT_ROOT_DIR = Path(__file__).parent.parent


class DerivedWaveform(Waveform, ABC):
    @property
    def _measured_data(self):
        """Implement the abstract method."""
        return "measured data"


class DerivedWaveformHandler:  # pylint: disable=too-few-public-methods
    @staticmethod
    def data_arrival(waveforms: List[DerivedWaveform]):
        """Override the data_arrival method to process waveforms."""
        for _ in waveforms:
            print("Processing waveform")


class TestServerManager:
    def __init__(self, port=TEST_SERVER_PORT_NUMBER):
        """Initialize the TestServerManager with a specified port."""
        self.server_process = None
        self.port = port

    def is_port_in_use(self):
        """Check if the port is currently in use."""
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                for conn in proc.connections(kind="inet"):
                    if conn.laddr.port == self.port:
                        return proc.pid
            except (psutil.AccessDenied, psutil.NoSuchProcess):  # noqa: PERF203
                continue
        return None

    def kill_process_on_port(self):
        """Kill the process using the specified port."""
        if pid := self.is_port_in_use():
            print(f"Killing process {pid} using port {self.port}")
            psutil.Process(pid).terminate()

    def __enter__(self):
        """Start the dummy server and ensure the port is free."""
        self.kill_process_on_port()  # Ensure the port is free before starting the server

        # Ensure the script path is correct
        server_script = os.path.join(os.path.dirname(__file__), "server", "tekhsi_test_server.py")
        if not os.path.exists(server_script):
            raise RuntimeError("Server script not found.")

            # Start the server
        self.server_process = subprocess.Popen([sys.executable, server_script, "--verbose"])  # noqa: S603
        # Wait a few seconds for the server to start
        time.sleep(5)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Terminate the dummy server process."""
        if self.server_process:
            self.server_process.terminate()
            self.server_process.wait()


@pytest.fixture
def capture_stdout():
    """Fixture to capture the standard output."""
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    yield mystdout
    sys.stdout = old_stdout


@pytest.fixture
def derived_waveform_handler():
    """Fixture to create an instance of DerivedWaveformHandler.

    Returns:
        DerivedWaveformHandler: An instance of the DerivedWaveformHandler.
    """
    return DerivedWaveformHandler()


@pytest.fixture
def expected_header():
    """Fixture to provide a sample waveform header.

    Returns:
        dict: A dictionary representing a waveform header.
    """
    return {
        "dataid": 1,
        "hasdata": True,
        "horizontalspacing": 1e-05,
        "horizontalUnits": "S",
        "horizontalzeroindex": 500,
        "noofsamples": 1000,
        "sourcename": "ch1",
        "sourcewidth": 1,
        "wfmtype": 1,
        "pairtype": 1,
        "verticaloffset": 0,
        "verticalspacing": 0.0043478260869565218,
        "verticalunits": "V",
    }


@pytest.fixture
def grpc_channel():  # pylint: disable=useless-suppression
    """Create a gRPC channel to the test server."""
    channel = grpc.insecure_channel(TEST_SERVER_ADDRESS)
    yield channel
    channel.close()


@pytest.fixture
def grpc_stub(grpc_channel):  # pylint: disable=redefined-outer-name
    """Create a gRPC stub for the Connect service."""
    return ConnectStub(grpc_channel)


@pytest.fixture(scope="session", autouse=True)
def start_test_server():
    """Start the test server for the test session."""
    with TestServerManager():
        yield


@pytest.fixture
def tekhsi_client():
    """Create a TekHSIConnect client."""
    return TekHSIConnect(TEST_SERVER_ADDRESS)
