"""This file provides a simple TekHSI streaming server implementation for testing.

The primary usage for this is to allow unit testing to occur on GitHub. An alternative usage is as
an example of how to build a simple streaming server with TekHSI.

The intention is for us to add more services moving forward. The intention is that older servers
will still work, but they might not provide later services. This allows us to move the interface
forward while remaining backwards compatible.
"""

import sys
import grpc
import time
import math
from threading import Lock, Thread
import numpy as np
from enum import Enum
from concurrent import futures

from tm_data_types import AnalogWaveform, IQWaveform, DigitalWaveform

import tekhsi._tek_highspeed_server_pb2 as tekhsi_pb2
import tekhsi._tek_highspeed_server_pb2_grpc as tekhsi_pb2_grpc

background_thread = None
mutex = Lock()
connect_server = None
verbose = False
server = None
acq_id = 0


class WfmDataType(Enum):
    Int8 = 1
    Int16 = 2
    Float = 4


class WfmEncoding(Enum):
    Sine = 1
    Square = 2
    PRBS7 = 3
    IQ = 4
    Digital = 5


class ServerWaveform:  # pylint: disable=too-many-instance-attributes
    """This class simplifies the process of creating new data for the server. It is divided into to sets of inputs:
    Signal Definition, and Signal Representation Properties.

    Signal Definition:
        frequency : float
            Defines the frequency (or data rate) of the signal.
        amplitude : float
            Defines the amplitude of the signal. Default is 1.
        encoding : WfmEncoding
            Options are WfmEncoding.Sine, WfmEncoding.Square, and WfmEncoding.PRBS7
        length : int
            The record length of the resulting waveform
        repeats : int
            The number of times the signal cycle or digital pattern repeats during the waveform.

    Signal Representation:
        type : WfmDataType
            Defines the underlying waveform representation. Options are: WfmDataType.Int8, WfmDatType.Int16,
            and WfmDataType.Float.


    The resulting class instance will contain both a waveform in the native format, and an equivalent float array.
    These are intended to target either NativeData or NormalizedData services.
    This simplifies the process of feeding the data to the streaming service.
    """

    def __init__(
        self,
        frequency: float = 1000.0,
        wfm_data_type: WfmDataType = WfmDataType.Int8,
        encoding: WfmEncoding = WfmEncoding.Sine,
        amplitude: float = 1.0,
        length: int = 1000,
        repeats: int = 10,
    ):
        self._type = wfm_data_type
        self._encoding = encoding
        self._vertical_data = None

        if frequency < 0:
            self._frequency = 1e4
        else:
            self._frequency = frequency

        if amplitude <= 0:
            self._amplitude = 1.0
        else:
            self._amplitude = amplitude

        if length <= 0:
            self._length = 1000
        else:
            self._length = length

        if repeats < 1:
            self._repeats = 1
        else:
            self._repeats = repeats

        if frequency <= 0.0:
            raise ValueError("frequency out of range")

        period = 1.0 / frequency
        resolution = None
        offset = 0
        noise = 0.01
        if self._type is WfmDataType.Int8:
            yincr = self.amplitude / 230
        if self._type is WfmDataType.Int16:
            yincr = self.amplitude / 58000
        if self._type is WfmDataType.Float:
            yincr = 1
        else:
            yincr = 1

        self._yincr = yincr

        if length > 0:
            resolution = (period * repeats) / length
        elif resolution is None or resolution <= 0.0:
            resolution = period / 100
            length = int(period * repeats / resolution)
        else:
            length = int(period * repeats / resolution)

        self._xincr = resolution
        increment = (2.0 * math.pi * repeats) / length
        self._hspacing = resolution
        self._trigger_index = length / 2

        if encoding in {WfmEncoding.Sine, WfmEncoding.IQ, WfmEncoding.Digital}:
            self._vertical_data = np.array(
                [
                    (math.cos(increment * index) / 2.0) * amplitude - offset
                    for index in range(length)
                ]
            )
        elif encoding == WfmEncoding.Square:
            ampl2 = amplitude / 2
            self._vertical_data = np.array(
                [
                    ampl2 if (math.cos(increment * index) / 2.0) >= 0 else -ampl2
                    for index in range(length)
                ]
            )
        elif encoding == WfmEncoding.PRBS7:
            pass

        if noise >= 0.0 and self._vertical_data is not None:
            self._vertical_data = ServerWaveform._add_noise(self._vertical_data, amplitude * noise)

        if self._type is WfmDataType.Int8 or self._type:
            self._raw_data = (self._vertical_data / yincr).astype(np.int8)
        if self._type is WfmDataType.Int16:
            self._raw_data = (self._vertical_data / yincr).astype(np.int16)
        if self._type is WfmDataType.Float:
            self._raw_data = (self._vertical_data / yincr).astype(np.float32)

    @property
    def frequency(self) -> float:
        """Returns the frequency/datarate used with the underlying waveform."""
        return self._frequency

    @property
    def type(self) -> WfmDataType:
        """Returns the underlying raw type of the waveform."""
        return self._type

    @property
    def encoding(self) -> WfmEncoding:
        """Returns the underlying signal type.

        Options are Sine, Square, or PRBS7
        """
        return self._encoding

    @property
    def amplitude(self) -> float:
        """Returns the amplitude of the underlying waveform."""
        return self._amplitude

    @property
    def length(self) -> int:
        """Returns the number of samples in the waveform."""
        return self._length

    @property
    def repeats(self) -> int:
        """Returns the number of repeated cycles or digital sequences."""
        return self._repeats

    @property
    def xincr(self) -> float:
        """Returns the horizontal spacing."""
        return self._xincr

    @property
    def trigger_index(self) -> int:
        """Returns the trigger location as sample index."""
        return self._trigger_index

    @property
    def yincr(self) -> float:
        """Returns the value is multiplied by the raw value to create the normalized value."""
        return self._yincr

    @staticmethod
    def _add_noise(array, noise_range: float):
        """Adds noise to the signal.

        This is to make it visually clear that each waveform is unique.
        """
        return np.array(array) + np.random.normal(loc=0.0, scale=noise_range / 4, size=len(array))


class TekHSI_NormalizedDataServer(tekhsi_pb2_grpc.NormalizedDataServicer):
    """Server for streaming Normalized Data.

    Data is returned as normalized vertical values. This is easier to use and interpret, but
    requires formatting and moving much more data than native data. This makes the transfer time
    slower than the native server.
    """

    def GetWaveform(self, request, context):
        """This message returns the stream of the data representing the requested channel/math.
        The data is returned as normalized data. This usually slower than using the raw service
        because this moves significantly more data because floats are 4 bytes while raw data is normally
        either 1 or 2 bytes.

        Parameters
        ----------
        request : WaveformRequest
            This contains sourcename, and chunksize

        context : Any
            This contains information relevant to the current gRPC call.
        """
        global connect_server
        global verbose
        if verbose:
            print(f"TekHSI_NormalizedDataServer.GetWaveform({request.sourcename})")
        try:
            if connect_server.dataaccess_allowed:
                if request.sourcename in connect_server.data:
                    wfm = connect_server.data[request.sourcename]
                    chunksize = request.chunksize
                    for cur in range(0, len(wfm._vertical_data), chunksize):
                        reply = tekhsi_pb2.NormalizedReply(
                            headerordata=tekhsi_pb2.NormalizedReply.DataOrHeaderAccess(
                                chunk=tekhsi_pb2.NormalizedReply.WaveformSampleChunk(
                                    data=wfm._vertical_data[cur : cur + chunksize]
                                )
                            )
                        )
                        yield reply
                    reply = tekhsi_pb2.NormalizedReply()
                    reply.status = tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_SUCCESS")
                    yield reply
                    return
        except Exception as e:
            print(e)
        return

    def GetHeader(self, request, context):
        """The message returns the header (equivalent to preamble when using SCPI commands).

        Parameters
        ----------
        request : WaveformRequest
            This contains sourcename, and chunksize

        context : Any
            This contains information relevant to the current gRPC call.

        Returns
        -------
        NormalizedReply
            The return reply contains the status + the requested header information.
        """
        global connect_server
        global verbose
        global acq_id
        if verbose:
            print(f"TekHSI_NormalizedDataServer.GetHeader({request.sourcename})")
        try:
            if connect_server.dataaccess_allowed:
                if request.sourcename in connect_server.data:
                    wfm = connect_server.data[request.sourcename]
                    reply = tekhsi_pb2.NormalizedReply()
                    reply.headerordata.header.dataid = acq_id
                    reply.headerordata.header.hasdata = True
                    reply.headerordata.header.horizontalspacing = wfm.xincr
                    reply.headerordata.header.horizontalUnits = "S"
                    reply.headerordata.header.horizontalzeroindex = wfm.trigger_index
                    reply.headerordata.header.noofsamples = wfm.length
                    reply.headerordata.header.sourcename = request.sourcename
                    reply.headerordata.header.sourcewidth = 4

                    if isinstance(data, AnalogWaveform):
                        reply.headerordata.header.wfmtype = 3
                    elif isinstance(data, IQWaveform):
                        reply.headerordata.header.wfmtype = 6
                    elif isinstance(data, DigitalWaveform):
                        reply.headerordata.header.wfmtype = 4

                    reply.headerordata.header.pairtype = 1
                    reply.headerordata.header.verticaloffset = 0
                    reply.headerordata.header.verticalspacing = 1.0
                    reply.headerordata.header.verticalunits = "V"
                    reply.status = tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_SUCCESS")
                    return reply
        except Exception as e:
            print(e)
        return tekhsi_pb2.NormalizedReply(
            status=tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_FAILURE")
        )


class TekHSI_NativeDataServer(tekhsi_pb2_grpc.NativeDataServicer):
    """Server for streaming Native Data.

    This moves the data in the native (data store) format. This is much faster than using the
    normalized version.
    """

    def GetWaveform(self, request, context):
        """This message returns the stream of the data representing the requested channel/math.
        The data is returned as native data. How the data is represented is defined in the
        header.

        Parameters
        ----------
        request : WaveformRequest
            This contains sourcename, and chunksize

        context : Any
            This contains information relevant to the current gRPC call.

        Returns
        -------
        NativeReply
            The return reply contains the status. The yield reply, returns
            each data chunk.
        """
        global connect_server
        global verbose
        if verbose:
            print(f"TekHSI_NativeDataServer.GetWaveform({request.sourcename})")
        try:
            if connect_server.dataaccess_allowed:
                if request.sourcename in connect_server.data:
                    wfm = connect_server.data[request.sourcename]
                    chunksize = request.chunksize
                    raw_bytes = wfm._raw_data.tobytes()
                    for cur in range(0, len(raw_bytes), chunksize):
                        reply = tekhsi_pb2.RawReply(
                            headerordata=tekhsi_pb2.RawReply.DataOrHeaderAccess(
                                chunk=tekhsi_pb2.RawReply.WaveformSampleByteChunk(
                                    data=raw_bytes[cur : cur + chunksize]
                                )
                            )
                        )
                        yield reply
                    reply = tekhsi_pb2.RawReply()
                    reply.status = tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_SUCCESS")
                    return reply
        except Exception as e:
            print(e)
        return tekhsi_pb2.RawReply(status=tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_FAILURE"))

    def GetHeader(self, request, context):
        """The message returns the header (equivalent to preamble when using SCPI commands).

        Parameters
        ----------
        request : WaveformRequest
            This contains sourcename, and chunksize

        context : Any
            This contains information relevant to the current gRPC call.

        Returns
        -------
        NativeReply
            The return reply contains the status + the requested header information.
        """
        global connect_server
        global verbose
        global acq_id
        if verbose:
            print(f"TekHSI_NativeDataServer.GetHeader({request.sourcename})")
        try:
            if connect_server.dataaccess_allowed:
                if request.sourcename in connect_server.data:
                    wfm = connect_server.data[request.sourcename]
                    reply = tekhsi_pb2.RawReply()
                    reply.headerordata.header.dataid = acq_id
                    reply.headerordata.header.hasdata = True
                    reply.headerordata.header.horizontalspacing = wfm.xincr
                    reply.headerordata.header.horizontalUnits = "S"
                    reply.headerordata.header.horizontalzeroindex = wfm.trigger_index
                    reply.headerordata.header.noofsamples = wfm.length
                    reply.headerordata.header.sourcename = request.sourcename

                    if isinstance(data, AnalogWaveform):
                        if wfm.type == WfmDataType.Int8:
                            reply.headerordata.header.sourcewidth = 1
                            reply.headerordata.header.wfmtype = 1
                        elif wfm.type == WfmDataType.Int16:
                            reply.headerordata.header.sourcewidth = 2
                            reply.headerordata.header.wfmtype = 2
                        elif wfm.type == WfmDataType.Float:
                            reply.headerordata.header.sourcewidth = 4
                            reply.headerordata.header.wfmtype = 3
                        else:
                            reply.headerordata.header.sourcewidth = 1
                            reply.headerordata.header.wfmtype = 1
                    elif isinstance(data, IQWaveform):
                        if wfm.type == WfmDataType.Int8:
                            reply.headerordata.header.sourcewidth = 1
                            reply.headerordata.header.wfmtype = 6
                        elif wfm.type == WfmDataType.Int16:
                            reply.headerordata.header.sourcewidth = 2
                            reply.headerordata.header.wfmtype = 7
                        else:
                            reply.headerordata.header.sourcewidth = 1
                            reply.headerordata.header.wfmtype = 6
                    elif isinstance(data, DigitalWaveform):
                        if wfm.type == WfmDataType.Int8:
                            reply.headerordata.header.sourcewidth = 1
                            reply.headerordata.header.wfmtype = 4
                        elif wfm.type == WfmDataType.Int16:
                            reply.headerordata.header.sourcewidth = 2
                            reply.headerordata.header.wfmtype = 5
                        else:
                            reply.headerordata.header.sourcewidth = 1
                            reply.headerordata.header.wfmtype = 4

                    reply.headerordata.header.pairtype = 1
                    reply.headerordata.header.verticaloffset = 0
                    reply.headerordata.header.verticalspacing = wfm.yincr
                    reply.headerordata.header.verticalunits = "V"
                    reply.status = tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_SUCCESS")
                    return reply
        except Exception as e:
            print(e)
        return tekhsi_pb2.RawReply(status=tekhsi_pb2.WfmReplyStatus.Value("WFMREPLYSTATUS_FAILURE"))


class TekHSI_Connect(tekhsi_pb2_grpc.ConnectServicer):
    """Presents the connect service. This synchronized access to the data.

    Generally, you must Connect, then accessing the data means calling WaitForDataAccess, you can
    ask what the set of names of available items are by calling RequestAvailableName. Then the
    Native or Normalized services are available. Either may be used to access the data items header
    and data.

    When done accessing the data, FinishedWithDataAccess must be called. Acquistions are held off in
    a scope while waiting for FinishedWithDataAccess. To keep the update rate up, it's best to get
    your data and release the acq before doing further processing.
    """

    def __init__(self):
        self._connections = {}
        self._channels = make_new_data()
        self._dataaccess_allowed = False
        self._new_data = True

    @property
    def dataaccess_allowed(self) -> bool:
        """Returns True if the Connect state is between WaitForDataAccess, and FinishedWithDataAccess."""
        return self._dataaccess_allowed

    def dataconnection_name(self, name) -> bool:
        """The name of the connected item."""
        return name in self._connections

    @property
    def data(self):
        """Returns symbol dictionary."""
        return self._channels

    def Connect(self, request, context):
        """Initiate a connection.

        Only one connection at a time is allowed.
        """
        try:
            if self._connections.get(request.name):
                context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                return tekhsi_pb2.ConnectReply(
                    status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_INUSE_FAILURE")
                )
            self._connections[request.name] = True
            context.set_code(grpc.StatusCode.OK)
            context.set_details("Connected")
            if mutex.locked():
                mutex.release()
            if verbose:
                print(f'connection successful - "{request.name}"')
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_SUCCESS")
            )
        except Exception as e:
            if verbose:
                print(f'** Exception:{e}: Connect - "{request.name}"')
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
            )

    def Disconnect(self, request, context):
        if verbose:
            print(f'Disconnect Request "{request.name}"')
        try:
            if self._connections.get(request.name):
                del self._connections[request.name]
                if self._new_data:
                    self.FinishedWithDataAccess(request, context)
                    self._new_data = False
                # nforce a cleanup
                self._new_data = False
                self._dataaccess_allowed = False
                if mutex.locked():
                    mutex.release()
                if verbose:
                    print(f'Disconnect Success "{request.name}"')
                context.set_code(grpc.StatusCode.OK)
                return tekhsi_pb2.ConnectReply(
                    status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_SUCCESS")
                )
            else:
                self._connections.clear()
                if self._new_data:
                    self.FinishedWithDataAccess(request, context)
                # force a cleanup
                self._new_data = False
                self._dataaccess_allowed = False
                if mutex.locked():
                    mutex.release()
                context.set_code(grpc.StatusCode.OK)
                if verbose:
                    print(f'Disconnect Success - but used a bad name {request.name}"')
                return tekhsi_pb2.ConnectReply(
                    status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
                )
        except Exception as e:
            if self._new_data:
                self.FinishedWithDataAccess(request, context)
            # force a cleanup
            self._new_data = False
            self._dataaccess_allowed = False
            if mutex.locked():
                mutex.release()
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            if verbose:
                print(f'** Exception: Disconnect - "{request.name} - {e}"')
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
            )

    def RequestNewSequence(self, request, context):
        try:
            if verbose:
                if self._connections.get(request.name):
                    print(f'RequestNewSequence Success "{request.name}"')
                else:
                    print(f'RequestNewSequence Failed - No Connection "{request.name}"')

            global connect_server
            mutex.acquire()
            if verbose:
                print("mutex-acquired: RequestNewSequence")
            self._channels = make_new_data()
            self._new_data = True
            mutex.release()
            if verbose:
                print("mutex-released: RequestNewSequence")
            context.set_code(grpc.StatusCode.OK)
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_SUCCESS")
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            if verbose:
                print(e)
                print(f'** Exception as: RequestNewSequence - "{request.name}"')
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
            )

    def RequestAvailableNames(self, request, context):
        try:
            if verbose:
                if self._connections.get(request.name):
                    print(f'RequestAvailableNames Success "{request.name}"')
                else:
                    print(f'RequestAvailableNames Failed - No Connection "{request.name}"')
            context.set_code(grpc.StatusCode.OK)
            return tekhsi_pb2.AvailableNamesReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_SUCCESS"),
                symbolnames=list(self._channels.keys()),
            )
        except Exception as e:
            if verbose:
                print(e)
                print(f'** Exception: RequestNewSequence - "{request.name}"')
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            return tekhsi_pb2.AvailableNamesReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
            )

    def WaitForDataAccess(self, request, context):
        try:
            if not self._connections:
                if verbose:
                    print("WaitForDataAccess Success - requested with no connections active")
                return

            if not self._connections.get(request.name) and len(request.name) > 0:
                return

            while not self._new_data:
                time.sleep(0.001)

            mutex.acquire()
            if verbose:
                print("mutex-acquired: WaitForDataAccess")
            self._dataaccess_allowed = True
            context.set_code(grpc.StatusCode.OK)
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_SUCCESS")
            )
        except Exception as e:
            if verbose:
                print(e)
                print(f'** Exception: WaitForDataAccess - "{request.name}"')
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
            )

    def FinishedWithDataAccess(self, request, context):
        try:
            if self._dataaccess_allowed:
                self._new_data = False
                self._dataaccess_allowed = False
                mutex.release()
                if verbose:
                    print("mutex-released: FinishedWithDataAccess")
                if verbose:
                    if self._connections.get(request.name):
                        print(f'FinishedWithDataAccess Success "{request.name}"')
                    else:
                        print(f'FinishedWithDataAccess Bad Connection Name "{request.name}"')
                context.set_code(grpc.StatusCode.OK)
                return tekhsi_pb2.ConnectReply(
                    status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_SUCCESS")
                )
            else:
                if verbose:
                    print(f'FinishedWithDataAccess Failed "{request.name} - No WaitForDataPending"')
                return tekhsi_pb2.ConnectReply(
                    status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
                )

        except Exception as e:
            if verbose:
                print(e)
                print(f'** Exception: FinishedWithDataAccess - "{request.name}"')
            return tekhsi_pb2.ConnectReply(
                status=tekhsi_pb2.ConnectStatus.Value("CONNECTSTATUS_UNSPECIFIED")
            )


def periodic_data_creation():
    """This is a background task that periodically creates new data.
    This coordinates with the Connect server so that WaitForDataAccess
    only returns when new data has arrived.

    If you want to change the named sets of data returned you should modify 'make_new_data()'
    """
    while True:
        global connect_server
        global acq_id
        try:
            mutex.acquire()
            acq_id = acq_id + 1
            connect_server._channels = make_new_data()
            connect_server._new_data = True
            mutex.release()
            time.sleep(2)  # Wait for 2 seconds
        except Exception as e:
            print(f"periodic_data_creation:{e}")


def make_new_data():
    """This function is called to make new data for the server. This defines both the
    symbol names and associated data. This is called on initialization of the TekHSI_Connect service
    and periodically to create new data. The symbols defined here well be seen by the client.

    Returns
    -------
    dict
        Returns a name/value dictionary defining a set of symbols and their associated waveforms.
    """
    return {
        "ch1": ServerWaveform(),
        "ch1_iq": ServerWaveform(encoding=WfmEncoding.IQ, wfm_data_type=WfmDataType.Int16),
        "ch2": ServerWaveform(wfm_data_type=WfmDataType.Int16),
        "ch3": ServerWaveform(wfm_data_type=WfmDataType.Int16),
        # "ch4_DAll": ServerWaveform(encoding=WfmEncoding.Digital, wfm_data_type=WfmDataType.Int8),
        "math1": ServerWaveform(wfm_data_type=WfmDataType.Float),
        "math2": ServerWaveform(wfm_data_type=WfmDataType.Float),
    }


def serve():
    """Startups up the server."""
    global connect_server
    global server
    global background_thread
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    connect_server = TekHSI_Connect()
    tekhsi_pb2_grpc.add_ConnectServicer_to_server(connect_server, server)
    tekhsi_pb2_grpc.add_NormalizedDataServicer_to_server(TekHSI_NormalizedDataServer(), server)
    tekhsi_pb2_grpc.add_NativeDataServicer_to_server(TekHSI_NativeDataServer(), server)
    try:
        if verbose:
            print("Server Startup Request")
        server.add_insecure_port("[::]:5000")
        server.start()
        time.sleep(2)
        if verbose:
            print("Server Started")
        background_thread = Thread(target=periodic_data_creation)
        background_thread.daemon = True  # Set as a daemon thread (exits when main thread exits)
        background_thread.start()
    except Exception as e:
        print(f"Startup failed: {e}")


def wait_for_termination():
    """Waits for server termination.

    This is a blocking call.
    """
    server.wait_for_termination()


def kill_server():
    """This stops the server and waits for its exit."""
    server.stop(grace=0)
    wait_for_termination()


if __name__ == "__main__":
    for i, arg in enumerate(sys.argv[1:]):
        if arg.lower() == "--verbose":
            verbose = True
    verbose = True
    serve()
    wait_for_termination()
