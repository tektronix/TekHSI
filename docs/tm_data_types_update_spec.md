# tm_data_types Update Specification — FastFrame + TekHSI v2

**Status:** Implemented in `tm_data_types` 0.3.0 (updated wheel bundled at repo root)  
**Baseline:** `tm_data_types==0.3.0` with `FastFrameDigitalWaveform`, `FrameTimingInfo.is_summary_frame`, and `digital_bitmask`  
**Driver:** TekHSI client in [TekHSI_FastFrame_Proto](https://github.com/TEK-Product-AI-Sandbox/TekHSI_FastFrame_Proto) with v2 `normalizedvector.proto` and live-scope validation

---

## 1. Summary

TekHSI v2 FastFrame reads work with `tm_data_types` 0.3.0, but **digital FastFrame** and **per-frame summary metadata** do not map cleanly to the current type model. TekHSI uses workarounds today (`FastFrameAnalogWaveform` + ad-hoc `digital_bitmask`). This spec proposes minimal, backward-compatible extensions so callers receive **correct, dispatchable types** without duck-typing.

**Recommendation:** Use the repo-root `tm_data_types-0.3.0-py3-none-any.whl` or PyPI `tm_data_types==0.3.0` with TekHSI FastFrame support.

---

## 2. Problem statement

### 2.1 What works today (0.3.0)

| Source (TekHSI) | Returned type | Correct? |
|-----------------|---------------|------------|
| Single-frame analog (`wfmtype` 1–3) | `AnalogWaveform` | Yes |
| Single-frame digital (`wfmtype` 4–5) | `DigitalWaveform` | Yes |
| FastFrame analog (`num_frames > 1`) | `FastFrameAnalogWaveform` | Yes |
| FastFrame digital (`chN_DAll`, etc.) | `FastFrameAnalogWaveform` + **`digital_bitmask`** (monkey-patched) | **Functional, wrong type** |

Live scope validation (MSO, TekHSI v2):

- `ch1` — 100 × 2500 analog FastFrame frames
- `ch2_DAll` — 100 × 2500 digital FastFrame frames, `bitmask=0x1`

### 2.2 Pain points for callers

```python
wfm = connection.get_data("ch2_dall")

isinstance(wfm, DigitalWaveform)   # False — isinstance(..., AnalogWaveform) is True
wfm.get_nth_bitstream(0)           # AttributeError
getattr(wfm, "digital_bitmask")    # Works only because TekHSI sets it ad hoc
```

Documentation and examples (`digital_waveform_usage.py`) assume `DigitalWaveform` for digital bus data. FastFrame digital breaks that contract.

### 2.3 Proto v2 metadata not fully represented

TekHSI v2 `FrameInfo` (in `normalizedvector.proto`) includes:

```protobuf
bool is_summary_frame = 5;
```

`tm_data_types.FrameTimingInfo` (0.3.0) has **no** `is_summary_frame`. TekHSI maps timing fields but drops the per-frame summary flag. Summary handling falls back to:

- `SummaryFrameType` enum on the waveform, and
- `summary_frame_index` = last frame when summary is “on”

That fails when:

- Summary frames are **disabled** on the scope (all frames are data — common on live captures).
- Summary frame is **not** the last index (future / edge cases).

---

## 3. Design goals

1. **Correct runtime types** — `isinstance` and type checkers match physical data (analog vs digital).
2. **Parallel APIs** — digital FastFrame mirrors analog FastFrame frame access patterns.
3. **Proto fidelity** — preserve `is_summary_frame` and `bitmask` from TekHSI headers.
4. **Backward compatibility** — 0.3.0 behavior remains valid; new types are additive.
5. **Minimal TekHSI churn** — swap wrapper class in one code path; no protocol changes.

---

## 4. Proposed changes

### 4.1 P0 — `FastFrameDigitalWaveform` (required)

Add a new class:

```python
class FastFrameDigitalWaveform(DigitalWaveform):
    """Multi-frame digital acquisition (FastFrame), TekHSI-compatible."""
```

**Mirror `FastFrameAnalogWaveform` surface** where applicable:

| Member | Semantics |
|--------|-----------|
| `create_fastframe(frame_count, record_length, dtype=np.int8, **kwargs)` | Class method; pre-allocate frame storage |
| `fill_frame(index, data)` | Copy raw byte/int sample array into frame `index` |
| `frame_data(index)` | Raw samples for frame without changing current frame |
| `frame(index) -> DigitalWaveform` | Single-frame **digital** view (`y_axis_byte_values`, `get_nth_bitstream`) |
| `frames(include_summary=False)` | Iterator of `(index, DigitalWaveform)` |
| `num_frames`, `current_frame_index`, `all_frames_loaded` | Same as analog FastFrame |
| `frame_info: list[FrameTimingInfo]` | Per-frame timing |
| `summary_frame_type`, `summary_frame_index`, `data_frame_count` | Same semantics as analog (updated per §4.2) |
| `is_summary_frame(index)` | Uses per-frame flags when available (§4.2) |
| `load_timing` | Optional opaque timing object (TekHSI sets `FastFrameLoadTiming`) |
| `digital_bitmask: int` | From proto `WaveformHeader.bitmask`; which digital lines are active |

**Frame view construction:** `_build_frame_view(index)` wraps backing bytes in `DigitalWaveform` with `y_axis_byte_values` set from the frame buffer (not `y_axis_values`).

**Storage:** Reuse the same backing-frame pattern as `FastFrameAnalogWaveform` (`_stream_frames` list or `_frame_data` 2-D array). Dtype typically `np.int8` / `np.int16` per `sourcewidth`.

**Export:** Add to `tm_data_types.__init__` and `__all__`.

---

### 4.2 P0 — `FrameTimingInfo.is_summary_frame` (required)

Extend the dataclass:

```python
@dataclass
class FrameTimingInfo:
    frame_index: int
    time_offset: float
    gmt_sec: int
    fract_sec: float
    real_point_offset: int
    frame_duration_sec: float
    is_summary_frame: bool = False   # NEW — default False for WFM / legacy paths
```

**Update summary logic on both FastFrame classes:**

```python
@property
def summary_frame_index(self) -> int | None:
    flagged = [info.frame_index for info in self.frame_info if info.is_summary_frame]
    if flagged:
        return flagged[0]   # or document rule if multiple allowed
    if self.summary_frame_type == SummaryFrameType.SUMMARY_FRAME_OFF:
        return None
    return self.num_frames - 1   # legacy WFM fallback

def is_summary_frame(self, index: int) -> bool:
    for info in self.frame_info:
        if info.frame_index == index:
            return info.is_summary_frame
    return self.summary_frame_index is not None and index == self.summary_frame_index
```

**TekHSI mapping** (already available in client; enable after tm_data_types update):

```python
FrameTimingInfo(
    frame_index=info.frame_index,
    time_offset=info.time_offset,
    gmt_sec=info.gmt_sec,
    fract_sec=info.fract_sec,
    real_point_offset=info.real_point_offset,
    frame_duration_sec=info.frame_duration_sec,
    is_summary_frame=info.is_summary_frame,  # from proto
)
```

When **no** frame has `is_summary_frame=True`, `summary_frame_index` must be **`None`** regardless of `summary_frame_type` inference.

---

### 4.3 P1 — First-class `digital_bitmask` on digital types (recommended)

| Type | Field |
|------|-------|
| `DigitalWaveform` | `digital_bitmask: int = 0` |
| `FastFrameDigitalWaveform` | `digital_bitmask: int = 0` (required at FastFrame level) |

Populate from TekHSI `WaveformHeader.bitmask`. Document: bit *n* set ⇒ line *n* present in the packed byte stream (scope convention).

Remove need for TekHSI to attach arbitrary attributes.

---

### 4.4 P2 — `waveform_kind` property (optional)

Add read-only property on `Waveform` base (or shared mixin):

```python
@property
def waveform_kind(self) -> Literal["analog", "digital", "iq"]:
    ...
```

Implementation: class-based dispatch (`DigitalWaveform` → `"digital"`, etc.). Helps generic plotting / file routing without `isinstance` chains.

---

### 4.5 P3 — WFM file I/O for digital FastFrame (future)

0.3.0 WFM reader/writer paths target `FastFrameAnalogWaveform`. Out of scope for initial 0.4.0 unless WFM format already defines digital FastFrame curves — track separately.

---

## 5. TekHSI client changes (after tm_data_types 0.4.0)

Minimal diff in `tek_hsi_connect.py`:

```python
# _read_digital_native — FastFrame branch
wrapped = self._read_native_fastframe(
    header,
    native_stub,
    self.d_datatypes[header.sourcewidth],
    wrapper=FastFrameDigitalWaveform,  # NEW parameter
)
wrapped.digital_bitmask = header.bitmask
return wrapped
```

Generalize `_build_fastframe_from_native` / `_read_native_fastframe` to accept `wrapper: type` defaulting to `FastFrameAnalogWaveform`.

Export from `tekhsi`:

```python
from tm_data_types import FastFrameAnalogWaveform, FastFrameDigitalWaveform, FrameTimingInfo
```

Update `get_frame()` docstring: digital FastFrame returns `DigitalWaveform` views from `frame()`.

**Pin:** `pyproject.toml` → `tm_data_types==0.4.0` when released.

---

## 6. Type dispatch guide (target state)

```python
wfm = connection.get_data("ch1")
if isinstance(wfm, FastFrameAnalogWaveform):
    volts = wfm.frame_array(0)
elif isinstance(wfm, FastFrameDigitalWaveform):
    bits = wfm.frame(0).get_nth_bitstream(0)
elif isinstance(wfm, AnalogWaveform):
    ...
elif isinstance(wfm, DigitalWaveform):
    ...
```

Or with P2:

```python
match wfm.waveform_kind:
    case "analog" if wfm.is_fastframe:
        ...
    case "digital" if wfm.is_fastframe:
        ...
```

---

## 7. Acceptance criteria

### 7.1 Unit tests (tm_data_types)

- [ ] `FastFrameDigitalWaveform.create_fastframe(100, 2500, dtype=np.int8)` pre-allocates 100 frames
- [ ] `fill_frame` + `frame_data` round-trip raw bytes
- [ ] `frame(i)` returns `DigitalWaveform`; `get_nth_bitstream(n)` works on frame view
- [ ] `digital_bitmask` preserved on parent and frame views
- [ ] `FrameTimingInfo.is_summary_frame` drives `summary_frame_index` / `data_frame_count`
- [ ] All-summary-false → `summary_frame_index is None`, `data_frame_count == num_frames`
- [ ] 0.3.0 pickle/API: existing `FastFrameAnalogWaveform` tests unchanged

### 7.2 Integration tests (TekHSI + tm_data_types)

- [ ] Live or mocked TekHSI: `ch1` FastFrame → `FastFrameAnalogWaveform`
- [ ] Live or mocked TekHSI: `ch2_DAll` FastFrame → `FastFrameDigitalWaveform`, `digital_bitmask == header.bitmask`
- [ ] `isinstance(get_data("ch2_dall"), DigitalWaveform)` is False; `isinstance(..., FastFrameDigitalWaveform)` is True
- [ ] Summary disabled on scope → `summary_frame_index is None` (regression for optional summary frames)

---

## 8. Non-goals

- Changing TekHSI gRPC proto definitions (frozen in `normalizedvector.proto`)
- Replacing `FastFrameAnalogWaveform` or breaking 0.3.0 import paths
- Normalized vs native sample interpretation in tm_data_types (TekHSI loads **native** raw codes)
- Symbol alias logic (`ch2` → `ch2_DAll`) — TekHSI client concern, not tm_data_types

---

## 9. Migration notes

| Consumer | Action |
|----------|--------|
| TekHSI demo repo | Bump pin to `0.4.0`, use `FastFrameDigitalWaveform` in digital FastFrame path |
| Code checking `FastFrameAnalogWaveform` only | Also handle `FastFrameDigitalWaveform` or use `waveform_kind` |
| Code using `digital_bitmask` hack | Switch to `FastFrameDigitalWaveform.digital_bitmask` |
| WFM-only workflows | No change until P3 |

---

## 10. References

- TekHSI proto: `normalizedvector.proto` (`FrameInfo.is_summary_frame`, `WaveformHeader.bitmask`)
- TekHSI client: `src/tekhsi/tek_hsi_connect.py` — `_build_fastframe_from_native`, `_read_digital_native`
- Demo guide: `docs/DEMO_README.md`
- Current types: `tm_data_types.datum.waveforms.fastframe_analog_waveform`, `digital_waveform`

---

## 11. Open questions

1. **Multiple summary frames** — Does any scope emit more than one `is_summary_frame=True`? If yes, document whether `summary_frame_index` returns first, last, or raises.
2. **FastFrame digital normalized values** — Should `frame_array()` exist on digital FastFrame (thresholded floats) or remain digital-only byte/bit APIs?
3. **Shared base class** — Worth a private `_FastFrameBase` shared by analog/digital to deduplicate frame indexing, or keep parallel classes for clarity?
