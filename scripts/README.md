# Scripts

Utility scripts for probing and measuring TekHSI on a live scope.

## Transfer rate measurement

[`measure_transfer_rate.py`](measure_transfer_rate.py) benchmarks gRPC waveform transfer speed on a
stopped scope. It reads one or more channels, reports timing from `WaveformTransferTiming`
(`waveform.load_timing`), and optionally averages results over multiple runs.

### Prerequisites

- TekHSI enabled on the scope and the instrument **stopped** (or use a stopped FastFrame capture).
- `tekhsi` and `tm_data_types` installed (see [docs/DEMO_README.md](../docs/DEMO_README.md)).
- Run from the repository root, or ensure `src/` is on `PYTHONPATH`.

For TLS or password-protected scopes, set:

```shell
set TEKHSI_PASSWORD=your_password
set TEKHSI_LOGIN=tektronix
```

### Basic usage

```shell
python scripts/measure_transfer_rate.py --url 169.254.6.254:5000 ch1
```

Multiple channels:

```shell
python scripts/measure_transfer_rate.py --url 169.254.6.254:5000 ch1 ch2
```

Digital channels may appear as `ch2_DAll` in `available_symbols`; the client resolves common
aliases (for example `ch2` → `ch2_DAll`) automatically.

### Averaging over multiple runs

Use `--iterations` to repeat the read. After the first run, the script calls `force_sequence()`
before each subsequent read so each measurement uses a fresh stopped acquisition. When
`--iterations` is greater than 1, an **`avg`** row is printed at the end with mean transfer time,
publish time, and Mbit/s.

```shell
python scripts/measure_transfer_rate.py --url 169.254.6.254:5000 ch1 ch2 --iterations 10
```

The first iteration often runs slower (connection warm-up); use `--iterations 10` or higher for
stable averages on large captures.

### Output columns

| Column | Meaning |
| ------ | ------- |
| **Run** | Iteration number, or `avg` for the mean row |
| **Channel** | TekHSI symbol (for example `ch1`, `ch2_DAll`) |
| **Kind** | Waveform type: `analog`, `digital`, or `iq` |
| **FastFrame** | `yes` when `num_frames > 1`, else `no` |
| **RecLen** | Samples per frame (record length) |
| **Bytes/Sample** | Raw bytes per sample from the waveform header (`sourcewidth`: typically 1, 2, or 4) |
| **Frames** | Number of frames in the capture |
| **RawBytes** | Total raw payload size: `RecLen × Bytes/Sample × Frames` |
| **Transfer** | Time to receive the gRPC stream and assemble sample arrays (ms) |
| **Publish** | Time to assign arrays into the waveform object (ms; non-zero for FastFrame) |
| **Mbit/s** | Transfer throughput: `RawBytes × 8 / Transfer` (megabits per second) |

### Example output

```
Run  Channel      Kind     FastFrame RecLen   Bytes/Sample Frames  RawBytes   Transfer   Publish   Mbit/s
------------------------------------------------------------------------------------------------------
1    ch1          analog   yes       1000000  1            100     100000000  1238.895 ms  22.886 ms  645.74
1    ch2          digital  yes       1000000  1            100     100000000   850.774 ms  26.166 ms  940.32
...
10   ch1          analog   yes       1000000  1            100     100000000   850.270 ms  22.706 ms  940.88
10   ch2          digital  yes       1000000  1            100     100000000   850.520 ms  26.220 ms  940.60
------------------------------------------------------------------------------------------------------
avg  ch1          analog   yes       1000000  1            100     100000000   889.234 ms  25.303 ms  899.65
avg  ch2          digital  yes       1000000  1            100     100000000   850.730 ms  25.120 ms  940.37
```

### Notes

- **Scope settings drive the numbers.** Record length, FastFrame frame count, and byte width come
  from the stopped capture on the instrument, not from script arguments.
- **Small payloads under-report throughput.** Fixed gRPC and framing overhead dominates at low
  `RawBytes`, so Mbit/s will be much lower than on multi-megabyte transfers.
- **Logging is quiet by default.** TekHSI logs are suppressed to WARNING so the table stays clean.
  Use [`read_channels.py`](read_channels.py) with `verbose=True` if you need connection and
  protocol details.

### Related scripts

| Script | Purpose |
| ------ | ------- |
| [`read_channels.py`](read_channels.py) | Read and describe waveforms (type, frames, `load_timing`) |
| [`probe_fastframe.py`](probe_fastframe.py) | FastFrame header and frame probe |
| [`manual_scope_waveform.py`](manual_scope_waveform.py) | Interactive scope waveform tests (TLS scenarios) |
