"""Enum definitions for Tektronix signal generators and analyzers."""

from enum import IntEnum


class WaveformType(IntEnum):
    """Enumeration for waveform types."""

    ANALOG_IQ = 6
    ANALOG_16_IQ = 7
    DIGITAL = 4
    DIGITAL_16 = 5
