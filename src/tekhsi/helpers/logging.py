# pyright: reportUnnecessaryTypeIgnoreComment=none
"""Helpers for TekHSI logging."""

from __future__ import annotations

import importlib.metadata
import logging
import sys
import time

from enum import Enum
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Union

import colorlog

from tzlocal import get_localzone  # pyright: ignore[reportUnknownVariableType]

from tekhsi.helpers.constants import (  # pylint: disable=import-outside-toplevel
    PACKAGE_NAME,
)

if TYPE_CHECKING:
    import os

_logger_initialized = False


class LoggingLevels(Enum):
    """A class holding the valid logging levels supported."""

    DEBUG = "DEBUG"
    """An enum member representing the DEBUG logging level."""
    INFO = "INFO"
    """An enum member representing the INFO logging level."""
    WARNING = "WARNING"
    """An enum member representing the WARNING logging level."""
    ERROR = "ERROR"
    """An enum member representing the ERROR logging level."""
    CRITICAL = "CRITICAL"
    """An enum member representing the CRITICAL logging level."""
    NONE = "NONE"
    """An enum member indicating no logging messages should be captured."""


def configure_logging(
    *,
    log_console_level: Union[str, LoggingLevels] = LoggingLevels.INFO,
    log_file_level: Union[str, LoggingLevels] = LoggingLevels.DEBUG,
    log_file_directory: Optional[Union[str, os.PathLike[str], Path]] = None,
    log_file_name: Optional[str] = None,
    log_colored_output: bool = False,
) -> logging.Logger:
    """Configure the logging for this package.

    !!! note
        After this function is called once, if it is called again, it will not perform any
        additional configuration. It will simply return the base logger for the package.

    Args:
        log_console_level: The logging level to set for the console. Defaults to INFO. Set to
            [`LoggingLevels.NONE`][tekhsi.helpers.logging.LoggingLevels.NONE] to disable all
            console logging/printouts except for certain warnings and exceptions.
        log_file_level: The logging level to set for the file. Defaults to DEBUG. Set to
            [`LoggingLevels.NONE`][tekhsi.helpers.logging.LoggingLevels.NONE] to disable logging
            to a file entirely.
        log_file_directory: The directory to save log files to. Defaults to "./logs" in the
            current working directory.
        log_file_name: The name of the log file to save the logs to. Defaults to a timestamped name
            with the .log extension.
        log_colored_output: Whether to use colored output from the `colorlog` package for the
            console. Defaults to False.

    Returns:
        The base logger for the package, this base logger can also be accessed using
            `logging.getLogger(tekhsi.PACKAGE_NAME)`.
    """
    global _logger_initialized  # noqa: PLW0603

    _logger: logging.Logger = logging.getLogger(PACKAGE_NAME)
    if _logger_initialized:
        # If the logger was previously initialized, just return it
        return _logger
    # Convert object types into enum values
    log_console_level = LoggingLevels(log_console_level)
    log_file_level = LoggingLevels(log_file_level)
    # Set the logger level to the lowest level, the handlers will filter out specific levels
    # based on user configuration
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(logging.NullHandler())
    # The logger/module name is not included in the message, since formatting the messages to
    # be aligned would cause the width of the message prefix to be almost 100 characters before
    # the message is even added to the line.
    logging_file_format_string = "[%(asctime)s] [%(levelname)8s] %(message)s"
    logging_console_format_string = "%(asctime)s - %(message)s"
    if not log_file_directory:  # pragma: no cover
        log_file_directory = Path("./logs")
    if not log_file_name:  # pragma: no cover
        log_file_name = f"{PACKAGE_NAME}_{time.strftime('%m-%d-%Y_%H-%M-%S', time.localtime())}.log"
    log_filepath = Path(log_file_directory) / log_file_name

    if log_file_level != LoggingLevels.NONE:
        # Set up logger
        log_filepath.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_filepath, mode="w", encoding="utf-8")
        file_formatter = logging.Formatter(logging_file_format_string)
        file_formatter.default_msec_format = "%s.%06d"  # Use 6 digits of precision for milliseconds

        file_handler.setLevel(getattr(logging, log_file_level.value))
        file_handler.setFormatter(file_formatter)
        _logger.addHandler(file_handler)

    # Log a few things to just the file
    _logger.debug("timezone==%s", get_localzone())  # pyright: ignore[reportUnknownArgumentType,reportUnnecessaryTypeIgnoreComment]
    _logger.debug("%s==%s", PACKAGE_NAME, importlib.metadata.version(PACKAGE_NAME))

    if log_console_level != LoggingLevels.NONE:
        if log_colored_output:
            console_handler = colorlog.StreamHandler(stream=sys.stdout)
            console_formatter = colorlog.ColoredFormatter(
                "%(log_color)s" + logging_console_format_string,
                log_colors=colorlog.default_log_colors,
            )
        else:
            console_handler = logging.StreamHandler(stream=sys.stdout)
            console_formatter = logging.Formatter(logging_console_format_string)
        console_formatter.default_msec_format = (
            "%s.%06d"  # Use 6 digits of precision for milliseconds
        )

        console_handler.setLevel(getattr(logging, log_console_level.value))
        console_handler.setFormatter(console_formatter)
        _logger.addHandler(console_handler)

    _logger_initialized = True
    return _logger
