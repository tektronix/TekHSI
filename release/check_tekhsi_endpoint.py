"""Check what a TekHSI server requires and whether this client can connect.

Install TekHSI first::

    pip install tekhsi-1.1.0-py3-none-any.whl

Then run::

    python check_tekhsi_endpoint.py 169.254.6.254
    python check_tekhsi_endpoint.py 192.168.1.50 --port 5000
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
import time
import uuid

import grpc

from tekhsi import TekHSIConnect, TekHSICredentials
from tekhsi._tek_highspeed_server_pb2 import ConnectRequest  # pylint: disable=no-name-in-module
from tekhsi._tek_highspeed_server_pb2_grpc import ConnectStub
from tekhsi.auth_basic import DEFAULT_MODE3_USERNAME
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.security import (  # pylint: disable=private-import
    _build_creds_from_entry,
    _fetch_server_cert,
    _parse_host_port,
    _secure_channel,
    _try_plain_grpc_channel,
)


def _host_port_arg(host: str, port: int) -> str:
    host = host.strip()
    if host.startswith("["):
        return f"{host}:{port}"
    if ":" in host and not host.replace(".", "").isdigit():
        # Already host:port (non-IPv4 literal with port)
        return host
    return f"{host}:{port}"


def _probe_connect(stub: ConnectStub, timeout: float) -> tuple[bool, str | None]:
    """Return (ok, error_code_name). error_code_name is e.g. UNAUTHENTICATED or None."""
    name = str(uuid.uuid4())
    try:
        stub.Connect(ConnectRequest(name=name), timeout=timeout)
    except grpc.RpcError as e:
        return False, e.code().name
    finally:
        try:
            stub.Disconnect(ConnectRequest(name=name), timeout=min(timeout, 3.0))
        except grpc.RpcError:
            pass
    return True, None


def _entry_from_cert(cert, pem_path: str) -> dict[str, str | None]:
    return {
        "cert_fingerprint": cert.cert_fingerprint,
        "cert_path": pem_path,
        "tls_server_name": cert.tls_server_name,
        "login": None,
        "password": None,
    }


def _tls_connect_result(
    url: str,
    entry: dict[str, str | None],
    *,
    password: str | None = None,
    login: str | None = None,
) -> tuple[bool, str | None]:
    """Try gRPC Connect over TLS; return (ok, grpc_error_code_name)."""
    if password:
        entry = {**entry, "password": password, "login": login or DEFAULT_MODE3_USERNAME}
        mode = "token"
    else:
        mode = "tls"
    creds = _build_creds_from_entry(entry, mode)
    ch = _secure_channel(url, creds, entry=entry)
    try:
        return _probe_connect(ConnectStub(ch), 8.0)
    finally:
        try:
            ch.close()
        except Exception:  # noqa: BLE001
            pass


def check_endpoint(
    url: str,
    *,
    password: str | None = None,
    login: str = DEFAULT_MODE3_USERNAME,
    prompt_for_password: bool = True,
) -> int:
    host, port = _parse_host_port(url)
    deadline = time.time() + 12.0

    print(f"TekHSI endpoint check: {url}")
    print("=" * 60)

    # --- discover server requirements ---
    plain_channel = _try_plain_grpc_channel(url, deadline)
    plain_ok = plain_channel is not None
    if plain_channel is not None:
        try:
            plain_channel.close()
        except Exception:  # noqa: BLE001
            pass

    cert = None
    pem_path: str | None = None
    tls_handshake = False
    try:
        cert = _fetch_server_cert(host, port, timeout=8.0)
        tls_handshake = True
    except Exception:  # noqa: BLE001
        cert = None

    tls_no_auth_ok = False
    tls_needs_password = False
    if cert is not None:
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        pem_path = tmp.name
        tmp.write(cert.cert_pem or b"")
        tmp.close()
        entry = _entry_from_cert(cert, pem_path)
        ok, err = _tls_connect_result(url, entry)
        if ok:
            tls_no_auth_ok = True
        elif err == "UNAUTHENTICATED":
            tls_needs_password = True

    if plain_ok:
        needs_encryption = False
        needs_password = False
    elif tls_handshake and tls_no_auth_ok:
        needs_encryption = True
        needs_password = False
    elif tls_handshake and tls_needs_password:
        needs_encryption = True
        needs_password = True
    elif tls_handshake:
        needs_encryption = True
        needs_password = True  # TLS present but Connect failed; try password next
    else:
        needs_encryption = False
        needs_password = False

    print("Server requires:")
    if not plain_ok and not tls_handshake:
        print("  Could not reach TekHSI on this address (no plain or TLS response).")
        return 1
    if needs_encryption:
        print("  - Encrypted connection (TLS): yes")
    else:
        print("  - Encrypted connection (TLS): no (plain connection is accepted)")
    if needs_password:
        print("  - Password: yes")
    else:
        print("  - Password: no")

    # --- can we provide what is needed? ---
    store = TekHSICredentialStore()
    store_entry = store.get(url)
    supplied_password = password
    if store_entry and store_entry.get("password") and supplied_password is None:
        supplied_password = store_entry["password"]

    if needs_password and not supplied_password and prompt_for_password:
        supplied_password = getpass.getpass(f"Password for TekHSI at {url}: ")

    can_connect = False
    connect_detail = ""

    if not needs_encryption and plain_ok:
        try:
            with TekHSIConnect(url) as conn:
                can_connect = True
                connect_detail = f"plain TekHSIConnect OK (channels: {conn.activesymbols})"
        except Exception as e:  # noqa: BLE001
            connect_detail = f"plain TekHSIConnect failed: {e}"

    elif needs_encryption and cert is not None and pem_path:
        entry = _entry_from_cert(cert, pem_path)
        if store_entry and store_entry.get("cert_path"):
            entry = {
                "cert_fingerprint": store_entry.get("cert_fingerprint") or cert.cert_fingerprint,
                "cert_path": store_entry["cert_path"],
                "tls_server_name": store_entry.get("tls_server_name") or cert.tls_server_name,
                "login": store_entry.get("login"),
                "password": supplied_password,
            }
        if needs_password:
            if not supplied_password:
                connect_detail = "password required but none supplied"
            else:
                ok, err = _tls_connect_result(
                    url, entry, password=supplied_password, login=login
                )
                if ok:
                    creds = TekHSICredentials.token(entry["cert_path"], supplied_password, username=login)
                    try:
                        with TekHSIConnect(url, credentials=creds) as conn:
                            can_connect = True
                            connect_detail = (
                                f"TLS + password OK (channels: {conn.activesymbols})"
                            )
                    except Exception as e:  # noqa: BLE001
                        connect_detail = f"TLS + password TekHSIConnect failed: {e}"
                else:
                    connect_detail = f"TLS + password Connect RPC failed: {err}"
        else:
            ok, err = _tls_connect_result(url, entry)
            if ok:
                creds = TekHSICredentials.tls(entry["cert_path"])
                try:
                    with TekHSIConnect(url, credentials=creds) as conn:
                        can_connect = True
                        connect_detail = f"TLS OK (channels: {conn.activesymbols})"
                except Exception as e:  # noqa: BLE001
                    connect_detail = f"TLS TekHSIConnect failed: {e}"
            else:
                connect_detail = f"TLS Connect RPC failed: {err}"

    print("\nClient can provide that:")
    if can_connect:
        print(f"  Yes - {connect_detail}")
        return 0
    print(f"  No - {connect_detail}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check TekHSI server security requirements and verify the client can connect.",
    )
    parser.add_argument(
        "host",
        help="Instrument IP address or host:port (port defaults to 5000)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="TekHSI port if host does not include one (default: 5000)",
    )
    parser.add_argument(
        "--login",
        default=DEFAULT_MODE3_USERNAME,
        help=f"HTTP Basic username when a password is required (default: {DEFAULT_MODE3_USERNAME})",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TEKHSI_PASSWORD"),
        help="Password (optional; prompted when required if omitted)",
    )
    args = parser.parse_args(argv)

    host = args.host
    if ":" not in host or host.count(":") == 1 and host.rsplit(":", 1)[-1].isdigit():
        url = _host_port_arg(host.split(":")[0] if host.count(":") == 1 else host, args.port)
    else:
        url = host

    return check_endpoint(
        url,
        password=args.password,
        login=args.login,
        prompt_for_password=args.password is None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
