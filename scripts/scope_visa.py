"""PyVISA SCPI helpers for scope configuration.

All functions accept a pyvisa Resource object returned by
``setup_scope_via_visa()``.  Each function prints a warning rather than
raising on failure so the benchmark can continue with the current scope
state when VISA is unavailable.
"""

from __future__ import annotations

import time

from typing import Any

DEFAULT_VISA_TIMEOUT_MS = 120_000
DEFAULT_ACQ_WAIT_TIMEOUT_S = 120.0


def send_command(
    scope: Any,
    command: str,
    *,
    is_query: bool = False,
    delay: float = 0.5,
    wait_opc: bool = False,
) -> str | None:
    """Send a SCPI write or query and return the response (queries only).

    Args:
        scope: Open pyvisa Resource object.
        command: SCPI command string.
        is_query: ``True`` to use ``query()`` and return the response.
        delay: Seconds to sleep after the command.
        wait_opc: ``True`` to block on ``*OPC?`` after a write command.

    Returns:
        Response string for queries; ``None`` for writes or on error.
    """
    try:
        if is_query:
            result: str = scope.query(command)
            time.sleep(delay)
            return result
        scope.write(command)
        if wait_opc:
            opc = scope.query("*OPC?").strip()
            if opc != "1":
                print(f"  [VISA] Warning: unexpected *OPC? response '{opc}'")
        time.sleep(delay)
        return None
    except Exception as exc:
        print(f"  [VISA] Error sending '{command}': {exc}")
        return None


def setup_scope_via_visa(
    ip: str,
    timeout_ms: int = DEFAULT_VISA_TIMEOUT_MS,
    afg_frequency: float = 50e6,
) -> tuple[Any, Any] | tuple[None, None]:
    """Open a VXI-11 PyVISA connection to the scope and run initial setup.

    Sequence: clear errors → *RST → AFG ON at ``afg_frequency`` → AUTOSet.

    Args:
        ip: Instrument IP address (no port).
        timeout_ms: Resource timeout in milliseconds.
        afg_frequency: AFG output frequency in Hz (default 50 MHz).

    Returns:
        ``(scope, resource_manager)`` on success; ``(None, None)`` on failure.
    """
    try:
        import pyvisa as visa  # pylint: disable=import-outside-toplevel
    except ImportError:
        print("  [VISA] pyvisa is not installed. Run: pip install pyvisa pyvisa-py")
        return None, None

    try:
        rm = visa.ResourceManager("@py")
        visa_addr = f"TCPIP::{ip}::INSTR"
        scope = rm.open_resource(visa_addr)
        scope.timeout = timeout_ms
        scope.encoding = "latin_1"
        scope.write_termination = "\n"

        # Clear instrument state.
        send_command(scope, "*ESR?", is_query=True)
        send_command(scope, "allev?", is_query=True)
        send_command(scope, "*cls")
        send_command(scope, "header OFF")
        send_command(scope, ":HSInterface:STATe 1")
        send_command(scope, "*RST", delay=3.0)
        send_command(scope, ":AFG:OUTPut:STATE 1")
        send_command(scope, f"AFG:FREQUENCY {int(afg_frequency)}", delay=1.0)
        # send_command(scope, "AUTOSet EXECute", delay=5.0)

        print(f"  [VISA] Connected to {visa_addr}")
        print(f"  [VISA] AFG ON at {afg_frequency / 1e6:.0f} MHz")
        return scope, rm
    except Exception as exc:
        print(f"  [VISA] Could not connect to {ip}: {exc}")
        return None, None


def configure_record_length(
    scope: Any,
    record_length: int,
) -> int | None:
    """Set horizontal record length on the scope.

    Args:
        scope: Open pyvisa Resource.
        record_length: Desired samples per frame.

    Returns:
        Actual record length reported by scope, or ``None`` on failure.
    """
    try:
        print(f"  [VISA] Setting record length: {record_length:,}")
        send_command(scope, "HORizontal:MODe MANual")
        send_command(scope, ":HSInterface:STATe 1")
        send_command(scope, "DISplay:WAVEform OFF")
        send_command(scope, f"HOR:MODE:RECO {record_length}", delay=2.0, wait_opc=True)

        response = send_command(scope, "HOR:MODE:RECO?", is_query=True)
        if response:
            actual = int(response.strip())
            if actual != record_length:
                print(f"  [VISA] Note: scope clamped record length {record_length:,} -> {actual:,}")
            else:
                print(f"  [VISA] Record length confirmed: {actual:,}")
            return actual
        return None
    except Exception as exc:
        print(f"  [VISA] Error configuring record length: {exc}")
        return None


def configure_fastframe(scope: Any, frame_count: int) -> int | None:
    """Enable FastFrame and set the frame count on the scope.

    Args:
        scope: Open pyvisa Resource.
        frame_count: Desired number of FastFrame frames (must be >= 2).

    Returns:
        Actual frame count reported by scope, or ``None`` on failure.
    """
    if frame_count < 2:
        print(f"  [VISA] Warning: frame_count={frame_count} < 2; FastFrame requires >= 2.")
        return None

    try:
        send_command(scope, "HORIZONTAL:FASTFRAME:STATE ON")
        send_command(scope, f"HORIZONTAL:FASTFRAME:COUNT {frame_count}", wait_opc=True)
        time.sleep(0.2)

        response = send_command(scope, "HORIZONTAL:FASTFRAME:COUNT?", is_query=True)
        if response:
            actual = int(response.strip())
            if actual != frame_count:
                print(f"  [VISA] Note: scope clamped frame count {frame_count} -> {actual}")
            else:
                print(f"  [VISA] FastFrame count confirmed: {actual}")
            return actual
        return None
    except Exception as exc:
        print(f"  [VISA] Error configuring FastFrame: {exc}")
        return None


def disable_fastframe(scope: Any) -> bool:
    """Disable FastFrame on the scope (set frame count to 1).

    Used for Default mode to ensure no FastFrame is active.

    Args:
        scope: Open pyvisa Resource.

    Returns:
        ``True`` if successful, ``False`` on failure.
    """
    try:
        send_command(scope, "HORIZONTAL:FASTFRAME:STATE OFF")
        print("  [VISA] FastFrame disabled.")
        return True
    except Exception as exc:
        print(f"  [VISA] Error disabling FastFrame: {exc}")
        return False


def clear_acquisitions(scope: Any, delay_s: float = 0.5) -> None:
    """Reset the scope acquisition counter via front-panel Clear.

    Sends ``FPanel:Press CLEAR`` then sleeps ``delay_s`` seconds to allow
    the scope to settle before the next acquisition timing loop starts.

    Args:
        scope: Open pyvisa Resource.
        delay_s: Seconds to wait after the Clear command.
    """
    send_command(scope, "FPanel:Press CLEAR", delay=delay_s)


def start_scope_acquisition(scope: Any, delay_s: float = 0.0) -> None:
    """Start or resume scope acquisition.

    Args:
        scope: Open pyvisa Resource.
        delay_s: Seconds to wait after sending the run command.
    """
    send_command(scope, "ACQUIRE:STATE RUN", delay=delay_s, wait_opc=True)


def wait_for_acquisition_complete(
    scope: Any,
    timeout_s: float = DEFAULT_ACQ_WAIT_TIMEOUT_S,
) -> tuple[bool, str]:
    """Poll until acquisition stops or ``timeout_s`` elapses.

    Returns:
        ``(True, "")`` when ``ACQuire:STATE?`` is ``0``; ``(False, reason)`` on timeout/error.
    """
    deadline = time.monotonic() + timeout_s
    saved_timeout = getattr(scope, "timeout", DEFAULT_VISA_TIMEOUT_MS)
    scope.timeout = 10_000
    try:
        while time.monotonic() < deadline:
            try:
                resp = scope.query("ACQuire:STATE?")
            except Exception as exc:
                return False, f"ACQuire:STATE? error: {exc}"
            if resp is not None and resp.strip() == "0":
                return True, ""
            time.sleep(0.05)
        return False, f"acquisition wait timeout after {timeout_s:.0f}s"
    finally:
        scope.timeout = saved_timeout


def stop_scope_acquisition(scope: Any, delay_s: float = 0.0) -> None:
    """Stop scope acquisition.

    Args:
        scope: Open pyvisa Resource.
        delay_s: Seconds to wait after sending the stop command.
    """
    send_command(scope, "ACQUIRE:STATE 0", delay=delay_s)


def close_visa(scope: Any, rm: Any) -> None:
    """Re-enable scope display and close the VISA connection gracefully."""
    try:
        send_command(scope, "DISplay:WAVEform ON")
        scope.close()
        rm.close()
        print("  [VISA] Connection closed.")
    except Exception as exc:
        print(f"  [VISA] Warning during close: {exc}")


def arm_sequence_acquisition(scope: Any, acq_count: int) -> None:
    """Configure sequence acquisition and arm the scope."""
    # Replace this with the exact acquisition-count SCPI for your scope model.
    # send_command(scope, f"ACQUIRE:SEQUENCE:NUMSEQUENCE {acq_count}")
    send_command(scope, "ACQUIRE:STOPAfter SEQUENCE")
