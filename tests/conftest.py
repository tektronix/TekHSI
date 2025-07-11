"""Pytest configuration."""

import logging
import subprocess
import sys
import time

from abc import ABC
from collections.abc import Generator
from io import StringIO
from pathlib import Path
from types import TracebackType
from typing import Dict, List, Optional, Type, Union

import grpc
import psutil
import pytest

from grpc import Channel
from tm_data_types import Waveform
from typing_extensions import Self

from tekhsi import configure_logging, LoggingLevels
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.tek_hsi_connect import TekHSIConnect

from server.tekhsi_test_server import TEST_SERVER_ADDRESS, TEST_SERVER_PORT_NUMBER

PROJECT_ROOT_DIR = Path(__file__).parent.parent


####################################################################################################
# Configure the logging for the package that will run during unit tests
class _DynamicStreamHandler(logging.StreamHandler):  # pyright: ignore[reportMissingTypeArgument]
    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


_logger = configure_logging(
    log_console_level=LoggingLevels.NONE,
    log_file_level=LoggingLevels.DEBUG,
    log_file_directory=Path(__file__).parent / "logs",
    log_file_name=f"unit_test_py{sys.version_info.major}{sys.version_info.minor}.log",
)
_unit_test_console_handler = _DynamicStreamHandler(stream=sys.stdout)
_unit_test_console_handler.setLevel(logging.DEBUG)
_unit_test_console_formatter = logging.Formatter("%(asctime)s - %(message)s")
_unit_test_console_formatter.default_msec_format = (
    "%s.%06d"  # Use 6 digits of precision for milliseconds
)
_unit_test_console_handler.setFormatter(_unit_test_console_formatter)
_logger.addHandler(_unit_test_console_handler)
####################################################################################################


class DerivedWaveform(Waveform, ABC):
    """A derived waveform class for testing purposes."""

    @property
    def _measured_data(self) -> str:
        """Implement the abstract method."""
        return "measured data"


class DerivedWaveformHandler:  # pylint: disable=too-few-public-methods
    """A derived waveform handler class for testing purposes."""

    @staticmethod
    def data_arrival(waveforms: List[DerivedWaveform]) -> None:
        """Override the data_arrival method to process waveforms."""
        for _ in waveforms:
            print("Processing waveform")


class TestServerManager:
    """A class to manage the test server process."""

    def __init__(self, port: int = TEST_SERVER_PORT_NUMBER) -> None:
        """Initialize the TestServerManager with a specified port."""
        self.server_process = None
        self.port = port

    def is_port_in_use(self) -> Optional[int]:
        """Check if the port is currently in use."""
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                for conn in proc.connections(kind="inet"):
                    if conn.laddr.port == self.port:
                        return proc.pid
            except (psutil.AccessDenied, psutil.NoSuchProcess):  # noqa: PERF203
                continue
        return None

    def kill_process_on_port(self) -> None:
        """Kill the process using the specified port."""
        if pid := self.is_port_in_use():
            print(f"Killing process {pid} using port {self.port}")
            psutil.Process(pid).terminate()

    def __enter__(self) -> Self:
        """Start the dummy server and ensure the port is free."""
        self.kill_process_on_port()  # Ensure the port is free before starting the server

        # Ensure the script path is correct
        server_script = Path(__file__).parent / "server" / "tekhsi_test_server.py"
        if not server_script.exists():
            msg = "Server script not found."
            raise RuntimeError(msg)

            # Start the server
        self.server_process = subprocess.Popen(  # noqa: S603
            [sys.executable, server_script.as_posix(), "--verbose"]
        )
        # Wait a few seconds for the server to start
        time.sleep(5)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Terminate the dummy server process."""
        if self.server_process:
            self.server_process.terminate()
            self.server_process.wait()


@pytest.fixture
def capture_stdout() -> StringIO:
    """Fixture to capture the standard output."""
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    yield mystdout
    sys.stdout = old_stdout


@pytest.fixture
def derived_waveform_handler() -> DerivedWaveformHandler:
    """Fixture to create an instance of DerivedWaveformHandler.

    Returns:
        DerivedWaveformHandler: An instance of the DerivedWaveformHandler.
    """
    return DerivedWaveformHandler()


@pytest.fixture
def expected_header() -> Dict[str, Union[int, bool, float, str]]:
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
def grpc_channel() -> Channel:  # pylint: disable=useless-suppression
    """Create a gRPC channel to the test server."""
    channel = grpc.insecure_channel(TEST_SERVER_ADDRESS)
    yield channel
    channel.close()


@pytest.fixture
def grpc_stub(grpc_channel: Channel) -> ConnectStub:  # pylint: disable=redefined-outer-name
    """Create a gRPC stub for the Connect service."""
    return ConnectStub(grpc_channel)


@pytest.fixture(scope="session", autouse=True)
def start_test_server() -> Generator[None, None, None]:
    """Start the test server for the test session."""
    with TestServerManager():
        yield


@pytest.fixture
def tekhsi_client() -> TekHSIConnect:
    """Create a TekHSIConnect client."""
    return TekHSIConnect(TEST_SERVER_ADDRESS)
