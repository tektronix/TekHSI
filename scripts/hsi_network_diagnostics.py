"""Host-side link diagnostics for HSI benchmark runs (Linux/WSL).

Uses ethtool, ip, ss, and tcpdump when available. On Windows without WSL,
writes skip notes so downstream sweeps can still run with a warning.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LinkCheckResult:
    ok: bool
    iface: str | None
    messages: list[str] = field(default_factory=list)
    host_ethtool_before: str = ""
    host_ethtool_stats_before: str = ""
    host_ip_link_before: str = ""
    host_ethtool_after: str = ""
    host_ethtool_stats_after: str = ""
    host_ip_link_after: str = ""
    mtu_notes: str = ""
    path_notes: str = ""


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        combined = out + (f"\n{err}" if err else "")
        return proc.returncode, combined.strip(), err.strip()
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout running {' '.join(cmd)}"


def _is_linux_like() -> bool:
    system = platform.system().lower()
    return system == "linux" or "microsoft" in platform.release().lower()


def resolve_iface_for_host(host: str) -> str | None:
    if not _tool("ip"):
        return None
    code, out, _ = _run(["ip", "route", "get", host])
    if code != 0:
        return None
    match = re.search(r"dev\s+(\S+)", out)
    return match.group(1) if match else None


def _parse_duplex(ethtool_out: str) -> str | None:
    for line in ethtool_out.splitlines():
        if "duplex" in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip().lower()
    return None


def _parse_negotiated_speed(ethtool_out: str) -> str | None:
    for line in ethtool_out.splitlines():
        lower = line.lower()
        if "speed" in lower and "supported" not in lower and "advertised" not in lower:
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return None


def _nonzero_stat_deltas(before: str, after: str) -> list[tuple[str, int]]:
    def parse_stats(text: str) -> dict[str, int]:
        stats: dict[str, int] = {}
        in_section = False
        for line in text.splitlines():
            if "statistics" in line.lower() or "NIC statistics" in line:
                in_section = True
                continue
            if not in_section:
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if not val.isdigit():
                continue
            stats[key] = int(val)
        return stats

    b = parse_stats(before)
    a = parse_stats(after)
    deltas: list[tuple[str, int]] = []
    for key in sorted(set(b) | set(a)):
        delta = a.get(key, 0) - b.get(key, 0)
        if delta != 0:
            deltas.append((key, delta))
    return deltas


def _error_like_deltas(deltas: list[tuple[str, int]]) -> list[tuple[str, int]]:
    keywords = ("err", "drop", "fail", "collision", "carrier", "pause", "crc", "fifo")
    return [(k, v) for k, v in deltas if any(word in k.lower() for word in keywords) and v > 0]


def capture_link_snapshot(iface: str) -> tuple[str, str, str]:
    ethtool = ""
    stats = ""
    ip_link = ""
    if _tool("ethtool"):
        _, ethtool, _ = _run(["ethtool", iface])
        _, stats, _ = _run(["ethtool", "-S", iface])
    if _tool("ip"):
        _, ip_link, _ = _run(["ip", "-s", "link", "show", iface])
    return ethtool, stats, ip_link


def mtu_and_path_notes(iface: str, host: str) -> tuple[str, str]:
    mtu_notes = ""
    path_notes = ""
    if _tool("ip"):
        _, ip_out, _ = _run(["ip", "link", "show", iface])
        mtu_match = re.search(r"mtu\s+(\d+)", ip_out)
        if mtu_match:
            mtu_notes = f"host {iface} MTU={mtu_match.group(1)}"
        _, route_out, _ = _run(["ip", "route", "get", host])
        hops = "direct" if "dev" in route_out and "via" not in route_out else route_out.strip()
        path_notes = f"route to {host}: {hops}"
    return mtu_notes, path_notes


def verify_link_before_sweeps(host: str, output_dir: Path) -> LinkCheckResult:
    result = LinkCheckResult(ok=True, iface=None)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "link_verification.txt"

    if not _is_linux_like():
        msg = (
            "Link verification skipped: ethtool/ip/ss/tcpdump require Linux or WSL. "
            f"Detected platform={platform.system()} release={platform.release()}."
        )
        result.ok = False
        result.messages.append(msg)
        log_path.write_text(msg + "\n", encoding="utf-8")
        return result

    missing = [t for t in ("ethtool", "ip") if not _tool(t)]
    if missing:
        msg = f"Link verification incomplete: missing tools {missing}"
        result.ok = False
        result.messages.append(msg)
        log_path.write_text(msg + "\n", encoding="utf-8")
        return result

    iface = resolve_iface_for_host(host)
    result.iface = iface
    if iface is None:
        msg = f"Could not resolve interface for host {host}"
        result.ok = False
        result.messages.append(msg)
        log_path.write_text(msg + "\n", encoding="utf-8")
        return result

    eth, stats, ip_link = capture_link_snapshot(iface)
    result.host_ethtool_before = eth
    result.host_ethtool_stats_before = stats
    result.host_ip_link_before = ip_link
    result.mtu_notes, result.path_notes = mtu_and_path_notes(iface, host)

    duplex = _parse_duplex(eth)
    speed = _parse_negotiated_speed(eth)
    lines = [
        f"iface={iface}",
        f"negotiated_speed={speed}",
        f"duplex={duplex}",
        result.mtu_notes,
        result.path_notes,
        "scope_side=not probed (requires instrument shell/SSH if available)",
        "",
        "=== ethtool (before) ===",
        eth,
        "",
        "=== ethtool -S (before) ===",
        stats,
        "",
        "=== ip -s link (before) ===",
        ip_link,
    ]

    if duplex and duplex != "full":
        result.ok = False
        result.messages.append(f"Duplex is '{duplex}', expected full — stop before sweeps.")

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def record_link_after_transfer(host: str, output_dir: Path, result: LinkCheckResult) -> LinkCheckResult:
    log_path = output_dir / "link_verification_after_transfer.txt"
    if result.iface is None or not _is_linux_like():
        log_path.write_text("skipped (no iface or non-Linux)\n", encoding="utf-8")
        return result

    eth, stats, ip_link = capture_link_snapshot(result.iface)
    result.host_ethtool_after = eth
    result.host_ethtool_stats_after = stats
    result.host_ip_link_after = ip_link

    deltas = _nonzero_stat_deltas(result.host_ethtool_stats_before, stats)
    bad = _error_like_deltas(deltas)

    lines = [
        f"iface={result.iface}",
        "",
        "=== ethtool (after large transfer) ===",
        eth,
        "",
        "=== ethtool -S (after) ===",
        stats,
        "",
        "=== ip -s link (after) ===",
        ip_link,
        "",
        "=== ethtool -S deltas (after - before) ===",
    ]
    if deltas:
        lines.extend(f"{k}: {v}" for k, v in deltas)
    else:
        lines.append("(no counter changes)")
    if bad:
        result.ok = False
        result.messages.append(f"Nonzero error/drop counters after transfer: {bad}")
        lines.append("")
        lines.append("ERROR: nonzero error/drop/collision/carrier/pause deltas — stop before sweeps.")

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


class SsSampler:
    """Sample `ss -ti` periodically during a transfer."""

    def __init__(self, host: str, port: int, interval_s: float = 0.1) -> None:
        self.host = host
        self.port = port
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lines: list[str] = []

    def start(self) -> None:
        if not _tool("ss"):
            self.lines.append("ss not available")
            return

        def worker() -> None:
            while not self._stop.is_set():
                ts = time.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(time.time()*1000)%1000:03d}"
                code, out, err = _run(["ss", "-ti", f"dst {self.host}:{self.port}"], timeout=5.0)
                block = out or err or f"ss exit {code}"
                self.lines.append(f"--- {ts} ---\n{block}")
                self._stop.wait(self.interval_s)

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def stop(self) -> str:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return "\n\n".join(self.lines)


def run_tcpdump(iface: str, output_pcap: Path, host: str, port: int, duration_s: float) -> str:
    if not _tool("tcpdump"):
        msg = "tcpdump not available"
        output_pcap.with_suffix(".txt").write_text(msg + "\n", encoding="utf-8")
        return msg

    filter_expr = f"host {host} and port {port}"
    cmd = [
        "tcpdump",
        "-i",
        iface,
        "-w",
        str(output_pcap),
        "-c",
        "100000",
        filter_expr,
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(duration_s)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr = proc.stderr.read() if proc.stderr else ""
        if output_pcap.exists():
            return f"pcap written: {output_pcap} ({output_pcap.stat().st_size} bytes)\n{stderr}".strip()
        return f"tcpdump ended without pcap: {stderr}".strip()
    except OSError as exc:
        return f"tcpdump failed: {exc}"
