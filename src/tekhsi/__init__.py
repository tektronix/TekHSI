"""Tektronix High Speed Interface.

Provides access to commonly imported items from the `TekHSI` package.
"""

from importlib.metadata import version

from tekhsi._tek_highspeed_server_pb2 import WaveformHeader  # pylint: disable= no-name-in-module
from tekhsi.credential_store import CertInfo, TekCredentialStore, TekHSICredentialStore
from tekhsi.helpers import configure_logging, LoggingLevels, PACKAGE_NAME
from tekhsi.load_timing import CAPABILITY_FASTFRAME, FastFrameLoadTiming, REPLY_CONTENT_MASK_FRAME_METADATA, WaveformTransferTiming
from tekhsi.security import (
    TekAuthenticationFailed,
    TekCertificateMismatch,
    TekHSICredentials,
    TekHSIUnknownInstrument,
    TekSecurityError,
    TekUnknownInstrument,
)
from tekhsi.tek_hsi_connect import AcqWaitOn, TekHSIConnect
from tm_data_types import FastFrameAnalogWaveform, FastFrameDigitalWaveform, FrameTimingInfo

# Read version from installed package.
__version__ = version(PACKAGE_NAME)

__all__ = [
    "CAPABILITY_FASTFRAME",
    "REPLY_CONTENT_MASK_FRAME_METADATA",
    "PACKAGE_NAME",
    "AcqWaitOn",
    "CertInfo",
    "FastFrameAnalogWaveform",
    "FastFrameDigitalWaveform",
    "FastFrameLoadTiming",
    "WaveformTransferTiming",
    "FrameTimingInfo",
    "LoggingLevels",
    "TekAuthenticationFailed",
    "TekCertificateMismatch",
    "TekCredentialStore",
    "TekHSICredentialStore",
    "TekHSICredentials",
    "TekHSIConnect",
    "TekHSIUnknownInstrument",
    "TekSecurityError",
    "TekUnknownInstrument",
    "WaveformHeader",
    "configure_logging",
]
