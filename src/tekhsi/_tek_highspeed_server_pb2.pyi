from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ConnectStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONNECTSTATUS_UNSPECIFIED: _ClassVar[ConnectStatus]
    CONNECTSTATUS_SUCCESS: _ClassVar[ConnectStatus]
    CONNECTSTATUS_NOT_CONNECTED_FAILURE: _ClassVar[ConnectStatus]
    CONNECTSTATUS_OUTSIDE_SEQUENCE_FAILURE: _ClassVar[ConnectStatus]
    CONNECTSTATUS_TIMEOUT_FAILURE: _ClassVar[ConnectStatus]
    CONNECTSTATUS_INUSE_FAILURE: _ClassVar[ConnectStatus]
    CONNECTSTATUS_UNKNOWN_FAILURE: _ClassVar[ConnectStatus]

class WfmReplyStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WFMREPLYSTATUS_UNSPECIFIED: _ClassVar[WfmReplyStatus]
    WFMREPLYSTATUS_SUCCESS: _ClassVar[WfmReplyStatus]
    WFMREPLYSTATUS_SOURCENAME_MISSING_FAILURE: _ClassVar[WfmReplyStatus]
    WFMREPLYSTATUS_OUTSIDE_SEQUENCE_FAILURE: _ClassVar[WfmReplyStatus]
    WFMREPLYSTATUS_NO_CONNECTION_FAILURE: _ClassVar[WfmReplyStatus]
    WFMREPLYSTATUS_TYPE_MISMATCH_FAILURE: _ClassVar[WfmReplyStatus]
    WFMREPLYSTATUS_INVALID_FRAME_INDEX: _ClassVar[WfmReplyStatus]

class WfmPairType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WFMPAIRTYPE_UNSPECIFIED: _ClassVar[WfmPairType]
    WFMPAIRTYPE_NONE: _ClassVar[WfmPairType]
    WFMPAIRTYPE_PAIR: _ClassVar[WfmPairType]

class WfmType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WFMTYPE_UNSPECIFIED: _ClassVar[WfmType]
    WFMTYPE_ANALOG_8: _ClassVar[WfmType]
    WFMTYPE_ANALOG_16: _ClassVar[WfmType]
    WFMTYPE_ANALOG_FLOAT: _ClassVar[WfmType]
    WFMTYPE_DIGITAL_8: _ClassVar[WfmType]
    WFMTYPE_DIGITAL_16: _ClassVar[WfmType]
    WFMTYPE_ANALOG_16_IQ: _ClassVar[WfmType]
    WFMTYPE_ANALOG_32_IQ: _ClassVar[WfmType]

CONNECTSTATUS_UNSPECIFIED: ConnectStatus
CONNECTSTATUS_SUCCESS: ConnectStatus
CONNECTSTATUS_NOT_CONNECTED_FAILURE: ConnectStatus
CONNECTSTATUS_OUTSIDE_SEQUENCE_FAILURE: ConnectStatus
CONNECTSTATUS_TIMEOUT_FAILURE: ConnectStatus
CONNECTSTATUS_INUSE_FAILURE: ConnectStatus
CONNECTSTATUS_UNKNOWN_FAILURE: ConnectStatus
WFMREPLYSTATUS_UNSPECIFIED: WfmReplyStatus
WFMREPLYSTATUS_SUCCESS: WfmReplyStatus
WFMREPLYSTATUS_SOURCENAME_MISSING_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_OUTSIDE_SEQUENCE_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_NO_CONNECTION_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_TYPE_MISMATCH_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_INVALID_FRAME_INDEX: WfmReplyStatus
WFMPAIRTYPE_UNSPECIFIED: WfmPairType
WFMPAIRTYPE_NONE: WfmPairType
WFMPAIRTYPE_PAIR: WfmPairType
WFMTYPE_UNSPECIFIED: WfmType
WFMTYPE_ANALOG_8: WfmType
WFMTYPE_ANALOG_16: WfmType
WFMTYPE_ANALOG_FLOAT: WfmType
WFMTYPE_DIGITAL_8: WfmType
WFMTYPE_DIGITAL_16: WfmType
WFMTYPE_ANALOG_16_IQ: WfmType
WFMTYPE_ANALOG_32_IQ: WfmType

class ConnectRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ConnectReply(_message.Message):
    __slots__ = ("status", "protocol_version", "capabilities")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    status: ConnectStatus
    protocol_version: int
    capabilities: int
    def __init__(
        self,
        status: _Optional[_Union[ConnectStatus, str]] = ...,
        protocol_version: _Optional[int] = ...,
        capabilities: _Optional[int] = ...,
    ) -> None: ...

class AvailableNamesReply(_message.Message):
    __slots__ = ("status", "symbolnames")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SYMBOLNAMES_FIELD_NUMBER: _ClassVar[int]
    status: ConnectStatus
    symbolnames: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        status: _Optional[_Union[ConnectStatus, str]] = ...,
        symbolnames: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class WaveformRequest(_message.Message):
    __slots__ = (
        "sourcename",
        "chunksize",
        "reply_content_mask",
        "frame_index",
        "start_frame",
        "end_frame",
        "stream_all_frames",
        "use_explicit_frame_index",
    )
    SOURCENAME_FIELD_NUMBER: _ClassVar[int]
    CHUNKSIZE_FIELD_NUMBER: _ClassVar[int]
    REPLY_CONTENT_MASK_FIELD_NUMBER: _ClassVar[int]
    FRAME_INDEX_FIELD_NUMBER: _ClassVar[int]
    START_FRAME_FIELD_NUMBER: _ClassVar[int]
    END_FRAME_FIELD_NUMBER: _ClassVar[int]
    STREAM_ALL_FRAMES_FIELD_NUMBER: _ClassVar[int]
    USE_EXPLICIT_FRAME_INDEX_FIELD_NUMBER: _ClassVar[int]
    sourcename: str
    chunksize: int
    reply_content_mask: int
    frame_index: int
    start_frame: int
    end_frame: int
    stream_all_frames: bool
    use_explicit_frame_index: bool
    def __init__(
        self,
        sourcename: _Optional[str] = ...,
        chunksize: _Optional[int] = ...,
        reply_content_mask: _Optional[int] = ...,
        frame_index: _Optional[int] = ...,
        start_frame: _Optional[int] = ...,
        end_frame: _Optional[int] = ...,
        stream_all_frames: _Optional[bool] = ...,
        use_explicit_frame_index: _Optional[bool] = ...,
    ) -> None: ...

class SParam(_message.Message):
    __slots__ = ("reference_impedance", "data", "frequencies", "ports")
    REFERENCE_IMPEDANCE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    FREQUENCIES_FIELD_NUMBER: _ClassVar[int]
    PORTS_FIELD_NUMBER: _ClassVar[int]
    reference_impedance: float
    data: _containers.RepeatedScalarFieldContainer[float]
    frequencies: _containers.RepeatedScalarFieldContainer[float]
    ports: _containers.RepeatedScalarFieldContainer[float]
    def __init__(
        self,
        reference_impedance: _Optional[float] = ...,
        data: _Optional[_Iterable[float]] = ...,
        frequencies: _Optional[_Iterable[float]] = ...,
        ports: _Optional[_Iterable[float]] = ...,
    ) -> None: ...

class ProbeInfo(_message.Message):
    __slots__ = ("probe_name", "probe_tip", "probe_attenuation", "probe_sparam", "filter")
    PROBE_NAME_FIELD_NUMBER: _ClassVar[int]
    PROBE_TIP_FIELD_NUMBER: _ClassVar[int]
    PROBE_ATTENUATION_FIELD_NUMBER: _ClassVar[int]
    PROBE_SPARAM_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    probe_name: str
    probe_tip: str
    probe_attenuation: float
    probe_sparam: SParam
    filter: _containers.RepeatedScalarFieldContainer[float]
    def __init__(
        self,
        probe_name: _Optional[str] = ...,
        probe_tip: _Optional[str] = ...,
        probe_attenuation: _Optional[float] = ...,
        probe_sparam: _Optional[_Union[SParam, _Mapping]] = ...,
        filter: _Optional[_Iterable[float]] = ...,
    ) -> None: ...

class WaveformHeader(_message.Message):
    __slots__ = (
        "sourcename",
        "sourcewidth",
        "dataid",
        "transid",
        "horizontalUnits",
        "horizontalspacing",
        "horizontalzeroindex",
        "horizontalfractionalzeroindex",
        "noofsamples",
        "chunksize",
        "wfmtype",
        "bitmask",
        "pairtype",
        "verticalunits",
        "verticalspacing",
        "verticaloffset",
        "iq_centerFrequency",
        "iq_fftLength",
        "iq_rbw",
        "iq_span",
        "iq_windowType",
        "hasdata",
        "num_frames",
        "frame_info",
        "current_frame_index",
        "probe_details",
        "channel_sparam",
    )
    SOURCENAME_FIELD_NUMBER: _ClassVar[int]
    SOURCEWIDTH_FIELD_NUMBER: _ClassVar[int]
    DATAID_FIELD_NUMBER: _ClassVar[int]
    TRANSID_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALUNITS_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALSPACING_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALZEROINDEX_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALFRACTIONALZEROINDEX_FIELD_NUMBER: _ClassVar[int]
    NOOFSAMPLES_FIELD_NUMBER: _ClassVar[int]
    CHUNKSIZE_FIELD_NUMBER: _ClassVar[int]
    WFMTYPE_FIELD_NUMBER: _ClassVar[int]
    BITMASK_FIELD_NUMBER: _ClassVar[int]
    PAIRTYPE_FIELD_NUMBER: _ClassVar[int]
    VERTICALUNITS_FIELD_NUMBER: _ClassVar[int]
    VERTICALSPACING_FIELD_NUMBER: _ClassVar[int]
    VERTICALOFFSET_FIELD_NUMBER: _ClassVar[int]
    IQ_CENTERFREQUENCY_FIELD_NUMBER: _ClassVar[int]
    IQ_FFTLENGTH_FIELD_NUMBER: _ClassVar[int]
    IQ_RBW_FIELD_NUMBER: _ClassVar[int]
    IQ_SPAN_FIELD_NUMBER: _ClassVar[int]
    IQ_WINDOWTYPE_FIELD_NUMBER: _ClassVar[int]
    HASDATA_FIELD_NUMBER: _ClassVar[int]
    NUM_FRAMES_FIELD_NUMBER: _ClassVar[int]
    FRAME_INFO_FIELD_NUMBER: _ClassVar[int]
    CURRENT_FRAME_INDEX_FIELD_NUMBER: _ClassVar[int]
    PROBE_DETAILS_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_SPARAM_FIELD_NUMBER: _ClassVar[int]
    sourcename: str
    sourcewidth: int
    dataid: int
    transid: int
    horizontalUnits: str
    horizontalspacing: float
    horizontalzeroindex: float
    horizontalfractionalzeroindex: float
    noofsamples: int
    chunksize: int
    wfmtype: WfmType
    bitmask: int
    pairtype: WfmPairType
    verticalunits: str
    verticalspacing: float
    verticaloffset: float
    iq_centerFrequency: float
    iq_fftLength: float
    iq_rbw: float
    iq_span: float
    iq_windowType: str
    hasdata: bool
    num_frames: int
    frame_info: _containers.RepeatedCompositeFieldContainer[FrameInfo]
    current_frame_index: int
    probe_details: ProbeInfo
    channel_sparam: SParam
    def __init__(
        self,
        sourcename: _Optional[str] = ...,
        sourcewidth: _Optional[int] = ...,
        dataid: _Optional[int] = ...,
        transid: _Optional[int] = ...,
        horizontalUnits: _Optional[str] = ...,
        horizontalspacing: _Optional[float] = ...,
        horizontalzeroindex: _Optional[float] = ...,
        horizontalfractionalzeroindex: _Optional[float] = ...,
        noofsamples: _Optional[int] = ...,
        chunksize: _Optional[int] = ...,
        wfmtype: _Optional[_Union[WfmType, str]] = ...,
        bitmask: _Optional[int] = ...,
        pairtype: _Optional[_Union[WfmPairType, str]] = ...,
        verticalunits: _Optional[str] = ...,
        verticalspacing: _Optional[float] = ...,
        verticaloffset: _Optional[float] = ...,
        iq_centerFrequency: _Optional[float] = ...,
        iq_fftLength: _Optional[float] = ...,
        iq_rbw: _Optional[float] = ...,
        iq_span: _Optional[float] = ...,
        iq_windowType: _Optional[str] = ...,
        hasdata: _Optional[bool] = ...,
        num_frames: _Optional[int] = ...,
        frame_info: _Optional[_Iterable[_Union[FrameInfo, _Mapping]]] = ...,
        current_frame_index: _Optional[int] = ...,
        probe_details: _Optional[_Union[ProbeInfo, _Mapping]] = ...,
        channel_sparam: _Optional[_Union[SParam, _Mapping]] = ...,
    ) -> None: ...

class FrameInfo(_message.Message):
    __slots__ = (
        "frame_index",
        "time_offset",
        "gmt_sec",
        "fract_sec",
        "is_summary_frame",
        "real_point_offset",
        "frame_duration_sec",
    )
    FRAME_INDEX_FIELD_NUMBER: _ClassVar[int]
    TIME_OFFSET_FIELD_NUMBER: _ClassVar[int]
    GMT_SEC_FIELD_NUMBER: _ClassVar[int]
    FRACT_SEC_FIELD_NUMBER: _ClassVar[int]
    IS_SUMMARY_FRAME_FIELD_NUMBER: _ClassVar[int]
    REAL_POINT_OFFSET_FIELD_NUMBER: _ClassVar[int]
    FRAME_DURATION_SEC_FIELD_NUMBER: _ClassVar[int]
    frame_index: int
    time_offset: float
    gmt_sec: int
    fract_sec: float
    is_summary_frame: bool
    real_point_offset: int
    frame_duration_sec: float
    def __init__(
        self,
        frame_index: _Optional[int] = ...,
        time_offset: _Optional[float] = ...,
        gmt_sec: _Optional[int] = ...,
        fract_sec: _Optional[float] = ...,
        is_summary_frame: _Optional[bool] = ...,
        real_point_offset: _Optional[int] = ...,
        frame_duration_sec: _Optional[float] = ...,
    ) -> None: ...

class FrameBoundary(_message.Message):
    __slots__ = ("frame_info",)
    FRAME_INFO_FIELD_NUMBER: _ClassVar[int]
    frame_info: FrameInfo
    def __init__(self, frame_info: _Optional[_Union[FrameInfo, _Mapping]] = ...) -> None: ...

class NormalizedReply(_message.Message):
    __slots__ = ("status", "headerordata", "frame_boundary")
    class WaveformSampleChunk(_message.Message):
        __slots__ = ("data",)
        DATA_FIELD_NUMBER: _ClassVar[int]
        data: _containers.RepeatedScalarFieldContainer[float]
        def __init__(self, data: _Optional[_Iterable[float]] = ...) -> None: ...

    class DataOrHeaderAccess(_message.Message):
        __slots__ = ("header", "chunk")
        HEADER_FIELD_NUMBER: _ClassVar[int]
        CHUNK_FIELD_NUMBER: _ClassVar[int]
        header: WaveformHeader
        chunk: NormalizedReply.WaveformSampleChunk
        def __init__(
            self,
            header: _Optional[_Union[WaveformHeader, _Mapping]] = ...,
            chunk: _Optional[_Union[NormalizedReply.WaveformSampleChunk, _Mapping]] = ...,
        ) -> None: ...

    STATUS_FIELD_NUMBER: _ClassVar[int]
    HEADERORDATA_FIELD_NUMBER: _ClassVar[int]
    FRAME_BOUNDARY_FIELD_NUMBER: _ClassVar[int]
    status: WfmReplyStatus
    headerordata: NormalizedReply.DataOrHeaderAccess
    frame_boundary: FrameBoundary
    def __init__(
        self,
        status: _Optional[_Union[WfmReplyStatus, str]] = ...,
        headerordata: _Optional[_Union[NormalizedReply.DataOrHeaderAccess, _Mapping]] = ...,
        frame_boundary: _Optional[_Union[FrameBoundary, _Mapping]] = ...,
    ) -> None: ...

class RawReply(_message.Message):
    __slots__ = ("status", "headerordata", "frame_boundary")
    class WaveformSampleByteChunk(_message.Message):
        __slots__ = ("data",)
        DATA_FIELD_NUMBER: _ClassVar[int]
        data: bytes
        def __init__(self, data: _Optional[bytes] = ...) -> None: ...

    class DataOrHeaderAccess(_message.Message):
        __slots__ = ("header", "chunk")
        HEADER_FIELD_NUMBER: _ClassVar[int]
        CHUNK_FIELD_NUMBER: _ClassVar[int]
        header: WaveformHeader
        chunk: RawReply.WaveformSampleByteChunk
        def __init__(
            self,
            header: _Optional[_Union[WaveformHeader, _Mapping]] = ...,
            chunk: _Optional[_Union[RawReply.WaveformSampleByteChunk, _Mapping]] = ...,
        ) -> None: ...

    STATUS_FIELD_NUMBER: _ClassVar[int]
    HEADERORDATA_FIELD_NUMBER: _ClassVar[int]
    FRAME_BOUNDARY_FIELD_NUMBER: _ClassVar[int]
    status: WfmReplyStatus
    headerordata: RawReply.DataOrHeaderAccess
    frame_boundary: FrameBoundary
    def __init__(
        self,
        status: _Optional[_Union[WfmReplyStatus, str]] = ...,
        headerordata: _Optional[_Union[RawReply.DataOrHeaderAccess, _Mapping]] = ...,
        frame_boundary: _Optional[_Union[FrameBoundary, _Mapping]] = ...,
    ) -> None: ...
