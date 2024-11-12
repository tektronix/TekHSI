"""Tests for the logging functionality."""

import logging
import shutil
import sys

from pathlib import Path
from typing import Generator

import colorlog
import pytest

import tekhsi

from tekhsi import configure_logging, LoggingLevels, PACKAGE_NAME
from tekhsi.helpers import logging as tekhsi_logging


def test_logging_singleton() -> None:
    """Verify the singleton behavior of the logging configuration function."""
    package_logger = logging.getLogger(PACKAGE_NAME)
    logger_handlers_copy = package_logger.handlers.copy()
    assert len(logger_handlers_copy) == 3
    logger = configure_logging()
    assert len(logger.handlers) == 3
    assert logger.handlers == logger_handlers_copy


@pytest.fixture(name="reset_package_logger")
def _reset_package_logger() -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
    """Reset the package logger."""
    logger = logging.getLogger(PACKAGE_NAME)
    handlers_copy = logger.handlers.copy()
    for handler in handlers_copy:
        logger.removeHandler(handler)
    tekhsi_logging._logger_initialized = False  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    yield
    # Reset the handlers back to what they were
    for handler in logger.handlers.copy():
        logger.removeHandler(handler)
    for handler in handlers_copy:
        logger.addHandler(handler)


def test_configure_logger_full(reset_package_logger: None) -> None:  # noqa: ARG001
    """Test the configuration function with all types of logs."""
    log_dir = (
        Path(__file__).parent / f"generated_logs_py{sys.version_info.major}{sys.version_info.minor}"
    )
    log_name = "custom_log.log"
    shutil.rmtree(log_dir, ignore_errors=True)

    assert len(logging.getLogger(PACKAGE_NAME).handlers) == 0  # pylint: disable=use-implicit-booleaness-not-comparison-to-zero
    logger = configure_logging(
        log_console_level="DEBUG",
        log_file_level="DEBUG",
        log_file_directory=log_dir,
        log_file_name=log_name,
        log_colored_output=False,
    )
    assert len(logger.handlers) == 3
    log_contents = (log_dir / log_name).read_text()
    assert "] [   DEBUG] timezone==" in log_contents
    assert f"] [   DEBUG] {PACKAGE_NAME}=={tekhsi.__version__}" in log_contents
    assert [type(x) for x in logger.handlers] == [
        logging.NullHandler,
        logging.FileHandler,
        logging.StreamHandler,
    ]


def test_configure_logger_no_file(reset_package_logger: None) -> None:  # noqa: ARG001
    """Test the configuration function with no file logging."""
    assert len(logging.getLogger(PACKAGE_NAME).handlers) == 0  # pylint: disable=use-implicit-booleaness-not-comparison-to-zero
    logger = configure_logging(
        log_console_level="DEBUG",
        log_file_level=LoggingLevels.NONE,
        log_colored_output=True,
    )
    assert len(logger.handlers) == 2
    assert [type(x) for x in logger.handlers] == [logging.NullHandler, colorlog.StreamHandler]
    assert isinstance(logger.handlers[1].formatter, colorlog.ColoredFormatter)
