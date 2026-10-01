"""Manual integration harness for a real TekHSI scope (not run by default CI).

Run directly::

    python scripts/manual_scope_waveform.py --scenario auto
    python scripts/manual_scope_waveform.py --list-scenarios
    python scripts/manual_scope_waveform.py --scenario legacy --url 169.254.6.254:5000

Or via pytest (only when explicitly enabled)::

    set TEKHSI_RUN_MANUAL_SCOPE=1
    pytest tests/manual/test_scope_waveform.py -v -s

Set ``TEKHSI_SCOPE_URL`` to override the default instrument address.
Results and issue steps are written under ``tests/manual/logs/``.
"""

from __future__ import annotations

import argparse
import importlib
import ipaddress
import json
import statistics
import sys
import time
import traceback

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from tekhsi import AcqWaitOn, TekHSIConnect, TekHSICredentials
from tekhsi.credential_store import TekHSICredentialStore
from tekhsi.security import (  # pylint: disable=import-private-name
    _parse_host_port,
    _tls_channel_options,
)
from tm_data_types import AnalogWaveform, Waveform

DEFAULT_SCOPE_URL = "169.254.6.254:5000"
DEFAULT_PASSWORD = "tek"
DEFAULT_LOGIN = "Tektronix"
DEFAULT_CHANNEL = "ch1"
DEFAULT_PULLS = 10
LOG_DIR = Path(__file__).resolve().parent.parent / "tests" / "manual" / "logs"

# Python 3.10 compatibility: datetime.UTC exists in 3.11+
UTC = getattr(datetime, "UTC", timezone.utc)


class StepStatus(str, Enum):
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class StepRecord:
    name: str
    status: StepStatus
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass
class RunReport:
    scenario: str
    url: str
    channel: str
    started_at: str
    finished_at: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    connection_summary: dict[str, Any] | None = None
    waveform_summary: dict[str, Any] | None = None
    data_transfer: dict[str, Any] | None = None

    def add(self, step: StepRecord) -> None:
        self.steps.append(step)

    def failed_steps(self) -> list[StepRecord]:
        return [s for s in self.steps if s.status == StepStatus.FAIL]


@dataclass
class ConnectTracker:
    """Records security/connect decisions during TekHSIConnect construction."""

    trust_events: list[dict[str, Any]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    auth_upgraded: bool = False
    plaintext_probe_succeeded: bool = False
    store_had_entry_before: bool = False
    store_had_cert_before: bool = False
    store_had_password_before: bool = False
    _orig_plain: Any = field(default=None, repr=False)
    _orig_upgrade: Any = field(default=None, repr=False)

    def record_trust(self, host: str, cert_info: Any, auth_required: bool, response: Any) -> None:
        fp = getattr(cert_info, "cert_fingerprint", "") or ""
        self.trust_events.append(
            {
                "host": host,
                "auth_required": auth_required,
                "fingerprint_prefix": fp[:16] if fp else None,
                "response": _describe_trust_response(response),
            }
        )

    def install_hooks(self) -> None:
        sec = importlib.import_module("tekhsi.security")
        thc = importlib.import_module("tekhsi.tek_hsi_connect")

        tracker = self
        tracker._orig_plain = sec._try_plain_grpc_channel
        tracker._orig_upgrade = thc.TekHSIConnect._upgrade_channel_with_token_after_unauthenticated

        def patched_plain(url: str, deadline: float):
            tracker.events.append("Probed instrument for plaintext gRPC (Connect/Disconnect test).")
            result = tracker._orig_plain(url, deadline)
            if result is not None:
                tracker.plaintext_probe_succeeded = True
                tracker.events.append(
                    "Plaintext probe succeeded - using insecure channel (Mode 1)."
                )
            else:
                tracker.events.append("Plaintext probe failed - continuing with TLS negotiation.")
            return result

        def patched_upgrade(self_conn: TekHSIConnect) -> None:
            tracker.auth_upgraded = True
            tracker.events.append(
                "Connect returned UNAUTHENTICATED on TLS-only channel; "
                "prompted for password and rebuilt channel with HTTP Basic auth."
            )
            tracker._orig_upgrade(self_conn)

        sec._try_plain_grpc_channel = patched_plain
        thc.TekHSIConnect._upgrade_channel_with_token_after_unauthenticated = patched_upgrade

    def remove_hooks(self) -> None:
        if self._orig_plain is not None:
            sec = importlib.import_module("tekhsi.security")

            sec._try_plain_grpc_channel = self._orig_plain
        if self._orig_upgrade is not None:
            thc = importlib.import_module("tekhsi.tek_hsi_connect")

            thc.TekHSIConnect._upgrade_channel_with_token_after_unauthenticated = self._orig_upgrade


def _describe_trust_response(response: Any) -> str:
    if response is True:
        return "True (trust cert, TLS only)"
    if isinstance(response, (list, tuple)) and response and response[0]:
        if len(response) >= 3:
            return "(True, password, login)"
        if len(response) >= 2:
            return "(True, password)"
        return "(True,)"
    return repr(response)


def _snapshot_store(store: TekHSICredentialStore | None, url: str) -> tuple[bool, bool, bool]:
    if store is None:
        return False, False, False
    entry = store.get(url)
    if not entry:
        return False, False, False
    return True, bool(entry.get("cert_path")), bool(entry.get("password"))


def build_connection_summary(
    connect: TekHSIConnect,
    *,
    scenario: str,
    sec_kw: dict[str, Any],
    tracker: ConnectTracker,
    connect_elapsed_s: float,
) -> dict[str, Any]:
    """Build human-readable connection path summary."""
    narrative: list[str] = []
    store = connect._credential_store_ref
    entry = store.get(connect.url) if store else None

    if not sec_kw:
        narrative.append("Requested legacy connection (no security parameters).")
        narrative.append("Client used grpc.insecure_channel with no credential store read.")
        inferred_mode = "Mode 1 - Plaintext gRPC (legacy path)"
    else:
        narrative.append(f"Requested scenario {scenario!r} with security negotiation enabled.")
        if tracker.store_had_entry_before:
            narrative.append("Credential store already had an entry for this host before connect.")
            if tracker.plaintext_probe_succeeded:
                narrative.append(
                    "Store had cert/password but plaintext probe succeeded first "
                    "- TLS credentials were not used this connect."
                )
            elif tracker.store_had_password_before:
                narrative.append(
                    "Stored password was present - built TLS + HTTP Basic credentials."
                )
            elif tracker.store_had_cert_before:
                narrative.append("Stored certificate was present - built TLS-only credentials.")
        else:
            narrative.append(
                "No usable store entry before connect - fetched live server certificate (TOFU)."
            )

        for ev in tracker.trust_events:
            if ev["auth_required"]:
                narrative.append(
                    f"Trust callback invoked with auth_required=True -> returned {ev['response']}."
                )
            else:
                narrative.append(
                    f"Trust callback invoked for first-time trust -> returned {ev['response']}."
                )

        for event in tracker.events:
            narrative.append(event)

        if tracker.auth_upgraded:
            inferred_mode = "Mode 3 - TLS + HTTP Basic (upgraded after UNAUTHENTICATED)"
        elif tracker.plaintext_probe_succeeded:
            inferred_mode = "Mode 1 - Plaintext gRPC (auto-negotiation chose plain)"
        elif entry and entry.get("password"):
            inferred_mode = "Mode 3 - TLS + HTTP Basic"
        elif sec_kw.get("credentials") and isinstance(sec_kw["credentials"], TekHSICredentials):
            mode = getattr(sec_kw["credentials"], "_store_mode", "tls")
            inferred_mode = (
                "Mode 3 - TLS + HTTP Basic (explicit token store resolve)"
                if mode == "token"
                else "Mode 2 - TLS only (explicit tls store resolve)"
            )
        elif entry and entry.get("cert_path"):
            inferred_mode = "Mode 2 - TLS only"
        else:
            inferred_mode = "Unknown - inspect trust events / store entry"

    narrative.append(f"Connect RPC and negotiation completed in {connect_elapsed_s:.3f}s.")

    host, _ = _parse_host_port(connect.url)
    tls_name = (entry or {}).get("tls_server_name")
    name_override = _tls_channel_options(host, tls_name)
    using_plaintext = tracker.plaintext_probe_succeeded or inferred_mode.startswith("Mode 1")

    if using_plaintext:
        transport = "Plaintext gRPC (insecure channel, encryption-free)"
    elif inferred_mode.startswith("Mode 2") or inferred_mode.startswith("Mode 3"):
        transport = "TLS (grpc.secure_channel, server cert pinned in store)"
    else:
        transport = "Plaintext gRPC (insecure channel)"

    if using_plaintext:
        auth_method = "None (no TLS, no authorization metadata on this channel)"
        if entry and entry.get("password"):
            auth_method += " - stored password not used; plain probe succeeded first"
    elif entry and entry.get("password"):
        auth_method = (
            f"HTTP Basic (username={(entry or {}).get('login') or 'tektronix'}, password in store)"
        )
    elif inferred_mode.startswith("Mode 2"):
        auth_method = "None (TLS only, no authorization metadata)"
    elif not sec_kw:
        auth_method = "None (legacy plaintext)"
    else:
        auth_method = "None at connect (TLS only; server may demand password later)"

    if using_plaintext:
        trust_source = "No certificate used on wire (plaintext channel)"
        if tracker.store_had_entry_before:
            trust_source += " - TLS cert remains in store for when plain is unavailable"
    elif tracker.store_had_entry_before:
        trust_source = "Reused trusted cert from credential store (no TOFU prompt)"
    elif tracker.trust_events:
        trust_source = (
            f"Trust established via on_trust_prompt ({len(tracker.trust_events)} call(s))"
        )
    elif not sec_kw:
        trust_source = "No certificate trust (plaintext legacy path)"
    else:
        trust_source = "Unknown trust path"

    impact: list[str] = []
    impact.append(f"Connect negotiation + Connect RPC: {connect_elapsed_s * 1000:.0f} ms")
    if tracker.plaintext_probe_succeeded:
        impact.append(
            "Encryption-free path: plaintext probe succeeded before TLS "
            "(no handshake, no cert verification, no Basic auth - typically faster connect)"
        )
    elif sec_kw and any("Probed instrument" in e for e in tracker.events):
        impact.append(
            "Plaintext probe ran and failed before TLS "
            "(extra Connect/Disconnect round-trip, then TLS + auth overhead)"
        )
    if tracker.store_had_entry_before and not using_plaintext:
        impact.append("Warm credential store - skipped TOFU cert fetch and trust prompt")
    elif tracker.store_had_entry_before and using_plaintext:
        impact.append("Warm store available but unused for transport this connect (plaintext won)")
    elif not tracker.store_had_entry_before and sec_kw:
        impact.append("Cold connect - live cert fetch (TOFU) and trust prompt add one-time latency")
    elif not sec_kw:
        impact.append("Legacy path - direct grpc.insecure_channel, no store, no probe, no certs")
    if tracker.auth_upgraded:
        impact.append(
            "Connect returned UNAUTHENTICATED once - password prompt + channel rebuild "
            "(one-time; stored for later connects)"
        )
    if name_override and not using_plaintext:
        impact.append(
            f"TLS name override active ({host} != cert name) - "
            f"required for link-local IP / .local host connections"
        )
    if entry and entry.get("password") and not using_plaintext:
        impact.append(
            "Basic auth metadata attached to all gRPC calls on this channel "
            "(Connect + waveform RPCs share the same authenticated channel)"
        )

    fp = (entry or {}).get("cert_fingerprint") or ""
    if not fp and tracker.trust_events:
        fp = tracker.trust_events[-1].get("fingerprint_prefix") or ""

    return {
        "inferred_mode": inferred_mode,
        "transport": transport,
        "auth_method": auth_method,
        "trust_source": trust_source,
        "using_plaintext": using_plaintext,
        "auto_security": getattr(connect, "_auto_security", None),
        "credential_store": str(getattr(store, "_path", None)) if store else None,
        "connect_url": connect.url,
        "connect_host": host,
        "tls_server_name": tls_name,
        "tls_name_override": name_override[0][1] if name_override else None,
        "cert_fingerprint_prefix": fp[:24] if fp else None,
        "cert_path": (entry or {}).get("cert_path"),
        "store_entry_after_connect": {
            "has_cert": bool(entry and entry.get("cert_path")) if entry else False,
            "has_password": bool(entry and entry.get("password")) if entry else False,
            "tls_server_name": tls_name,
            "login": (entry or {}).get("login"),
        },
        "trust_events": tracker.trust_events,
        "narrative": narrative,
        "impact": impact,
        "flags": {
            "plaintext_probe_attempted": any("Probed instrument" in e for e in tracker.events),
            "plaintext_probe_succeeded": tracker.plaintext_probe_succeeded,
            "using_plaintext": using_plaintext,
            "store_warm_before_connect": tracker.store_had_entry_before,
            "auth_upgraded_at_connect": tracker.auth_upgraded,
            "tls_name_override_required": bool(name_override) and not using_plaintext,
        },
    }


def print_connection_summary(summary: dict[str, Any]) -> None:
    print("\n=== SECURITY, CERT & AUTH ===")
    print(f"  Mode:              {summary['inferred_mode']}")
    print(f"  Transport:         {summary.get('transport', '?')}")
    print(f"  Connect URL:       {summary.get('connect_url', '?')}")
    using_plaintext = (summary.get("flags") or {}).get("using_plaintext", False)
    tls_name = summary.get("tls_server_name")
    if tls_name and not using_plaintext:
        print(f"  Cert name (TLS):   {tls_name}")
    elif tls_name and using_plaintext:
        print(f"  Cert name (store): {tls_name}  (not used - plaintext connect)")
    override = summary.get("tls_name_override")
    if override and not using_plaintext:
        print(f"  TLS name override: {override}  (URL host differs from cert name)")
    fp = summary.get("cert_fingerprint_prefix")
    if fp and not using_plaintext:
        print(f"  Cert fingerprint:  {fp}...")
    elif fp and using_plaintext:
        print(f"  Cert fingerprint (store): {fp}...  (not used this connect)")
    if summary.get("cert_path") and not using_plaintext:
        print(f"  Cert PEM:          {summary['cert_path']}")
    print(f"  Trust:             {summary.get('trust_source', '?')}")
    print(f"  Authentication:    {summary.get('auth_method', '?')}")
    if summary.get("credential_store"):
        print(f"  Credential store:  {summary['credential_store']}")
    entry = summary.get("store_entry_after_connect") or {}
    print(
        "  Store state:"
        f" cert={'yes' if entry.get('has_cert') else 'no'}"
        f" password={'yes' if entry.get('has_password') else 'no'}"
    )

    print("\n=== CONNECT IMPACT ===")
    print(f"  Total connect time: {summary.get('connect_elapsed_s', 0) * 1000:.0f} ms")
    for line in summary.get("impact", []):
        if not line.startswith("Connect negotiation"):
            print(f"  - {line}")

    print("\n  Steps taken:")
    for line in summary.get("narrative", []):
        print(f"    - {line}")


def print_data_transfer_summary(transfer: dict[str, Any], channel: str) -> None:
    num_pulls = transfer.get("num_pulls", 1)
    title = f"DATA TRANSFER ({channel})"
    if num_pulls > 1:
        title += f" - {num_pulls} pulls averaged"
    print(f"\n=== {title} ===")

    if transfer.get("payload_bytes") is not None:
        print(f"  Payload size:                   {transfer['payload_bytes']:,} bytes")
    if transfer.get("sample_count") is not None:
        print(f"  Samples:                        {transfer['sample_count']:,}")

    averages = transfer.get("averages")
    if averages:
        _print_stat_line("Total time (wait + cache read)", averages.get("total_s"), "s")
        _print_stat_line("Wait for acquisition in cache", averages.get("wait_for_data_s"), "s")
        _print_stat_line("Read from client cache", averages.get("read_cache_s"), "s")
        _print_stat_line("gRPC transfer (scope->client)", averages.get("grpc_transfer_s"), "s")
        _print_stat_line("gRPC transfer rate", averages.get("grpc_transfer_mbs"), "Mbs")
        _print_stat_line("Effective transfer rate", averages.get("effective_mbs"), "Mbs")
        return

    print(f"  Total time (wait + cache read): {transfer['total_s']:.3f}s")
    print(f"  Wait for acquisition in cache:  {transfer['wait_for_data_s']:.3f}s")
    print(f"  Read from client cache:         {transfer['read_cache_s']:.3f}s")
    if transfer.get("grpc_transfer_s") is not None:
        print(f"  gRPC waveform transfer (scope->client): {transfer['grpc_transfer_s']:.3f}s")
    if transfer.get("grpc_transfer_mbs") is not None:
        print(f"  gRPC transfer rate:             {transfer['grpc_transfer_mbs']:.2f} Mbs")
    if transfer.get("effective_mbs") is not None:
        print(f"  Effective transfer rate:        {transfer['effective_mbs']:.2f} Mbs")


def _stat_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    return {
        "mean": statistics.mean(values),
        "min": min(values),
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "count": len(values),
    }


def _print_stat_line(label: str, stats: dict[str, Any] | None, unit: str) -> None:
    if not stats:
        return
    mean = stats["mean"]
    if unit == "s":
        print(
            f"  {label + ':':32} {mean:.3f}s mean"
            f"  (min {stats['min']:.3f}, max {stats['max']:.3f},"
            f" stdev {stats['stdev']:.3f}, n={stats['count']})"
        )
    else:
        print(
            f"  {label + ':':32} {mean:.2f} {unit} mean"
            f"  (min {stats['min']:.2f}, max {stats['max']:.2f},"
            f" stdev {stats['stdev']:.2f}, n={stats['count']})"
        )


def _collect_numeric(samples: list[dict[str, Any]], key: str) -> list[float]:
    return [float(s[key]) for s in samples if s.get(key) is not None]


def validate_url(url: str) -> str:
    """Return url if host portion is a valid IP or hostname; raise on bad IPv4 octets."""
    host_port = url.strip()
    if ":" in host_port and not host_port.startswith("["):
        host, _, port_str = host_port.rpartition(":")
        if not port_str.isdigit():
            msg = f"Invalid port in URL: {url!r}"
            raise ValueError(msg)
    else:
        host = host_port
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if host.count(".") == 3:
            parts = host.split(".")
            if any(not p.isdigit() or int(p) > 255 for p in parts):
                msg = (
                    f"Invalid IPv4 address in {url!r} "
                    f"(each octet must be 0-255; e.g. 169.254.6.254)"
                )
                raise ValueError(msg) from None
    return url


def make_trust_prompt(
    password: str,
    login: str,
    *,
    tls_only_on_first: bool = False,
    verbose: bool = True,
    tracker: ConnectTracker | None = None,
):
    """Build on_trust_prompt callback; logs each invocation for issue tracking."""

    def on_trust_prompt(host: str, cert_info: Any, auth_required: bool = False) -> Any:
        fp = getattr(cert_info, "cert_fingerprint", "") or ""
        fp_short = fp[:16] + "..." if len(fp) >= 16 else fp or "(none)"
        if verbose:
            print(
                f"  [TRUST PROMPT] host={host!r} auth_required={auth_required} "
                f"fingerprint={fp_short}"
            )
        if auth_required or not tls_only_on_first:
            response: Any = (True, password, login)
        else:
            response = True
        if tracker is not None:
            tracker.record_trust(host, cert_info, auth_required, response)
        return response

    return on_trust_prompt


def scenario_connect_kwargs(
    scenario: str,
    *,
    password: str,
    login: str,
    store_path: Path | None,
    require_tls: bool,
    tracker: ConnectTracker | None = None,
) -> dict[str, Any]:
    """Map scenario name to TekHSIConnect keyword arguments (security-related only)."""
    store = TekHSICredentialStore(path=str(store_path)) if store_path else None
    prompt = make_trust_prompt(password, login, tracker=tracker)

    if scenario == "legacy":
        return {}

    if scenario == "auto":
        kw: dict[str, Any] = {"on_trust_prompt": prompt}
        if store is not None:
            kw["credential_store"] = store
        return kw

    if scenario == "auto-default-store":
        return {"on_trust_prompt": prompt}

    if scenario == "auto-isolated-store":
        if store is None:
            msg = "auto-isolated-store requires --store-path"
            raise ValueError(msg)
        return {"on_trust_prompt": prompt, "credential_store": store}

    if scenario == "require-tls":
        return {"on_trust_prompt": prompt, "require_tls": True}

    if scenario == "tls-store":
        if store is None:
            msg = "tls-store requires --store-path"
            raise ValueError(msg)
        return {
            "credentials": TekHSICredentials.tls(),
            "credential_store": store,
            "on_trust_prompt": prompt,
        }

    if scenario == "token-store":
        if store is None:
            msg = "token-store requires --store-path"
            raise ValueError(msg)
        return {
            "credentials": TekHSICredentials.token(),
            "credential_store": store,
            "on_trust_prompt": prompt,
        }

    if scenario == "second-connect":
        return (
            {"on_trust_prompt": prompt, "credential_store": store}
            if store
            else {"on_trust_prompt": prompt}
        )

    msg = f"Unknown scenario: {scenario}"
    raise ValueError(msg)


SCENARIOS: dict[str, str] = {
    "legacy": "Plain TekHSIConnect(url) — no security negotiation (Mode 1 if server allows).",
    "auto": "Opt-in auto-negotiation with trust prompt; optional --store-path.",
    "auto-default-store": "Auto-negotiation using the platform default credentials.ini.",
    "auto-isolated-store": "Auto-negotiation with an isolated temp/store INI (--store-path required).",
    "require-tls": "Refuse plaintext; TOFU/prompt with require_tls=True.",
    "tls-store": "TekHSICredentials.tls() resolved from store + TOFU prompt.",
    "token-store": "TekHSICredentials.token() resolved from store + TOFU prompt (Mode 3).",
    "second-connect": "Connect twice in one run to verify store persistence (no re-prompt).",
}


def run_step(report: RunReport, name: str, func: Any) -> Any:
    """Run one step, record timing and outcome."""
    print(f"\n--- {name} ---")
    t0 = time.perf_counter()
    try:
        result = func()
        elapsed = time.perf_counter() - t0
        report.add(StepRecord(name, StepStatus.OK, detail="success", elapsed_s=elapsed))
        print(f"  OK ({elapsed:.2f}s)")
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        detail = f"{type(exc).__name__}: {exc}"
        report.add(StepRecord(name, StepStatus.FAIL, detail=detail, elapsed_s=elapsed))
        print(f"  FAIL ({elapsed:.2f}s): {detail}")
        traceback.print_exc()
        raise


def summarize_waveform(waveform: Waveform) -> dict[str, Any]:
    """Extract a small summary dict for the run report."""
    summary: dict[str, Any] = {
        "type": type(waveform).__name__,
        "source_name": getattr(waveform, "source_name", None),
    }
    if isinstance(waveform, AnalogWaveform):
        summary["sample_count"] = len(waveform.normalized_vertical_values)
        summary["y_units"] = waveform.y_axis_units
        summary["x_units"] = waveform.x_axis_units
    return summary


def pull_waveform_timed(
    connect: TekHSIConnect,
    channel: str,
    *,
    wait_on: AcqWaitOn = AcqWaitOn.NewData,
) -> tuple[Waveform, dict[str, Any]]:
    """Wait for one acquisition, return waveform plus transfer timing breakdown."""
    symbols = [s.lower() for s in connect.activesymbols]
    if channel.lower() not in symbols:
        msg = f"Channel {channel!r} not in activesymbols {symbols}"
        raise ValueError(msg)

    before_transfer = connect._sum_transfer_time
    before_count = connect._sum_count
    connect.instrumentation_enabled = True

    t0 = time.perf_counter()
    with connect.access_data(wait_on):
        t_wait_done = time.perf_counter()
        waveform = connect.get_data(channel)
        t_get_done = time.perf_counter()
    t1 = time.perf_counter()

    if waveform is None:
        msg = f"No waveform data in cache for {channel!r} (is the scope acquiring?)"
        raise ValueError(msg)

    grpc_transfer_s: float | None = None
    if connect._sum_count > before_count:
        grpc_transfer_s = connect._sum_transfer_time - before_transfer

    payload_bytes: int | None = None
    sample_count: int | None = None
    if isinstance(waveform, AnalogWaveform):
        sample_count = len(waveform.normalized_vertical_values)
        width = getattr(waveform, "source_width", None)
        if width is None and hasattr(waveform, "y_axis_values"):
            itemsize = getattr(waveform.y_axis_values, "itemsize", None)
            width = int(itemsize) if itemsize else None
        if width and sample_count:
            payload_bytes = sample_count * width

    def _mbs(payload: int, seconds: float) -> float:
        return (payload * 8 / 1e6) / seconds

    grpc_transfer_mbs: float | None = None
    if grpc_transfer_s and grpc_transfer_s > 0 and payload_bytes:
        grpc_transfer_mbs = _mbs(payload_bytes, grpc_transfer_s)

    effective_mbs: float | None = None
    wait_s = t_wait_done - t0
    if payload_bytes and wait_s > 0:
        effective_mbs = _mbs(payload_bytes, wait_s)

    timing = {
        "total_s": t1 - t0,
        "wait_for_data_s": wait_s,
        "read_cache_s": t_get_done - t_wait_done,
        "grpc_transfer_s": grpc_transfer_s,
        "payload_bytes": payload_bytes,
        "sample_count": sample_count,
        "grpc_transfer_mbs": grpc_transfer_mbs,
        "effective_mbs": effective_mbs,
    }
    return waveform, timing


def pull_waveform(connect: TekHSIConnect, channel: str) -> Waveform:
    """Wait for one acquisition and return the requested channel."""
    waveform, _timing = pull_waveform_timed(connect, channel)
    return waveform


def pull_waveforms_averaged(
    connect: TekHSIConnect,
    channel: str,
    num_pulls: int,
) -> tuple[Waveform, dict[str, Any]]:
    """Pull ``num_pulls`` waveforms and return stats over the transfer measurements."""
    if num_pulls < 1:
        msg = "num_pulls must be at least 1"
        raise ValueError(msg)

    pulls: list[dict[str, Any]] = []
    last_waveform: Waveform | None = None
    for i in range(num_pulls):
        wait_on = AcqWaitOn.NewData if i == 0 else AcqWaitOn.NextAcq
        wfm, timing = pull_waveform_timed(connect, channel, wait_on=wait_on)
        timing["pull_index"] = i + 1
        pulls.append(timing)
        last_waveform = wfm
        if num_pulls > 1:
            print(
                f"    pull {i + 1}/{num_pulls}: "
                f"grpc={timing.get('grpc_transfer_mbs') or 0:.1f} Mbs, "
                f"effective={timing.get('effective_mbs') or 0:.1f} Mbs, "
                f"transfer={timing.get('grpc_transfer_s') or 0:.3f}s"
            )

    assert last_waveform is not None
    keys = (
        "total_s",
        "wait_for_data_s",
        "read_cache_s",
        "grpc_transfer_s",
        "grpc_transfer_mbs",
        "effective_mbs",
    )
    averages = {key: _stat_summary(_collect_numeric(pulls, key)) for key in keys}
    # Drop empty stat entries
    averages = {k: v for k, v in averages.items() if v}

    payload_bytes = pulls[0].get("payload_bytes")
    sample_count = pulls[0].get("sample_count")

    return last_waveform, {
        "num_pulls": num_pulls,
        "pulls": pulls,
        "averages": averages,
        "payload_bytes": payload_bytes,
        "sample_count": sample_count,
    }


def run_scenario(
    scenario: str,
    *,
    url: str,
    channel: str,
    password: str,
    login: str,
    store_path: Path | None,
    timeout: float,
    log_dir: Path,
    num_pulls: int = DEFAULT_PULLS,
) -> RunReport:
    """Execute one manual scenario and return a structured report."""
    url = validate_url(url)
    report = RunReport(
        scenario=scenario,
        url=url,
        channel=channel,
        started_at=datetime.now(tz=UTC).isoformat(),
    )

    print("=" * 72)
    print(f"MANUAL SCOPE TEST  scenario={scenario}")
    print(f"  url={url}  channel={channel}  login={login}  pulls={num_pulls}")
    if store_path:
        print(f"  store={store_path}")
    print("=" * 72)

    tracker = ConnectTracker()
    sec_kw = scenario_connect_kwargs(
        scenario,
        password=password,
        login=login,
        store_path=store_path,
        require_tls=scenario == "require-tls",
        tracker=tracker,
    )
    store_for_snapshot = TekHSICredentialStore(path=str(store_path)) if store_path else None
    if store_for_snapshot is None and sec_kw.get("credential_store") is not None:
        store_for_snapshot = sec_kw["credential_store"]
    if store_for_snapshot is None and scenario in {
        "auto-default-store",
        "require-tls",
    }:
        store_for_snapshot = TekHSICredentialStore()
    (
        tracker.store_had_entry_before,
        tracker.store_had_cert_before,
        tracker.store_had_password_before,
    ) = _snapshot_store(store_for_snapshot, url)

    def connect_once(label: str) -> TekHSIConnect:
        def _connect() -> TekHSIConnect:
            tracker.install_hooks()
            try:
                conn = TekHSIConnect(
                    url,
                    [channel],
                    timeout=timeout,
                    **sec_kw,
                )
            finally:
                tracker.remove_hooks()
            return conn

        return run_step(report, label, _connect)

    connect: TekHSIConnect | None = None
    try:
        if scenario == "second-connect":
            c1 = connect_once("connect_first")
            run_step(report, "list_symbols_first", lambda: list(c1.activesymbols))
            run_step(
                report, "waveform_first", lambda: summarize_waveform(pull_waveform(c1, channel))
            )
            c1.close()
            report.add(StepRecord("close_first", StepStatus.OK, "closed first connection"))
            connect = connect_once("connect_second")
        else:
            connect = connect_once("connect")

        assert connect is not None
        connect_step = next(
            (s for s in reversed(report.steps) if s.name in ("connect", "connect_second")),
            StepRecord("connect", StepStatus.OK, elapsed_s=0.0),
        )
        conn_summary = build_connection_summary(
            connect,
            scenario=scenario,
            sec_kw=sec_kw,
            tracker=tracker,
            connect_elapsed_s=connect_step.elapsed_s,
        )
        conn_summary["connect_elapsed_s"] = connect_step.elapsed_s
        report.connection_summary = conn_summary
        print_connection_summary(conn_summary)

        def list_symbols() -> list[str]:
            return list(connect.activesymbols)

        symbols = run_step(report, "list_symbols", list_symbols)
        print(f"  activesymbols: {symbols}")

        def fetch_waveform() -> tuple[dict[str, Any], dict[str, Any]]:
            wfm, timing = pull_waveforms_averaged(connect, channel, num_pulls)
            return summarize_waveform(wfm), timing

        summary, timing = run_step(report, f"pull_waveform_x{num_pulls}", fetch_waveform)
        report.waveform_summary = summary
        report.data_transfer = timing
        print(f"  waveform: {summary}")
        print_data_transfer_summary(timing, channel)

    finally:
        if connect is not None:
            try:
                connect.close()
            except Exception as exc:
                report.add(
                    StepRecord(
                        "close",
                        StepStatus.FAIL,
                        f"{type(exc).__name__}: {exc}",
                    )
                )

    report.finished_at = datetime.now(tz=UTC).isoformat()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out = log_dir / f"manual_scope_{scenario}_{stamp}.json"
    out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(f"\nReport written: {out}")

    failures = report.failed_steps()
    if failures:
        print("\n*** ISSUES TO TRACK ***")
        for step in failures:
            print(f"  - [{step.name}] {step.detail}")
    else:
        print("\nAll steps passed.")

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manual TekHSI scope integration test (waveform pull + issue tracking).",
    )
    parser.add_argument(
        "--url",
        default=__import__("os").environ.get("TEKHSI_SCOPE_URL", DEFAULT_SCOPE_URL),
        help=f"Scope host:port (default: {DEFAULT_SCOPE_URL} or TEKHSI_SCOPE_URL)",
    )
    parser.add_argument(
        "--scenario",
        default="auto",
        choices=sorted(SCENARIOS),
        help="Connection/security scenario to exercise",
    )
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="Waveform source (default: ch1)")
    parser.add_argument(
        "--pulls",
        type=int,
        default=int(__import__("os").environ.get("TEKHSI_SCOPE_PULLS", str(DEFAULT_PULLS))),
        help=f"Number of waveform pulls to average (default: {DEFAULT_PULLS})",
    )
    parser.add_argument(
        "--password", default=DEFAULT_PASSWORD, help="Mode 3 password (default: tek)"
    )
    parser.add_argument(
        "--login", default=DEFAULT_LOGIN, help="Basic auth username (default: tektronix)"
    )
    parser.add_argument(
        "--store-path",
        type=Path,
        help="Isolated credentials.ini path (recommended for tls-store/token-store/auto-isolated-store)",
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0, help="Security negotiation timeout (seconds)"
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        help="Directory for JSON run reports",
    )
    parser.add_argument("--list-scenarios", action="store_true", help="Print scenarios and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_scenarios:
        print("Available scenarios:\n")
        for name, desc in sorted(SCENARIOS.items()):
            print(f"  {name:22}  {desc}")
        print("\nSuggested manual sweep (adjust --url if needed):")
        for name in (
            "legacy",
            "auto-isolated-store",
            "require-tls",
            "token-store",
            "second-connect",
        ):
            print(
                f"  python scripts/manual_scope_waveform.py --scenario {name} --store-path %TEMP%\\tekhsi_manual.ini"
            )
        return 0

    try:
        report = run_scenario(
            args.scenario,
            url=args.url,
            channel=args.channel,
            password=args.password,
            login=args.login,
            store_path=args.store_path,
            timeout=args.timeout,
            log_dir=args.log_dir,
            num_pulls=max(1, args.pulls),
        )
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        return 1

    return 1 if report.failed_steps() else 0


if __name__ == "__main__":
    raise SystemExit(main())
