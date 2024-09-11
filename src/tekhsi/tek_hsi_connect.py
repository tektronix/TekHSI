"""Module for connecting to Tektronix instruments and retrieving waveform data using gRPC."""

import contextlib
import threading
import time
import uuid

from atexit import register
from enum import Enum
from typing import ClassVar, Dict, List, Optional

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
from tekhsi.helpers.functions import print_with_timestamp


class AcqWaitOn(Enum):
    """This defines enumeration for wait_for_data."""

    NextAcq = 1
    """Wait for the next acquisition."""
    Time = 2
    """Wait for a specific time."""
    AnyAcq = 3
    """Wait for any acquisition."""
    NewData = 4
    """Wait for new data."""


class TekHSIConnect:  # pylint:disable=too-many-instance-attributes
    """Support for Tektronix highspeed data API.

    - this API is intended to aid in retrieving data from instruments as fast as possible.
    """

    _connections: ClassVar[Dict[str, "TekHSIConnect"]] = {}

    ################################################################################################
    # Magic Methods
    ################################################################################################
    def __init__(self, url: str, activesymbols=None, callback=None, data_filter=None):
        """Initialize a connection to a Tektronix instrument using gRPC.

        Args:
           url (str): The URL of the gRPC server.
           activesymbols (list, optional): List of active symbols to monitor.
           callback (function, optional): Callback function to handle incoming data.
           data_filter (function, optional): Filter function to apply to incoming data.
        """
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

        TekHSIConnect._connections[self.clientname] = self

        if not activesymbols:
            self.activesymbols = self._available_symbols()
        else:
            self.activesymbols = [x.lower() for x in activesymbols]

        self.thread = threading.Thread(target=self._run, args=())
        self.thread.daemon = True
        self.thread.start()

    def __enter__(self):
        """Enter the runtime context related to this object.

        Returns:
            The object itself.
        """
        # Required for "with" command to work with this class
        if self.verbose:
            print_with_timestamp("enter()")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context related to this object.

        Args:
            exc_type: The exception type.
            exc_val: The exception value.
            exc_tb: The traceback object.
        """
        # Required for "with" command to work with this class

        self._is_exiting = True

        if self.verbose:
            print_with_timestamp("exit()")

        self.close()

        if self._instrument and self._sum_count > 0:
            print_with_timestamp(
                f"Average Update Rate:{(1 / (self._sum_acq_time / self._sum_count)):.2f}, "
                f"Data Rate:{(self._sum_data_rate / self._sum_count):.2f}Mbs",
            )

    ################################################################################################
    # Properties - Private and Public
    ################################################################################################
    @property
    def available_symbols(self) -> List[str]:
        """Returns the list of available symbols on the instrument.

        Returns:
            List[str]: List of available symbols.
        """
        return self._available_symbols()

    @property
    def current_time(self) -> float:
        """This property returns time relative to the connection to the gRPC client.

        Returns:
            float: current time relative to the start time of the gRPC client
        """
        return time.time() - self._start_time

    @property
    def instrumentation_enabled(self) -> bool:
        """Indicates if instrumentation is enabled.

        Returns:
            True if instrumentation is enabled, False otherwise.
        """
        return self._instrument

    @instrumentation_enabled.setter
    def instrumentation_enabled(self, value: bool):
        """Sets the instrumentation enabled state.

        Args:
            value: True to enable instrumentation, False to disable.
        """
        self._instrument = value

    @property
    def source_names(self) -> List[str]:
        """Returns the list of names of sources on the instrument.

        Returns:
            List[str]: list of sources
        """
        return self.activesymbols

    @property
    def verbose(self) -> bool:
        """Indicates if verbose mode is enabled.

        Returns:
            True if verbose mode is enabled, False otherwise.
        """
        return self._verbose

    @verbose.setter
    def verbose(self, value: bool):
        """Sets the verbose mode state.

        Args:
            value: True to enable verbose mode, False to disable.
        """
        self._verbose = value

    ################################################################################################
    # Context Manager Methods
    ################################################################################################
    @contextlib.contextmanager
    def access_data(self, on: AcqWaitOn = AcqWaitOn.NewData, after: float = -1):
        """Grants access to data.

        Must be called as part of a with command to grant access for get_data().

        Args:
            on: Criterion for acceptance. Defaults to AcqWaitOn.NewData.
            after: Additional criterion when AcqWaitOn.Time is passed. Defaults to -1.
        """
        try:
            self.wait_for_data(on, after)
            yield self
        finally:
            self.done_with_data()

    ################################################################################################
    # Public Methods
    ################################################################################################
    @staticmethod
    def any_acq(
        previous_header: Dict[str, WaveformHeader],  # noqa: ARG004
        current_header: Dict[str, WaveformHeader],  # noqa: ARG004
    ) -> bool:
        """Prebuilt acq acceptance filter that accepts all new acqs.

        Args:
            previous_header: Previous header.
            current_header: Current header.

        Returns:
            True if the acquisition is accepted, False otherwise.
        """
        return True

    @staticmethod
    def any_horizontal_change(
        previous_header: Dict[str, WaveformHeader],
        current_header: Dict[str, WaveformHeader],
    ) -> bool:
        """Acq acceptance filter that accepts only acqs with changes to horizontal settings.

        Args:
            previous_header (dict[str, WaveformHeader]): Previous header dictionary.
            current_header (dict[str, WaveformHeader]): Current header dictionary.

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

    @staticmethod
    def any_vertical_change(
        previous_header: Dict[str, WaveformHeader],
        current_header: Dict[str, WaveformHeader],
    ) -> bool:
        """Prebuilt acq acceptance filter that accepts only acqs with changes to vertical settings.

        Args:
            previous_header (dict[str, WaveformHeader]): Previous header dictionary.
            current_header (dict[str, WaveformHeader]): Current header dictionary.

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

    def close(self):
        """Close and clean up gRPC connection."""
        if not self._connected:
            return

        if self.verbose:
            print_with_timestamp("close")

        # This will force the scope to give the background
        # thread access to data. That should cause it to exit.
        try:
            self.thread_active = False
            self.force_sequence()
            # Wait for thread to exit
            self.thread.join(20.0)
        except RuntimeError as error:
            # Handle specific exceptions related to threading
            if self.verbose:
                msg = f"Thread error: {error}"
                print_with_timestamp(msg)

        try:
            # Take this connection out of the connection list
            if self.clientname in TekHSIConnect._available_symbols(self):
                del TekHSIConnect._available_symbols[self.clientname]  # pylint:disable=unsupported-delete-operation
        except KeyError as error:
            # Handle specific exception if the key is not found
            if self.verbose:
                msg = f"Key error: {error}"
                print_with_timestamp(msg)

        if self.verbose:
            print_with_timestamp("disconnect")

        # disconnect from the instrument
        self._disconnect()

    @staticmethod
    def data_arrival(waveforms: List[Waveform]) -> None:  # noqa: ARG004
        """Available to be overridden if user wants to create a derived class.

        This method will be called on every accepted acq.

        Args:
            waveforms: List of waveforms.
        """
        return

    def done_with_data(self):
        """Releases the acquisition after accessing the required data."""
        if not self._cachedataenabled:
            return

        if self._wait_for_data_count <= 0:
            if self.verbose:
                print_with_timestamp("** done_with_data called when no wait_for_data pending")
            return

        self._wait_for_data_count -= 1
        self._lastacqseen = self._acqcount
        self._done_with_data_release_lock()
        return

    def force_sequence(self) -> None:
        """force_sequence asks the instrument to please give us access.

        to the current acquisition data. This is useful when connecting to a stopped instrument to
        get access to the currently available data. Otherwise, the API will wait until the next
        acquisition.
        """
        if self.verbose:
            print_with_timestamp("force sequence")
        request = ConnectRequest(name=self.clientname)
        self.connection.RequestNewSequence(request)

    def get_data(self, name: str) -> Optional[Waveform]:
        """Returns the saved data of the previous acquisition with the data item.

        of the requested name.

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

    def set_acq_filter(self, acq_filter):
        """Sets rules for acquisitions that are accepted and forwarded.

        This is to allow only import data changes to be passed to the callback or saved to backing
        store.

        Args:
            acq_filter  (function): A function that takes two headers and returns True if the data
        """
        if acq_filter is None:
            raise ValueError("Filter cannot be None")

        self._lock_filter.acquire()
        self._filter = acq_filter
        self._lastacqseen = self._acqcount
        self._lock_filter.release()

    def wait_for_data(self, on: AcqWaitOn = AcqWaitOn.NewData, after: float = -1):
        """Waits until specified acquisition criterion is met.

        Args:
            on (AcqWaitOn, optional): criterion for acceptance. Defaults to AcqWaitOn.NewData.
            after (float, optional): additional criterion when AcqWaitOn.Time is passed.
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
    def _acq_id(headers: List[WaveformHeader]):
        """Retrieve the data ID from the first header in the list.

        Args:
            headers (List[WaveformHeader]): List of waveform headers.

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
        if self.verbose:
            print_with_timestamp("connect")
        request = ConnectRequest(name=self.clientname)
        self.connection.Connect(request)

    def _disconnect(self) -> None:
        """Disconnect from gRPC server."""
        if not self._connected:
            return
        self._connected = False
        if self.verbose:
            print_with_timestamp("disconnect")
        request = ConnectRequest(name=self.clientname)
        self.connection.Disconnect(request)

    def _done_with_data_release_lock(self):
        """Releases the lock after accessing the required data."""
        if self._wait_for_data_holds_lock:
            self._lock.release()
            self._wait_for_data_holds_lock = False

    def _instrumentation(self, acqtime, transfertime, datasize, datawidth) -> None:
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
            print(
                f"UpdateRate:{(1 / acqtime):.2f},"
                f"Data Rate:{((datasize * 8 / 1e6) / transfertime):.2f}Mbs,Data Width:{datawidth}",
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
        """Releases access to instrument data - this is required
        to allow the instrument to continue acquiring
        """
        if not self._in_wait_for_data:
            return

        if self.verbose:
            print_with_timestamp("finished_with_data_access")

        request = ConnectRequest(name=self.clientname)
        self.connection.FinishedWithDataAccess(request)

    def _read_header(self, name: str) -> WaveformHeader:
        """Reads header for the named source.

        Args:
            name (str): name of header

        Returns:
            WaveformHeader: the description of the properties of the specified waveform
        """
        if self.verbose:
            print(f"{name}:read header")
        request = WaveformRequest(sourcename=name, chunksize=self.chunksize)
        response = self.native.GetHeader(request)
        return response.headerordata.header

    def _read_headers(self, headers, header_dict: dict):
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
    def _read_waveform(self, header: WaveformHeader):  # noqa: C901,PLR0912,PLR0915
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
            if self.verbose:
                print_with_timestamp(f"Exception: {e}")

        return waveform

    def _read_waveforms(self, headers, waveforms):
        """Reads the waveforms for the headers.

        Args:
            headers (list): list of headers
            waveforms (list): list of waveforms
        """
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
        return datasize

    def _run(self):
        """Background thread for participating in the instruments sequence."""
        while self.thread_active and not self._is_exiting:
            waveforms = []
            headers = []

            startwait = time.perf_counter()
            self._wait_for_data_access()
            self._holding_scope_open = True
            self._lock_filter.acquire()

            try:
                self._run_inner(headers, waveforms, startwait)
            finally:
                self._finished_with_data_access()
                self._lock_filter.release()
                self._holding_scope_open = False

    def _run_inner(self, headers, waveforms, startwait):  # noqa: C901,PLR0912
        """Background thread for participating in the instruments sequence.

        Args:
            headers (list): list of headers
            waveforms (list): list of waveforms
            startwait (float): start time
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
            if self.verbose:
                print_with_timestamp(f"exception:_run_inner:{ex}")
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
            if self.verbose:
                print_with_timestamp(f"exception:_run_inner:{ex}")

        if self._connected and not self._is_exiting:
            self._acqcount += 1
            self._instrumentation(time.perf_counter() - startwait, duration, datasize, datawidth)

    def _wait_for_acq_time(self, after: float) -> None:
        """Waits until both a new acquisition has arrived and it is later than after.

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
        """Waits for instrument server to give the gRPC service a
        chance at the datastore.
        """
        self._in_wait_for_data = True

        if self.verbose:
            print("wait_for_data_access")

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

    def _wait_next_acq(self):
        self._lock.acquire(blocking=True)
        self._wait_for_data_holds_lock = True

    ################################################################################################
    # Register Methods
    ################################################################################################
    @staticmethod
    @register
    def _terminate():
        """Cleans up mess on termination if possible - this is required
        to keep the scope from hanging
        """
        for key in TekHSIConnect._connections:  # pylint:disable=consider-using-dict-items
            with contextlib.suppress(Exception):
                if TekHSIConnect._connections[key]._holding_scope_open:
                    TekHSIConnect._connections[key]._finished_with_data_access()
            with contextlib.suppress(Exception):
                TekHSIConnect._connections[key].close()
