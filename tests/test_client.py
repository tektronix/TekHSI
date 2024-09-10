"""Unit tests for the TekHSI client functionality."""

import sys

from io import StringIO
from unittest.mock import patch

import numpy as np
import pytest
from tm_data_types import AnalogWaveform, IQWaveform, DigitalWaveform

from tm_data_types import AnalogWaveform, DigitalWaveform, IQWaveform

from conftest import DerivedWaveform, DerivedWaveformHandler
from tekhsi._tek_highspeed_server_pb2 import (  # pylint: disable=no-name-in-module
    ConnectRequest,
    ConnectStatus,
    WaveformHeader,
)
from tekhsi.helpers import print_with_timestamp
from tekhsi.tek_hsi_connect import AcqWaitOn, TekHSIConnect


@pytest.mark.parametrize(
    ("instrument", "sum_count", "sum_acq_time", "sum_data_rate", "expected_output"),
    [
        (True, 5, 10.0, 50.0, "Average Update Rate:0.50, Data Rate:10.00Mbs"),
    ],
)
def test_server_connection(
    tekhsi_client,
    capsys,
    instrument,
    sum_count,
    sum_acq_time,
    sum_data_rate,
    expected_output,
):
    """Test the server connection using the TekHSI client.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
    """
    # Set the required attributes
    tekhsi_client._instrument = instrument
    tekhsi_client._sum_count = sum_count
    tekhsi_client._sum_acq_time = sum_acq_time
    tekhsi_client._sum_data_rate = sum_data_rate

    # Set the verbose attribute to True
    tekhsi_client.verbose = True
    # Use the context manager to handle connection
    with tekhsi_client as connection:
        captured = capsys.readouterr()
        request = ConnectRequest(name="test_client")
        response = connection.connection.Connect(request)
        assert "enter()" in captured.out

        # Verify the connection status
        assert response.status == ConnectStatus.CONNECTSTATUS_SUCCESS

    # Capture the printed output
    captured = capsys.readouterr()

    # Verify the printed output
    assert expected_output in captured.out


@pytest.mark.parametrize(
    ("prevheader", "currentheader", "expected"),
    [
        ({}, {}, True),  # Always returns True
    ],
)
def test_any_acq(prevheader, currentheader, expected):
    """Test the any_acq method of TekHSIConnect.

    Args:
        prevheader (dict): The previous header data.
        currentheader (dict): The current header data.
        expected (bool): The expected result of the any_acq method.
    """
    result = TekHSIConnect.any_acq(prevheader, currentheader)
    assert result == expected, f"Expected any_acq to return {expected}"


@pytest.mark.parametrize(
    ("prevheader", "currentheader", "expected"),
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
def test_any_horizontal_change(prevheader, currentheader, expected):
    """Test the any_horizontal_change method of TekHSIConnect.

    Args:
        prevheader (dict): The previous header data.
        currentheader (dict): The current header data.
        expected (bool): The expected result of the any_horizontal_change method.
    """
    result = TekHSIConnect.any_horizontal_change(prevheader, currentheader)
    assert result == expected, f"Expected any_horizontal_change to return {expected}"


@pytest.mark.parametrize(
    ("prevheader", "currentheader", "expected"),
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
def test_any_vertical_change(prevheader, currentheader, expected):
    """Test the any_vertical_change method of TekHSIConnect.

    Args:
        prevheader (dict): The previous header data.
        currentheader (dict): The current header data.
        expected (bool): The expected result of the any_vertical_change method.
    """
    result = TekHSIConnect.any_vertical_change(prevheader, currentheader)
    assert result == expected, f"Expected any_vertical_change to return {expected}"


@pytest.mark.parametrize(
    ("acq_filter", "expected_exception", "expected_message"),
    [
        ({"name": "TestFilter"}, None, None),
        (None, ValueError, "Filter cannot be None"),
    ],
)
def test_set_acq_filter(tekhsi_client, acq_filter, expected_exception, expected_message):
    """Test the set_acq_filter method of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        acq_filter (dict): The acquisition filter to be set.
        expected_exception (Exception): The expected exception to be raised, if any.
        expected_message (str): The expected exception message, if any.
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
def test_get_data(tekhsi_client, cache_enabled, data_cache, name, expected_result):
    """Test the get_data method of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        cache_enabled (bool): Whether the data cache is enabled.
        data_cache (dict): The data cache to be used.
        name (str): The name of the data to retrieve.
        expected_result (Any): The expected result of the get_data method.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._datacache = data_cache

        # Call the method
        result = connection.get_data(name)

        # Verify the result
        assert result == expected_result, f"Expected {expected_result}, got {result}"


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
        (True, 0, 5, 0, 0, "** done_with_data called when no wait_for_data pending", True),
        (False, 1, 5, 1, 0, None, True),  # Caching disabled
        (True, -1, 5, -1, 0, "** done_with_data called when no wait_for_data pending", True),
        (True, 2, 5, 1, 5, None, True),  # wait_for_data_count greater than 1
        (True, 0, 5, 0, 0, None, False),  # No wait_for_data pending, verbose is False
    ],
)
@patch("tekhsi.tek_hsi_connect.print_with_timestamp")
def test_done_with_data(
    mock_print_with_timestamp,
    tekhsi_client,
    capsys,
    cache_enabled,
    wait_for_data_count,
    acqcount,
    expected_wait_for_data_count,
    expected_lastacqseen,
    expected_output,
    verbose,
):
    """Test the done_with_data method of TekHSIConnect.

    Args:
        mock_print_with_timestamp (MagicMock): Mocked print_with_timestamp function.
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        capsys (CaptureFixture): Pytest fixture to capture system output.
        cache_enabled (bool): Whether the data cache is enabled.
        wait_for_data_count (int): The initial wait_for_data_count value.
        acqcount (int): The initial acquisition count.
        expected_wait_for_data_count (int): The expected wait_for_data_count after the method call.
        expected_lastacqseen (int): The expected last acquisition seen after the method call.
        expected_output (str): The expected output message, if any.
        verbose (bool): Whether verbose mode is enabled.
    """
    with tekhsi_client as connection:
        # Set up the client state
        connection._cachedataenabled = cache_enabled
        connection._wait_for_data_count = wait_for_data_count
        connection._acqcount = acqcount
        connection.verbose = verbose

        # Mock the print_with_timestamp to capture its output
        if expected_output:
            mock_print_with_timestamp.return_value = print_with_timestamp(expected_output)

            # Call the method
        connection.done_with_data()

        # Verify the internal state
        assert connection._wait_for_data_count == expected_wait_for_data_count
        assert connection._lastacqseen == expected_lastacqseen
        # Verify the output
        if expected_output:
            mock_print_with_timestamp.assert_called_once_with(expected_output)
            captured = mock_print_with_timestamp.return_value
            assert (
                expected_output in captured
            ), f"Expected output '{expected_output}', got '{captured}'"
        elif verbose:
            mock_print_with_timestamp.assert_not_called()


def test_done_with_data_lock(tekhsi_client):
    """Test the done_with_data method of TekHSIConnect when the lock is not acquired.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
    """
    with tekhsi_client as connection:
        # Negative test case: Simulate lock not being acquired
        connection._cachedataenabled = True
        connection._wait_for_data_count = 1
        connection._acqcount = 5

        def mock_method():
            raise RuntimeError("Lock not acquired")

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
def test_wait_for_data(
    tekhsi_client,
    cache_enabled,
    wait_on,
    after,
    datacache,
    acqcount,
    acqtime,
    lastacqseen,
    expected_wait_for_data_count,
    expected_lastacqseen,
    expected_output,
):
    """Test the wait_for_data method of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        cache_enabled (bool): Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        after (float): The time after which the acquisition must occur.
        datacache (dict): The data cache to be used.
        acqcount (int): The initial acquisition count.
        acqtime (float): The initial acquisition time.
        lastacqseen (int): The last acquisition seen.
        expected_wait_for_data_count (int): The expected wait_for_data_count after the method call.
        expected_lastacqseen (int): The expected last acquisition seen after the method call.
        expected_output (str): The expected output message, if any.
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
        assert (
            connection._wait_for_data_count == expected_wait_for_data_count
        ), f"Expected wait_for_data_count {expected_wait_for_data_count}, got {connection._wait_for_data_count}"
        assert (
            connection._lastacqseen == expected_lastacqseen
        ), f"Expected lastacqseen {expected_lastacqseen}, got {connection._lastacqseen}"


@pytest.mark.parametrize(
    "expected_symbols",
    [
        (["ch1", "ch1_iq", "ch2", "ch3", "math1", "math2"]),  # Default symbols
    ],
)
def test_available_symbols(tekhsi_client, expected_symbols):
    """Test the available_symbols property of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        expected_symbols (list): The expected list of available symbols.
    """
    with tekhsi_client as connection:
        # Retrieve the available symbols
        symbols = connection.available_symbols

        # Check that the symbols match the expected values from the test server
        assert sorted(symbols) == sorted(
            expected_symbols,
        ), f"Expected symbols {expected_symbols}, got {symbols}"


@pytest.mark.parametrize(
    ("initial_value", "new_value", "expected_value"),
    [
        (True, False, False),  # Change from True to False
        (False, True, True),  # Change from False to True
        (True, True, True),  # No change
        (False, False, False),  # No change
    ],
)
def test_instrumentation_enabled(tekhsi_client, initial_value, new_value, expected_value):
    """Test the instrumentation_enabled property of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        initial_value (bool): The initial value of the instrumentation_enabled property.
        new_value (bool): The new value to set for the instrumentation_enabled property.
        expected_value (bool): The expected value of the instrumentation_enabled property after setting the new value.
    """
    with tekhsi_client as connection:
        # Set the initial value
        connection.instrumentation_enabled = initial_value

        # Verify the initial value
        assert (
            connection.instrumentation_enabled == initial_value
        ), f"Expected initial value {initial_value}, got {connection.instrumentation_enabled}"

        # Change the value
        connection.instrumentation_enabled = new_value

        # Verify the new value
        assert (
            connection.instrumentation_enabled == expected_value
        ), f"Expected new value {expected_value}, got {connection.instrumentation_enabled}"


@pytest.mark.parametrize(
    ("initial_symbols", "expected_symbols"),
    [
        (["source1", "source2"], ["source1", "source2"]),  # Valid case
        ([], []),  # No sources
        (["source1"], ["source1"]),  # Single source
        (["source1", "source2", "source3"], ["source1", "source2", "source3"]),  # Multiple sources
    ],
)
def test_source_names(tekhsi_client, initial_symbols, expected_symbols):
    """Test the source_names property of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        initial_symbols (list): The initial list of active symbols to set.
        expected_symbols (list): The expected list of source names.
    """
    with tekhsi_client as connection:
        # Set the initial symbols
        connection.activesymbols = initial_symbols

        # Retrieve the source names
        source_names = connection.source_names

        # Verify the source names match the expected values
        assert (
            source_names == expected_symbols
        ), f"Expected source names {expected_symbols}, got {source_names}"


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
def test_is_header_value(header, expected):
    """Test the _is_header_value method of TekHSIConnect.

    Args:
        header (WaveformHeader): The header to be checked.
        expected (bool): The expected result of the _is_header_value method.
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
def test_wait_for_data_acq_time(
    tekhsi_client,
    cache_enabled,
    wait_on,
    after,
    datacache,
    acqcount,
    acqtime,
    lastacqseen,
    expected_wait_for_data_count,
    expected_lastacqseen,
):
    """Test the wait_for_data method of TekHSIConnect with acquisition time condition.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        cache_enabled (bool): Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        after (float): The time after which the acquisition must occur.
        datacache (dict): The data cache to be used.
        acqcount (int): The initial acquisition count.
        acqtime (float): The initial acquisition time.
        lastacqseen (int): The last acquisition seen.
        expected_wait_for_data_count (int): The expected wait_for_data_count after the method call.
        expected_lastacqseen (int): The expected last acquisition seen after the method call.
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
        assert (
            connection._wait_for_data_count == expected_wait_for_data_count
        ), f"Expected wait_for_data_count {expected_wait_for_data_count}, got {connection._wait_for_data_count}"
        assert (
            connection._lastacqseen == expected_lastacqseen
        ), f"Expected lastacqseen {expected_lastacqseen}, got {connection._lastacqseen}"


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
    tekhsi_client,
    cache_enabled,
    wait_on,
    datacache,
    acqcount,
    expected_wait_for_data_count,
    expected_lastacqseen,
):
    """Test the wait_for_data method of TekHSIConnect with any acquisition condition.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        cache_enabled (bool): Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        datacache (dict): The data cache to be used.
        acqcount (int): The initial acquisition count.
        expected_wait_for_data_count (int): The expected wait_for_data_count after the method call.
        expected_lastacqseen (int): The expected last acquisition seen after the method call.
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
        assert (
            connection._wait_for_data_count == expected_wait_for_data_count
        ), f"Expected wait_for_data_count {expected_wait_for_data_count}, got {connection._wait_for_data_count}"
        assert (
            connection._lastacqseen == expected_lastacqseen
        ), f"Expected lastacqseen {expected_lastacqseen}, got {connection._lastacqseen}"


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
def test_wait_for_data_new_and_next_acq(
    tekhsi_client,
    cache_enabled,
    wait_on,
    datacache,
    acqcount,
    lastacqseen,
    expected_wait_for_data_count,
    expected_lastacqseen,
):
    """Test the wait_for_data method of TekHSIConnect with new and next acquisition conditions.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        cache_enabled (bool): Whether the data cache is enabled.
        wait_on (AcqWaitOn): The condition to wait on (e.g., NewData, AnyAcq, NextAcq, Time).
        datacache (dict): The data cache to be used.
        acqcount (int): The initial acquisition count.
        lastacqseen (int): The last acquisition seen.
        expected_wait_for_data_count (int): The expected wait_for_data_count after the method call.
        expected_lastacqseen (int): The expected last acquisition seen after the method call.
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
        assert (
            connection._wait_for_data_count == expected_wait_for_data_count
        ), f"Expected wait_for_data_count {expected_wait_for_data_count}, got {connection._wait_for_data_count}"
        assert (
            connection._lastacqseen == expected_lastacqseen
        ), f"Expected lastacqseen {expected_lastacqseen}, got {connection._lastacqseen}"

        assert connection._wait_for_data_holds_lock, "_wait_next_acq was not called"


@pytest.mark.parametrize(
    ("headers", "expected_datasize"),
    [
        (
            [
                WaveformHeader(
                    sourcename="ch1",
                    wfmtype=1,
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
def test_read_waveforms(tekhsi_client, headers, expected_datasize):
    """Test the _read_waveforms method of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        headers (list): A list of WaveformHeader objects.
        expected_datasize (int): The expected size of the data read.
    """
    waveforms = []
    datasize = tekhsi_client._read_waveforms(headers, waveforms)
    assert datasize == expected_datasize
    assert len(waveforms) == len(headers)


def test_data_arrival(derived_waveform_handler: DerivedWaveformHandler):
    """Test the data_arrival method of DerivedWaveformHandler.

    Args:
        derived_waveform_handler (DerivedWaveformHandler): An instance of the DerivedWaveformHandler to be tested.
    """
    waveforms = [DerivedWaveform(), DerivedWaveform()]  # pylint: disable=abstract-class-instantiated

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
def test_acq_id(headers, expected):
    """Test the _acq_id method of TekHSIConnect.

    Args:
        headers (list): A list of WaveformHeader objects.
        expected (int): The expected acquisition ID.
    """
    result = TekHSIConnect._acq_id(headers)
    assert result == expected, f"Expected {expected}, got {result}"


@pytest.mark.parametrize(
    ("header", "response_data", "expected_waveform_type", "expected_length"),
    [
        (
            WaveformHeader(
                sourcename="ch1",
                wfmtype=1,  # Analog waveform type
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
    tekhsi_client,
    header,
    response_data,
    expected_waveform_type,
    expected_length,
):
    """Test reading an analog or IQ waveform.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        header (WaveformHeader): The header information for the waveform.
        response_data (bytes): The response data for the waveform.
        expected_waveform_type (type): The expected type of the waveform (e.g., AnalogWaveform, IQWaveform).
        expected_length (int): The expected length of the waveform data.
    """
    client = tekhsi_client
    client.chunksize = 1024
    client.thread_active = True
    client.verbose = True
    client._response_data = response_data

    waveform = client._read_waveform(header)
    assert isinstance(waveform, expected_waveform_type)
    if expected_waveform_type == AnalogWaveform:
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
@patch("builtins.print")
def test_instrumentation(
    mock_print,
    tekhsi_client,
    instrument,
    connected,
    is_exiting,
    acqtime,
    transfertime,
    datasize,
    datawidth,
    expected_output,
):
    """Test the _instrumentation method of TekHSIConnect.

    Args:
        mock_print (MagicMock): Mocked print function.
        instrument (bool): Whether the instrument is enabled.
        connected (bool): Whether the client is connected.
        is_exiting (bool): Whether the client is in the process of exiting.
        acqtime (float): The acquisition time.
        transfertime (float): The transfer time.
        datasize (int): The size of the data.
        datawidth (int): The width of the data.
        expected_output (str): The expected output message, if any.
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
        mock_print.assert_called_once_with(expected_output)
    else:
        mock_print.assert_not_called()


@pytest.mark.parametrize(
    ("header", "response_data", "expected_length"),
    [
        (
            WaveformHeader(
                sourcename="ch1",
                wfmtype=4,
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
def test_read_waveform_digital(tekhsi_client, header, response_data, expected_length):
    """Test reading a digital waveform.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
        header (WaveformHeader): The header information for the waveform.
        response_data (bytes): The response data for the waveform.
        expected_length (int): The expected length of the waveform data.
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


class DummyConnection:
    def __init__(self, holding_scope_open):
        """Initialize the DummyConnection.

        Args:
            holding_scope_open (bool): Indicates if the scope is open.
        """
        self._holding_scope_open = holding_scope_open
        self.finished_with_data_access_called = False
        self.close_called = False

    def _finished_with_data_access(self):
        """Mark data access as finished."""
        self.finished_with_data_access_called = True

    def close(self):
        """Close the connection."""
        self.close_called = True


@pytest.fixture()
def setup_tekhsi_connections():
    """Fixture to set up dummy connections for TekHSIConnect."""
    TekHSIConnect._connections = {
        "conn1": DummyConnection(holding_scope_open=True),
        "conn2": DummyConnection(holding_scope_open=False),
    }


def test_terminate(setup_tekhsi_connections):
    """Test the _terminate method of TekHSIConnect.

    Args:
        setup_tekhsi_connections (fixture): Fixture to set up dummy connections.
    """
    TekHSIConnect._terminate()

    conn1 = TekHSIConnect._connections["conn1"]
    conn2 = TekHSIConnect._connections["conn2"]

    assert conn1.finished_with_data_access_called
    assert conn1.close_called
    assert conn2.close_called


def test_active_symbols(tekhsi_client):
    """Test the active_symbols method of TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
    """
    symbols = ["symbol1", "symbol2", "symbol3"]

    # Call the method to set active symbols
    tekhsi_client.active_symbols(symbols)

    # Verify that the activesymbols attribute is updated correctly
    assert (
        tekhsi_client.activesymbols == symbols
    ), f"Expected {symbols}, got {tekhsi_client.activesymbols}"


def test_callback_invocation(tekhsi_client):
    """Test the invocation of the callback function in TekHSIConnect.

    Args:
        tekhsi_client (TekHSIConnect): An instance of the TekHSI client to be tested.
    """

    def real_callback(waveforms):
        assert waveforms == ["waveform1", "waveform2"]

    tekhsi_client._callback = real_callback
    waveforms = ["waveform1", "waveform2"]

    tekhsi_client._callback(waveforms)


@pytest.mark.parametrize(
    "header, expected_sample_rate",
    [
        (
            WaveformHeader(wfmtype=6, iq_windowType="Blackharris", iq_fftLength=1024, iq_rbw=1e6),
            1024 * 1e6 / 1.9,
        ),
        (
            WaveformHeader(wfmtype=6, iq_windowType="Flattop2", iq_fftLength=1024, iq_rbw=1e6),
            1024 * 1e6 / 3.77,
        ),
    ],
)
def test_read_waveform_iq(tekhsi_client, header, expected_sample_rate):
    waveform = tekhsi_client._read_waveform(header)
    assert isinstance(waveform, IQWaveform)
    assert waveform.meta_info.iq_sample_rate == pytest.approx(expected_sample_rate)
