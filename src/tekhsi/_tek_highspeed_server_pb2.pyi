from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

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
    def __init__(self, name: str | None = ...) -> None: ...

class ConnectReply(_message.Message):
    __slots__ = ("capabilities", "protocol_version", "status")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    status: ConnectStatus
    protocol_version: int
    capabilities: int
    def __init__(
        self,
        status: _Union[ConnectStatus, str] | None = ...,
        protocol_version: int | None = ...,
        capabilities: int | None = ...,
    ) -> None: ...

class AvailableNamesReply(_message.Message):
    __slots__ = ("status", "symbolnames")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SYMBOLNAMES_FIELD_NUMBER: _ClassVar[int]
    status: ConnectStatus
    symbolnames: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        status: _Union[ConnectStatus, str] | None = ...,
        symbolnames: _Iterable[str] | None = ...,
    ) -> None: ...

class WaveformRequest(_message.Message):
    __slots__ = (
        "chunksize",
        "end_frame",
        "frame_index",
        "reply_content_mask",
        "sourcename",
        "start_frame",
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
        sourcename: str | None = ...,
        chunksize: int | None = ...,
        reply_content_mask: int | None = ...,
        frame_index: int | None = ...,
        start_frame: int | None = ...,
        end_frame: int | None = ...,
        stream_all_frames: bool | None = ...,
        use_explicit_frame_index: bool | None = ...,
    ) -> None: ...

class SParam(_message.Message):
    __slots__ = ("data", "frequencies", "ports", "reference_impedance")
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
        reference_impedance: float | None = ...,
        data: _Iterable[float] | None = ...,
        frequencies: _Iterable[float] | None = ...,
        ports: _Iterable[float] | None = ...,
    ) -> None: ...

class ProbeInfo(_message.Message):
    __slots__ = ("filter", "probe_attenuation", "probe_name", "probe_sparam", "probe_tip")
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
        probe_name: str | None = ...,
        probe_tip: str | None = ...,
        probe_attenuation: float | None = ...,
        probe_sparam: _Union[SParam, _Mapping] | None = ...,
        filter: _Iterable[float] | None = ...,
    ) -> None: ...

class WaveformHeader(_message.Message):
    __slots__ = (
        "bitmask",
        "channel_sparam",
        "chunksize",
        "current_frame_index",
        "dataid",
        "frame_info",
        "hasdata",
        "horizontalUnits",
        "horizontalfractionalzeroindex",
        "horizontalspacing",
        "horizontalzeroindex",
        "iq_centerFrequency",
        "iq_fftLength",
        "iq_rbw",
        "iq_span",
        "iq_windowType",
        "noofsamples",
        "num_frames",
        "pairtype",
        "probe_details",
        "sourcename",
        "sourcewidth",
        "transid",
        "verticaloffset",
        "verticalspacing",
        "verticalunits",
        "wfmtype",
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
        sourcename: str | None = ...,
        sourcewidth: int | None = ...,
        dataid: int | None = ...,
        transid: int | None = ...,
        horizontalUnits: str | None = ...,
        horizontalspacing: float | None = ...,
        horizontalzeroindex: float | None = ...,
        horizontalfractionalzeroindex: float | None = ...,
        noofsamples: int | None = ...,
        chunksize: int | None = ...,
        wfmtype: _Union[WfmType, str] | None = ...,
        bitmask: int | None = ...,
        pairtype: _Union[WfmPairType, str] | None = ...,
        verticalunits: str | None = ...,
        verticalspacing: float | None = ...,
        verticaloffset: float | None = ...,
        iq_centerFrequency: float | None = ...,
        iq_fftLength: float | None = ...,
        iq_rbw: float | None = ...,
        iq_span: float | None = ...,
        iq_windowType: str | None = ...,
        hasdata: bool | None = ...,
        num_frames: int | None = ...,
        frame_info: _Iterable[_Union[FrameInfo, _Mapping]] | None = ...,
        current_frame_index: int | None = ...,
        probe_details: _Union[ProbeInfo, _Mapping] | None = ...,
        channel_sparam: _Union[SParam, _Mapping] | None = ...,
    ) -> None: ...

class FrameInfo(_message.Message):
    __slots__ = (
        "fract_sec",
        "frame_duration_sec",
        "frame_index",
        "gmt_sec",
        "is_summary_frame",
        "real_point_offset",
        "time_offset",
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
        frame_index: int | None = ...,
        time_offset: float | None = ...,
        gmt_sec: int | None = ...,
        fract_sec: float | None = ...,
        is_summary_frame: bool | None = ...,
        real_point_offset: int | None = ...,
        frame_duration_sec: float | None = ...,
    ) -> None: ...

class FrameBoundary(_message.Message):
    __slots__ = ("frame_info",)
    FRAME_INFO_FIELD_NUMBER: _ClassVar[int]
    frame_info: FrameInfo
    def __init__(self, frame_info: _Union[FrameInfo, _Mapping] | None = ...) -> None: ...

class NormalizedReply(_message.Message):
    __slots__ = ("frame_boundary", "headerordata", "status")
    class WaveformSampleChunk(_message.Message):
        __slots__ = ("data",)
        DATA_FIELD_NUMBER: _ClassVar[int]
        data: _containers.RepeatedScalarFieldContainer[float]
        def __init__(self, data: _Iterable[float] | None = ...) -> None: ...

    class DataOrHeaderAccess(_message.Message):
        __slots__ = ("chunk", "header")
        HEADER_FIELD_NUMBER: _ClassVar[int]
        CHUNK_FIELD_NUMBER: _ClassVar[int]
        header: WaveformHeader
        chunk: NormalizedReply.WaveformSampleChunk
        def __init__(
            self,
            header: _Union[WaveformHeader, _Mapping] | None = ...,
            chunk: _Union[NormalizedReply.WaveformSampleChunk, _Mapping] | None = ...,
        ) -> None: ...

    STATUS_FIELD_NUMBER: _ClassVar[int]
    HEADERORDATA_FIELD_NUMBER: _ClassVar[int]
    FRAME_BOUNDARY_FIELD_NUMBER: _ClassVar[int]
    status: WfmReplyStatus
    headerordata: NormalizedReply.DataOrHeaderAccess
    frame_boundary: FrameBoundary
    def __init__(
        self,
        status: _Union[WfmReplyStatus, str] | None = ...,
        headerordata: _Union[NormalizedReply.DataOrHeaderAccess, _Mapping] | None = ...,
        frame_boundary: _Union[FrameBoundary, _Mapping] | None = ...,
    ) -> None: ...

class RawReply(_message.Message):
    __slots__ = ("frame_boundary", "headerordata", "status")
    class WaveformSampleByteChunk(_message.Message):
        __slots__ = ("data",)
        DATA_FIELD_NUMBER: _ClassVar[int]
        data: bytes
        def __init__(self, data: bytes | None = ...) -> None: ...

    class DataOrHeaderAccess(_message.Message):
        __slots__ = ("chunk", "header")
        HEADER_FIELD_NUMBER: _ClassVar[int]
        CHUNK_FIELD_NUMBER: _ClassVar[int]
        header: WaveformHeader
        chunk: RawReply.WaveformSampleByteChunk
        def __init__(
            self,
            header: _Union[WaveformHeader, _Mapping] | None = ...,
            chunk: _Union[RawReply.WaveformSampleByteChunk, _Mapping] | None = ...,
        ) -> None: ...

    STATUS_FIELD_NUMBER: _ClassVar[int]
    HEADERORDATA_FIELD_NUMBER: _ClassVar[int]
    FRAME_BOUNDARY_FIELD_NUMBER: _ClassVar[int]
    status: WfmReplyStatus
    headerordata: RawReply.DataOrHeaderAccess
    frame_boundary: FrameBoundary
    def __init__(
        self,
        status: _Union[WfmReplyStatus, str] | None = ...,
        headerordata: _Union[RawReply.DataOrHeaderAccess, _Mapping] | None = ...,
        frame_boundary: _Union[FrameBoundary, _Mapping] | None = ...,
    ) -> None: ...
