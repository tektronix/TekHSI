from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import (
    ClassVar as _ClassVar,
    Iterable as _Iterable,
    Mapping as _Mapping,
    Optional as _Optional,
    Union as _Union,
)

CONNECTSTATUS_INUSE_FAILURE: ConnectStatus
CONNECTSTATUS_NOT_CONNECTED_FAILURE: ConnectStatus
CONNECTSTATUS_OUTSIDE_SEQUENCE_FAILURE: ConnectStatus
CONNECTSTATUS_SUCCESS: ConnectStatus
CONNECTSTATUS_TIMEOUT_FAILURE: ConnectStatus
CONNECTSTATUS_UNKNOWN_FAILURE: ConnectStatus
CONNECTSTATUS_UNSPECIFIED: ConnectStatus
DESCRIPTOR: _descriptor.FileDescriptor
WFMPAIRTYPE_NONE: WfmPairType
WFMPAIRTYPE_PAIR: WfmPairType
WFMPAIRTYPE_UNSPECIFIED: WfmPairType
WFMREPLYSTATUS_NO_CONNECTION_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_OUTSIDE_SEQUENCE_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_SOURCENAME_MISSING_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_SUCCESS: WfmReplyStatus
WFMREPLYSTATUS_TYPE_MISMATCH_FAILURE: WfmReplyStatus
WFMREPLYSTATUS_UNSPECIFIED: WfmReplyStatus
WFMTYPE_ANALOG_16: WfmType
WFMTYPE_ANALOG_16_IQ: WfmType
WFMTYPE_ANALOG_32_IQ: WfmType
WFMTYPE_ANALOG_8: WfmType
WFMTYPE_ANALOG_FLOAT: WfmType
WFMTYPE_DIGITAL_16: WfmType
WFMTYPE_DIGITAL_8: WfmType
WFMTYPE_UNSPECIFIED: WfmType

class AvailableNamesReply(_message.Message):
    __slots__ = ["status", "symbolnames"]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SYMBOLNAMES_FIELD_NUMBER: _ClassVar[int]
    status: ConnectStatus
    symbolnames: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        status: _Optional[_Union[ConnectStatus, str]] = ...,
        symbolnames: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class ConnectReply(_message.Message):
    __slots__ = ["status"]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: ConnectStatus
    def __init__(self, status: _Optional[_Union[ConnectStatus, str]] = ...) -> None: ...

class ConnectRequest(_message.Message):
    __slots__ = ["name"]
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class NormalizedReply(_message.Message):
    __slots__ = ["headerordata", "status"]
    class DataOrHeaderAccess(_message.Message):
        __slots__ = ["chunk", "header"]
        CHUNK_FIELD_NUMBER: _ClassVar[int]
        HEADER_FIELD_NUMBER: _ClassVar[int]
        chunk: NormalizedReply.WaveformSampleChunk
        header: WaveformHeader
        def __init__(
            self,
            header: _Optional[_Union[WaveformHeader, _Mapping]] = ...,
            chunk: _Optional[_Union[NormalizedReply.WaveformSampleChunk, _Mapping]] = ...,
        ) -> None: ...

    class WaveformSampleChunk(_message.Message):
        __slots__ = ["data"]
        DATA_FIELD_NUMBER: _ClassVar[int]
        data: _containers.RepeatedScalarFieldContainer[float]
        def __init__(self, data: _Optional[_Iterable[float]] = ...) -> None: ...

    HEADERORDATA_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    headerordata: NormalizedReply.DataOrHeaderAccess
    status: WfmReplyStatus
    def __init__(
        self,
        status: _Optional[_Union[WfmReplyStatus, str]] = ...,
        headerordata: _Optional[_Union[NormalizedReply.DataOrHeaderAccess, _Mapping]] = ...,
    ) -> None: ...

class RawReply(_message.Message):
    __slots__ = ["headerordata", "status"]
    class DataOrHeaderAccess(_message.Message):
        __slots__ = ["chunk", "header"]
        CHUNK_FIELD_NUMBER: _ClassVar[int]
        HEADER_FIELD_NUMBER: _ClassVar[int]
        chunk: RawReply.WaveformSampleByteChunk
        header: WaveformHeader
        def __init__(
            self,
            header: _Optional[_Union[WaveformHeader, _Mapping]] = ...,
            chunk: _Optional[_Union[RawReply.WaveformSampleByteChunk, _Mapping]] = ...,
        ) -> None: ...

    class WaveformSampleByteChunk(_message.Message):
        __slots__ = ["data"]
        DATA_FIELD_NUMBER: _ClassVar[int]
        data: bytes
        def __init__(self, data: _Optional[bytes] = ...) -> None: ...

    HEADERORDATA_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    headerordata: RawReply.DataOrHeaderAccess
    status: WfmReplyStatus
    def __init__(
        self,
        status: _Optional[_Union[WfmReplyStatus, str]] = ...,
        headerordata: _Optional[_Union[RawReply.DataOrHeaderAccess, _Mapping]] = ...,
    ) -> None: ...

class WaveformHeader(_message.Message):
    __slots__ = [
        "bitmask",
        "chunksize",
        "dataid",
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
        "pairtype",
        "sourcename",
        "sourcewidth",
        "transid",
        "verticaloffset",
        "verticalspacing",
        "verticalunits",
        "wfmtype",
    ]
    BITMASK_FIELD_NUMBER: _ClassVar[int]
    CHUNKSIZE_FIELD_NUMBER: _ClassVar[int]
    DATAID_FIELD_NUMBER: _ClassVar[int]
    HASDATA_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALFRACTIONALZEROINDEX_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALSPACING_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALUNITS_FIELD_NUMBER: _ClassVar[int]
    HORIZONTALZEROINDEX_FIELD_NUMBER: _ClassVar[int]
    IQ_CENTERFREQUENCY_FIELD_NUMBER: _ClassVar[int]
    IQ_FFTLENGTH_FIELD_NUMBER: _ClassVar[int]
    IQ_RBW_FIELD_NUMBER: _ClassVar[int]
    IQ_SPAN_FIELD_NUMBER: _ClassVar[int]
    IQ_WINDOWTYPE_FIELD_NUMBER: _ClassVar[int]
    NOOFSAMPLES_FIELD_NUMBER: _ClassVar[int]
    PAIRTYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCENAME_FIELD_NUMBER: _ClassVar[int]
    SOURCEWIDTH_FIELD_NUMBER: _ClassVar[int]
    TRANSID_FIELD_NUMBER: _ClassVar[int]
    VERTICALOFFSET_FIELD_NUMBER: _ClassVar[int]
    VERTICALSPACING_FIELD_NUMBER: _ClassVar[int]
    VERTICALUNITS_FIELD_NUMBER: _ClassVar[int]
    WFMTYPE_FIELD_NUMBER: _ClassVar[int]
    bitmask: int
    chunksize: int
    dataid: int
    hasdata: bool
    horizontalUnits: str
    horizontalfractionalzeroindex: float
    horizontalspacing: float
    horizontalzeroindex: float
    iq_centerFrequency: float
    iq_fftLength: float
    iq_rbw: float
    iq_span: float
    iq_windowType: str
    noofsamples: int
    pairtype: WfmPairType
    sourcename: str
    sourcewidth: int
    transid: int
    verticaloffset: float
    verticalspacing: float
    verticalunits: str
    wfmtype: WfmType
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
        hasdata: bool = ...,
    ) -> None: ...

class WaveformRequest(_message.Message):
    __slots__ = ["chunksize", "sourcename"]
    CHUNKSIZE_FIELD_NUMBER: _ClassVar[int]
    SOURCENAME_FIELD_NUMBER: _ClassVar[int]
    chunksize: int
    sourcename: str
    def __init__(
        self, sourcename: _Optional[str] = ..., chunksize: _Optional[int] = ...
    ) -> None: ...

class ConnectStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []

class WfmReplyStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []

class WfmPairType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []

class WfmType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
