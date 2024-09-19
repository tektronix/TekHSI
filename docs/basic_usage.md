# Basic Usage

This example shows how to use TekHSI and tm_data_types to pull analog waveforms from a Tektronix oscilloscope and use matplotlib to plot them very easily.

> [!IMPORTANT]
> Matching the type of waveform with the channel type is critical. AnalogWaveform will be the most common, but TekHSI supports DigitalWaveform and IQWaveform as well.

```python
# fmt: off
--8<-- "examples/simple_single_hs.py"
```

## Advanced Topics

### Supported Data types

Currently, 3 data types are supported: AnalogWaveform, DigitalWaveform, and IQWaveform.
Please keep in mind that as these library evolve, we will be adding new data types.

The following code shows how you decide at runtime, which type you have using a simple plotting example.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/supported_data_types.py"
```

#### AnalogWaveform

AnalogWaveform is the most commonly retrieved type of data from an oscilloscope.
It represents analog data captured by an oscilloscope. It is accessed by being
granted access to the data (which ensures access to the data from the current acquisition). Then using get_data and the name of the channel to be accessed.
The data returned will be whatever type is requested. In the example below,
we know the type is Analog, so we type 'waveform' accordingly. This gives access to
type hinting in your IDE.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/analog_waveform_usage.py"
```

#### DigitalWaveform

DigitalWavefrom is available when you have plugged a digital probe into a scope channel and have turned on that channel. This returns an array of 8-bit integers that represent the 8-bit digital data.

In addition, there are special methods for digital waveforms. Probably the most useful is 'get_n_bitstream()' which returns just one of the selected bits as a bitstream for use.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/digital_waveform_usage.py"
```

#### IQWaveform

IQWaveform data allows for live-streaming of IQ data from an oscilloscope. Spectrum View on
for a channel cause a corresponding symbol to be available. These symbols can be accessed using
the appropriate name with 'get_data()' access.

Proper usage of the IQWaveform type requires accessing metadata about the waveform. Other than that, the data type was designed to make usage with signal processing libraries a breeze. The example below shows how easy it is to feed that live data into Python libraries.

This shows the minimal code required to display a spectrogram using matplotlib.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/iq_waveform_usage.py"
```

## TekHSIConnect

> [!TIP]
> Visit the [API Reference](https://tekhsi.readthedocs.io/stable/reference/tekhsi/) to see detailed information of all classes and methods.

The [`TekHSIConnect`][tekhsi.tek_hsi_connect.TekHSIConnect] method is defined as follows:

**TekHSIConnect**(**url**, **activeSymbols**_=None_, **callback**_=None_ **filter**_=None_)

- **url** - the IP Address and port of the TekHSI server.
- **activeSymbols** - A list of the symbols to transfer from the scope. If _None_, then all available symbols are moved. Otherwise, only the selected list.
- **callback** - A method to call when new data arrives. This is the fastest way to access data, and it ensures no acquisitions are missed. However, this happens in a background thread, which limits the libraries you can call from this method. If set to _None_, no function is called.
- **filter** - a method that is used to determine if arriving data meets a custom criterion for acceptance by the client. If _None_, all acquisitions are accepted. However, if customer behavior is desired, then this method can be provided. Typically, these functions are used to look for specific kinds of changes, such as record length changing.

### activesymbols

The 'activesymbols' property returns a list of the available symbols. Available means, the channel is on and what type returned will depend upon the probe installed or action requested by the user. This call will only return the currently available channel list. If channels are off, or modes are disabled, the corresponding symbol will not be present.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/active_symbols.py"
```

Example output is:
\['ch1', 'ch1_iq', 'ch3', 'ch4_DAll'\]

In this case, 'ch1' is an analog channel, 'ch1_iq' is the spectrum view channel associated with 'ch1' (when enabled). 'ch3' is another analog channel, and 'ch4_DAll'
is a digital probe on 'ch4'. Types are generally determined by the name of the symbol.

### access_data()

The call 'access_data()' is used to get access to the available data.
It holds access to the current acquisition as long as the subsequent
'get_data()' calls happen within the indented region below it. This is how
you ensure that all data you get is from the same acquisition. It does not matter
if the scope is running continuously or using single step - all the data is from
the same acquisition when inside the 'access_data()' code block.

This also means you are potentially holding off scope acquisitions when inside the 'access_data()' code block. So, it's recommended you only get the data and do any processing outside of this block.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/access_data.py"
```

### AcqWaitOn

You can change the rules around how data is accessed by adding an argument. By default,
'access_data()' uses the AcqWaitOn.NewData option. However, you can set other options as
needed.

#### AcqWaitOn.NewData

This code snippet will continue when the current data from the stored acquisition
has not been read by 'get_data()'. This is import because, the underlying data is buffered because it's stored as data on the instrument is available. If you have seen the underlying data since the last 'get_data()' it will return the buffered data. If you have seen the data, it will block until the next new piece of data arrives.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/wait_on_new_data.py"
```

#### AcqWaitOn.NewData

This option requests that data access wait until the next new acquisitions is available.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/wait_on_next_acq.py"
```

#### AcqWaitOn.Time

This option requests a time delay before accepting the next acquisition. The typical usage of this is if you are using multiple instruments and PyVISA. If you are turning on an AFG you need some time for the instrument to be setup and the data to arrive. This
command is approximately the same as sleeping for half a second then calling access_data(AcqWaitOn.NextAcq).

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/wait_on_time.py"
```

### get_data()

The method 'get_data()' returns the data associated with the passed name. The
names must correspond to the names returned from 'activesymbols' however, the
names are case-insensitive.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/blocking_methods.py"
```

### Acquisition Filters

An acquisition filter allows custom rules to be applied that can be used to filter (or restrict)
the acquisition that are accepted for processing by the client. Normally the filter is set to None,
which lets all acquisitions through. However, there are several predefined 'filters'

- **any_acq** - This is equivalent to setting None, and it allows all acquisitions to be processed.
- **any_vertical_change** - This looks at the previous and current acquisition and checks to see if any
    of the channels have seen any vertical change. If so, that acquisition is processed, otherwise it is skipped.
- **any_horizontal_change** - This looks at the previous and current acquisition and checks to see if any
    of the channels have seen any horizontal change. If so, that acquisition is processed, otherwise it is skipped.

These filters are either set in the TekHSIConnect definition or by using the 'set_acq_filter()' method.

Custom rules can be created by the user.

Below is an example of 'any_horizontal_change()' the arguments are the 'previous header list' and the
'current header list'. This allows you to compare changes from the current headers against the previous header.
If this returns 'True' the acquisition is pass on, otherwise it is ignored. This allows you an easy way to only
consider the changes you deem relevant. For example, this allows you to make a change to the scope while continuously
running and then only consider the change when it arrives. It reduces the need for expensive synchronization using
start and '\*OPC?'.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/acq_filters.py"
```

### Blocking Methods

The method 'access_data()' blocks until data meeting the specified criterion arrives. In the following code, that means that the first line will hold off execution beyond that point until data is available for the subsequent 'get_data()' methods.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/blocking_methods.py"
```

Most other methods won't block.

### Mixing TekHSI and PyVISA

TekHSI is compatible with PyVISA. You can mix PyVISA with TekHSI. This has some advantages over just using PyVISA.

1. TekHSI is much faster than using curve queries, because no data transformation is done on the scope,
    only the underly binary data is moved. This means there is no need to process the data on the instrument side,
    the buffers are directly moved.
2. TekHSI receives the data in a background thread. So when mixing PyVISA and TekHSI, often data arrival appears
    to take little or no time.
3. TekHSI requires much less code that the normal processing of curve commands.
4. The waveform output from TekHSI is easy to use with file readers/writers that allow this data to be quickly exported using the [tm_data_types](https://github.com/tektronix/tm_data_types) module.

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/pyvisa_usage.py"
```

#### `tm_devices` can be used along with TekHSI

```python
# fmt: off
--8<-- "docs/additional_examples_and_pseudo_codes/tm_devices_usage.py"
```
