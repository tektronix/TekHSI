# Basic Usage

## Connect to a Scope and save waveform data

This example shows how to use `TekHSI` and `tm_data_types` to pull analog waveforms from a
Tektronix oscilloscope and save them to a csv file very easily.

!!! important

    Matching the type of waveform with the channel type is critical. See the
    [supported data types section](#supported-data-types) for more information.

```python
# fmt: off
--8<-- "examples/simple_single_hs.py"
```

## Supported Data types

Currently, 3 data types are supported: [`AnalogWaveform`][tm_data_types.AnalogWaveform],
[`DigitalWaveform`][tm_data_types.DigitalWaveform], and
[`IQWaveform`][tm_data_types.IQWaveform].
Please keep in mind that as this library evolves, we will be adding new data types.

### Analog Waveforms

[`AnalogWaveform`][tm_data_types.AnalogWaveform] is the most commonly retrieved type of data from an
oscilloscope. It represents analog data captured by an oscilloscope. It is accessed by being
granted access to the data (which ensures access to the data from the current acquisition) and
then using `get_data()` and the name of the channel to be accessed. The data returned will be
whatever type is requested. In the example below, we know the type is Analog, so we type
`waveform` accordingly. This gives access to type hinting in your IDE.

```python
# fmt: off
--8<-- "examples/analog_waveform_usage.py"
```

### Digital Waveforms

[`DigitalWaveform`][tm_data_types.DigitalWaveform] is available when you have plugged a digital
probe into a scope channel and have turned on that channel. This returns an array of n-bit integers
that represent the digital data, where 'n' is the number of bits available on the digital probe.

In addition, there are special methods for digital waveforms available from
[`tm_data_types`](https://tm-data-types.readthedocs.io/). Probably the most useful is
[`get_nth_bitstream()`][tm_data_types.datum.waveforms.digital_waveform.DigitalWaveform.get_nth_bitstream]
which returns just one of the selected bits as a bitstream for use.

```python
# fmt: off
--8<-- "examples/digital_waveform_usage.py"
```

### IQ Waveforms

[`IQWaveform`][tm_data_types.IQWaveform] data allows for live-streaming of IQ data from an
oscilloscope. Turning Spectrum View on for a channel causes a corresponding symbol to be available.
These symbols can be accessed using the appropriate name with `get_data()`.

Proper usage of the `IQWaveform` type requires accessing metadata about the waveform. Other than that,
the data type was designed to make usage with signal processing libraries a breeze. The example
below shows how easy it is to feed that live data into Python libraries.

This shows the minimal code required to display a spectrogram using `matplotlib`.

```python
# fmt: off
--8<-- "examples/iq_waveform_usage.py"
```

## TekHSIConnect

The [`TekHSIConnect`][tekhsi.tek_hsi_connect.TekHSIConnect] class handles the connection and
data retrieval for TekHSI, check out [its API documentation][tekhsi.tek_hsi_connect.TekHSIConnect]
for more information.

## Acquisition Filters

An acquisition filter allows custom rules to be applied that can be used to filter (or restrict)
the acquisitions that are accepted for processing by the client. Normally the filter is set to `None`,
which lets all acquisitions through. However, there are several predefined filters that can be used:

- [`any_acq`][tekhsi.TekHSIConnect.any_acq] - This is equivalent to setting the acquisition filter
    to `None`, and it allows all acquisitions to be processed.
- [`any_vertical_change`][tekhsi.TekHSIConnect.any_vertical_change] - This looks at the previous and
    current acquisition and checks to see if any of the channels have seen any vertical change. If
    so, that acquisition is processed, otherwise it is skipped.
- [`any_horizontal_change`][tekhsi.TekHSIConnect.any_horizontal_change] - This looks at the previous
    and current acquisition and checks to see if any of the channels have seen any horizontal
    change. If so, that acquisition is processed, otherwise it is skipped.

Custom rules can also be created by the user.

These filters (pre-defined or user-defined) are either set during `TekHSIConnect`
instantiation or by using the [`set_acq_filter()`][tekhsi.TekHSIConnect.set_acq_filter] method.

Below is the source code of [`any_horizontal_change()`][tekhsi.TekHSIConnect.any_horizontal_change].
The arguments are the previous header and the current header. This allows you to compare changes
from the current headers against the previous header. If this returns `True` the acquisition is
passed on, otherwise it is ignored. This provides an easy way to only consider the changes which are
relevant. For example, this allows a change to be made to the scope while it is continuously running
and then only consider the change when it arrives. It reduces the need for expensive
synchronization using start and `*OPC?`.

```python
# fmt: off
--8<-- "src/tekhsi/tek_hsi_connect.py:any_horizontal_change"
```

## Mixing TekHSI and PyVISA

TekHSI is compatible with PyVISA (or [`tm_devices`](https://tm-devices.readthedocs.io/)!) and provides
several benefits over the traditional data retrieval methods.

1. `TekHSI` is much faster than using curve queries, because no data transformation is done on the
    scope, only the underlying binary data is moved. This means there is no need to process the
    data on the instrument side, the buffers are directly moved.
2. `TekHSI` receives the data in a background thread. So when mixing `PyVISA` and `TekHSI`, often
    data arrival appears to take little or no time.
3. `TekHSI` requires less code than the normal processing of curve commands.
4. The waveform output from `TekHSI` is easy to use with file readers/writers that allow this data
    to be quickly exported using the [tm_data_types](https://github.com/tektronix/tm_data_types) package.

### Example using `pyvisa`

```python
# fmt: off
--8<-- "examples/pyvisa_usage.py"
```

### Example using `tm_devices`

```python
# fmt: off
--8<-- "examples/tm_devices_usage.py"
```

## Customize logging and console output

The amount of console output and logging saved to the log file can be customized as needed. This
configuration can be done in the Python code itself as demonstrated here. If no logging is
explicitly configured, the default logging settings will be used (as defined by the
[`configure_logging()`][tekhsi.helpers.logging.configure_logging] function).

```python
# fmt: off
--8<-- "examples/customize_logging.py"
```

## Experimental Parallel Waveform Reads

!!! warning

    This feature is experimental and disabled by default.

!!! note

    A Python example demonstrating the parallel waveform reading will be added once those
    functions are thoroughly validated and benchmarked.

`TekHSI` includes optional experimental support for parallel waveform reads.
This behavior can be controlled using environment variables.

### Environment Variables

| Variable                        | Type                         | Default | Description                                                         |
| ------------------------------- | ---------------------------- | ------- | ------------------------------------------------------------------- |
| `TEKHSI_USE_PARALLEL_READS`     | Boolean (`1`, `true`, `yes`) | `false` | Enables experimental parallel waveform reads                        |
| `TEKHSI_PARALLEL_THRESHOLD`     | Integer                      | `2`     | Minimum number of waveforms required before parallelization is used |
| `TEKHSI_PARALLEL_WORKERS`       | Integer                      | `4`     | Number of worker threads used for parallel reads                    |
| `TEKHSI_DISABLE_PARALLEL_READS` | Boolean (`1`, `true`, `yes`) | `false` | Forces parallel reads to be disabled even if otherwise enabled      |

### Usage Examples

**Linux / macOS**

```bash
export TEKHSI_USE_PARALLEL_READS=1
export TEKHSI_PARALLEL_THRESHOLD=3
```

**Windows (PowerShell)**

```powershell
setx TEKHSI_USE_PARALLEL_READS 1
setx TEKHSI_PARALLEL_THRESHOLD 3
```
