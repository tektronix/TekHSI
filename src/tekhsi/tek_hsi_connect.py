"""Module for connecting to Tektronix instruments and retrieving waveform data using gRPC."""

# Explicit intermediate values make connection and stream parsing branches easier to
# inspect while debugging instrument responses.
# pylint: disable=consider-using-assignment-expr,too-many-locals

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
from typing import ClassVar, NoReturn, TYPE_CHECKING, TypeVar

import grpc
import numpy as np

from tm_data_types import (
    AnalogWaveform,
    DigitalWaveform,
    FastFrameAnalogWaveform,
    FastFrameDigitalWaveform,
    FrameTimingInfo,
    IQWaveform,
    IQWaveformMetaInfo,
    SummaryFrameType,
    Waveform,
)

from tekhsi._tek_highspeed_server_pb2 import (  # pylint: disable=no-name-in-module
    ConnectRequest,
    WaveformHeader,
    WaveformRequest,
    WfmReplyStatus,
)
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub, NativeDataStub
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import TekCredentialStore
from tekhsi.helpers.enums import WaveformType  # Added for enum-based waveform type checks
from tekhsi.helpers.logging import configure_logging
from tekhsi.load_timing import (
    CAPABILITY_FASTFRAME,
    FastFrameLoadTiming,
    REPLY_CONTENT_MASK_FRAME_METADATA,
    WaveformTransferTiming,
)
from tekhsi.security import (  # pylint: disable=import-private-name
    _auto_negotiate_channel,
    _build_creds_from_entry,
    _call_on_trust,
    _fetch_server_cert,
    _parse_host_port,
    _resolve_credentials_from_store,
    _secure_channel,
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekHSICredentials,
    TekSecurityError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import TracebackType
    from typing import Any

    from typing_extensions import Self

_logger = logging.getLogger(__name__)

# Retries for placeholder headers returned before metadata is committed after
# WaitForDataAccess (live scopes may grant access slightly before GetHeader is ready).
_HEADER_PENDING_MAX_ATTEMPTS = 50
_HEADER_PENDING_RETRY_SLEEP_S = 0.002
_LOGIN_INDEX = 2
_ON_TRUST_PROMPT_INDEX = 2
_DATA_FILTER_INDEX = 2
_VECTOR_WAVEFORM_MAX_TYPE = 3

AnyWaveform = TypeVar("AnyWaveform", bound=Waveform)


def _normalize_constructor_args(
    legacy_args: tuple[object, ...], security_options: dict[str, object]
) -> tuple[object, object, object, tuple[object, ...]]:
    """Separate legacy waveform arguments from positional security arguments."""
    if len(legacy_args) > 7:  # noqa: PLR2004
        msg = "At most seven positional arguments after url are supported"
        raise TypeError(msg)
    activesymbols = security_options.pop("activesymbols", legacy_args[0] if legacy_args else None)
    callback = security_options.pop("callback", legacy_args[1] if len(legacy_args) > 1 else None)
    data_filter = security_options.pop(
        "data_filter",
        legacy_args[_DATA_FILTER_INDEX] if len(legacy_args) > _DATA_FILTER_INDEX else None,
    )
    return activesymbols, callback, data_filter, legacy_args[3:]


def any_acq(
    _previous_header: dict[str, WaveformHeader],
    _current_header: dict[str, WaveformHeader],
) -> bool:
    """Prebuilt acquisition acceptance filter that accepts all new acquisitions."""
    return True


# --8<-- [start:any_horizontal_change]
def any_horizontal_change(
    previous_header: dict[str, WaveformHeader],
    current_header: dict[str, WaveformHeader],
) -> bool:
    """Accept acquisitions with changes to horizontal settings."""
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


def any_vertical_change(
    previous_header: dict[str, WaveformHeader],
    current_header: dict[str, WaveformHeader],
) -> bool:
    """Accept acquisitions with changes to vertical settings."""
    for key, cur in current_header.items():
        if key not in previous_header:
            return True
        prev = previous_header[key]
        if prev is not None and (
            prev.verticalspacing != cur.verticalspacing or prev.verticaloffset != cur.verticaloffset
        ):
            return True
        if prev is None and cur is not None:
            return True
    return False


def _raise_unknown_waveform_type(waveform_type: int) -> NoReturn:
    """Raise the standard error for an unsupported waveform type."""
    msg = f"Unknown waveform type: {waveform_type}"
    raise ValueError(msg)


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
    [`access_data(AcqWaitOn.NextAcq)`][tekhsi.tek_hsi_connect.TekHSIConnect.access_data].

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
    stored acquisition has not been read by
    [`get_data()`][tekhsi.tek_hsi_connect.TekHSIConnect.get_data]. This is
    import since the underlying data is buffered because it's stored as data on the instrument is
    available. If you have seen the underlying data since the last
    [`get_data()`][tekhsi.tek_hsi_connect.TekHSIConnect.get_data] call,
    it will return the buffered data. If you
    haven't seen the data, it will block until the next new piece of data arrives.

    Examples:
        >>> from tekhsi import AcqWaitOn, TekHSIConnect
        >>> with TekHSIConnect("192.168.0.1:5000") as connection:
        ...     with connection.access_data(AcqWaitOn.NewData):
        ...         ...
    """


class TekHSIConnect:  # pylint:disable=too-many-instance-attributes,too-many-public-methods
    """Support for Tektronix High-Speed Interface data API.

    - This API is intended to aid in retrieving data from instruments as fast as possible.
    """

    _connections: ClassVar[dict[str, "TekHSIConnect"]] = {}

    @staticmethod
    def any_acq(
        previous_header: dict[str, WaveformHeader], current_header: dict[str, WaveformHeader]
    ) -> bool:
        """Accept all new acquisitions."""
        return any_acq(previous_header, current_header)

    @staticmethod
    def any_horizontal_change(
        previous_header: dict[str, WaveformHeader], current_header: dict[str, WaveformHeader]
    ) -> bool:
        """Accept acquisitions with changes to horizontal settings."""
        return any_horizontal_change(previous_header, current_header)

    @staticmethod
    def any_vertical_change(
        previous_header: dict[str, WaveformHeader], current_header: dict[str, WaveformHeader]
    ) -> bool:
        """Accept acquisitions with changes to vertical settings."""
        return any_vertical_change(previous_header, current_header)

    ################################################################################################
    # Magic Methods
    ################################################################################################
    def __init__(  # noqa: PLR0912, PLR0915
        self, url: str, *legacy_args: object, **security_options: object
    ) -> None:
        """Initialize a connection to a Tektronix instrument using gRPC.

        Args:
            url: The IP Address and port of the TekHSI server.
            legacy_args: Legacy positional arguments for symbols, callbacks, filters, and
                positional security credentials.
            security_options: Keyword options for credentials, credential stores, trust prompts,
                TLS requirements, and security-negotiation timeout.
        """
        activesymbols, callback, data_filter, security_args = _normalize_constructor_args(
            legacy_args, security_options
        )
        if len(security_args) > 3:  # noqa: PLR2004
            msg = "At most three positional security arguments are supported"
            raise TypeError(msg)
        credentials = security_options.pop(
            "credentials", security_args[0] if len(security_args) > 0 else None
        )
        credential_store = security_options.pop(
            "credential_store", security_args[1] if len(security_args) > 1 else None
        )
        on_trust_prompt = security_options.pop(
            "on_trust_prompt",
            security_args[_ON_TRUST_PROMPT_INDEX]
            if len(security_args) > _ON_TRUST_PROMPT_INDEX
            else None,
        )
        require_tls = security_options.pop("require_tls", False)
        timeout = security_options.pop("timeout", 10.0)
        if security_options:
            unexpected = next(iter(security_options))
            msg = f"Unexpected security option: {unexpected}"
            raise TypeError(msg)

        # Configure logging in case it hasn't been done yet
        configure_logging()

        self.previous_headers = []
        self.chunksize = 80000
        self.url = url
        self.v_datatypes = {1: np.int8, 2: np.int16, 4: np.float32, 8: np.double}
        self.iq_datatypes = {1: np.int8, 2: np.int16, 4: np.int32}
        # Public and internal digital datatype mappings are kept in sync.
        self.d_datatypes = {1: np.int8}
        self._digital_datatypes = {1: np.int8, 2: np.int16}

        _legacy_plain = (
            credentials is None
            and credential_store is None
            and on_trust_prompt is None
            and not require_tls
        )
        if _legacy_plain:
            self.channel = grpc.insecure_channel(url)
            self._credential_store_ref = None
            self._on_trust_ref = None
            self._auto_security = False
        else:
            deadline = time.time() + max(1.0, float(timeout))
            store_for_auto = (
                credential_store if credential_store is not None else TekCredentialStore()
            )
            if credentials is not None:
                if isinstance(credentials, TekHSICredentials) and getattr(
                    credentials, "_use_store", False
                ):
                    if credential_store is None:
                        msg = "credential_store is required when credentials use the store"
                        raise ValueError(msg)
                    creds = _resolve_credentials_from_store(
                        url,
                        credential_store,
                        credentials.store_mode,
                        on_trust_prompt,
                        deadline,
                    )
                    entry = credential_store.get(url)
                    self.channel = _secure_channel(url, creds, entry=entry)
                    self._credential_store_ref = credential_store
                    self._on_trust_ref = on_trust_prompt
                    self._auto_security = True
                else:
                    if isinstance(credentials, TekHSICredentials):
                        creds = credentials.grpc_credentials()
                    else:
                        creds = credentials
                    tls_name = (
                        credentials.tls_server_name
                        if isinstance(credentials, TekHSICredentials)
                        else None
                    )
                    self.channel = _secure_channel(url, creds, tls_server_name=tls_name)
                    self._credential_store_ref = store_for_auto
                    self._on_trust_ref = None
                    self._auto_security = False
            else:
                self.channel = _auto_negotiate_channel(
                    url,
                    store_for_auto,
                    on_trust_prompt,
                    require_tls=require_tls,
                    deadline=deadline,
                    timeout=timeout,
                )
                self._credential_store_ref = store_for_auto
                self._on_trust_ref = on_trust_prompt
                self._auto_security = True

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
        self._available_symbol_names: list[str] | None = None
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
        self._protocol_version = 0
        self._capabilities = 0
        self._connect()
        self._connected = True

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

        self._cache_available_symbols()
        if not activesymbols:
            self.activesymbols = self._available_symbols()
        else:
            self.activesymbols = [self._resolve_symbol(x) for x in activesymbols]

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
        exc_type: type[BaseException] | None,
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
    def available_symbols(self) -> list[str]:
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

        When a channel is digital-only, the scope may expose `chN_DAll` without a plain `chN`
        symbol. TekHSI resolves that common mistake automatically when `chN` is requested but only
        `chN_DAll` is available (not when both symbols exist).

        Returns:
            A list of available symbols.
        """
        return self._available_symbols()

    @staticmethod
    def _resolve_symbol_name(
        name: str,
        available: frozenset[str],
    ) -> tuple[str, str | None]:
        """Map a user symbol to an available TekHSI name when cheaply inferable.

        Returns:
            ``(resolved_name, aliased_from)`` where ``aliased_from`` is set when ``name`` was
            mapped (for example ``ch2`` -> ``ch2_dall``).
        """
        key = name.lower()
        if key in available:
            return key, None
        digital_bundle = f"{key}_dall"
        if digital_bundle in available:
            return digital_bundle, key
        return key, None

    def _resolve_symbol(self, name: str) -> str:
        """Resolve ``name`` against cached available symbols."""
        available = frozenset(self._cache_available_symbols())
        resolved, alias_from = self._resolve_symbol_name(name, available)
        if alias_from is not None:
            _logger.debug("Resolved symbol %r -> %r (digital bundle)", alias_from, resolved)
        return resolved

    @property
    def protocol_version(self) -> int:
        """Server protocol version reported at connect (200 = v2.0)."""
        return self._protocol_version

    @property
    def capabilities(self) -> int:
        """Server capability bitmask from connect (bit 0 = FastFrame)."""
        return self._capabilities

    @property
    def fastframe_capable(self) -> bool:
        """True when the connected server advertises FastFrame support."""
        return bool(self._capabilities & CAPABILITY_FASTFRAME)

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
    def source_names(self) -> list[str]:
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

    @contextlib.contextmanager
    def access_stopped_data(self) -> Self:
        """Grant access to waveform data on a stopped scope.

        TekHSI blocks on ``WaitForDataAccess`` until the instrument offers a sequence.
        On a stopped scope (including stopped FastFrame captures), call
        ``RequestNewSequence`` via ``force_sequence()`` before waiting for data.
        """
        self.force_sequence()
        with self.access_data(AcqWaitOn.NewData):
            yield self

    ################################################################################################
    # Public Methods
    ################################################################################################

    def active_symbols(self, symbols: list[str]) -> None:
        """Sets symbols to consider moving from instrument into data cache.

        Args:
            symbols (list[str]): list of symbols to be moved
        """
        self.activesymbols = [self._resolve_symbol(x) for x in symbols]

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
            self.thread.join(20.0)
        except RuntimeError as error:
            # Handle specific exceptions related to threading
            _logger.log(logging.ERROR if self.verbose else logging.DEBUG, "Thread error: %s", error)

        try:
            # NOTE: Investigate this block; it may not work as intended.
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
            except Exception:
                _logger.exception("Error shutting down read executor")
            finally:
                self._read_executor = None

        # disconnect from the instrument
        self._disconnect()

    @staticmethod
    def data_arrival(waveforms: list[AnyWaveform]) -> None:  # noqa: ARG004
        """Available to be overridden if user wants to create a derived class.

        This method will be called on every accepted acq.

        Args:
            waveforms: list of waveforms.
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
        [`available_symbols`][tekhsi.tek_hsi_connect.TekHSIConnect.available_symbols] property,
        however, the names are case-insensitive.

        Args:
            name: Name of the data item.

        Returns:
            The waveform data or None if caching is off or data is not found.
        """
        if not self._cachedataenabled:
            return None  # Return None if caching off.

        self._lock_getdata.acquire()
        try:
            key = name.lower()
            retval = self._datacache.get(key)
            if retval is None:
                resolved = self._resolve_symbol(name)
                if resolved != key:
                    retval = self._datacache.get(resolved)
        finally:
            self._lock_getdata.release()
        return retval

    def get_frame(
        self,
        name: str,
        frame_index: int,
    ) -> AnyWaveform | None:
        """Return a single frame view from a cached FastFrame capture.

        All frames are loaded when the waveform is first read; this does not
        perform additional instrument I/O. ``frame()`` returns ``AnalogWaveform`` or
        ``DigitalWaveform`` views for analog and digital FastFrame captures.
        """
        cached = self.get_data(name)
        if cached is None:
            return None
        if isinstance(cached, (FastFrameAnalogWaveform, FastFrameDigitalWaveform)):
            return cached.frame(frame_index)
        return cached

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
    def _acq_id(headers: list[WaveformHeader]) -> int | None:
        """Retrieve the data ID from the first header in the list.

        Args:
            headers: list of waveform headers.

        Returns:
            The data ID of the first header, or None if the list is empty.
        """
        for header in headers:
            return header.dataid
        return None

    def _cache_available_symbols(self) -> list[str]:
        """Fetch and cache available symbol names from the instrument."""
        if self._available_symbol_names is None:
            request = ConnectRequest(name=self.clientname)
            response = self.connection.RequestAvailableNames(request)
            self._available_symbol_names = [symbol.lower() for symbol in response.symbolnames]
        return self._available_symbol_names

    def _available_symbols(self) -> list[str]:
        """Returns the list of available channels.

        Returns:
            list of available channels.
        """
        return list(self._cache_available_symbols())

    def _connect(self) -> None:
        """Connect to the gRPC server, upgrading to Mode 3 if the server demands auth."""
        _logger.debug("connect")
        request = ConnectRequest(name=self.clientname)
        upgrade_done = False
        while True:
            try:
                reply = self.connection.Connect(request)
                self._protocol_version = reply.protocol_version
                self._capabilities = reply.capabilities
                if self._verbose and self._protocol_version:
                    _logger.info(
                        "Connected: protocol v%s, capabilities=0x%04x%s",
                        self._protocol_version / 100,
                        self._capabilities,
                        ", FastFrame" if self.fastframe_capable else "",
                    )
            except grpc.RpcError as e:
                if (
                    e.code() == grpc.StatusCode.UNAUTHENTICATED  # pylint: disable=no-member
                    and getattr(self, "_auto_security", False)
                    and not upgrade_done
                ):
                    self._upgrade_channel_with_token_after_unauthenticated()
                    upgrade_done = True
                    continue
                if e.code() == grpc.StatusCode.UNAUTHENTICATED:  # pylint: disable=no-member
                    if getattr(self, "_auto_security", False):
                        detail = (e.details() or "").strip() or "UNAUTHENTICATED"
                        if upgrade_done:
                            detail = (
                                f"{detail} "
                                "(Check Mode 3 password matches the server's --password; "
                                f"Basic username defaults to {DEFAULT_MODE3_USERNAME}.)"
                            )
                        raise TekAuthenticationFailed(self.url, detail) from e
                    raise
                raise
            return

    def _upgrade_channel_with_token_after_unauthenticated(self) -> None:
        """After Connect returns UNAUTHENTICATED on TLS, prompt for password and retry channel."""
        store = self._credential_store_ref
        cb = self._on_trust_ref
        if store is None or cb is None:
            raise TekAuthenticationFailed(
                self.url,
                "Authentication required; provide on_trust_prompt or store password for this host.",
            )
        entry = store.get(self.url)
        if not entry or not entry.get("cert_path"):
            raise TekAuthenticationFailed(
                self.url,
                "Authentication required but no stored certificate for this host.",
            )
        host, port = _parse_host_port(self.url)
        live = _fetch_server_cert(host, port, timeout=8.0)
        fp = entry.get("cert_fingerprint")
        if fp and live.cert_fingerprint != fp:
            raise TekCertificateMismatch(self.url, fp, live.cert_fingerprint)
        result = _call_on_trust(cb, self.url, live, auth_required=True)
        password: str | None = None
        login: str | None = None
        if isinstance(result, (list, tuple)):
            if len(result) >= 1 and result[0]:
                password = result[1] if len(result) > 1 else None
                login = result[_LOGIN_INDEX] if len(result) > _LOGIN_INDEX else None
                if not login:
                    login = None
        elif result is True:
            password = None
        else:
            raise TekAuthenticationFailed(self.url, "Authentication declined in on_trust_prompt.")
        if not password:
            raise TekAuthenticationFailed(
                self.url,
                "Server requires a password; when auth_required is True, return "
                "(True, password) or (True, password, login) from on_trust_prompt.",
            )
        store.set(
            self.url,
            password=password,
            login=login if login is not None else DEFAULT_MODE3_USERNAME,
        )
        store.save()
        entry2 = store.get(self.url)
        if not entry2 or not entry2.get("cert_path"):
            msg = "Store update failed after authentication prompt."
            raise TekSecurityError(msg)
        with contextlib.suppress(Exception):
            self.channel.close()
        self.channel = _secure_channel(
            self.url, _build_creds_from_entry(entry2, "token"), entry=entry2
        )
        self.connection = ConnectStub(self.channel)
        self.native = NativeDataStub(self.channel)

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
        with contextlib.suppress(Exception):
            _logger.log(
                logging.WARNING if self.verbose else logging.DEBUG,
                "Unexpected error during disconnect",
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
            and (header.hasdata or bool(header.num_frames and header.num_frames > 1))
        )

    @staticmethod
    def _is_pending_header(header: WaveformHeader) -> bool:
        """True when the instrument granted access before header metadata is ready."""
        return header is not None and not header.noofsamples and not header.sourcename

    def _finished_with_data_access(self) -> None:
        """Releases access to instrument data.

        This is required to allow the instrument to continue acquiring
        """
        if not self._in_wait_for_data:
            return

        _logger.debug("finished_with_data_access")

        request = ConnectRequest(name=self.clientname)
        self.connection.FinishedWithDataAccess(request)

    @staticmethod
    def _make_waveform_request(
        sourcename: str,
        chunksize: int,
        *,
        stream_all_frames: bool = False,
        include_frame_metadata: bool = False,
    ) -> WaveformRequest:
        """Build a WaveformRequest using the v2 reply_content_mask fields."""
        reply_content_mask = REPLY_CONTENT_MASK_FRAME_METADATA if include_frame_metadata else 0
        return WaveformRequest(
            sourcename=sourcename,
            chunksize=chunksize,
            reply_content_mask=reply_content_mask,
            stream_all_frames=stream_all_frames,
        )

    @staticmethod
    def _waveform_kind_from_header(header: WaveformHeader) -> str:
        if header.wfmtype in {WaveformType.DIGITAL, WaveformType.DIGITAL_16}:
            return "digital"
        if header.wfmtype in {WaveformType.ANALOG_IQ, WaveformType.ANALOG_16_IQ}:
            return "iq"
        return "analog"

    @staticmethod
    def _transfer_timing_from_header(
        header: WaveformHeader,
        kind: str,
        transfer_ms: float,
        publish_ms: float = 0.0,
        *,
        summary_frame_count: int | None = None,
    ) -> WaveformTransferTiming:
        num_frames = int(header.num_frames) if header.num_frames and header.num_frames > 1 else 1
        resolved_summary_frame_count = (
            TekHSIConnect._summary_frame_count_from_header(header)
            if summary_frame_count is None
            else int(summary_frame_count)
        )
        return WaveformTransferTiming(
            kind=kind,
            transfer_ms=transfer_ms,
            publish_ms=publish_ms,
            record_length=int(header.noofsamples),
            bytes_per_sample=int(header.sourcewidth),
            num_frames=num_frames,
            summary_frame_count=resolved_summary_frame_count,
        )

    @staticmethod
    def _summary_frame_count_from_header(header: WaveformHeader) -> int:
        """Count summary frames declared in FastFrame metadata."""
        if not header.frame_info:
            return 0
        return sum(1 for info in header.frame_info if info.is_summary_frame)

    @staticmethod
    def _summary_frame_type_from_header(header: WaveformHeader) -> SummaryFrameType:
        """Infer summary-frame handling from FastFrame header metadata."""
        if not TekHSIConnect._summary_frame_count_from_header(header):
            return SummaryFrameType.SUMMARY_FRAME_OFF
        return SummaryFrameType.SUMMARY_FRAME_AVERAGE

    @staticmethod
    def _is_wfm_data_status(status: WfmReplyStatus | int) -> bool:
        """Return True when a stream message may carry sample data."""
        return status in {
            WfmReplyStatus.WFMREPLYSTATUS_SUCCESS,
            WfmReplyStatus.WFMREPLYSTATUS_UNSPECIFIED,
        }

    @staticmethod
    def _is_fastframe_header(header: WaveformHeader) -> bool:
        return bool(header.num_frames and header.num_frames > 1)

    @staticmethod
    def _trim_raw_frames(
        frame_arrays: list[np.ndarray], samples_per_frame: int
    ) -> list[np.ndarray]:
        trimmed: list[np.ndarray] = []
        for frame in frame_arrays:
            if len(frame) == samples_per_frame:
                trimmed.append(frame)
            else:
                trimmed.append(frame[:samples_per_frame])
        return trimmed

    @staticmethod
    def _frame_info_from_header(header: WaveformHeader) -> list[FrameTimingInfo]:
        return [
            FrameTimingInfo(
                frame_index=info.frame_index,
                time_offset=info.time_offset,
                gmt_sec=info.gmt_sec,
                fract_sec=info.fract_sec,
                real_point_offset=info.real_point_offset,
                frame_duration_sec=info.frame_duration_sec,
                is_summary_frame=info.is_summary_frame,
            )
            for info in header.frame_info
        ]

    @staticmethod
    def _frame_info_map(frame_info_list: list[FrameTimingInfo]) -> dict[int, FrameTimingInfo]:
        """Map frame index to metadata, keeping the last record for duplicate indices."""
        info_map: dict[int, FrameTimingInfo] = {}
        for info in frame_info_list:
            info_map[int(info.frame_index)] = info
        return info_map

    @staticmethod
    def _merge_fastframe_frame_info(
        header: WaveformHeader,
        stream_frame_info: list[FrameTimingInfo],
    ) -> list[FrameTimingInfo]:
        """Merge header and stream metadata, preferring stream records when both exist."""
        merged = TekHSIConnect._frame_info_map(TekHSIConnect._frame_info_from_header(header))
        merged.update(TekHSIConnect._frame_info_map(stream_frame_info))
        return [merged[idx] for idx in sorted(merged)]

    @staticmethod
    def _summary_frame_type_from_frame_info(
        frame_info_list: list[FrameTimingInfo],
    ) -> SummaryFrameType:
        """Infer summary-frame mode from concrete per-frame metadata."""
        if any(info.is_summary_frame for info in frame_info_list):
            return SummaryFrameType.SUMMARY_FRAME_AVERAGE
        return SummaryFrameType.SUMMARY_FRAME_OFF

    @staticmethod
    def _build_fastframe_from_native(
        header: WaveformHeader,
        raw_frames: list[np.ndarray],
        samples_per_frame: int,
        dt_type: type,
        load_timing: FastFrameLoadTiming | None,
        *,
        wrapper: type = FastFrameAnalogWaveform,
        frame_info: list[FrameTimingInfo] | None = None,
    ) -> FastFrameAnalogWaveform | FastFrameDigitalWaveform:
        """Populate a tm_data_types FastFrame waveform from native sample arrays."""
        effective_frame_info = (
            frame_info if frame_info is not None else TekHSIConnect._frame_info_from_header(header)
        )
        common_kwargs = {
            "source_name": header.sourcename,
            "x_axis_spacing": header.horizontalspacing,
            "x_axis_units": header.horizontalUnits,
            "trigger_index": header.horizontalzeroindex,
        }
        if wrapper is FastFrameDigitalWaveform:
            waveform = FastFrameDigitalWaveform.create_fastframe(
                header.num_frames,
                samples_per_frame,
                dtype=dt_type,
                y_axis_units=header.verticalunits,
                digital_bitmask=header.bitmask,
                **common_kwargs,
            )
        else:
            waveform = FastFrameAnalogWaveform.create_fastframe(
                header.num_frames,
                samples_per_frame,
                dtype=dt_type,
                y_axis_spacing=header.verticalspacing,
                y_axis_offset=header.verticaloffset,
                y_axis_units=header.verticalunits,
                **common_kwargs,
            )
        waveform.summary_frame_type = TekHSIConnect._summary_frame_type_from_frame_info(
            effective_frame_info
        )
        max_frame_index = max(0, len(raw_frames) - 1)
        current_index = int(header.current_frame_index)
        if current_index < 0 or current_index > max_frame_index:
            current_index = 0
        waveform.current_frame_index = current_index
        waveform.frame_info = effective_frame_info
        waveform.per_frame_summary_authoritative = bool(effective_frame_info)
        waveform.load_timing = load_timing

        frame_info_by_index = TekHSIConnect._frame_info_map(effective_frame_info)

        for index, frame in enumerate(raw_frames):
            waveform.fill_frame(index, np.asarray(frame, dtype=dt_type))
            info = frame_info_by_index.get(index)
            if info is not None:
                waveform.set_frame_timing(
                    index,
                    info.time_offset,
                    info.gmt_sec,
                    info.fract_sec,
                )

        return waveform

    def _waveform_request_for_header(
        self,
        header: WaveformHeader,
    ) -> WaveformRequest:
        stream_all = self._is_fastframe_header(header)
        return self._make_waveform_request(
            header.sourcename,
            self.chunksize,
            stream_all_frames=stream_all,
            include_frame_metadata=stream_all,
        )

    @staticmethod
    def _populate_analog_waveform(waveform: AnalogWaveform, header: WaveformHeader) -> None:
        waveform.source_name = header.sourcename
        waveform.y_axis_spacing = header.verticalspacing
        waveform.y_axis_offset = header.verticaloffset
        waveform.y_axis_units = header.verticalunits
        waveform.x_axis_spacing = header.horizontalspacing
        waveform.x_axis_units = header.horizontalUnits
        waveform.trigger_index = header.horizontalzeroindex

    def _read_analog_native(
        self,
        header: WaveformHeader,
        native_stub: NativeDataStub,
    ) -> Waveform:
        """Read an analog waveform from NativeData.

        FastFrame captures (``num_frames > 1``) always stream every frame in one call.
        """
        if not self._is_fastframe_header(header):
            waveform = AnalogWaveform()
            self._populate_analog_waveform(waveform, header)
            return self._read_analog_native_single_frame(waveform, header, native_stub)

        return self._read_native_fastframe(
            header,
            native_stub,
            self.v_datatypes[header.sourcewidth],
        )

    @staticmethod
    def _populate_digital_waveform(waveform: DigitalWaveform, header: WaveformHeader) -> None:
        waveform.source_name = header.sourcename
        waveform.y_axis_units = header.verticalunits
        waveform.x_axis_spacing = header.horizontalspacing
        waveform.x_axis_units = header.horizontalUnits
        waveform.trigger_index = header.horizontalzeroindex
        waveform.digital_bitmask = header.bitmask

    def _read_digital_native(
        self,
        header: WaveformHeader,
        native_stub: NativeDataStub,
    ) -> Waveform:
        """Read a digital waveform from NativeData, including FastFrame captures."""
        if header.sourcewidth not in self._digital_datatypes:
            msg = (
                f"unsupported digital sourcewidth {header.sourcewidth} for {header.sourcename}; "
                f"expected one of {sorted(self._digital_datatypes)}"
            )
            raise ValueError(msg)

        if not self._is_fastframe_header(header):
            waveform = DigitalWaveform()
            self._populate_digital_waveform(waveform, header)
            return self._read_digital_native_single_frame(waveform, header, native_stub)

        return self._read_native_fastframe(
            header,
            native_stub,
            self._digital_datatypes[header.sourcewidth],
            wrapper=FastFrameDigitalWaveform,
        )

    def _read_digital_native_single_frame(
        self,
        waveform: DigitalWaveform,
        header: WaveformHeader,
        native_stub: NativeDataStub,
    ) -> DigitalWaveform:
        request = self._waveform_request_for_header(header)
        transfer_start = time.perf_counter()
        response_iterator = native_stub.GetWaveform(request)
        dt_type = self._digital_datatypes[header.sourcewidth]
        sum_of_chunks = 0
        waveform.y_axis_byte_values = np.empty(header.noofsamples, dtype=dt_type)
        try:
            for response in response_iterator:
                if not self.thread_active:
                    break
                if not self._is_wfm_data_status(response.status):
                    continue
                if response.headerordata.WhichOneof("value") != "chunk":
                    continue
                chunk = response.headerordata.chunk.data
                if not chunk:
                    continue
                dt = np.frombuffer(chunk, dtype=dt_type)
                waveform.y_axis_byte_values[sum_of_chunks : sum_of_chunks + len(dt)] = dt
                sum_of_chunks += len(dt)
        finally:
            with contextlib.suppress(Exception):
                response_iterator.cancel()
        waveform.load_timing = self._transfer_timing_from_header(
            header,
            "digital",
            (time.perf_counter() - transfer_start) * 1000,
        )
        return waveform

    @staticmethod
    def _normalize_fastframe_arrays(
        frame_arrays: list[np.ndarray],
        expected_frames: int,
        samples_per_frame: int,
    ) -> list[np.ndarray]:
        """Split or trim frame buffers to match the header frame count."""
        if len(frame_arrays) == expected_frames:
            return frame_arrays
        if len(frame_arrays) == 1 and frame_arrays[0].size >= samples_per_frame * expected_frames:
            combined = frame_arrays[0][: samples_per_frame * expected_frames]
            return [
                combined[i * samples_per_frame : (i + 1) * samples_per_frame]
                for i in range(expected_frames)
            ]
        return frame_arrays

    def _read_native_fastframe(
        self,
        header: WaveformHeader,
        native_stub: NativeDataStub,
        dt_type: type,
        *,
        wrapper: type = FastFrameAnalogWaveform,
    ) -> FastFrameAnalogWaveform | FastFrameDigitalWaveform:
        """Stream and assemble a multi-frame native capture into a FastFrame wrapper."""
        request = self._waveform_request_for_header(header)
        samples_per_frame = int(header.noofsamples)
        bytes_per_sample = header.sourcewidth
        expected_bytes = header.num_frames * samples_per_frame * bytes_per_sample
        timeout_sec = min(120.0, max(15.0, expected_bytes / (5 * 1024 * 1024)))

        transfer_start = time.perf_counter()
        response_iterator = native_stub.GetWaveform(request, timeout=timeout_sec)
        try:
            frame_arrays, stream_frame_info = self._read_fastframe_stream(
                response_iterator,
                header,
                dt_type,
                samples_per_frame,
            )
        finally:
            with contextlib.suppress(Exception):
                response_iterator.cancel()
        transfer_ms = (time.perf_counter() - transfer_start) * 1000

        frame_arrays = self._normalize_fastframe_arrays(
            frame_arrays,
            int(header.num_frames),
            samples_per_frame,
        )
        if len(frame_arrays) != header.num_frames:
            msg = (
                f"expected {header.num_frames} FastFrame segments for {header.sourcename}, "
                f"received {len(frame_arrays)}"
            )
            raise RuntimeError(msg)

        publish_start = time.perf_counter()
        raw_frames = self._trim_raw_frames(frame_arrays, samples_per_frame)
        effective_frame_info = self._merge_fastframe_frame_info(header, stream_frame_info)
        summary_frame_count = sum(1 for info in effective_frame_info if info.is_summary_frame)
        wrapped = self._build_fastframe_from_native(
            header,
            raw_frames,
            samples_per_frame,
            dt_type,
            None,
            wrapper=wrapper,
            frame_info=effective_frame_info,
        )
        load_timing = self._transfer_timing_from_header(
            header,
            "digital" if wrapper is FastFrameDigitalWaveform else "analog",
            transfer_ms,
            (time.perf_counter() - publish_start) * 1000,
            summary_frame_count=summary_frame_count,
        )
        wrapped.load_timing = load_timing
        if self.verbose:
            _logger.info(
                "FastFrame raw load %s: %s", header.sourcename, load_timing.format_summary()
            )
        return wrapped

    def _read_analog_native_single_frame(
        self,
        waveform: AnalogWaveform,
        header: WaveformHeader,
        native_stub: NativeDataStub,
    ) -> Waveform:
        request = self._waveform_request_for_header(header)
        transfer_start = time.perf_counter()
        response_iterator = native_stub.GetWaveform(request)
        dt_type = self.v_datatypes[header.sourcewidth]
        sum_of_chunks = 0
        waveform.y_axis_values = np.empty(header.noofsamples, dtype=dt_type)
        try:
            for response in response_iterator:
                if not self.thread_active:
                    break
                if not self._is_wfm_data_status(response.status):
                    continue
                if response.headerordata.WhichOneof("value") != "chunk":
                    continue
                chunk = response.headerordata.chunk.data
                if not chunk:
                    continue
                dt = np.frombuffer(chunk, dtype=dt_type)
                waveform.y_axis_values[sum_of_chunks : sum_of_chunks + len(dt)] = dt
                sum_of_chunks += len(dt)
        finally:
            with contextlib.suppress(Exception):
                response_iterator.cancel()
        waveform.load_timing = self._transfer_timing_from_header(
            header,
            "analog",
            (time.perf_counter() - transfer_start) * 1000,
        )
        return waveform

    def _read_fastframe_stream(
        self,
        response_iterator: Iterator[Any],
        header: WaveformHeader,
        dt_type: type,
        samples_per_frame: int,
    ) -> tuple[list[np.ndarray], list[FrameTimingInfo]]:
        expected_frames = int(header.num_frames)
        expected_samples = expected_frames * samples_per_frame
        frame_arrays: list[np.ndarray] = []
        current_parts: list[np.ndarray] = []
        stream_frame_info: list[FrameTimingInfo] = []

        try:
            for response in response_iterator:
                if not self.thread_active:
                    break
                if not self._is_wfm_data_status(response.status):
                    continue
                self._append_fastframe_response(
                    response, dt_type, frame_arrays, current_parts, stream_frame_info
                )
                if self._fastframe_stream_complete(
                    frame_arrays, current_parts, expected_frames, expected_samples
                ):
                    break
        finally:
            with contextlib.suppress(Exception):
                response_iterator.cancel()
        self._flush_fastframe_parts(frame_arrays, current_parts)
        return self._split_combined_fastframe(
            frame_arrays,
            expected_frames,
            expected_samples,
            samples_per_frame,
        ), stream_frame_info

    @staticmethod
    def _flush_fastframe_parts(
        frame_arrays: list[np.ndarray], current_parts: list[np.ndarray]
    ) -> None:
        if current_parts:
            frame_arrays.append(np.concatenate(current_parts))
            current_parts.clear()

    def _append_fastframe_response(
        self,
        response: Any,
        dt_type: type,
        frame_arrays: list[np.ndarray],
        current_parts: list[np.ndarray],
        stream_frame_info: list[FrameTimingInfo],
    ) -> None:
        if response.HasField("frame_boundary"):
            info = self._fastframe_info(response)
            stream_frame_info.append(info)
            self._flush_fastframe_parts(frame_arrays, current_parts)
        if response.headerordata.WhichOneof("value") == "chunk":
            chunk = response.headerordata.chunk.data
            if chunk:
                current_parts.append(np.frombuffer(chunk, dtype=dt_type))

    @staticmethod
    def _fastframe_stream_complete(
        frame_arrays: list[np.ndarray],
        current_parts: list[np.ndarray],
        expected_frames: int,
        expected_samples: int,
    ) -> bool:
        total_samples = sum(array.size for array in frame_arrays)
        total_samples += sum(array.size for array in current_parts)
        return total_samples >= expected_samples or (
            len(frame_arrays) >= expected_frames and not current_parts
        )

    @staticmethod
    def _fastframe_info(response: Any) -> FrameTimingInfo:
        boundary_info = response.frame_boundary.frame_info
        return FrameTimingInfo(
            frame_index=boundary_info.frame_index,
            time_offset=boundary_info.time_offset,
            gmt_sec=boundary_info.gmt_sec,
            fract_sec=boundary_info.fract_sec,
            real_point_offset=boundary_info.real_point_offset,
            frame_duration_sec=boundary_info.frame_duration_sec,
            is_summary_frame=boundary_info.is_summary_frame,
        )

    @staticmethod
    def _split_combined_fastframe(
        frame_arrays: list[np.ndarray],
        expected_frames: int,
        expected_samples: int,
        samples_per_frame: int,
    ) -> list[np.ndarray]:
        if (
            len(frame_arrays) != 1
            or expected_frames <= 1
            or frame_arrays[0].size < expected_samples
        ):
            return frame_arrays
        combined = frame_arrays[0][:expected_samples]
        return [
            combined[index * samples_per_frame : (index + 1) * samples_per_frame]
            for index in range(expected_frames)
        ]

    def _read_header(self, name: str) -> WaveformHeader:
        """Reads header for the named source.

        Args:
            name (str): name of header

        Returns:
            WaveformHeader: the description of the properties of the specified waveform
        """
        _logger.debug("%s:read header", name)
        name = self._resolve_symbol(name)
        request = self._make_waveform_request(name, self.chunksize, include_frame_metadata=True)
        response = self.native.GetHeader(request)
        return response.headerordata.header

    def _collect_headers_once(
        self,
        symbols: list[str],
        headers: list[WaveformHeader],
        header_dict: dict[str, WaveformHeader],
        reject_log_level: int,
    ) -> tuple[bool, bool, list[str]]:
        """Read and classify one set of active-symbol headers."""
        any_pending = False
        any_invalid = False
        pending_symbols: list[str] = []
        for symbol in symbols:
            header = self._read_header(symbol)
            if self._is_header_value(header):
                headers.append(header)
                header_dict[header.sourcename] = header
            elif self._is_pending_header(header):
                any_pending = True
                pending_symbols.append(symbol)
            else:
                any_invalid = True
                _logger.log(
                    reject_log_level,
                    "Header rejected for %s: sourcename=%r wfmtype=%s num_frames=%s "
                    "noofsamples=%s sourcewidth=%s hasdata=%s",
                    symbol,
                    header.sourcename,
                    header.wfmtype,
                    header.num_frames,
                    header.noofsamples,
                    header.sourcewidth,
                    header.hasdata,
                )
        return any_pending, any_invalid, pending_symbols

    def _read_headers(
        self,
        headers: list[WaveformHeader],
        header_dict: dict[str, WaveformHeader],
        *,
        pending_ok: bool = False,
        max_attempts: int = _HEADER_PENDING_MAX_ATTEMPTS,
        retry_sleep_s: float = _HEADER_PENDING_RETRY_SLEEP_S,
        reject_log_level: int = logging.WARNING,
    ) -> bool:
        """Read headers for the active symbols.

        When ``pending_ok`` is True, placeholder headers (``noofsamples=0``, empty
        ``sourcename``) are retried briefly within the current data-access window instead
        of being logged as rejections.

        Args:
            headers: Cleared and populated with valid headers on success.
            header_dict: Cleared and populated keyed by ``sourcename`` on success.
            pending_ok: Retry while the instrument reports pending placeholders.
            max_attempts: Maximum read attempts when ``pending_ok`` is True.
            retry_sleep_s: Sleep between retry attempts in seconds.
            reject_log_level: Log level for non-pending invalid headers (DEBUG in ``_run``).

        Returns:
            True when every active symbol has a valid header.
        """
        symbols = self.activesymbols
        expected = len(symbols)
        if not expected:
            headers.clear()
            header_dict.clear()
            return True

        attempts = max_attempts if pending_ok else 1
        for attempt in range(attempts):
            if self._is_exiting:
                headers.clear()
                header_dict.clear()
                return False

            headers.clear()
            header_dict.clear()
            any_pending, any_invalid, pending_symbols = self._collect_headers_once(
                symbols, headers, header_dict, reject_log_level
            )

            if any_pending and not attempt:
                _logger.debug(
                    "Headers pending for %s (metadata not ready); retrying",
                    ", ".join(pending_symbols) or symbols,
                )

            if len(headers) == expected:
                return True
            if any_invalid:
                return False
            if any_pending and pending_ok and attempt + 1 < attempts:
                time.sleep(retry_sleep_s)
                continue
            if any_pending and pending_ok:
                _logger.debug(
                    "Headers still pending after %d attempts; releasing access window",
                    attempts,
                )
            return False

        return False

    # pylint: disable= too-many-locals
    def _read_waveform(self, header: WaveformHeader) -> Waveform:
        """Read the waveform associated with ``header``."""
        try:
            return self._read_waveform_from_stub(header, self.native)
        except Exception as error:
            _logger.log(logging.ERROR if self.verbose else logging.DEBUG, "Exception: %s", error)
            raise

    def _read_waveform_from_stub(
        self, header: WaveformHeader, native_stub: NativeDataStub
    ) -> Waveform:
        if 0 < header.wfmtype <= _VECTOR_WAVEFORM_MAX_TYPE:
            return self._read_analog_native(header, native_stub)
        if header.wfmtype in {WaveformType.ANALOG_IQ, WaveformType.ANALOG_16_IQ}:
            return self._read_iq_waveform(header, native_stub)
        if header.wfmtype in {WaveformType.DIGITAL, WaveformType.DIGITAL_16}:
            return self._read_digital_native(header, native_stub)
        _raise_unknown_waveform_type(header.wfmtype)

    def _iq_sample_rate(self, header: WaveformHeader) -> float:
        window_factors = {
            "Blackharris": 1.9,
            "Flattop2": 3.77,
            "Hanning": 1.44,
            "Hamming": 1.3,
            "Rectangle": 0.89,
            "Kaiserbessel": 2.23,
        }
        factor = window_factors.get(header.iq_windowType)
        if factor is None:
            return header.iq_span
        return (header.iq_fftLength * header.iq_rbw) / factor

    def _read_iq_waveform(self, header: WaveformHeader, native_stub: NativeDataStub) -> IQWaveform:
        waveform = IQWaveform()
        waveform.source_name = header.sourcename
        waveform.iq_axis_spacing = header.verticalspacing
        waveform.iq_axis_offset = header.verticaloffset
        waveform.iq_axis_units = header.verticalunits
        waveform.x_axis_spacing = header.horizontalspacing
        waveform.x_axis_units = header.horizontalUnits
        waveform.trigger_index = header.horizontalzeroindex
        waveform.meta_info = IQWaveformMetaInfo(
            iq_center_frequency=header.iq_centerFrequency,
            iq_fft_length=header.iq_fftLength,
            iq_resolution_bandwidth=header.iq_rbw,
            iq_span=header.iq_span,
            iq_window_type=header.iq_windowType,
            iq_sample_rate=self._iq_sample_rate(header),
        )
        self._read_iq_samples(waveform, header, native_stub)
        return waveform

    def _read_iq_samples(
        self, waveform: IQWaveform, header: WaveformHeader, native_stub: NativeDataStub
    ) -> None:
        request = self._make_waveform_request(header.sourcename, self.chunksize)
        transfer_start = time.perf_counter()
        response_iterator = native_stub.GetWaveform(request)
        dt_type = self.iq_datatypes[header.sourcewidth]
        waveform.interleaved_iq_axis_values = np.empty(header.noofsamples, dtype=dt_type)
        sample_index = 0
        try:
            for response in response_iterator:
                if not self.thread_active:
                    break
                if not self._is_wfm_data_status(response.status):
                    continue
                if response.headerordata.WhichOneof("value") != "chunk":
                    continue
                chunk = response.headerordata.chunk.data
                if not chunk:
                    continue
                values = np.frombuffer(chunk, dtype=dt_type)
                end = sample_index + len(values)
                waveform.interleaved_iq_axis_values[sample_index:end] = values
                sample_index = end
        finally:
            with contextlib.suppress(Exception):
                response_iterator.cancel()
        waveform.load_timing = self._transfer_timing_from_header(
            header, "iq", (time.perf_counter() - transfer_start) * 1000
        )

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
        if sys.version_info < (3, 11):
            return False

        # Python 3.13+: Free-threaded mode available but experimental
        # Note: Free-threaded mode helps CPU-bound work, not I/O-bound
        # Since gRPC is I/O-bound and already releases GIL, free-threaded mode
        # is unlikely to help with the current hanging issues
        # The problem is more likely gRPC/server-side serialization

        # Check environment variable for explicit disable
        disabled = os.getenv("TEKHSI_DISABLE_PARALLEL_READS", "").lower() in {
            "1",
            "true",
            "yes",
        }
        return not disabled

    def _read_waveforms(self, headers: list[WaveformHeader], waveforms: list[Waveform]) -> int:
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
        self, headers: list[WaveformHeader], waveforms: list[Waveform]
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
            waveform = self._read_waveform(header)
            self._recordlength = waveform.record_length
            datasize += waveform.record_length * header.sourcewidth
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
            waveform = self._read_waveform_from_stub(header, native_stub)
            if not isinstance(waveform, IQWaveform):
                waveform.record_length = header.noofsamples
        except Exception as e:
            error_message = "Waveform read failed for %s: %s"
            _logger.error(error_message, header.sourcename, e)  # noqa: TRY400
            raise
        return waveform

    def _read_waveforms_parallel(
        self, headers: list[WaveformHeader], waveforms: list[Waveform]
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
        try:
            futures = self._submit_parallel_reads(headers)
            results = self._collect_parallel_reads(futures, 30.0)
            datasize = self._append_parallel_results(headers, results, waveforms)
        except Exception:
            _logger.exception("Error in parallel read, falling back to sequential")
            self._cancel_futures(futures)
            return self._read_waveforms_sequential(headers, waveforms)
        elapsed = time.perf_counter() - start_time
        self._parallel_read_time += elapsed
        self._parallel_read_count += 1
        if self.verbose:
            _logger.info(
                "Parallel read: %d waveforms in %.3f ms (avg: %.3f ms)",
                len(headers),
                elapsed * 1000,
                (self._parallel_read_time / self._parallel_read_count) * 1000,
            )
        return datasize

    def _submit_parallel_reads(self, headers: list[WaveformHeader]) -> dict[Any, WaveformHeader]:
        futures = {}
        for header in headers:
            if not self.thread_active:
                break
            native_stub = NativeDataStub(self.channel)
            future = self._read_executor.submit(self._read_waveform_with_stub, header, native_stub)
            futures[future] = header
        return futures

    @staticmethod
    def _cancel_futures(futures: dict[Any, WaveformHeader]) -> None:
        for future in futures:
            if not future.done():
                future.cancel()

    def _collect_parallel_reads(
        self, futures: dict[Any, WaveformHeader], timeout_seconds: float
    ) -> dict[WaveformHeader, Waveform]:
        results = {}
        deadline = time.perf_counter() + timeout_seconds
        for future in as_completed(futures, timeout=timeout_seconds):
            if time.perf_counter() > deadline or not self.thread_active:
                self._cancel_futures(futures)
                break
            try:
                results[futures[future]] = future.result(timeout=1.0)
            except (RuntimeError, ValueError, grpc.RpcError):
                header = futures.get(future)
                _logger.exception(
                    "Error reading waveform %s; continuing with remaining reads",
                    header.sourcename if header else "unknown",
                )
        return results

    def _append_parallel_results(
        self,
        headers: list[WaveformHeader],
        results: dict[WaveformHeader, Waveform],
        waveforms: list[Waveform],
    ) -> int:
        datasize = 0
        for header in headers:
            waveform = results.get(header)
            if waveform is None or waveform.record_length <= 0:
                continue
            self._recordlength = waveform.record_length
            datasize += waveform.record_length * header.sourcewidth
            if self._cachedataenabled:
                with self._lock_getdata:
                    self._datacache[header.sourcename.lower()] = waveform
            waveforms.append(waveform)
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
            except grpc.RpcError as rpc_error:  # Server went away or connection reset;
                # exit thread cleanly
                _logger.log(
                    logging.DEBUG if not self.verbose else logging.INFO,
                    "Background thread exiting (connection closed): %s",
                    rpc_error,
                )
                # Ensure we release lock if we bailed before releasing
                if self._holding_scope_open:
                    with contextlib.suppress(Exception):
                        self._finished_with_data_access()
                    with contextlib.suppress(Exception):
                        self._lock_filter.release()
                    self._holding_scope_open = False

                return

    def _run_inner(
        self, headers: list[WaveformHeader], waveforms: list[Waveform], startwait: float
    ) -> None:
        """Read, publish, and account for one background acquisition."""
        if self._cachedataenabled:
            self._lock.acquire(blocking=True)
        try:
            prepared = self._prepare_run_data(headers, waveforms)
        except Exception as error:  # noqa: BLE001
            _logger.log(
                logging.ERROR if self.verbose else logging.DEBUG,
                "exception:_run_inner:%s",
                error,
            )
            return
        finally:
            if self._cachedataenabled:
                self._acqtime = self.current_time
                self._lock.release()
        if prepared is None:
            return
        datasize, datawidth, duration = prepared
        try:
            self._deliver_run_data(waveforms)
        except Exception as error:  # noqa: BLE001
            _logger.log(
                logging.ERROR if self.verbose else logging.DEBUG,
                "exception:_run_inner:%s",
                error,
            )
        self._finish_run_data(startwait, duration, datasize, datawidth)

    def _prepare_run_data(
        self, headers: list[WaveformHeader], waveforms: list[Waveform]
    ) -> tuple[int, int, float] | None:
        if self._is_exiting:
            return None
        header_dict: dict[str, WaveformHeader] = {}
        if not self._read_headers(
            headers, header_dict, pending_ok=True, reject_log_level=logging.DEBUG
        ):
            _logger.debug(
                "No valid headers in access window; releasing and waiting for next sequence"
            )
            return None
        acquisition_id = self._acq_id(headers)
        if acquisition_id is None or self._prev_data_id == acquisition_id:
            return None
        self._prev_data_id = acquisition_id
        if self._filter is not None and not self._filter(self._headers, header_dict):
            self._headers = header_dict
            return None
        if self._is_exiting:
            return None
        self._headers = header_dict
        start = time.perf_counter()
        datasize = self._read_waveforms(headers, waveforms)
        datawidth = headers[0].sourcewidth if headers else 1
        return datasize, datawidth, time.perf_counter() - start

    def _deliver_run_data(self, waveforms: list[Waveform]) -> None:
        if not waveforms or not self._connected or self._is_exiting:
            return
        self.data_arrival(waveforms)
        if self._callback is not None:
            self._callback(waveforms)

    def _finish_run_data(
        self, startwait: float, duration: float, datasize: int, datawidth: int
    ) -> None:
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

    def cleanup_at_exit(self) -> None:
        """Release any scope access held when the process is exiting."""
        if self._holding_scope_open:
            self._finished_with_data_access()

    ################################################################################################
    # Register Methods
    ################################################################################################
    # NOTE: Confirm whether this method is still necessary.
    @staticmethod
    @register
    def _terminate() -> None:
        """Terminate the connection to the instrument.

        Cleans up mess on termination if possible - this is required
        to keep the scope from hanging
        """
        for key in TekHSIConnect._connections:  # pylint:disable=consider-using-dict-items
            with contextlib.suppress(Exception):
                TekHSIConnect._connections[key].cleanup_at_exit()
            with contextlib.suppress(Exception):
                TekHSIConnect._connections[key].close()
