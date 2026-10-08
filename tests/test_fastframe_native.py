"""Unit tests for FastFrame native build/stream-assembly logic.

These exercise the pure/static FastFrame helpers on ``TekHSIConnect`` directly with
synthetic protobuf messages, without requiring a live scope or the (single-frame-only)
mock test server. This covers the code paths that previously had no automated coverage:
``_build_fastframe_from_native``, ``_read_fastframe_stream``, and the small header/frame
metadata helpers that feed them.
"""

# Test methods describe behavior through their names; the helper imports and stub shape
# are intentional for isolated protobuf tests.
# pylint: disable=missing-function-docstring,import-outside-toplevel,too-few-public-methods

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import numpy as np
import pytest

from tm_data_types import (
    FastFrameAnalogWaveform,
    FastFrameDigitalWaveform,
    FrameTimingInfo,
    SummaryFrameType,
)

from tekhsi._tek_highspeed_server_pb2 import (  # pylint: disable=no-name-in-module
    FrameBoundary,
    FrameInfo,
    RawReply,
    WaveformHeader,
    WaveformRequest,
    WfmReplyStatus,
    WfmType,
)
from tekhsi.tek_hsi_connect import TekHSIConnect

if TYPE_CHECKING:
    from collections.abc import Iterator


def _static_helper(name: str) -> Any:
    """Resolve an internal client helper for focused unit coverage."""
    return getattr(TekHSIConnect, name)


def _instance_helper(client: TekHSIConnect, name: str) -> Any:
    """Resolve an internal client method for focused unit coverage."""
    return getattr(client, name)


def _make_header(  # noqa: PLR0913
    *,
    num_frames: int = 3,
    noofsamples: int = 4,
    sourcewidth: int = 1,
    wfmtype: int = WfmType.WFMTYPE_ANALOG_8,
    bitmask: int = 0,
    current_frame_index: int = 0,
    with_frame_info: bool = False,
    summary_last: bool = False,
) -> WaveformHeader:
    header = WaveformHeader(
        sourcename="ch1",
        sourcewidth=sourcewidth,
        noofsamples=noofsamples,
        wfmtype=wfmtype,
        num_frames=num_frames,
        current_frame_index=current_frame_index,
        verticalspacing=1.0,
        verticaloffset=0.0,
        verticalunits="V",
        horizontalspacing=1e-9,
        horizontalUnits="s",
        horizontalzeroindex=0,
        bitmask=bitmask,
        hasdata=True,
    )
    if with_frame_info:
        for idx in range(num_frames):
            header.frame_info.add(
                frame_index=idx,
                time_offset=idx * 1e-6,
                gmt_sec=1000 + idx,
                fract_sec=0.5,
                is_summary_frame=summary_last and idx == num_frames - 1,
                real_point_offset=idx * noofsamples,
                frame_duration_sec=1e-6,
            )
    return header


class TestHeaderHelpers:
    """Static header/frame-metadata helper coverage."""

    def test_is_fastframe_header_true(self) -> None:
        """Accept headers describing multiple frames."""
        assert _static_helper("_is_fastframe_header")(_make_header(num_frames=5)) is True

    def test_is_fastframe_header_false_single_frame(self) -> None:
        """Reject headers describing only one frame."""
        assert _static_helper("_is_fastframe_header")(_make_header(num_frames=1)) is False

    def test_summary_frame_count_from_header_none(self) -> None:
        """Report no summary frame when frame metadata has none."""
        header = _make_header(num_frames=3, with_frame_info=True, summary_last=False)
        assert not _static_helper("_summary_frame_count_from_header")(header)

    def test_summary_frame_count_from_header_one(self) -> None:
        """Count a single summary frame from header metadata."""
        header = _make_header(num_frames=3, with_frame_info=True, summary_last=True)
        assert _static_helper("_summary_frame_count_from_header")(header) == 1

    def test_summary_frame_type_from_header_off(self) -> None:
        """Return the disabled summary type when no summary exists."""
        header = _make_header(num_frames=2, with_frame_info=True, summary_last=False)
        assert (
            _static_helper("_summary_frame_type_from_header")(header)
            == SummaryFrameType.SUMMARY_FRAME_OFF
        )

    def test_summary_frame_type_from_header_average(self) -> None:
        """Return the average summary type when metadata marks a summary frame."""
        header = _make_header(num_frames=2, with_frame_info=True, summary_last=True)
        assert (
            _static_helper("_summary_frame_type_from_header")(header)
            == SummaryFrameType.SUMMARY_FRAME_AVERAGE
        )

    def test_frame_info_from_header_round_trips_fields(self) -> None:
        """Convert protobuf frame metadata into timing information."""
        header = _make_header(num_frames=2, with_frame_info=True, summary_last=True)
        info_list = _static_helper("_frame_info_from_header")(header)
        assert len(info_list) == 2
        assert info_list[1].is_summary_frame is True
        assert not info_list[0].frame_index

    def test_frame_info_map_keeps_last_for_duplicate_index(self) -> None:
        """Keep the latest timing record for duplicate frame indexes."""
        infos = [
            FrameTimingInfo(0, 0.0, 0, 0.0, 0, 0.0, is_summary_frame=False),
            FrameTimingInfo(0, 1.0, 1, 0.0, 0, 0.0, is_summary_frame=True),
        ]
        mapped = _static_helper("_frame_info_map")(infos)
        assert mapped[0].time_offset == 1.0
        assert mapped[0].is_summary_frame is True

    def test_merge_fastframe_frame_info_prefers_stream(self) -> None:
        """Prefer stream timing metadata over matching header metadata."""
        header = _make_header(num_frames=2, with_frame_info=True, summary_last=False)
        stream_info = [FrameTimingInfo(1, 9.0, 9, 0.0, 0, 0.0, is_summary_frame=True)]
        merged = _static_helper("_merge_fastframe_frame_info")(header, stream_info)
        assert len(merged) == 2
        assert merged[1].is_summary_frame is True
        assert merged[1].time_offset == 9.0

    def test_summary_frame_type_from_frame_info(self) -> None:
        """Determine summary type from timing metadata."""
        none_summary = [FrameTimingInfo(0, 0.0, 0, 0.0, 0, 0.0, is_summary_frame=False)]
        with_summary = [FrameTimingInfo(0, 0.0, 0, 0.0, 0, 0.0, is_summary_frame=True)]
        assert (
            _static_helper("_summary_frame_type_from_frame_info")(none_summary)
            == SummaryFrameType.SUMMARY_FRAME_OFF
        )
        assert (
            _static_helper("_summary_frame_type_from_frame_info")(with_summary)
            == SummaryFrameType.SUMMARY_FRAME_AVERAGE
        )

    def test_trim_raw_frames_pads_or_trims_to_samples_per_frame(self) -> None:
        """Trim frames to the requested sample count without padding short frames."""
        frames = [np.array([1, 2, 3, 4, 5], dtype=np.int8), np.array([1, 2], dtype=np.int8)]
        trimmed = _static_helper("_trim_raw_frames")(frames, samples_per_frame=4)
        assert len(trimmed[0]) == 4
        assert len(trimmed[1]) == 2  # shorter frame is left as-is (not padded)

    def test_transfer_timing_from_header_reports_fastframe(self) -> None:
        """Report FastFrame timing and summary metadata from a header."""
        header = _make_header(num_frames=4, noofsamples=10, with_frame_info=True, summary_last=True)
        timing = _static_helper("_transfer_timing_from_header")(header, "analog", 12.5, 1.5)
        assert timing.fastframe is True
        assert timing.num_frames == 4
        assert timing.summary_frame_count == 1
        assert timing.record_length == 10

    def test_transfer_timing_from_header_single_frame(self) -> None:
        """Report non-FastFrame timing for a single-frame header."""
        header = _make_header(num_frames=1, noofsamples=10)
        timing = _static_helper("_transfer_timing_from_header")(header, "analog", 1.0)
        assert timing.fastframe is False
        assert timing.num_frames == 1

    def test_waveform_kind_from_header(self) -> None:
        """Classify analog, digital, and IQ waveform headers."""
        assert (
            _static_helper("_waveform_kind_from_header")(
                _make_header(wfmtype=WfmType.WFMTYPE_ANALOG_8)
            )
            == "analog"
        )
        assert (
            _static_helper("_waveform_kind_from_header")(
                _make_header(wfmtype=WfmType.WFMTYPE_DIGITAL_8)
            )
            == "digital"
        )
        assert (
            _static_helper("_waveform_kind_from_header")(
                _make_header(wfmtype=WfmType.WFMTYPE_ANALOG_16_IQ)
            )
            == "iq"
        )

    def test_waveform_request_for_header_sets_stream_all_frames(self) -> None:
        """Set stream-all-frames only for FastFrame requests."""
        ff_header = _make_header(num_frames=3)
        single_header = _make_header(num_frames=1)
        client = TekHSIConnect.__new__(TekHSIConnect)
        client.chunksize = 4096
        ff_request = _instance_helper(client, "_waveform_request_for_header")(ff_header)
        single_request = _instance_helper(client, "_waveform_request_for_header")(single_header)
        assert ff_request.stream_all_frames is True
        assert single_request.stream_all_frames is False


class TestBuildFastFrameFromNative:
    """``_build_fastframe_from_native`` — analog and digital wrapper construction."""

    def test_builds_analog_fastframe_with_summary(self) -> None:
        """Build an analog FastFrame waveform with summary metadata."""
        header = _make_header(num_frames=3, noofsamples=4, with_frame_info=True, summary_last=True)
        raw_frames = [np.arange(4, dtype=np.int8) + (i * 10) for i in range(3)]
        waveform = _static_helper("_build_fastframe_from_native")(
            header,
            raw_frames,
            samples_per_frame=4,
            dt_type=np.int8,
            load_timing=None,
        )
        assert isinstance(waveform, FastFrameAnalogWaveform)
        assert waveform.num_frames == 3
        assert waveform.summary_frame_type == SummaryFrameType.SUMMARY_FRAME_AVERAGE
        assert waveform.summary_frame_index == 2
        np.testing.assert_array_equal(waveform.frame_data(1), raw_frames[1])

    def test_builds_digital_fastframe_with_bitmask(self) -> None:
        """Build a digital FastFrame waveform with its bitmask."""
        header = _make_header(
            num_frames=2,
            noofsamples=4,
            wfmtype=WfmType.WFMTYPE_DIGITAL_8,
            bitmask=0x0F,
        )
        raw_frames = [np.array([1, 2, 3, 4], dtype=np.int8), np.array([5, 6, 7, 8], dtype=np.int8)]
        waveform = _static_helper("_build_fastframe_from_native")(
            header,
            raw_frames,
            samples_per_frame=4,
            dt_type=np.int8,
            load_timing=None,
            wrapper=FastFrameDigitalWaveform,
        )
        assert isinstance(waveform, FastFrameDigitalWaveform)
        assert waveform.digital_bitmask == 0x0F
        assert waveform.num_frames == 2

    def test_clamps_out_of_range_current_frame_index(self) -> None:
        """Clamp a header current-frame index outside the available frames."""
        header = _make_header(num_frames=2, noofsamples=4, current_frame_index=99)
        raw_frames = [np.zeros(4, dtype=np.int8), np.ones(4, dtype=np.int8)]
        waveform = _static_helper("_build_fastframe_from_native")(
            header, raw_frames, samples_per_frame=4, dt_type=np.int8, load_timing=None
        )
        assert not waveform.current_frame_index

    def test_no_summary_when_frame_info_absent(self) -> None:
        """Leave summary metadata disabled when the header has no frame info."""
        header = _make_header(num_frames=2, noofsamples=4, with_frame_info=False)
        raw_frames = [np.zeros(4, dtype=np.int8), np.ones(4, dtype=np.int8)]
        waveform = _static_helper("_build_fastframe_from_native")(
            header, raw_frames, samples_per_frame=4, dt_type=np.int8, load_timing=None
        )
        assert waveform.summary_frame_type == SummaryFrameType.SUMMARY_FRAME_OFF
        assert waveform.per_frame_summary_authoritative is False


def _chunk_reply(data: bytes) -> RawReply:
    reply = RawReply()
    reply.status = WfmReplyStatus.WFMREPLYSTATUS_SUCCESS
    reply.headerordata.chunk.data = data
    return reply


def _boundary_reply(frame_index: int) -> RawReply:
    reply = RawReply()
    reply.status = WfmReplyStatus.WFMREPLYSTATUS_SUCCESS
    boundary = FrameBoundary(frame_info=FrameInfo(frame_index=frame_index, is_summary_frame=False))
    reply.frame_boundary.CopyFrom(boundary)
    return reply


class TestReadFastFrameStream:
    """``_read_fastframe_stream`` — chunk/frame-boundary stream assembly."""

    def _make_client(self) -> TekHSIConnect:
        client = TekHSIConnect.__new__(TekHSIConnect)
        client.thread_active = True
        return client

    def test_assembles_frames_split_by_boundary(self) -> None:
        """Assemble sample chunks separated by stream frame boundaries."""
        client = self._make_client()
        header = _make_header(num_frames=2, noofsamples=4)
        frame0 = np.array([1, 2, 3, 4], dtype=np.int8)
        frame1 = np.array([5, 6, 7, 8], dtype=np.int8)
        responses = [
            _boundary_reply(0),
            _chunk_reply(frame0.tobytes()),
            _boundary_reply(1),
            _chunk_reply(frame1.tobytes()),
        ]
        frame_arrays, stream_frame_info = _instance_helper(client, "_read_fastframe_stream")(
            iter(responses), header, np.int8, samples_per_frame=4
        )
        assert len(frame_arrays) == 2
        np.testing.assert_array_equal(frame_arrays[0], frame0)
        np.testing.assert_array_equal(frame_arrays[1], frame1)
        assert [info.frame_index for info in stream_frame_info] == [0, 1]

    def test_recombines_single_concatenated_message_into_frames(self) -> None:
        """Some servers may send all samples in one chunk with no boundaries."""
        client = self._make_client()
        header = _make_header(num_frames=2, noofsamples=3)
        combined = np.array([1, 2, 3, 4, 5, 6], dtype=np.int8)
        responses = [_chunk_reply(combined.tobytes())]
        frame_arrays, _ = _instance_helper(client, "_read_fastframe_stream")(
            iter(responses), header, np.int8, samples_per_frame=3
        )
        assert len(frame_arrays) == 2
        np.testing.assert_array_equal(frame_arrays[0], combined[:3])
        np.testing.assert_array_equal(frame_arrays[1], combined[3:6])

    def test_ignores_non_success_non_unspecified_status(self) -> None:
        """Ignore failed replies and retain valid waveform chunks."""
        client = self._make_client()
        header = _make_header(num_frames=1, noofsamples=2)
        bad = RawReply()
        bad.status = WfmReplyStatus.WFMREPLYSTATUS_TYPE_MISMATCH_FAILURE
        bad.headerordata.chunk.data = np.array([9, 9], dtype=np.int8).tobytes()
        good = _chunk_reply(np.array([1, 2], dtype=np.int8).tobytes())
        frame_arrays, _ = _instance_helper(client, "_read_fastframe_stream")(
            iter([bad, good]), header, np.int8, samples_per_frame=2
        )
        assert len(frame_arrays) == 1
        np.testing.assert_array_equal(frame_arrays[0], np.array([1, 2], dtype=np.int8))

    def test_stops_early_when_thread_not_active(self) -> None:
        """Stop stream assembly when the client thread is inactive."""
        client = self._make_client()
        client.thread_active = False
        header = _make_header(num_frames=2, noofsamples=4)
        frame_arrays, stream_frame_info = _instance_helper(client, "_read_fastframe_stream")(
            iter([_boundary_reply(0), _chunk_reply(b"\x01\x02\x03\x04")]),
            header,
            np.int8,
            samples_per_frame=4,
        )
        assert frame_arrays == []
        assert not stream_frame_info


class _FakeNativeStub:
    """Stand-in for ``NativeDataStub`` that returns a canned GetWaveform stream."""

    def __init__(self, responses: list[RawReply]) -> None:
        self._responses = responses
        self.calls: list[tuple[object, float | None]] = []

    def get_waveform(
        self, request: WaveformRequest, timeout: float | None = None
    ) -> Iterator[RawReply]:
        """Return the canned native waveform response stream."""
        self.calls.append((request, timeout))
        return iter(self._responses)


_FakeNativeStub.GetWaveform = _FakeNativeStub.get_waveform


class TestReadNativeFastFrame:
    """``_read_native_fastframe`` — end-to-end orchestration without a live scope."""

    def _make_client(self) -> TekHSIConnect:
        client = TekHSIConnect.__new__(TekHSIConnect)
        client.thread_active = True
        client.chunksize = 4096
        client.verbose = False
        return client

    def test_reads_and_builds_analog_fastframe(self) -> None:
        """Read and build an analog FastFrame waveform from native replies."""
        client = self._make_client()
        header = _make_header(num_frames=2, noofsamples=4, with_frame_info=True, summary_last=True)
        frame0 = np.array([1, 2, 3, 4], dtype=np.int8)
        frame1 = np.array([5, 6, 7, 8], dtype=np.int8)
        responses = [
            _boundary_reply(0),
            _chunk_reply(frame0.tobytes()),
            _boundary_reply(1),
            _chunk_reply(frame1.tobytes()),
        ]
        stub = _FakeNativeStub(responses)

        waveform = _instance_helper(client, "_read_native_fastframe")(header, stub, np.int8)

        assert isinstance(waveform, FastFrameAnalogWaveform)
        assert waveform.num_frames == 2
        np.testing.assert_array_equal(waveform.frame_data(0), frame0)
        np.testing.assert_array_equal(waveform.frame_data(1), frame1)
        assert waveform.load_timing is not None
        assert waveform.load_timing.num_frames == 2
        assert stub.calls[0][0].stream_all_frames is True

    def test_reads_and_builds_digital_fastframe(self) -> None:
        """Read and build a digital FastFrame waveform from native replies."""
        client = self._make_client()
        header = _make_header(
            num_frames=2,
            noofsamples=3,
            wfmtype=WfmType.WFMTYPE_DIGITAL_8,
            bitmask=0x01,
        )
        frame0 = np.array([1, 1, 1], dtype=np.int8)
        frame1 = np.array([0, 0, 0], dtype=np.int8)
        responses = [
            _boundary_reply(0),
            _chunk_reply(frame0.tobytes()),
            _boundary_reply(1),
            _chunk_reply(frame1.tobytes()),
        ]
        stub = _FakeNativeStub(responses)

        waveform = _instance_helper(client, "_read_native_fastframe")(
            header, stub, np.int8, wrapper=FastFrameDigitalWaveform
        )

        assert isinstance(waveform, FastFrameDigitalWaveform)
        assert waveform.digital_bitmask == 0x01
        np.testing.assert_array_equal(waveform.frame_data(0), frame0)

    def test_raises_when_frame_count_mismatch(self) -> None:
        """If the stream yields fewer segments than the header promises, raise clearly."""
        client = self._make_client()
        header = _make_header(num_frames=3, noofsamples=4)
        # Only one frame's worth of data/boundaries provided for a 3-frame header.
        raw = np.array([1, 2, 3, 4], dtype=np.int8).tobytes()
        responses = [
            _boundary_reply(0),
            _chunk_reply(raw),
        ]
        stub = _FakeNativeStub(responses)

        with pytest.raises(RuntimeError, match="expected 3 FastFrame segments"):
            _instance_helper(client, "_read_native_fastframe")(header, stub, np.int8)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
