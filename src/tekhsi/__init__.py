"""Tektronix High Speed Interface.

Provides access to commonly imported items from the `TekHSI` package.
"""

from importlib.metadata import version

from tekhsi._tek_highspeed_server_pb2 import WaveformHeader  # pylint: disable= no-name-in-module
from tekhsi.credential_store import (
    CertInfo,
    TekCredentialStore,
    TekHSICredentialStore,
)
from tekhsi.helpers import configure_logging, LoggingLevels, PACKAGE_NAME
from tekhsi.load_timing import FastFrameLoadTiming, WaveformTransferTiming
from tekhsi.security import (
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekHSICredentials,
    TekHSIUnknownInstrument,
    TekSecurityError,
    TekUnknownInstrument,
)
from tekhsi.tek_hsi_connect import AcqWaitOn, TekHSIConnect

# Read version from installed package.
__version__ = version(PACKAGE_NAME)

__all__ = [
    "PACKAGE_NAME",
    "AcqWaitOn",
    "CertInfo",
    "FastFrameLoadTiming",
    "LoggingLevels",
    "TekAuthenticationFailed",
    "TekCertificateMismatch",
    "TekCredentialStore",
    "TekHSIConnect",
    "TekHSICredentialStore",
    "TekHSICredentials",
    "TekHSIUnknownInstrument",
    "TekSecurityError",
    "TekUnknownInstrument",
    "WaveformHeader",
    "WaveformTransferTiming",
    "configure_logging",
]
