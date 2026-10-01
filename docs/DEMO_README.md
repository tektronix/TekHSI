# TekHSI FastFrame Guide

`TekHSI` includes **FastFrame** support on top of the v2 TekHSI protocol (`normalizedvector.proto`),
using the `FastFrameAnalogWaveform` / `FastFrameDigitalWaveform` types from `tm_data_types`
(`~=0.4.0`, see [`pyproject.toml`](https://github.com/tektronix/TekHSI/blob/main/pyproject.toml)).

This feature is part of the standard `tekhsi` package — no separate wheel or demo build is
required; a normal `pip install tekhsi` (or upgrade) is sufficient. See the
[CHANGELOG](https://github.com/tektronix/TekHSI/blob/main/docs/CHANGELOG.md) for the release this
first shipped in.

## What's included

| Feature                   | Description                                                                                  |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| **FastFrame reads**       | Multi-frame analog → `FastFrameAnalogWaveform`; digital → `FastFrameDigitalWaveform`         |
| **Stopped-scope access**  | `access_stopped_data()` handles `force_sequence()` + `AnyAcq` for stopped FastFrame captures |
| **Raw digitizer access**  | `frame_data(index)` returns raw ADC codes; `frame_array(index)` returns normalized volts     |
| **Summary frame**         | High Res FastFrame captures include an average/summary frame at `summary_frame_index`        |
| **Load timing**           | `waveform.load_timing` reports transfer and publish time (TekHSI-specific instrumentation)   |
| **tm_data_types ~=0.4.0** | Shared waveform types across TekHSI, tm_devices, and file I/O                                |

## Requirements

- 64-bit Python 3.10–3.13
- A Tektronix scope with TekHSI enabled (4/5/6 Series MSO family)
- For TLS-enabled scopes: a trust callback or credential store (see FastFrame example below, and
    [`EUCRA_USAGE.md`](EUCRA_USAGE.md) for the full security guide)

## Installation

```shell
pip install tekhsi
```

Or, to build and install from a local checkout:

```shell
python -m pip install build
python -m build --wheel --outdir dist
pip install dist/tekhsi-*.whl
```

Verify:

```shell
python -c "from tekhsi import FastFrameAnalogWaveform, TekHSIConnect; print('ok')"
```

## Quick start — read one channel

From [`examples/analog_waveform_usage.py`](https://github.com/tektronix/TekHSI/blob/main/examples/analog_waveform_usage.py):

```python
import matplotlib.pyplot as plt

from tm_data_types import AnalogWaveform
from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    with connection.access_data():
        waveform: AnalogWaveform = connection.get_data("ch1")

    vd = waveform.normalized_vertical_values
    hd = waveform.normalized_horizontal_values

    _, ax = plt.subplots()
    ax.plot(hd, vd)
    ax.set(xlabel=waveform.x_axis_units, ylabel=waveform.y_axis_units, title="CH1")
    plt.show()
```

## Examples from `examples/`

The [`examples/`](https://github.com/tektronix/TekHSI/tree/main/examples) folder contains runnable scripts. Set your scope IP before running.

### Save repeated acquisitions — `simple_single_hs.py`

Pull ten consecutive acquisitions and write each to CSV:

```python
from tm_data_types import AnalogWaveform, write_file
from tekhsi import AcqWaitOn, TekHSIConnect

addr = "192.168.0.1"

with TekHSIConnect(f"{addr}:5000", ["ch1"]) as connect:
    for i in range(10):
        with connect.access_data(AcqWaitOn.NextAcq):
            wfm: AnalogWaveform = connect.get_data("ch1")
        write_file(f"{wfm.source_name}_{i}.csv", wfm)
```

Run: `python examples/simple_single_hs.py`

### Plot multiple channels — `simple_plot.py`

Read two channels in one acquisition and plot them:

```python
import matplotlib.pyplot as plt

from tm_data_types import AnalogWaveform
from tekhsi import AcqWaitOn, TekHSIConnect

address = "192.168.0.1"

with TekHSIConnect(f"{address}:5000", ["ch1", "ch3"]) as connection:
    with connection.access_data(AcqWaitOn.NewData):
        ch1: AnalogWaveform = connection.get_data("ch1")
        ch3: AnalogWaveform = connection.get_data("ch3")

fig, subplot = plt.subplots(2)

if ch1 is not None:
    subplot[0].set_title(ch1.source_name)
    subplot[0].plot(ch1.normalized_horizontal_values, ch1.normalized_vertical_values)

if ch3 is not None:
    subplot[1].set_title(ch3.source_name)
    subplot[1].plot(ch3.normalized_horizontal_values, ch3.normalized_vertical_values)

plt.show()
```

Run: `python examples/simple_plot.py`

### Custom acquisition filter — `custom_filter.py`

Only accept acquisitions when horizontal or vertical scale changes:

```python
from tm_data_types import AnalogWaveform, write_file
from tekhsi import TekHSIConnect, WaveformHeader


def custom_filter(
    previous_header: dict[str, WaveformHeader],
    current_header: dict[str, WaveformHeader],
) -> bool:
    for key, cur in current_header.items():
        if key not in previous_header:
            return True
        prev = previous_header[key]
        if prev is not None and (
            prev.verticalspacing != cur.verticalspacing
            or prev.horizontalspacing != cur.horizontalspacing
        ):
            return True
    return False


with TekHSIConnect("192.168.0.1:5000", ["ch1"]) as connect:
    connect.set_acq_filter(custom_filter)
    for i in range(10):
        connect.wait_for_data()
        wfm: AnalogWaveform = connect.get_data("ch1")
        connect.done_with_data()
        write_file(f"{wfm.source_name}_{i}.csv", wfm)
```

Run: `python examples/custom_filter.py`

### Digital bus — `digital_waveform_usage.py`

Plot one bit from a digital waveform:

```python
import matplotlib.pyplot as plt
import numpy as np

from tm_data_types import DigitalWaveform
from tekhsi import AcqWaitOn, TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    with connection.access_data(AcqWaitOn.NewData):
        waveform: DigitalWaveform = connection.get_data("ch4_DAll")

    vd = waveform.get_nth_bitstream(3).astype(np.float32)
    hd = waveform.normalized_horizontal_values

    _, ax = plt.subplots()
    ax.plot(hd, vd)
    plt.show()
```

Run: `python examples/digital_waveform_usage.py`

### IQ / spectrogram — `iq_waveform_usage.py`

```python
import matplotlib.pyplot as plt

from tm_data_types import IQWaveform
from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    with connection.access_data():
        waveform: IQWaveform = connection.get_data("ch1_iq")

    iq_data = waveform.normalized_vertical_values

    _, ax = plt.subplots()
    ax.specgram(
        iq_data,
        NFFT=int(waveform.meta_info.iq_fft_length),
        Fc=waveform.meta_info.iq_center_frequency,
        Fs=waveform.meta_info.iq_sample_rate,
    )
    ax.set_title("Spectrogram")
    plt.show()
```

Run: `python examples/iq_waveform_usage.py`

### Read a saved waveform file — `simple_read.py`

Works offline with sample files under `sample_waveforms/`:

```python
import matplotlib.pyplot as plt
import numpy as np

from tm_data_types import AnalogWaveform, DigitalWaveform, IQWaveform, read_file

file = read_file("sample_waveforms/test_sine.wfm")

if isinstance(file, AnalogWaveform):
    vertical_data = file.normalized_vertical_values
elif isinstance(file, IQWaveform):
    vertical_data = file.normalized_vertical_values.real
elif isinstance(file, DigitalWaveform):
    vertical_data = file.get_nth_bitstream(3).astype(np.float32)

horizontal_data = file.normalized_horizontal_values

_, ax = plt.subplots()
ax.plot(horizontal_data, vertical_data)
plt.show()
```

Run: `python examples/simple_read.py`

### Customize logging — `customize_logging.py`

```python
from tm_data_types import AnalogWaveform, write_file
from tekhsi import configure_logging, LoggingLevels, TekHSIConnect

configure_logging(
    log_console_level=LoggingLevels.NONE,
    log_file_level=LoggingLevels.DEBUG,
    log_file_directory="./log_files",
    log_file_name="custom_log_filename.log",
)

with TekHSIConnect("192.168.0.1:5000", ["ch1"]) as connect:
    for i in range(10):
        with connect.access_data():
            wfm: AnalogWaveform = connect.get_data("ch1")
        write_file(f"{wfm.source_name}_{i}.csv", wfm)
```

Run: `python examples/customize_logging.py`

## FastFrame example

FastFrame captures return `FastFrameAnalogWaveform` from `tm_data_types`. All frames are
streamed and loaded when you first call `get_data()` — there is no lazy per-frame I/O.

On a **stopped** scope (typical for FastFrame review), use `access_stopped_data()`:

```python
import os

from tm_data_types import FastFrameAnalogWaveform
from tekhsi import TekHSIConnect
from tekhsi.credential_store import TekHSICredentialStore


def auto_trust(host, cert_info, auth_required=False):
    if auth_required:
        password = os.environ.get("TEKHSI_PASSWORD")
        if not password:
            return False
        return True, password, os.environ.get("TEKHSI_LOGIN", "tektronix")
    return True


with TekHSIConnect(
    "169.254.6.254:5000",
    activesymbols=["ch1", "ref1"],
    on_trust_prompt=auto_trust,
    credential_store=TekHSICredentialStore(),
) as connection:
    with connection.access_stopped_data():
        ch1 = connection.get_data("ch1")
        ref1 = connection.get_data("ref1")

    for label, wfm in [("CH1", ch1), ("Ref1", ref1)]:
        if not isinstance(wfm, FastFrameAnalogWaveform):
            print(f"{label}: single-frame capture ({type(wfm).__name__})")
            continue

        print(f"{label}: {wfm.data_frame_count} data frames + 1 summary = {wfm.num_frames} total")
        print(f"  record_length={wfm.record_length}")
        print(f"  current_frame={wfm.current_frame_index}, summary_frame={wfm.summary_frame_index}")

        raw = wfm.frame_data(0)
        print(f"  frame[0] raw[0]={int(raw[0])}, len={len(raw)}")

        volts = wfm.frame_array(0)
        print(f"  frame[0] normalized[0]={volts[0]:.6f}")

        if wfm.load_timing:
            print(f"  {wfm.load_timing.format_summary()}")

    frame3 = connection.get_frame("ch1", frame_index=3)
    if frame3 is not None:
        print(f"get_frame(ch1, 3): {len(frame3.normalized_vertical_values)} samples")
```

Full script: [`examples/fastframe_usage.py`](https://github.com/tektronix/TekHSI/blob/main/examples/fastframe_usage.py)

Probe script (prints timing and optional per-frame listing):

```shell
python scripts/probe_fastframe.py --url 169.254.6.254:5000 --channel ch1 --list-frames
python scripts/read_channels.py ch1 ref1
```

### FastFrame API notes

| Method / property     | Purpose                                                       |
| --------------------- | ------------------------------------------------------------- |
| `frame_data(i)`       | Raw digitizer sample array for frame `i`                      |
| `frame_array(i)`      | Normalized vertical values (volts) for frame `i`              |
| `frame(i)`            | `AnalogWaveform` view of frame `i`                            |
| `get_summary_frame()` | Summary/average frame as `AnalogWaveform`                     |
| `summary_frame_index` | Index of the High Res average frame (last frame when present) |
| `data_frame_count`    | Number of individual acquisition frames (excludes summary)    |
| `all_frames_loaded`   | Always `True` after TekHSI read completes                     |
| `load_timing`         | TekHSI transfer/publish timing (`FastFrameLoadTiming`)        |

## Helper scripts

| Script                                                                                                               | Purpose                                                             |
| -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| [`scripts/probe_fastframe.py`](https://github.com/tektronix/TekHSI/blob/main/scripts/probe_fastframe.py)             | Connect, read one channel, print FastFrame metadata and load timing |
| [`scripts/read_channels.py`](https://github.com/tektronix/TekHSI/blob/main/scripts/read_channels.py)                 | Read multiple stopped channels (e.g. `ch1 ref1`)                    |
| [`scripts/confirm_average_frame.py`](https://github.com/tektronix/TekHSI/blob/main/scripts/confirm_average_frame.py) | Verify the summary frame matches the mean of data frames            |

## Version compatibility

`TekHSI` currently requires:

```
tm_data_types~=0.4.0
```

(see [`pyproject.toml`](https://github.com/tektronix/TekHSI/blob/main/pyproject.toml) for the
exact, up-to-date constraint). Do not mix with an older `tm_data_types==0.3.x` install — the
FastFrame types (notably `FastFrameDigitalWaveform` and `FrameTimingInfo.is_summary_frame`) differ
between versions; see
[`tm_data_types_update_spec.md`](tm_data_types_update_spec.md) for the full migration history.

## License

Apache License 2.0 — see [LICENSE.md](LICENSE.md).
