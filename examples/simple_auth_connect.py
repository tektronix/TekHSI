"""Simple TekHSI connect: probes the scope, reports mode, then connects.

Every run does a fresh discovery (like :mod:`authentication_check`) so the
output always reflects the scope's *current* configuration. If the server
requires a password, it is prompted interactively.
"""

from __future__ import annotations

import getpass
import sys

from auth_helpers import discover, guard_placeholder_addr, verify_password
from tekhsi import TekHSIConnect, TekHSICredentials

addr = "192.168.0.1"  # Replace with the IP address of your instrument
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

# ---- 3. Real TekHSIConnect session ----------------------------------------
if plain_ok:
    credentials = None
elif needs_password:
    credentials = TekHSICredentials.token(str(cert_path), password)
else:
    credentials = TekHSICredentials.tls(str(cert_path))

try:
    kwargs = {"credentials": credentials} if credentials is not None else {}
    with TekHSIConnect(url, **kwargs) as connect:
        print("Channels:", connect.activesymbols)
finally:
    if cert_path is not None:
        cert_path.unlink(missing_ok=True)
