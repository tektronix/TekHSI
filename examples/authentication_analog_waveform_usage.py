"""Discover the scope's auth mode, connect, and plot an analog waveform.

Every run does a fresh discovery (like :mod:`authentication_check`) and
transparently handles all three modes:

- plain gRPC (no TLS, no password)
- TLS only (Mode 2)
- TLS + password (Mode 3) - prompts for the password if the server needs one
"""

from __future__ import annotations

import getpass
import sys

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt

from auth_helpers import discover, guard_placeholder_addr, verify_password
from tekhsi import TekHSIConnect, TekHSICredentials

if TYPE_CHECKING:
    from tm_data_types import AnalogWaveform

addr = "192.168.0.1"  # Replace with the IP address of your instrument 192.168.0.1
channel = "ch2"  # Analog channel to plot
url = f"{addr}:5000"

guard_placeholder_addr(addr)

# ---- 1. Discover what the server requires ---------------------------------
plain_ok, cert_path, entry, needs_password = discover(url)

print(f"Server at {url} requires:")
print(f"  - Encryption (TLS): {'no' if plain_ok else 'yes'}")
print(f"  - Password:         {'yes' if needs_password else 'no'}")

# ---- 2. Prompt only when needed -------------------------------------------
password: str | None = None
if needs_password:
    if not (password := getpass.getpass(f"Password for TekHSI at {url}: ") or None):
        print("Password is required but none was provided.")
        if cert_path is not None:
            cert_path.unlink(missing_ok=True)
        sys.exit(1)
    verify_password(url, entry, password, cert_path)

# ---- 3. Build credentials --------------------------------------------------
if plain_ok:
    credentials = None
elif needs_password:
    credentials = TekHSICredentials.token(str(cert_path), password)
else:
    credentials = TekHSICredentials.tls(str(cert_path))

# ---- 4. Connect, capture one acquisition, then release the scope ---------
waveform: AnalogWaveform | None = None
try:
    kwargs = {"credentials": credentials} if credentials is not None else {}
    with TekHSIConnect(url, **kwargs) as connection:
        print("Channels:", connection.activesymbols)
        with connection.access_data():
            waveform = connection.get_data(channel)
finally:
    if cert_path is not None:
        cert_path.unlink(missing_ok=True)

# ---- 5. Plot AFTER the TekHSIConnect session is released -----------------
# ``plt.show()`` blocks until the plot window is closed; doing this outside
# the ``with`` block releases the instrument as soon as the capture is done.
if waveform is None:
    print(
        f"No data for channel '{channel}'. "
        f"Make sure the channel is enabled on the scope and try again.",
    )
    sys.exit(1)

vd = waveform.normalized_vertical_values
hd = waveform.normalized_horizontal_values

_, ax = plt.subplots()
ax.plot(hd, vd)
ax.set(
    xlabel=waveform.x_axis_units,
    ylabel=waveform.y_axis_units,
    title=f"{channel} on {addr}",
)
plt.show()
