"""Module for connecting to Tektronix instruments and retrieving waveform data using gRPC."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
import uuid

from atexit import register
from concurrent.futures import as_completed, ThreadPoolExecutor
from enum import Enum
from typing import Callable, ClassVar, Dict, List, Type, TYPE_CHECKING, TypeVar

import grpc
import numpy as np

from tm_data_types import (
    AnalogWaveform,
    DigitalWaveform,
    IQWaveform,
    IQWaveformMetaInfo,
    Waveform,
)

from tekhsi._tek_highspeed_server_pb2 import (  # pylint: disable=no-name-in-module
    ConnectRequest,
    WaveformHeader,
    WaveformRequest,
)
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub, NativeDataStub
from tekhsi.helpers.logging import configure_logging

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self

_logger = logging.getLogger(__name__)

AnyWaveform = TypeVar("AnyWaveform", bound=Waveform)


class AcqWaitOn(Enum):
    """This enumeration is used to select how to wait to access data."""

    NextAcq = 1
    """Wait for the next acquisition.

    Using the `NextAcq` criterion for data acceptance will force the data access call to wait until
    the next new acquisition is available.

    Examples:
        >>> from tekhsi import AcqWaitOn, TekHSIConnect
        >>> with TekHSIConnect("192.168.0.1:5000") as connection:
        ...     with connection.access_data(AcqWaitOn.NextAcq):
        ...         ...
    """
    Time = 2
    """Wait for a specific time.

    Using the `Time` criterion for data acceptance will force a time delay before accepting the next
    acquisition. The typical usage of this is if you are using multiple instruments and PyVISA. If
    you are turning on an AFG you need some time for the instrument to be set up and the data to
    arrive. This process is approximately the same as sleeping for half a second then calling
    [`access_data(AcqWaitOn.NextAcq)`][tekhsi.TekHSIConnect.access_data].

    Examples:
        >>> from tekhsi import AcqWaitOn, TekHSIConnect
        >>> with TekHSIConnect("192.168.0.1:5000") as connection:
        ...     with connection.access_data(AcqWaitOn.Time, after=0.5):
        ...         ...
    """
    AnyAcq = 3
    """Wait for any acquisition."""
    NewData = 4
    """Wait for new data.

    Using the `NewData` criterion for data acceptance will continue when the current data from the
    stored acquisition has not been read by [`get_data()`][tekhsi.TekHSIConnect.get_data]. This is
    import since the underlying data is buffered because it's stored as data on the instrument is
    available. If you have seen the underlying data since the last
    [`get_data()`][tekhsi.TekHSIConnect.get_data] call, it will return the buffered data. If you
    haven't seen the data, it will block until the next new piece of data arrives.

    Examples:
        >>> from tekhsi import AcqWaitOn, TekHSIConnect
        >>> with TekHSIConnect("192.168.0.1:5000") as connection:
        ...     with connection.access_data(AcqWaitOn.NewData):
        ...         ...
    """


class TekHSIConnect:  # pylint:disable=too-many-instance-attributes
    """Support for Tektronix High-Speed Interface data API.

    - This API is intended to aid in retrieving data from instruments as fast as possible.
    """

    _connections: ClassVar[Dict[str, "TekHSIConnect"]] = {}

    ################################################################################################
    # Magic Methods
    ################################################################################################
    def __init__(
        self,
        url: str,
        activesymbols: List[str] | None = None,
        callback: Callable | None = None,
        data_filter: Callable | None = None,
    ) -> None:
        """Initialize a connection to a Tektronix instrument using gRPC.

        Args:
            url: The IP Address and port of the TekHSI server.
            activesymbols: A list of the symbols to transfer from the scope. If
                `None`, then all available symbols are transferred. Otherwise, only the selected
                list is transferred.
            callback: An optional function to call when new data arrives. This
                is the fastest way to access data, and it ensures no acquisitions are missed.
                However, this happens in a background thread, which limits the libraries you can
                call from this method.
            data_filter: An optional function that is used to determine if
                arriving data meets a custom criterion for acceptance by the client. If `None`,
                all acquisitions are accepted. However, if customer behavior is desired, then this
                method can be provided. Typically, these functions are used to look for specific
                kinds of changes, such as record length changing.
        """
        # Configure logging in case it hasn't been done yet
        configure_logging()

        self.previous_headers = []
        self.chunksize = 80000
        self.url = url
        self.v_datatypes = {1: np.int8, 2: np.int16, 4: np.float32, 8: np.double}
        self.iq_datatypes = {1: np.int8, 2: np.int16, 4: np.int32}
        self.d_datatypes = {1: np.int8}
        self.channel = grpc.insecure_channel(url)
        self.clientname = str(uuid.uuid4())
        self.connection = ConnectStub(self.channel)
        self.native = NativeDataStub(self.channel)
        self.thread_active = True
        self._callback = callback
        self._holding_scope_open = False
        self._verbose = False
        self._instrument = False
        self._cachedataenabled = True
        self._lock = threading.Lock()
        self._lock_getdata = threading.Lock()
        self._lock_filter = threading.Lock()
        self._datacache = {}
        self._headers = {}
        self._connect()
        self._connected = True
        self._recordlength = 0
        self._acqcount = 0
        self._acqtime = -1
        self._filter = data_filter
        self._lastacqseen = self._acqcount
        self._wait_for_data_count = 0
        self._start_time = time.time()
        self._wait_for_data_holds_lock = False
        self._in_wait_for_data = False
        self._sum_transfer_time = 0
        self._sum_acq_time = 0
        self._sum_data_rate = 0
        self._sum_count = 0
        self._is_exiting = False
        self._prev_data_id = -1

        # Parallel read support for A/B testing (DISABLED BY DEFAULT - experimental)
        self._parallel_reads_enabled = self._should_enable_parallel_reads()
        self._parallel_reads_threshold = int(
            os.getenv("TEKHSI_PARALLEL_THRESHOLD", "2")
        )  # Min waveforms to parallelize
        self._read_executor: ThreadPoolExecutor | None = None
        # Only enable if explicitly requested (not "auto" - too risky)
        self._use_parallel_reads = os.getenv("TEKHSI_USE_PARALLEL_READS", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._parallel_read_time = 0.0
        self._sequential_read_time = 0.0
        self._parallel_read_count = 0
        self._sequential_read_count = 0

        if self._parallel_reads_enabled and self._use_parallel_reads:
            # Use max_workers based on typical number of channels (2-4 is optimal for I/O-bound)
            max_workers = int(os.getenv("TEKHSI_PARALLEL_WORKERS", "4"))
            self._read_executor = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix=f"tekhsi-read-{self.clientname}"
            )
            _logger.warning("Parallel reads enabled (EXPERIMENTAL) with %d workers", max_workers)

        TekHSIConnect._connections[self.clientname] = self

        if not activesymbols:
            self.activesymbols = self._available_symbols()
        else:
            self.activesymbols = [x.lower() for x in activesymbols]

        self.thread = threading.Thread(target=self._run, args=())
        self.thread.daemon = True
        self.thread.start()

    def __enter__(self) -> Self:
        """Enter the runtime context related to this object.

        Returns:
            The object itself.
        """
        # Required for "with" command to work with this class
        _logger.debug("enter()")
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the runtime context related to this object.

        Args:
            exc_type: The exception type.
            exc_val: The exception value.
            exc_tb: The traceback object.
        """
        # Required for "with" command to work with this class

        self._is_exiting = True

        _logger.debug("exit()")

        self.close()

        if self._instrument and self._sum_count > 0:
            _logger.info(
                "Average Update Rate:%.2f, Data Rate:%.2fMbs",
                (1 / (self._sum_acq_time / self._sum_count)),
                (self._sum_data_rate / self._sum_count),
            )

    ################################################################################################
    # Properties - Private and Public
    ################################################################################################
    @property
    def available_symbols(self) -> List[str]:
        """Returns the list of available symbols on the instrument.

        "Available" means the channel is on. What data type is returned will depend upon the probe
        attached or action requested by the user. This property will only return the currently
        available channel list. If channels are off or modes are disabled, the corresponding symbols
        will not be present.

        Examples:
            >>> from tekhsi import TekHSIConnect
            >>> with TekHSIConnect("192.168.0.1:5000") as connection:
            ...     print(connection.available_symbols)
            ['ch1', 'ch1_iq', 'ch3', 'ch4_DAll']

        In the above example, `'ch1'` is an analog channel, `'ch1_iq'` is the spectrum view channel
        associated with `'ch1'` (when enabled). `'ch3'` is another analog channel, and `'ch4_DAll'`
        is a digital probe on `'ch4'`. Types are generally determined by the name of the symbol.

        Returns:
            A list of available symbols.
        """
        return self._available_symbols()

    @property
    def current_time(self) -> float:
        """This property returns time relative to the connection to the gRPC client.

        Returns:
            The current time relative to the start time of the gRPC client
        """
        return time.time() - self._start_time

    @property
    def instrumentation_enabled(self) -> bool:
        """Indicates if instrumentation is enabled.

        Returns:
            `True` if instrumentation is enabled, `False` otherwise.
        """
        return self._instrument

    @instrumentation_enabled.setter
    def instrumentation_enabled(self, value: bool) -> None:
        """Sets the instrumentation enabled state.

        Args:
            value: `True` to enable instrumentation, `False` to disable.
        """
        self._instrument = value

    @property
    def source_names(self) -> List[str]:
        """Returns the list of names of sources on the instrument.

        Returns:
            The list of sources.
        """
        return self.activesymbols

    @property
    def verbose(self) -> bool:
        """Indicates if verbose mode is enabled.

        Returns:
            `True` if verbose mode is enabled, `False` otherwise.
        """
        return self._verbose

    @verbose.setter
    def verbose(self, value: bool) -> None:
        """Sets the verbose mode state.

        Args:
            value: `True` to enable verbose mode, `False` to disable.
        """
        self._verbose = value

    ################################################################################################
    # Context Manager Methods
    ################################################################################################
    @contextlib.contextmanager
    def access_data(self, on: AcqWaitOn = AcqWaitOn.NewData, after: float = -1) -> Self:
        """Grants access to data.

        Must be used as a context manager to grant access for
        [`get_data()`][tekhsi.tek_hsi_connect.TekHSIConnect.get_data] method calls.

        The `access_data()` context manager is used to get access to the available data. It holds
        access to the current acquisition (as a blocking method) for the duration of the current
        context. This is how you ensure that all data you get is from the same acquisition.
        It does not matter if the scope is running continuously or using single sequence, all the
        data is from the same acquisition when inside the `access_data()` context manager code
        block.

        This also means you are potentially holding off scope acquisitions when inside the
        `access_data()` code block. So, it's recommended you only get the data in the context
        manager, and then do any processing outside the context manager block.

        Examples:
            >>> from tm_data_types import AnalogWaveform
            >>> from tekhsi import TekHSIConnect
            >>> with TekHSIConnect("192.168.0.1:5000") as connection:
            ...     # Request access to data
            ...     with connection.access_data():
            ...         # Access granted
            ...         ch1: AnalogWaveform = connection.get_data("ch1")
            ...         ch3: AnalogWaveform = connection.get_data("ch3")

        Args:
            on: Criterion for acceptance of data. See
                [`AcqWaitOn`][tekhsi.tek_hsi_connect.AcqWaitOn] for details on each available
                criterion option.
            after: Additional criterion when the `on` input parameter is set to `AcqWaitOn.Time`.
        """
        try:
            self.wait_for_data(on, after)
            yield self
        finally:
            self.done_with_data()

    ################################################################################################
    # Public Methods
    ################################################################################################
    # TODO: Investigate moving this to a separate module as a standalone function
    @staticmethod
    def any_acq(
        previous_header: Dict[str, WaveformHeader],  # noqa: ARG004
        current_header: Dict[str, WaveformHeader],  # noqa: ARG004
    ) -> bool:
        """Prebuilt acq acceptance filter that accepts all new acqs.

        Args:
            previous_header: Previous header dictionary.
            current_header: Current header dictionary.

        Returns:
            True if the acquisition is accepted, False otherwise.
        """
        return True

    # TODO: Investigate moving this to a separate module as a standalone function
    @staticmethod
    # --8<-- [start:any_horizontal_change]
    def any_horizontal_change(
        previous_header: Dict[str, WaveformHeader],
        current_header: Dict[str, WaveformHeader],
    ) -> bool:
        """Acq acceptance filter that accepts only acqs with changes to horizontal settings.

        Args:
            previous_header: Previous header dictionary.
            current_header: Current header dictionary.

        Returns:
            True if the acquisition is accepted, False otherwise.
        """
        for key, cur in current_header.items():
            if key not in previous_header:
                return True
            prev = previous_header[key]
            if prev is None and cur is not None:
                return True
            if prev is not None and (
                prev.noofsamples != cur.noofsamples
                or prev.horizontalspacing != cur.horizontalspacing
                or prev.horizontalzeroindex != cur.horizontalzeroindex
            ):
                return True
        return False

    # --8<-- [end:any_horizontal_change]

    # TODO: Investigate moving this to a separate module as a standalone function
    @staticmethod
    def any_vertical_change(
        previous_header: Dict[str, WaveformHeader],
        current_header: Dict[str, WaveformHeader],
    ) -> bool:
        """Prebuilt acq acceptance filter that accepts only acqs with changes to vertical settings.

        Args:
            previous_header: Previous header dictionary.
            current_header: Current header dictionary.

        Returns:
            True if the acquisition is accepted, False otherwise.
        """
        for key, cur in current_header.items():
            if key not in previous_header:
                return True
            prev = previous_header[key]
            if prev is not None and (
                prev.verticalspacing != cur.verticalspacing
                or prev.verticaloffset != cur.verticaloffset
            ):
                return True
            if prev is None and cur is not None:
                return True
        return False

    def active_symbols(self, symbols: List[str]) -> None:
        """Sets symbols to consider moving from instrument into data cache.

        Args:
            symbols (List[str]): list of symbols to be moved
        """
        self.activesymbols = symbols

    def close(self) -> None:
        """Close and clean up gRPC connection."""
        if not self._connected:
            return

        _logger.debug("close")

        # Call force_sequence while still connected so it can run. This asks the
        # server to provide new data and unblocks the background thread's
        # WaitForDataAccess so it can exit. Do this before setting _connected=False.
        try:
            self.force_sequence()
        except grpc.RpcError as rpc_error:
            # Handle gRPC errors gracefully during cleanup (e.g. server already down)
            _logger.log(
                logging.WARNING if self.verbose else logging.DEBUG,
                "Error during force_sequence in close: %s",
                rpc_error,
            )

        # Mark as disconnected and stop the background thread
        self._connected = False
        self.thread_active = False

        try:
            # Wait for thread to exit
            self.thread.join(20.0)
        except RuntimeError as error:
            # Handle specific exceptions related to threading
            _logger.log(logging.ERROR if self.verbose else logging.DEBUG, "Thread error: %s", error)

        try:
            # TODO: investigate this block, it seems like this code might not work as intended
            # Take this connection out of the connection list
            if self.clientname in TekHSIConnect._available_symbols(self):
                del TekHSIConnect._available_symbols[self.clientname]  # pylint:disable=unsupported-delete-operation
        except KeyError as error:
            # Handle specific exception if the key is not found
            _logger.log(logging.ERROR if self.verbose else logging.DEBUG, "Key error: %s", error)

        _logger.debug("disconnect")

        # Shutdown parallel read executor if it exists
        if self._read_executor:
            try:
                self._read_executor.shutdown(wait=True, timeout=5.0)
                if self.verbose and (
                    self._parallel_read_count > 0 or self._sequential_read_count > 0
                ):
                    _logger.info(
                        "Read performance: Parallel=%d (avg %.3f ms), Sequential=%d (avg %.3f ms)",
                        self._parallel_read_count,
                        (self._parallel_read_time / self._parallel_read_count) * 1000
                        if self._parallel_read_count > 0
                        else 0,
                        self._sequential_read_count,
                        (self._sequential_read_time / self._sequential_read_count) * 1000
                        if self._sequential_read_count > 0
                        else 0,
                    )
            except Exception as e:
                _logger.warning("Error shutting down read executor: %s", e)
            finally:
                self._read_executor = None

        # disconnect from the instrument
        self._disconnect()

    @staticmethod
    def data_arrival(waveforms: List[AnyWaveform]) -> None:  # noqa: ARG004
        """Available to be overridden if user wants to create a derived class.

        This method will be called on every accepted acq.

        Args:
            waveforms: List of waveforms.
        """
        return

    def done_with_data(self) -> None:
        """Releases the acquisition after accessing the required data."""
        if not self._cachedataenabled:
            return

        if self._wait_for_data_count <= 0:
            _logger.log(
                logging.WARNING if self.verbose else logging.DEBUG,
                "done_with_data called when no wait_for_data pending",
            )
            return

        self._wait_for_data_count -= 1
        self._lastacqseen = self._acqcount
        self._done_with_data_release_lock()

    def force_sequence(self) -> None:
        """force_sequence asks the instrument to please give us access.

        to the current acquisition data. This is useful when connecting to a stopped instrument to
        get access to the currently available data. Otherwise, the API will wait until the next
        acquisition.
        """
        if not self._connected:
            _logger.debug("force_sequence skipped - not connected")
            return

        _logger.debug("force_sequence")
        request = ConnectRequest(name=self.clientname)
        self.connection.RequestNewSequence(request)

    def get_data(self, name: str) -> AnyWaveform | None:
        """Gets the saved data of the previous acquisition with the data item of the requested name.

        The provided `name` parameter must correspond to the names returned from the
        [`available_symbols`][tekhsi.TekHSIConnect.available_symbols] property, however, the names
        are case-insensitive.

        Args:
            name: Name of the data item.

        Returns:
            The waveform data or None if caching is off or data is not found.
        """
        if not self._cachedataenabled:
            return None  # Return None if caching off.

        self._lock_getdata.acquire()
        try:
            retval = self._datacache.get(
                name.lower(),
                None,
            )  # Return None if cached data is not found
        finally:
            self._lock_getdata.release()
        return retval

    def set_acq_filter(self, acq_filter: Callable) -> None:
        """Sets rules for acquisitions that are accepted and forwarded.

        This is to allow only import data changes to be passed to the callback or saved to backing
        store.

        Args:
            acq_filter  (function): A function that takes two headers and returns True if the data
        """
        if acq_filter is None:
            msg = "Filter cannot be None"
            raise ValueError(msg)

        self._lock_filter.acquire()
        self._filter = acq_filter
        self._lastacqseen = self._acqcount
        self._lock_filter.release()

    def wait_for_data(self, on: AcqWaitOn = AcqWaitOn.NewData, after: float = -1) -> None:
        """Waits until specified acquisition criterion is met.

        Args:
            on: Criterion for acceptance of data.
            after: Additional criterion when the `on` input parameter is set to `AcqWaitOn.Time`.
        """
        if not self._cachedataenabled:
            return

        if on == AcqWaitOn.AnyAcq:
            self._wait_for_any_acq()
        elif on == AcqWaitOn.NextAcq:
            self._wait_for_next_acq()
        elif on == AcqWaitOn.Time:
            self._wait_for_acq_time(after)
        elif on == AcqWaitOn.NewData:
            self._wait_for_new_data()

    ################################################################################################
    # Private Methods
    ################################################################################################
    @staticmethod
    def _acq_id(headers: List[WaveformHeader]) -> int | None:
        """Retrieve the data ID from the first header in the list.

        Args:
            headers: List of waveform headers.

        Returns:
            The data ID of the first header, or None if the list is empty.
        """
        for header in headers:
            return header.dataid
        return None

    def _available_symbols(self) -> List[str]:
        """Returns the list of available channels.

        Returns:
            List of available channels.
        """
        request = ConnectRequest(name=self.clientname)
        response = self.connection.RequestAvailableNames(request)
        return response.symbolnames

    def _connect(self) -> None:
        """Request connect to the gRCP server."""
        _logger.debug("connect")
        request = ConnectRequest(name=self.clientname)
        self.connection.Connect(request)

    def _disconnect(self) -> None:
        """Disconnect from gRPC server."""
        # Note: _connected may already be False if called from close()
        # but we still want to attempt the disconnect RPC call for cleanup
        _logger.debug("disconnect")
        try:
            request = ConnectRequest(name=self.clientname)
            self.connection.Disconnect(request)
        except grpc.RpcError as rpc_error:
            # Handle gRPC errors gracefully during disconnect
            # This can happen if the server is already shutting down or connection is in a bad state
            _logger.log(
                logging.WARNING if self.verbose else logging.DEBUG,
                "Error during disconnect: %s",
                rpc_error,
            )
        except Exception as error:
            # Handle any other unexpected errors during disconnect
            _logger.log(
                logging.WARNING if self.verbose else logging.DEBUG,
                "Unexpected error during disconnect: %s",
                error,
            )

    def _done_with_data_release_lock(self) -> None:
        """Releases the lock after accessing the required data."""
        if self._wait_for_data_holds_lock:
            self._lock.release()
            self._wait_for_data_holds_lock = False

    def _instrumentation(
        self, acqtime: float, transfertime: float, datasize: int, datawidth: int
    ) -> None:
        """Prints the performance information for debugging.

        Args:
            acqtime: Acquisition time.
            transfertime: Transfer time.
            datasize: Data size.
            datawidth: Data width.
        """
        if self._instrument and self._connected and not self._is_exiting:
            self._sum_acq_time += acqtime
            self._sum_transfer_time += transfertime
            self._sum_data_rate += (datasize * 8 / 1e6) / transfertime
            self._sum_count += 1
            _logger.info(
                "UpdateRate:%.2f,Data Rate:%.2fMbs,Data Width:%d",
                (1 / acqtime),
                ((datasize * 8 / 1e6) / transfertime),
                datawidth,
            )

    @staticmethod
    def _is_header_value(header: WaveformHeader) -> bool:
        """Check if the header has valid data.

        Args:
            header (WaveformHeader): The waveform header to check.

        Returns:
            bool: True if the header has valid data, False otherwise.
        """
        return (
            header is not None
            and header.noofsamples > 0
            and header.sourcewidth in {1, 2, 4}
            and header.hasdata
        )

    def _finished_with_data_access(self) -> None:
        """Releases access to instrument data.

        This is required to allow the instrument to continue acquiring
        """
        if not self._in_wait_for_data:
            return

        _logger.debug("finished_with_data_access")

        request = ConnectRequest(name=self.clientname)
        self.connection.FinishedWithDataAccess(request)

    def _read_header(self, name: str) -> WaveformHeader:
        """Reads header for the named source.

        Args:
            name (str): name of header

        Returns:
            WaveformHeader: the description of the properties of the specified waveform
        """
        _logger.debug("%s:read header", name)
        request = WaveformRequest(sourcename=name, chunksize=self.chunksize)
        response = self.native.GetHeader(request)
        return response.headerordata.header

    def _read_headers(
        self, headers: List[WaveformHeader], header_dict: Dict[str, WaveformHeader]
    ) -> None:
        """Reads headers for the active symbols.

        Args:
            headers (list): list of headers
            header_dict (dict): dictionary of headers
        """
        symbols = self.activesymbols
        n = len(symbols)
        for index in range(n):
            symbol = symbols[index]
            header = self._read_header(symbol)
            if self._is_header_value(header):
                headers.append(header)
                header_dict[header.sourcename] = header

    # pylint: disable= too-many-locals
    def _read_waveform(self, header: WaveformHeader) -> Waveform:
        """Reads the analog waveform associated with the passed header.

        Args:
            header (WaveformHeader): the header of the source to read data from

        Returns:
            Waveform: contains definition and data for the specified source
        """
        try:
            if 0 < header.wfmtype <= 3:  # Vector  # noqa: PLR2004
                waveform = AnalogWaveform()
                waveform.source_name = header.sourcename
                waveform.y_axis_spacing = header.verticalspacing
                waveform.y_axis_offset = header.verticaloffset
                waveform.y_axis_units = header.verticalunits
                waveform.x_axis_spacing = header.horizontalspacing
                waveform.x_axis_units = header.horizontalUnits
                waveform.trigger_index = header.horizontalzeroindex

                sum_of_chunks = 0
                data_size = header.sourcewidth
                request = WaveformRequest(sourcename=header.sourcename, chunksize=self.chunksize)
                response_iterator = self.native.GetWaveform(request)
                dt = None
                sum_chunk_size = 0
                dt_type = self.v_datatypes[header.sourcewidth]

                waveform.y_axis_values = np.empty(header.noofsamples, dtype=dt_type)
                for response in response_iterator:
                    if not self.thread_active:
                        return waveform
                    chunk_size = len(response.headerordata.chunk.data)
                    sum_chunk_size += chunk_size
                    dt = np.frombuffer(response.headerordata.chunk.data, dtype=dt_type)
                    waveform.y_axis_values[
                        sum_of_chunks : sum_of_chunks + int(chunk_size / data_size)
                    ] = dt
                    if dt is not None:
                        sum_of_chunks += len(dt)

            elif header.wfmtype in {7, 6}:  # WFMTYPE_ANALOG_IQ
                waveform = IQWaveform()
                waveform.source_name = header.sourcename
                waveform.iq_axis_spacing = header.verticalspacing
                waveform.iq_axis_offset = header.verticaloffset
                waveform.iq_axis_units = header.verticalunits
                waveform.x_axis_spacing = header.horizontalspacing
                waveform.x_axis_units = header.horizontalUnits
                waveform.trigger_index = header.horizontalzeroindex

                if header.iq_windowType == "Blackharris":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 1.9
                elif header.iq_windowType == "Flattop2":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 3.77
                elif header.iq_windowType == "Hanning":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 1.44
                elif header.iq_windowType == "Hamming":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 1.3
                elif header.iq_windowType == "Rectangle":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 0.89
                elif header.iq_windowType == "Kaiserbessel":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 2.23
                else:
                    sample_rate = header.iq_span

                waveform.meta_info = IQWaveformMetaInfo(
                    iq_center_frequency=header.iq_centerFrequency,
                    iq_fft_length=header.iq_fftLength,
                    iq_resolution_bandwidth=header.iq_rbw,
                    iq_span=header.iq_span,
                    iq_window_type=header.iq_windowType,
                    iq_sample_rate=sample_rate,
                )

                sample_index = 0
                request = WaveformRequest(sourcename=header.sourcename, chunksize=self.chunksize)
                response_iterator = self.native.GetWaveform(request)
                dt = None
                sum_chunk_size = 0
                dt_type = self.iq_datatypes[header.sourcewidth]

                waveform.interleaved_iq_axis_values = np.empty(header.noofsamples, dtype=dt_type)
                for response in response_iterator:
                    if not self.thread_active:
                        return waveform

                    chunk_size = len(response.headerordata.chunk.data)
                    sum_chunk_size += chunk_size
                    dt = np.frombuffer(response.headerordata.chunk.data, dtype=dt_type)
                    sample_count = len(dt)
                    waveform.interleaved_iq_axis_values[
                        sample_index : sample_index + sample_count
                    ] = dt
                    if dt is not None:
                        sample_index += sample_count
            elif header.wfmtype in {4, 5}:  # Digital
                waveform = DigitalWaveform()
                waveform.source_name = header.sourcename
                waveform.y_axis_units = header.verticalunits
                waveform.x_axis_spacing = header.horizontalspacing
                waveform.x_axis_units = header.horizontalUnits
                waveform.trigger_index = header.horizontalzeroindex

                sum_of_chunks = 0
                data_size = header.sourcewidth
                request = WaveformRequest(sourcename=header.sourcename, chunksize=self.chunksize)
                response_iterator = self.native.GetWaveform(request)
                dt = None
                sum_chunk_size = 0
                dt_type = self.d_datatypes[header.sourcewidth]

                waveform.y_axis_byte_values = np.empty(header.noofsamples, dtype=dt_type)
                for response in response_iterator:
                    if not self.thread_active:
                        return waveform
                    chunk_size = len(response.headerordata.chunk.data)
                    sum_chunk_size += chunk_size
                    dt = np.frombuffer(response.headerordata.chunk.data, dtype=dt_type)
                    waveform.y_axis_byte_values[
                        sum_of_chunks : sum_of_chunks + int(chunk_size / data_size)
                    ] = dt
                    if dt is not None:
                        sum_of_chunks += len(dt)

        except Exception as e:
            _logger.log(logging.ERROR if self.verbose else logging.DEBUG, "Exception: %s", e)

        return waveform

    def _should_enable_parallel_reads(self) -> bool:
        """Determine if parallel reads should be enabled based on Python version.

        Note: Python version is unlikely to be the limiting factor - the issue is
        more likely gRPC/server-side behavior. All Python 3.x versions release
        the GIL during I/O operations (including gRPC calls).

        Returns:
            True if parallel reads are supported, False otherwise.
        """
        # Python 3.8-3.12: Enable for I/O-bound gRPC calls
        # (gRPC releases GIL during I/O, so parallel reads can theoretically help)
        if sys.version_info < (3, 8):
            return False

        # Python 3.13+: Free-threaded mode available but experimental
        # Note: Free-threaded mode helps CPU-bound work, not I/O-bound
        # Since gRPC is I/O-bound and already releases GIL, free-threaded mode
        # is unlikely to help with the current hanging issues
        # The problem is more likely gRPC/server-side serialization

        # Check environment variable for explicit disable
        if os.getenv("TEKHSI_DISABLE_PARALLEL_READS", "").lower() in ("1", "true", "yes"):
            return False

        return True

    def _read_waveforms(self, headers: List[WaveformHeader], waveforms: List[Waveform]) -> int:
        """Reads the waveforms for the headers.

        Automatically chooses between sequential and parallel reads based on:
        - Number of waveforms (threshold-based)
        - Configuration settings
        - Whether parallel reads are enabled

        Args:
            headers: list of headers
            waveforms: list of waveforms
        """
        n = len(headers)

        # Decide whether to use parallel reads
        use_parallel = (
            self._parallel_reads_enabled
            and self._use_parallel_reads
            and self._read_executor is not None
            and n >= self._parallel_reads_threshold
        )

        if use_parallel:
            return self._read_waveforms_parallel(headers, waveforms)
        return self._read_waveforms_sequential(headers, waveforms)

    def _read_waveforms_sequential(
        self, headers: List[WaveformHeader], waveforms: List[Waveform]
    ) -> int:
        """Reads the waveforms sequentially (original implementation).

        Args:
            headers: list of headers
            waveforms: list of waveforms
        """
        start_time = time.perf_counter()
        n = len(headers)
        datasize = 0
        for index in range(n):
            header = headers[index]
            read_start = time.perf_counter()
            waveform = self._read_waveform(header)
            self._recordlength = waveform.record_length
            datasize += waveform.record_length * header.sourcewidth
            # TODO: reuse this variable later
            _ = (
                waveform.record_length
                * header.sourcewidth
                * 8
                / ((time.perf_counter() - read_start) * 1e6)
            )
            if self._cachedataenabled:
                self._lock_getdata.acquire()
                self._datacache[header.sourcename.lower()] = waveform
                self._lock_getdata.release()
            if self._recordlength > 0:
                waveforms.append(waveform)

        elapsed = time.perf_counter() - start_time
        self._sequential_read_time += elapsed
        self._sequential_read_count += 1

        if self.verbose:
            _logger.info(
                "Sequential read: %d waveforms in %.3f ms (avg: %.3f ms)",
                n,
                elapsed * 1000,
                (self._sequential_read_time / self._sequential_read_count) * 1000
                if self._sequential_read_count > 0
                else 0,
            )

        return datasize

    def _read_waveform_with_stub(
        self, header: WaveformHeader, native_stub: NativeDataStub
    ) -> Waveform:
        """Reads a waveform using a provided stub (thread-safe version).

        This creates a thread-local stub to avoid thread-safety issues with shared stubs.

        Args:
            header: Waveform header to read
            native_stub: NativeDataStub instance for this thread

        Returns:
            Waveform: The read waveform
        """
        # Create a temporary method that uses the provided stub instead of self.native
        # We'll need to replicate _read_waveform logic but with the stub parameter
        # For now, let's use a wrapper that creates a new stub per call
        try:
            if 0 < header.wfmtype <= 3:  # Vector  # noqa: PLR2004
                waveform = AnalogWaveform()
                waveform.source_name = header.sourcename
                waveform.y_axis_spacing = header.verticalspacing
                waveform.y_axis_offset = header.verticaloffset
                waveform.y_axis_units = header.verticalunits
                waveform.x_axis_spacing = header.horizontalspacing
                waveform.x_axis_units = header.horizontalUnits
                waveform.trigger_index = header.horizontalzeroindex

                sum_of_chunks = 0
                data_size = header.sourcewidth
                request = WaveformRequest(sourcename=header.sourcename, chunksize=self.chunksize)
                response_iterator = native_stub.GetWaveform(request)
                dt = None
                sum_chunk_size = 0
                dt_type = self.v_datatypes[header.sourcewidth]

                waveform.y_axis_values = np.empty(header.noofsamples, dtype=dt_type)
                for response in response_iterator:
                    if not self.thread_active:
                        return waveform
                    chunk_size = len(response.headerordata.chunk.data)
                    sum_chunk_size += chunk_size
                    dt = np.frombuffer(response.headerordata.chunk.data, dtype=dt_type)
                    waveform.y_axis_values[
                        sum_of_chunks : sum_of_chunks + int(chunk_size / data_size)
                    ] = dt
                    if dt is not None:
                        sum_of_chunks += len(dt)

            elif header.wfmtype in {7, 6}:  # WFMTYPE_ANALOG_IQ
                waveform = IQWaveform()
                waveform.source_name = header.sourcename
                waveform.iq_axis_spacing = header.verticalspacing
                waveform.iq_axis_offset = header.verticaloffset
                waveform.iq_axis_units = header.verticalunits
                waveform.x_axis_spacing = header.horizontalspacing
                waveform.x_axis_units = header.horizontalUnits
                waveform.trigger_index = header.horizontalzeroindex

                if header.iq_windowType == "Blackharris":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 1.9
                elif header.iq_windowType == "Flattop2":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 3.77
                elif header.iq_windowType == "Hanning":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 1.44
                elif header.iq_windowType == "Hamming":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 1.3
                elif header.iq_windowType == "Rectangle":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 0.89
                elif header.iq_windowType == "Kaiserbessel":
                    sample_rate = (header.iq_fftLength * header.iq_rbw) / 2.23
                else:
                    sample_rate = header.iq_span

                waveform.meta_info = IQWaveformMetaInfo(
                    iq_center_frequency=header.iq_centerFrequency,
                    iq_fft_length=header.iq_fftLength,
                    iq_resolution_bandwidth=header.iq_rbw,
                    iq_span=header.iq_span,
                    iq_window_type=header.iq_windowType,
                    iq_sample_rate=sample_rate,
                )

                sample_index = 0
                request = WaveformRequest(sourcename=header.sourcename, chunksize=self.chunksize)
                response_iterator = native_stub.GetWaveform(request)
                dt = None
                sum_chunk_size = 0
                dt_type = self.iq_datatypes[header.sourcewidth]

                waveform.interleaved_iq_axis_values = np.empty(header.noofsamples, dtype=dt_type)
                for response in response_iterator:
                    if not self.thread_active:
                        return waveform

                    chunk_size = len(response.headerordata.chunk.data)
                    sum_chunk_size += chunk_size
                    dt = np.frombuffer(response.headerordata.chunk.data, dtype=dt_type)
                    sample_count = len(dt)
                    waveform.interleaved_iq_axis_values[
                        sample_index : sample_index + sample_count
                    ] = dt
                    if dt is not None:
                        sample_index += sample_count
            elif header.wfmtype in {4, 5}:  # Digital
                waveform = DigitalWaveform()
                waveform.source_name = header.sourcename
                waveform.y_axis_units = header.verticalunits
                waveform.x_axis_spacing = header.horizontalspacing
                waveform.x_axis_units = header.horizontalUnits
                waveform.trigger_index = header.horizontalzeroindex

                sum_of_chunks = 0
                data_size = header.sourcewidth
                request = WaveformRequest(sourcename=header.sourcename, chunksize=self.chunksize)
                response_iterator = native_stub.GetWaveform(request)
                dt = None
                sum_chunk_size = 0
                dt_type = self.d_datatypes[header.sourcewidth]

                waveform.y_axis_byte_values = np.empty(header.noofsamples, dtype=dt_type)
                for response in response_iterator:
                    if not self.thread_active:
                        return waveform
                    chunk_size = len(response.headerordata.chunk.data)
                    sum_chunk_size += chunk_size
                    dt = np.frombuffer(response.headerordata.chunk.data, dtype=dt_type)
                    waveform.y_axis_byte_values[
                        sum_of_chunks : sum_of_chunks + int(chunk_size / data_size)
                    ] = dt
                    if dt is not None:
                        sum_of_chunks += len(dt)
            else:
                msg = f"Unknown waveform type: {header.wfmtype}"
                raise ValueError(msg)

            waveform.record_length = header.noofsamples
            return waveform
        except Exception as e:
            _logger.error("Error in _read_waveform_with_stub for %s: %s", header.sourcename, e)
            raise

    def _read_waveforms_parallel(
        self, headers: List[WaveformHeader], waveforms: List[Waveform]
    ) -> int:
        """Reads waveforms in parallel using ThreadPoolExecutor.

        EXPERIMENTAL: This may cause issues with some gRPC servers or configurations.
        Only used when parallel reads are explicitly enabled and beneficial.
        Creates a new stub per thread to avoid thread-safety issues.

        Args:
            headers: list of headers
            waveforms: list of waveforms
        """
        if not self._read_executor:
            # Fall back to sequential if executor not available
            return self._read_waveforms_sequential(headers, waveforms)

        start_time = time.perf_counter()
        n = len(headers)
        datasize = 0
        futures = {}

        try:
            # Submit all read tasks - each thread gets its own stub to avoid thread-safety issues
            for header in headers:
                if not self.thread_active:
                    break
                # Create a new stub for each thread (gRPC channels are thread-safe,
                # but stubs may not be)
                native_stub = NativeDataStub(self.channel)
                future = self._read_executor.submit(
                    self._read_waveform_with_stub, header, native_stub
                )
                futures[future] = header

            # Collect results as they complete with timeout protection
            results = {}
            timeout_seconds = 30.0  # Maximum time to wait for all reads
            deadline = time.perf_counter() + timeout_seconds

            for future in as_completed(futures, timeout=timeout_seconds):
                if time.perf_counter() > deadline:
                    _logger.warning("Parallel read timeout - cancelling remaining reads")
                    break

                if not self.thread_active:
                    # Cancel remaining if thread is stopping
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break

                try:
                    waveform = future.result(timeout=1.0)  # Individual read timeout
                    header = futures[future]
                    results[header] = waveform
                except Exception as e:
                    header = futures.get(future)
                    header_name = header.sourcename if header else "unknown"
                    _logger.warning("Error reading waveform %s: %s", header_name, e)
                    # Continue with other reads even if one fails

            # Process results in original order
            for header in headers:
                if header in results:
                    waveform = results[header]
                    if waveform.record_length > 0:
                        self._recordlength = waveform.record_length
                        datasize += waveform.record_length * header.sourcewidth

                        if self._cachedataenabled:
                            with self._lock_getdata:
                                self._datacache[header.sourcename.lower()] = waveform

                        waveforms.append(waveform)
        except Exception as e:
            _logger.error("Error in parallel read, falling back to sequential: %s", e)
            # Cancel all futures and fall back
            for f in futures:
                if not f.done():
                    f.cancel()
            # Fall back to sequential for remaining headers
            return self._read_waveforms_sequential(headers, waveforms)

        elapsed = time.perf_counter() - start_time
        self._parallel_read_time += elapsed
        self._parallel_read_count += 1

        if self.verbose:
            _logger.info(
                "Parallel read: %d waveforms in %.3f ms (avg: %.3f ms)",
                n,
                elapsed * 1000,
                (self._parallel_read_time / self._parallel_read_count) * 1000
                if self._parallel_read_count > 0
                else 0,
            )

        return datasize

    def _run(self) -> None:
        """Background thread for participating in the instruments sequence."""
        while self.thread_active and not self._is_exiting:
            waveforms = []
            headers = []

            startwait = time.perf_counter()
            try:
                self._wait_for_data_access()
                self._holding_scope_open = True
                self._lock_filter.acquire()

                try:
                    self._run_inner(headers, waveforms, startwait)
                finally:
                    self._finished_with_data_access()
                    self._lock_filter.release()
                    self._holding_scope_open = False
            except grpc.RpcError as rpc_error:
                # Server went away or connection reset; exit thread cleanly
                _logger.log(
                    logging.DEBUG if not self.verbose else logging.INFO,
                    "Background thread exiting (connection closed): %s",
                    rpc_error,
                )
                # Ensure we release lock if we bailed before releasing
                if self._holding_scope_open:
                    try:
                        self._finished_with_data_access()
                    except Exception:  # noqa: S110
                        pass
                    try:
                        self._lock_filter.release()
                    except Exception:  # noqa: S110
                        pass
                    self._holding_scope_open = False
                return

    def _run_inner(
        self, headers: List[WaveformHeader], waveforms: List[Waveform], startwait: float
    ) -> None:
        """Background thread for participating in the instruments sequence.

        Args:
            headers: list of headers
            waveforms: list of waveforms
            startwait: start time
        """
        datasize = 0
        datawidth = 1
        start = time.perf_counter()
        header_dict = {}

        try:
            if self._cachedataenabled:
                self._lock.acquire(blocking=True)

            if self._is_exiting:
                return

            self._read_headers(headers, header_dict)

            cur_acq_id = self._acq_id(headers)

            if cur_acq_id is None or self._prev_data_id == cur_acq_id:
                return

            self._prev_data_id = cur_acq_id

            if self._filter is not None and not self._filter(self._headers, header_dict):
                self._headers = header_dict
                return

            if len(headers) > 0:
                datawidth = headers[0].sourcewidth

            if self._is_exiting:
                return

            self._headers = header_dict
            datasize += self._read_waveforms(headers, waveforms)
            duration = time.perf_counter() - start
        except Exception as ex:
            _logger.log(
                logging.ERROR if self.verbose else logging.DEBUG, "exception:_run_inner:%s", ex
            )
            # We're exiting so silence any issues and not
            # accumulate bad stats or send bad data
            return

        finally:
            if self._cachedataenabled:
                self._acqtime = self.current_time
                self._lock.release()

        try:
            if len(waveforms) > 0 and self._connected and not self._is_exiting:
                self.data_arrival(waveforms)
                if self._callback is not None:
                    self._callback(waveforms)

        except Exception as ex:
            _logger.log(
                logging.ERROR if self.verbose else logging.DEBUG, "exception:_run_inner:%s", ex
            )

        if self._connected and not self._is_exiting:
            self._acqcount += 1
            self._instrumentation(time.perf_counter() - startwait, duration, datasize, datawidth)

    def _wait_for_acq_time(self, after: float) -> None:
        """Waits until both a new acquisition has arrived, and it is later than after.

        Args:
            after (float): Acquisition must occur after this time
        """
        while len(self._datacache) <= 0 or after > self._acqtime:
            self._wait_next_acq()
            if len(self._datacache) <= 0 or after > self._acqtime:
                self._done_with_data_release_lock()
                time.sleep(0.0001)
        self._wait_for_data_count += 1

    def _wait_for_any_acq(self) -> None:
        """Waits for any data to arrive.

        This does not guarantee the data returned is a new acquisition
        """
        while self._acqcount <= 0 or len(self._datacache) <= 0:
            self._wait_next_acq()
            if self._acqcount <= 0 or len(self._datacache) <= 0:
                self._done_with_data_release_lock()
                time.sleep(0.0001)
        self._wait_for_data_count += 1

    def _wait_for_data_access(self) -> None:
        """Waits for instrument server to give the gRPC service a chance at the datastore."""
        self._in_wait_for_data = True

        _logger.debug("wait_for_data_access")

        request = ConnectRequest(name=self.clientname)
        self.connection.WaitForDataAccess(request)

    def _wait_for_new_data(self) -> None:
        """Waits for either data from a new acquisition or returns if there.

        is previously unseen data.
        """
        if len(self._datacache) > 0 and self._lastacqseen < self._acqcount:
            self._lock.acquire(blocking=True)
            self._wait_for_data_holds_lock = True
            if self._wait_for_data_count <= 0:
                self._wait_for_data_count = 1
        else:
            self._wait_for_next_acq()

    def _wait_for_next_acq(self) -> None:
        """Waits for the next, new acquisition to arrive."""
        while len(self._datacache) <= 0 or self._lastacqseen >= self._acqcount:
            self._wait_next_acq()
            if len(self._datacache) <= 0 or self._lastacqseen >= self._acqcount:
                self._done_with_data_release_lock()
                time.sleep(0.0001)
        self._wait_for_data_count += 1

    def _wait_next_acq(self) -> None:
        self._lock.acquire(blocking=True)
        self._wait_for_data_holds_lock = True

    ################################################################################################
    # Register Methods
    ################################################################################################
    # TODO: is this method actually necessary?
    @staticmethod
    @register
    def _terminate() -> None:
        """Terminate the connection to the instrument.

        Cleans up mess on termination if possible - this is required
        to keep the scope from hanging
        """
        for key in TekHSIConnect._connections:  # pylint:disable=consider-using-dict-items
            with contextlib.suppress(Exception):
                if TekHSIConnect._connections[key]._holding_scope_open:  # noqa: SLF001
                    TekHSIConnect._connections[key]._finished_with_data_access()  # noqa: SLF001
            with contextlib.suppress(Exception):
                TekHSIConnect._connections[key].close()
