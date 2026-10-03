"""Probe a TekHSI endpoint for plaintext/TLS/auth capabilities (read-only checks)."""

from __future__ import annotations

import contextlib
import sys
import time
import uuid

import grpc

import tekhsi.security as _sec

from tekhsi._tek_highspeed_server_pb2 import ConnectRequest  # pylint: disable=no-name-in-module
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.credential_store import TekHSICredentialStore


def probe_connect(stub: ConnectStub, timeout: float) -> str:
    """Return Connect RPC outcome: ok, unauthenticated, or error detail."""
    name = str(uuid.uuid4())
    try:
        stub.Connect(ConnectRequest(name=name), timeout=timeout)
    except grpc.RpcError as e:
        with contextlib.suppress(grpc.RpcError):
            stub.Disconnect(ConnectRequest(name=name), timeout=min(timeout, 3.0))
        return f"RpcError {e.code().name}: {(e.details() or '').strip()}"
    with contextlib.suppress(grpc.RpcError):
        stub.Disconnect(ConnectRequest(name=name), timeout=min(timeout, 3.0))
    return "OK"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "169.254.6.254:5000"
    host, port = _sec._parse_host_port(url)
    deadline = time.time() + 12.0

    print(f"TekHSI endpoint probe: {url}")
    print("=" * 60)

    # 1) Plaintext gRPC probe
    plain = _sec._try_plain_grpc_channel(url, deadline)
    if plain is not None:
        print("Plaintext gRPC:     AVAILABLE (Connect/Disconnect probe succeeded)")
        with contextlib.suppress(Exception):
            plain.close()
    else:
        print("Plaintext gRPC:     NOT AVAILABLE (probe failed or timed out)")

    # 2) TLS certificate on same host:port
    try:
        cert = _sec._fetch_server_cert(host, port, timeout=8.0)
        print("TLS handshake:      AVAILABLE (server presented a certificate)")
        print(f"  Fingerprint:      {cert.cert_fingerprint[:32]}...")
        if cert.tls_server_name:
            print(f"  TLS server name:  {cert.tls_server_name}")
    except OSError as e:
        print(f"TLS handshake:      NOT AVAILABLE ({e})")
        cert = None
    except Exception as e:
        print(f"TLS handshake:      NOT AVAILABLE ({type(e).__name__}: {e})")
        cert = None

    # 3) gRPC Connect over TLS without client auth
    tls_connect = "n/a"
    if cert is not None:
        entry = {
            "cert_fingerprint": cert.cert_fingerprint,
            "cert_path": None,
            "tls_server_name": cert.tls_server_name,
            "login": None,
            "password": None,
        }
        pem_path = None
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as tmp:
            tmp.write(cert.cert_pem or b"")
            pem_path = tmp.name
        entry["cert_path"] = pem_path
        try:
            creds = _sec._build_creds_from_entry(entry, "tls")
            ch = _sec._secure_channel(url, creds, entry=entry)
            stub = ConnectStub(ch)
            tls_connect = probe_connect(stub, 8.0)
            ch.close()
        finally:
            if pem_path:
                with contextlib.suppress(OSError):
                    os.unlink(pem_path)
        print(f"TLS gRPC Connect:   {tls_connect}")
        if tls_connect.startswith("RpcError UNAUTHENTICATED"):
            print("  -> Server requires client auth (Mode 3 / HTTP Basic likely)")

    # 4) gRPC Connect over TLS + stored password (if any)
    store = TekHSICredentialStore()
    entry = store.get(url)
    if entry and entry.get("cert_path"):
        print(f"Credential store:   entry present ({store._path})")
        mode = "token" if entry.get("password") else "tls"
        try:
            creds = _sec._build_creds_from_entry(entry, mode)
            ch = _sec._secure_channel(url, creds, entry=entry)
            stub = ConnectStub(ch)
            auth_connect = probe_connect(stub, 8.0)
            ch.close()
            label = "TLS + Basic auth" if mode == "token" else "TLS only (stored cert)"
            print(f"{label} Connect: {auth_connect}")
        except Exception as e:
            print(f"Stored-credentials Connect: FAILED ({type(e).__name__}: {e})")
    else:
        print("Credential store:   no entry for this host")

    # Summary
    print("\n--- INFERRED ENDPOINT CAPABILITIES ---")
    modes = []
    if plain is not None:
        modes.append("Mode 1 (plaintext gRPC)")
    if cert is not None:
        modes.append("Mode 2 (TLS server cert)")
        if tls_connect.startswith("RpcError UNAUTHENTICATED"):
            modes.append("Mode 3 (TLS + password required on Connect)")
        elif tls_connect == "OK":
            modes.append("Mode 2 active without client password")
    if not modes:
        print("Could not establish any TekHSI transport to this address.")
        return 1
    for m in modes:
        print(f"  - {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
