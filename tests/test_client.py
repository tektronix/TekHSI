"""Unit tests for the TekHSI client functionality."""

import logging
import sys

from collections.abc import Callable
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tm_data_types import AnalogWaveform, DigitalWaveform, IQWaveform, Waveform

from conftest import DerivedWaveform, DerivedWaveformHandler
from tekhsi._tek_highspeed_server_pb2 import (  # pylint: disable=no-name-in-module
    WaveformHeader,
    WfmType,
)
from tekhsi.tek_hsi_connect import AcqWaitOn, TekHSIConnect


@pytest.mark.parametrize(
    ("instrument", "sum_count", "sum_acq_time", "sum_data_rate", "expected_output"),
    [
        (True, 5, 10.0, 50.0, "Average Update Rate:0.50, Data Rate:10.00Mbs"),
    ],
)
def test_server_connection(  # noqa: PLR0913
    tekhsi_client: TekHSIConnect,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    instrument: bool,
    sum_count: int,
    sum_acq_time: float,
    sum_data_rate: float,
    expected_output: str,
) -> None:
    """Test the server connection using the TekHSI client.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        capsys (CaptureFixture): Pytest fixture to capture system output.
        caplog (LogCaptureFixture): Pytest fixture to capture log output.
        instrument: Whether the instrument is connected.
        sum_count: The sum count.
        sum_acq_time: The sum acquisition time.
        sum_data_rate: The sum data rate.
        expected_output: The expected output message.
    """
    # Set the required attributes
    tekhsi_client._instrument = instrument
    tekhsi_client._sum_count = sum_count
    tekhsi_client._sum_acq_time = sum_acq_time
    tekhsi_client._sum_data_rate = sum_data_rate

    tekhsi_client.verbose = True
    with caplog.at_level(logging.DEBUG), tekhsi_client as connection:
        assert "enter()" in caplog.text
        # Check connection success by internal state
        assert getattr(connection, "_connected", False) is True

    captured = capsys.readouterr()

    # Verify the printed output
    assert expected_output in captured.out


@pytest.mark.parametrize(
    ("previous_header", "current_header", "expected"),
    [
        ({}, {}, True),  # Always returns True
    ],
)
def test_any_acq(
    previous_header: dict[str, WaveformHeader],
    current_header: dict[str, WaveformHeader],
    expected: bool,
) -> None:
    """Test the any_acq method of TekHSIConnect.

    Args:
        previous_header (dict): The previous header data.
        current_header (dict): The current header data.
        expected: The expected result of the any_acq method.
    """
    result = TekHSIConnect.any_acq(previous_header, current_header)
    assert result == expected


@pytest.mark.parametrize(
    ("previous_header", "current_header", "expected"),
    [
        # No changes
        (
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 1000, "horizontalspacing": 0.1, "horizontalzeroindex": 500},
                ),
            },
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 1000, "horizontalspacing": 0.1, "horizontalzeroindex": 500},
                ),
            },
            False,
        ),
        # Changes in header values
        (
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 1000, "horizontalspacing": 0.1, "horizontalzeroindex": 500},
                ),
            },
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 2000, "horizontalspacing": 0.2, "horizontalzeroindex": 1000},
                ),
            },
            True,
        ),
        # New key added to current header
        (
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 1000, "horizontalspacing": 0.1, "horizontalzeroindex": 500},
                ),
            },
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 1000, "horizontalspacing": 0.1, "horizontalzeroindex": 500},
                ),
                "ch2": type(
                    "Header",
                    (object,),
                    {"noofsamples": 2000, "horizontalspacing": 0.2, "horizontalzeroindex": 1000},
                ),
            },
            True,
        ),
        # Value changes from None to a valid header
        (
            {
                "ch1": None,
            },
            {
                "ch1": type(
                    "Header",
                    (object,),
                    {"noofsamples": 2000, "horizontalspacing": 0.2, "horizontalzeroindex": 1000},
                ),
            },
            True,
        ),
    ],
)
def test_any_horizontal_change(
    previous_header: dict[str, WaveformHeader],
    current_header: dict[str, WaveformHeader],
    expected: bool,
) -> None:
    """Test the any_horizontal_change method of TekHSIConnect.

    Args:
        previous_header (dict): The previous header data.
        current_header (dict): The current header data.
        expected: The expected result of the any_horizontal_change method.
    """
    result = TekHSIConnect.any_horizontal_change(previous_header, current_header)
    assert result == expected


@pytest.mark.parametrize(
    ("previous_header", "current_header", "expected"),
    [
        # No changes
        (
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 5}),
            },
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 5}),
            },
            False,
        ),
        # Changes in vertical spacing
        (
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 5}),
            },
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.2, "verticaloffset": 5}),
            },
            True,
        ),
        # Changes in vertical offset
        (
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 5}),
            },
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 10}),
            },
            True,
        ),
        # New key added to current header
        (
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 5}),
            },
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.1, "verticaloffset": 5}),
                "ch2": type("Header", (object,), {"verticalspacing": 0.2, "verticaloffset": 10}),
            },
            True,
        ),
        # Previous header has None
        (
            {
                "ch1": None,
            },
            {
                "ch1": type("Header", (object,), {"verticalspacing": 0.2, "verticaloffset": 10}),
            },
            True,
        ),
    ],
)
def test_any_vertical_change(
    previous_header: dict[str, WaveformHeader],
    current_header: dict[str, WaveformHeader],
    expected: bool,
) -> None:
    """Test the any_vertical_change method of TekHSIConnect.

    Args:
        previous_header (dict): The previous header data.
        current_header (dict): The current header data.
        expected: The expected result of the any_vertical_change method.
    """
    result = TekHSIConnect.any_vertical_change(previous_header, current_header)
    assert result == expected


@pytest.mark.parametrize(
    ("acq_filter", "expected_exception", "expected_message"),
    [
        ({"name": "TestFilter"}, None, None),
        (None, ValueError, "Filter cannot be None"),
    ],
)
def test_set_acq_filter(
    tekhsi_client: TekHSIConnect,
    acq_filter: Callable,
    expected_exception: type[BaseException],
    expected_message: str,
) -> None:
    """Test the set_acq_filter method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        acq_filter (dict): The acquisition filter to be set.
        expected_exception (Exception): The expected exception to be raised, if any.
        expected_message: The expected exception message, if any.
    """
    with tekhsi_client as connection:
        if expected_exception:
            with pytest.raises(expected_exception, match=expected_message):
                connection.set_acq_filter(acq_filter)
        else:
            connection.set_acq_filter(acq_filter)
            # Verify that the filter is set correctly
            assert connection._filter == acq_filter
            # Verify that the acquisition count is updated
            assert connection._lastacqseen == connection._acqcount


@pytest.mark.parametrize(
    ("cache_enabled", "data_cache", "name", "expected_result"),
    [
        (True, {"test_data": "waveform_data"}, "test_data", "waveform_data"),  # Valid case
        (True, {"test_data": "waveform_data"}, "nonexistent_data", None),  # Data not found
        (False, {"test_data": "waveform_data"}, "test_data", None),  # Caching disabled
    ],
)
def test_get_data(
    tekhsi_client: TekHSIConnect,
    cache_enabled: bool,
    data_cache: dict[str, str],
    name: str,
    expected_result: str | None,
) -> None:
    """Test the get_data method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        cache_enabled: Whether the data cache is enabled.
        data_cache (dict): The data cache to be used.
        name: The name of the data to retrieve.
        expected_result (Any): The expected result of the get_data method.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._datacache = data_cache

        # Call the method
        result = connection.get_data(name)

        # Verify the result
        assert result == expected_result


@pytest.mark.parametrize(
    (
        "cache_enabled",
        "wait_for_data_count",
        "acqcount",
        "expected_wait_for_data_count",
        "expected_lastacqseen",
        "expected_output",
        "verbose",
    ),
    [
        (True, 1, 5, 0, 5, None, True),  # Valid case: Cache enabled and data count decrement
        (True, 0, 5, 0, 0, "done_with_data called when no wait_for_data pending", True),
        (False, 1, 5, 1, 0, None, True),  # Caching disabled
        (True, -1, 5, -1, 0, "done_with_data called when no wait_for_data pending", True),
        (True, 2, 5, 1, 5, None, True),  # wait_for_data_count greater than 1
        (True, 0, 5, 0, 0, None, False),  # No wait_for_data pending, verbose is False
    ],
)
def test_done_with_data(  # noqa: PLR0913
    tekhsi_client: TekHSIConnect,
    cache_enabled: bool,
    wait_for_data_count: int,
    acqcount: int,
    expected_wait_for_data_count: int,
    expected_lastacqseen: int,
    expected_output: str | None,
    verbose: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the done_with_data method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        cache_enabled: Whether the data cache is enabled.
        wait_for_data_count: The initial wait_for_data_count value.
        acqcount: The initial acquisition count.
        expected_wait_for_data_count: The expected wait_for_data_count after the method call.
        expected_lastacqseen: The expected last acquisition seen after the method call.
        expected_output: The expected output message, if any.
        verbose: Whether verbose mode is enabled.
        caplog: Pytest fixture to capture log messages.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._wait_for_data_count = wait_for_data_count
        connection._acqcount = acqcount
        connection.verbose = verbose

        # Call the method
        connection.done_with_data()

        # Verify the internal state
        assert connection._wait_for_data_count == expected_wait_for_data_count
        assert connection._lastacqseen == expected_lastacqseen
        # Verify the output
        if expected_output:
            assert expected_output in caplog.messages[-1]


def test_done_with_data_lock(tekhsi_client: TekHSIConnect) -> None:
    """Test the done_with_data method of TekHSIConnect when the lock is not acquired.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
    """
    with tekhsi_client as connection:
        # Negative test case: Simulate lock not being acquired
        connection._cachedataenabled = True
        connection._wait_for_data_count = 1
        connection._acqcount = 5

        def mock_method() -> None:
            msg = "Lock not acquired"
            raise RuntimeError(msg)

        connection._done_with_data_release_lock = mock_method

        with pytest.raises(RuntimeError, match="Lock not acquired"):
            connection.done_with_data()

        # Restore the original method
        connection.done_with_data()


@pytest.mark.parametrize(
    (
        "cache_enabled",
        "wait_on",
        "after",
        "datacache",
        "acqcount",
        "acqtime",
        "lastacqseen",
        "expected_wait_for_data_count",
        "expected_lastacqseen",
        "expected_output",
    ),
    [
        (
            True,
            AcqWaitOn.NewData,
            -1,
            {"data": "value"},
            5,
            0,
            0,
            1,
            0,
            None,
        ),  # Valid case: NewData with unseen data
        (True, AcqWaitOn.AnyAcq, -1, {"data": "value"}, 5, 0, 0, 1, 0, None),  # Valid case: AnyAcq
        (
            True,
            AcqWaitOn.NextAcq,
            -1,
            {"data": "value"},
            5,
            0,
            0,
            1,
            0,
            None,
        ),  # Valid case: NextAcq
        (True, AcqWaitOn.Time, 5, {"data": "value"}, 0, 10, 0, 1, 0, None),  # Valid case: Time
        (False, AcqWaitOn.NewData, -1, {}, 0, 0, 0, 0, 0, None),  # Caching disabled
    ],
)
def test_wait_for_data(  # noqa: PLR0913
    tekhsi_client: TekHSIConnect,
    cache_enabled: bool,
    wait_on: AcqWaitOn,
    after: int,
    datacache: dict[str, str],
    acqcount: int,
    acqtime: int,
    lastacqseen: int,
    expected_wait_for_data_count: int,
    expected_lastacqseen: int,
    expected_output: str | None,
) -> None:
    """Test the wait_for_data method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        cache_enabled: Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        after: The time after which the acquisition must occur.
        datacache (dict): The data cache to be used.
        acqcount: The initial acquisition count.
        acqtime: The initial acquisition time.
        lastacqseen: The last acquisition seen.
        expected_wait_for_data_count: The expected wait_for_data_count after the method call.
        expected_lastacqseen: The expected last acquisition seen after the method call.
        expected_output: The expected output message, if any.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._datacache = datacache
        connection._acqcount = acqcount
        connection._acqtime = acqtime
        connection._lastacqseen = lastacqseen

        # Mocking print_with_timestamp if expected_output is provided
        if expected_output:
            with patch(
                "tekhsi.tekhsi_client.print_with_timestamp",
                side_effect=lambda x: x,
            ) as mock_print:
                connection.wait_for_data(wait_on, after)
                mock_print.assert_called_once_with(expected_output)
        else:
            connection.wait_for_data(wait_on, after)

        # Verify the internal state
        assert connection._wait_for_data_count == expected_wait_for_data_count
        assert connection._lastacqseen == expected_lastacqseen


@pytest.mark.parametrize(
    "expected_symbols",
    [
        (["ch1", "ch1_iq", "ch2", "ch3", "math1", "math2"]),  # Default symbols
    ],
)
def test_available_symbols(tekhsi_client: TekHSIConnect, expected_symbols: list[str]) -> None:
    """Test the available_symbols property of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        expected_symbols: The expected list of available symbols.
    """
    with tekhsi_client as connection:
        # Retrieve the available symbols
        symbols = connection.available_symbols

        # Check that the symbols match the expected values from the test server
        assert sorted(symbols) == sorted(expected_symbols)


@pytest.mark.parametrize(
    ("initial_value", "new_value", "expected_value"),
    [
        (True, False, False),  # Change from True to False
        (False, True, True),  # Change from False to True
        (True, True, True),  # No change
        (False, False, False),  # No change
    ],
)
def test_instrumentation_enabled(
    tekhsi_client: TekHSIConnect, initial_value: bool, new_value: bool, expected_value: bool
) -> None:
    """Test the instrumentation_enabled property of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        initial_value: The initial value of the instrumentation_enabled property.
        new_value: The new value to set for the instrumentation_enabled property.
        expected_value: The expected value of the instrumentation_enabled property after
            setting the new value.
    """
    with tekhsi_client as connection:
        # Set the initial value
        connection.instrumentation_enabled = initial_value

        # Verify the initial value
        assert connection.instrumentation_enabled == initial_value

        # Change the value
        connection.instrumentation_enabled = new_value

        # Verify the new value
        assert connection.instrumentation_enabled == expected_value


@pytest.mark.parametrize(
    ("initial_symbols", "expected_symbols"),
    [
        (["source1", "source2"], ["source1", "source2"]),  # Valid case
        ([], []),  # No sources
        (["source1"], ["source1"]),  # Single source
        (["source1", "source2", "source3"], ["source1", "source2", "source3"]),  # Multiple sources
    ],
)
def test_source_names(
    tekhsi_client: TekHSIConnect, initial_symbols: list[str], expected_symbols: list[str]
) -> None:
    """Test the source_names property of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        initial_symbols: The initial list of active symbols to set.
        expected_symbols: The expected list of source names.
    """
    with tekhsi_client as connection:
        # Set the initial symbols
        connection.activesymbols = initial_symbols

        # Retrieve the source names
        source_names = connection.source_names

        # Verify the source names match the expected values
        assert source_names == expected_symbols


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (WaveformHeader(noofsamples=100, sourcewidth=1, hasdata=True), True),
        (WaveformHeader(noofsamples=0, sourcewidth=1, hasdata=True), False),
        (WaveformHeader(noofsamples=100, sourcewidth=3, hasdata=True), False),
        (WaveformHeader(noofsamples=100, sourcewidth=1, hasdata=False), False),
        (None, False),
    ],
)
def test_is_header_value(header: WaveformHeader, expected: bool) -> None:
    """Test the _is_header_value method of TekHSIConnect.

    Args:
        header: The header to be checked.
        expected: The expected result of the _is_header_value method.
    """
    assert TekHSIConnect._is_header_value(header) == expected


@pytest.mark.parametrize(
    (
        "cache_enabled",
        "wait_on",
        "after",
        "datacache",
        "acqcount",
        "acqtime",
        "lastacqseen",
        "expected_wait_for_data_count",
        "expected_lastacqseen",
    ),
    [
        (True, AcqWaitOn.Time, 1, {"data": "value"}, 0, 0, 0, 1, 0),
        (True, AcqWaitOn.Time, 0, {"data": "value"}, 0, 1, 0, 1, 0),
    ],
)
def test_wait_for_data_acq_time(  # noqa: PLR0913
    tekhsi_client: TekHSIConnect,
    cache_enabled: bool,
    wait_on: AcqWaitOn,
    after: int,
    datacache: dict[str, str],
    acqcount: int,
    acqtime: int,
    lastacqseen: int,
    expected_wait_for_data_count: int,
    expected_lastacqseen: int,
) -> None:
    """Test the wait_for_data method of TekHSIConnect with acquisition time condition.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        cache_enabled: Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        after: The time after which the acquisition must occur.
        datacache (dict): The data cache to be used.
        acqcount: The initial acquisition count.
        acqtime: The initial acquisition time.
        lastacqseen: The last acquisition seen.
        expected_wait_for_data_count: The expected wait_for_data_count after the method call.
        expected_lastacqseen: The expected last acquisition seen after the method call.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._datacache = datacache
        connection._acqcount = acqcount
        connection._acqtime = acqtime
        connection._lastacqseen = lastacqseen

        # Call the wait_for_data method
        connection.wait_for_data(wait_on, after)

        # Verify the internal state
        assert connection._wait_for_data_count == expected_wait_for_data_count
        assert connection._lastacqseen == expected_lastacqseen


@pytest.mark.parametrize(
    (
        "cache_enabled",
        "wait_on",
        "datacache",
        "acqcount",
        "expected_wait_for_data_count",
        "expected_lastacqseen",
    ),
    [
        (True, AcqWaitOn.AnyAcq, {"data": "value"}, 1, 1, 0),  # acqcount > 0
    ],
)
def test_wait_for_data_any_acq(
    tekhsi_client: TekHSIConnect,
    cache_enabled: bool,
    wait_on: AcqWaitOn,
    datacache: dict[str, str],
    acqcount: int,
    expected_wait_for_data_count: int,
    expected_lastacqseen: int,
) -> None:
    """Test the wait_for_data method of TekHSIConnect with any acquisition condition.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        cache_enabled: Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        datacache (dict): The data cache to be used.
        acqcount: The initial acquisition count.
        expected_wait_for_data_count: The expected wait_for_data_count after the method call.
        expected_lastacqseen: The expected last acquisition seen after the method call.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._datacache = datacache
        connection._acqcount = acqcount
        connection._lastacqseen = 0

        # Call the wait_for_data method
        connection.wait_for_data(wait_on)

        # Verify the internal state
        assert connection._wait_for_data_count == expected_wait_for_data_count
        assert connection._lastacqseen == expected_lastacqseen


@pytest.mark.parametrize(
    (
        "cache_enabled",
        "wait_on",
        "datacache",
        "acqcount",
        "lastacqseen",
        "expected_wait_for_data_count",
        "expected_lastacqseen",
    ),
    [
        (True, AcqWaitOn.NewData, {"data": "value"}, 5, 0, 1, 0),
    ],
)
def test_wait_for_data_new_and_next_acq(  # noqa: PLR0913
    tekhsi_client: TekHSIConnect,
    cache_enabled: bool,
    wait_on: AcqWaitOn,
    datacache: dict[str, str],
    acqcount: int,
    lastacqseen: int,
    expected_wait_for_data_count: int,
    expected_lastacqseen: int,
) -> None:
    """Test the wait_for_data method of TekHSIConnect with new and next acquisition conditions.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        cache_enabled: Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        datacache (dict): The data cache to be used.
        acqcount: The initial acquisition count.
        lastacqseen: The last acquisition seen.
        expected_wait_for_data_count: The expected wait_for_data_count after the method call.
        expected_lastacqseen: The expected last acquisition seen after the method call.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._datacache = datacache
        connection._acqcount = acqcount
        connection._lastacqseen = lastacqseen

        # Call the wait_for_data method
        connection.wait_for_data(wait_on)

        # Verify the internal state
        assert connection._wait_for_data_count == expected_wait_for_data_count
        assert connection._lastacqseen == expected_lastacqseen
        assert connection._wait_for_data_holds_lock, "_wait_next_acq was not called"


@pytest.mark.parametrize(
    ("headers", "expected_datasize"),
    [
        (
            [
                WaveformHeader(
                    sourcename="ch1",
                    wfmtype=WfmType.WFMTYPE_ANALOG_8,
                    verticalspacing=1.0,
                    verticaloffset=0.0,
                    verticalunits="V",
                    horizontalspacing=1.0,
                    horizontalUnits="s",
                    horizontalzeroindex=0,
                    sourcewidth=1,
                    noofsamples=4,
                ),
            ],
            4,
        ),
    ],
)
def test_read_waveforms(
    tekhsi_client: TekHSIConnect, headers: list[WaveformHeader], expected_datasize: int
) -> None:
    """Test the _read_waveforms method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        headers: A list of WaveformHeader objects.
        expected_datasize: The expected size of the data read.
    """
    waveforms = []
    datasize = tekhsi_client._read_waveforms(headers, waveforms)
    assert datasize == expected_datasize
    assert len(waveforms) == len(headers)


def test_data_arrival(derived_waveform_handler: DerivedWaveformHandler) -> None:
    """Test the data_arrival method of DerivedWaveformHandler.

    Args:
        derived_waveform_handler (DerivedWaveformHandler): An instance of the DerivedWaveformHandler
            to be tested.
    """
    # pylint: disable=abstract-class-instantiated
    waveforms = [
        DerivedWaveform(),
        DerivedWaveform(),
    ]

    # Capture the output
    captured_output = StringIO()
    sys.stdout = captured_output

    # Call the data_arrival method
    derived_waveform_handler.data_arrival(waveforms)
    # Verify the output
    expected_output = "Processing waveform\n" * 2
    assert captured_output.getvalue() == expected_output
    # Verify the return value
    assert derived_waveform_handler.data_arrival(waveforms) is None


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ([WaveformHeader(dataid=1), WaveformHeader(dataid=2)], 1),  # Multiple headers
        ([], None),  # Empty list
        ([WaveformHeader(dataid=3)], 3),  # Single header
    ],
)
def test_acq_id(headers: list[WaveformHeader], expected: int) -> None:
    """Test the _acq_id method of TekHSIConnect.

    Args:
        headers: A list of WaveformHeader objects.
        expected: The expected acquisition ID.
    """
    result = TekHSIConnect._acq_id(headers)
    assert result == expected


@pytest.mark.parametrize(
    ("header", "response_data", "expected_waveform_type", "expected_length"),
    [
        (
            WaveformHeader(
                sourcename="ch1",
                wfmtype=WfmType.WFMTYPE_ANALOG_8,  # Analog waveform type
                verticalspacing=1.0,
                verticaloffset=0.0,
                verticalunits="V",
                horizontalspacing=1.0,
                horizontalUnits="s",
                horizontalzeroindex=0,
                sourcewidth=1,
                noofsamples=4,
            ),
            np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32).tobytes(),
            AnalogWaveform,
            4,
        ),
    ],
)
def test_read_waveform_analog(
    tekhsi_client: TekHSIConnect,
    header: WaveformHeader,
    response_data: bytes,
    expected_waveform_type: type[Waveform],
    expected_length: int,
) -> None:
    """Test reading an analog or IQ waveform.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        header: The header information for the waveform.
        response_data: The response data for the waveform.
        expected_waveform_type: The expected type of the waveform.
        expected_length: The expected length of the waveform data.
    """
    client = tekhsi_client
    client.chunksize = 1024
    client.thread_active = True
    client.verbose = True
    client._response_data = response_data

    waveform = client._read_waveform(header)
    assert isinstance(waveform, expected_waveform_type)
    if isinstance(expected_waveform_type, AnalogWaveform):
        assert isinstance(waveform, AnalogWaveform)
        assert len(waveform.y_axis_values) == expected_length


@pytest.mark.parametrize(
    (
        "instrument",
        "connected",
        "is_exiting",
        "acqtime",
        "transfertime",
        "datasize",
        "datawidth",
        "expected_output",
    ),
    [
        (True, True, False, 0.5, 0.2, 1000, 16, "UpdateRate:2.00,Data Rate:0.04Mbs,Data Width:16"),
        (False, True, False, 0.5, 0.2, 1000, 16, None),
        (True, False, False, 0.5, 0.2, 1000, 16, None),
        (True, True, True, 0.5, 0.2, 1000, 16, None),
    ],
)
def test_instrumentation(  # noqa: PLR0913
    tekhsi_client: TekHSIConnect,
    instrument: bool,
    connected: bool,
    is_exiting: bool,
    acqtime: float,
    transfertime: float,
    datasize: int,
    datawidth: int,
    expected_output: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the _instrumentation method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        instrument: Whether the instrument is enabled.
        connected: Whether the client is connected.
        is_exiting: Whether the client is in the process of exiting.
        acqtime: The acquisition time.
        transfertime: The transfer time.
        datasize: The size of the data.
        datawidth: The width of the data.
        expected_output: The expected output message, if any.
        caplog: Pytest fixture to capture log messages.
    """
    client = tekhsi_client
    client._instrument = instrument
    client._connected = connected
    client._is_exiting = is_exiting
    client._sum_acq_time = 0
    client._sum_transfer_time = 0
    client._sum_data_rate = 0
    client._sum_count = 0

    client._instrumentation(acqtime, transfertime, datasize, datawidth)

    if expected_output:
        assert expected_output in caplog.messages[-1]


@pytest.mark.parametrize(
    ("header", "response_data", "expected_length"),
    [
        (
            WaveformHeader(
                sourcename="ch1",
                wfmtype=WfmType.WFMTYPE_DIGITAL_8,
                verticalspacing=1.0,
                verticaloffset=0.0,
                verticalunits="V",
                horizontalspacing=1.0,
                horizontalUnits="s",
                horizontalzeroindex=0,
                sourcewidth=1,
                noofsamples=4,
            ),
            np.array([1, 2, 3, 4], dtype=np.uint8).tobytes(),
            4,
        ),
    ],
)
def test_read_waveform_digital(
    tekhsi_client: TekHSIConnect, header: WaveformHeader, response_data: bytes, expected_length: int
) -> None:
    """Test reading a digital waveform.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        header: The header information for the waveform.
        response_data: The response data for the waveform.
        expected_length: The expected length of the waveform data.
    """
    tekhsi_client.chunksize = 1024
    tekhsi_client.thread_active = True
    tekhsi_client.verbose = True
    tekhsi_client.d_datatypes = {1: np.uint8, 2: np.uint16}
    # Directly set the response data in the client
    tekhsi_client._response_data = response_data

    # Call the method to be tested
    waveform = tekhsi_client._read_waveform(header)

    # Assertions to verify the behavior
    assert isinstance(waveform, DigitalWaveform)
    assert len(waveform.y_axis_byte_values) == expected_length


class DummyConnection:  # pylint: disable=too-few-public-methods
    """A dummy connection class for testing purposes."""

    def __init__(self, holding_scope_open: bool) -> None:
        """Initialize the DummyConnection.

        Args:
            holding_scope_open: Indicates if the scope is open.
        """
        self._holding_scope_open = holding_scope_open
        self.finished_with_data_access_called = False
        self.close_called = False

    def _finished_with_data_access(self) -> None:
        """Mark data access as finished."""
        self.finished_with_data_access_called = True

    def close(self) -> None:
        """Close the connection."""
        self.close_called = True


@pytest.fixture(name="setup_tekhsi_connections")
def fixture_setup_tekhsi_connections() -> None:
    """Fixture to set up dummy connections for TekHSIConnect."""
    TekHSIConnect._connections = {
        "conn1": DummyConnection(holding_scope_open=True),
        "conn2": DummyConnection(holding_scope_open=False),
    }


def test_terminate(setup_tekhsi_connections: None) -> None:  # noqa: ARG001
    """Test the _terminate method of TekHSIConnect.

    Args:
        setup_tekhsi_connections (fixture): Fixture to set up dummy connections.
    """
    TekHSIConnect._terminate()

    conn1 = TekHSIConnect._connections["conn1"]
    conn2 = TekHSIConnect._connections["conn2"]

    assert getattr(conn1, "finished_with_data_access_called", False)
    assert getattr(conn1, "close_called", False)
    assert getattr(conn2, "close_called", False)


def test_active_symbols(tekhsi_client: TekHSIConnect) -> None:
    """Test the active_symbols method of TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
    """
    symbols = ["symbol1", "symbol2", "symbol3"]

    # Call the method to set active symbols
    tekhsi_client.active_symbols(symbols)

    # Verify that the activesymbols attribute is updated correctly
    assert tekhsi_client.activesymbols == symbols


def test_callback_invocation(tekhsi_client: TekHSIConnect) -> None:
    """Test the invocation of the callback function in TekHSIConnect.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
    """

    def real_callback(waveforms_inner: list[str]) -> None:
        assert waveforms_inner == ["waveform1", "waveform2"]

    tekhsi_client._callback = real_callback
    waveforms = ["waveform1", "waveform2"]

    tekhsi_client._callback(waveforms)


@pytest.mark.parametrize(
    ("header", "expected_sample_rate"),
    [
        (
            WaveformHeader(wfmtype=6, iq_windowType="Blackharris", iq_fftLength=1024, iq_rbw=1e6),  # type: ignore[arg-type]
            1024 * 1e6 / 1.9,
        ),
        (
            WaveformHeader(wfmtype=6, iq_windowType="Flattop2", iq_fftLength=1024, iq_rbw=1e6),  # type: ignore[arg-type]
            1024 * 1e6 / 3.77,
        ),
    ],
)
def test_read_waveform_iq(
    tekhsi_client: TekHSIConnect, header: WaveformHeader, expected_sample_rate: float
) -> None:
    """Test reading an IQ waveform.

    Args:
        tekhsi_client: An instance of the TekHSI client to be tested.
        header: The header information for the waveform.
        expected_sample_rate: The expected IQ sample rate.
    """
    waveform = tekhsi_client._read_waveform(header)
    assert isinstance(waveform, IQWaveform)
    assert waveform.meta_info.iq_sample_rate == pytest.approx(expected_sample_rate)


def test_close_normal(tekhsi_client: TekHSIConnect) -> None:
    """Test the close method of TekHSIConnect under normal conditions.

    Ensures that the client is properly disconnected and the thread is joined.
    """
    tekhsi_client._connected = True
    tekhsi_client.thread_active = True

    tekhsi_client.force_sequence = MagicMock()
    tekhsi_client._disconnect = MagicMock()

    mock_thread = MagicMock()
    tekhsi_client.thread = mock_thread

    tekhsi_client._read_executor = None

    tekhsi_client.close()

    tekhsi_client.force_sequence.assert_called_once()
    mock_thread.join.assert_called_once()
    tekhsi_client._disconnect.assert_called_once()
    assert tekhsi_client.thread_active is False


def test_close_executor_metrics_logging(
    tekhsi_client: TekHSIConnect, caplog: pytest.LogCaptureFixture
) -> None:
    """Test close() when the read executor is active.

    Ensures performance metrics are logged when verbose is enabled.
    """
    tekhsi_client._connected = True
    tekhsi_client.thread_active = True
    tekhsi_client.verbose = True

    tekhsi_client.force_sequence = MagicMock()
    tekhsi_client._disconnect = MagicMock()
    tekhsi_client.thread = MagicMock()

    mock_executor = MagicMock()
    tekhsi_client._read_executor = mock_executor

    # Force metrics logging branch
    tekhsi_client._parallel_read_count = 2
    tekhsi_client._parallel_read_time = 0.2
    tekhsi_client._sequential_read_count = 1
    tekhsi_client._sequential_read_time = 0.1

    with caplog.at_level(logging.INFO):
        tekhsi_client.close()

    assert "Read performance:" in caplog.text


def test_close_when_not_connected(tekhsi_client: TekHSIConnect) -> None:
    """Test the close method when the client is not connected.

    Should return immediately and not raise.
    """
    tekhsi_client._connected = False

    # Should return immediately and not raise
    tekhsi_client.close()


@pytest.mark.skipif(
    sys.version_info[:2] == (3, 10),
    reason="triggers gRPC cleanup path in Python 3.10; requires refactor to avoid RPC side effects",
)
def test_set_acq_filter_none_raises(tekhsi_client: TekHSIConnect) -> None:
    """Test set_acq_filter(None) raises ValueError without side effects.

    Ensures no background thread is running and not connected.
    """
    # Remove unnecessary assignments and ensure no background thread
    tekhsi_client.thread_active = False
    tekhsi_client._connected = False

    with pytest.raises(ValueError, match="Filter cannot be None"):
        tekhsi_client.set_acq_filter(None)  # type: ignore[arg-type]


def test_read_waveform_with_stub_unknown_type() -> None:
    """Test _read_waveform_with_stub with an unknown waveform type.

    Expects a ValueError to be raised.
    """
    client = TekHSIConnect.__new__(TekHSIConnect)

    header = SimpleNamespace(
        wfmtype=999,
        sourcename="CH1",
        noofsamples=0,
        sourcewidth=1,
    )

    native_stub = object()

    with pytest.raises(ValueError, match="Unknown waveform type"):
        TekHSIConnect._read_waveform_with_stub(client, header, native_stub)  # type: ignore[arg-type]


def test_any_acq_with_new_key() -> None:
    """Test any_acq when a new key is added to the current headers.

    Should return True.
    """
    prev = {"ch1": WaveformHeader(noofsamples=1)}
    curr = {
        "ch1": WaveformHeader(noofsamples=1),
        "ch2": WaveformHeader(noofsamples=1),
    }
    assert TekHSIConnect.any_acq(prev, curr)


def test_is_header_value_false_cases() -> None:
    """Test _is_header_value for cases that should return False.

    Covers None header, zero samples, invalid source width, and hasdata False.
    """
    # None header
    assert not TekHSIConnect._is_header_value(None)  # type: ignore[arg-type]

    # Case: zero samples
    h = WaveformHeader(noofsamples=0, sourcewidth=1, hasdata=True)
    assert not TekHSIConnect._is_header_value(h)

    # invalid sourcewidth
    h = WaveformHeader(noofsamples=1, sourcewidth=8, hasdata=True)
    assert not TekHSIConnect._is_header_value(h)

    # hasdata False
    h = WaveformHeader(noofsamples=1, sourcewidth=1, hasdata=False)
    assert not TekHSIConnect._is_header_value(h)
