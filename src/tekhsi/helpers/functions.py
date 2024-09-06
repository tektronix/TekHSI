"""Module containing helpers for the `TekHSI` package."""

import datetime

from dateutil.tz import tzlocal


####################################################################################################
# Public Functions
####################################################################################################
def print_with_timestamp(message: str, end: str = "\n") -> str:
    """Print and return a string prepended with a timestamp.

    Args:
        message: The message to print.
        end: The end of the line to print.
    """
    message = f"{get_timestamp_string()} - {message}"
    print(message, end=end)
    return message


####################################################################################################
# Private Functions
####################################################################################################
def get_timestamp_string() -> str:
    """Return a string containing the current timestamp."""
    return str(datetime.datetime.now(tz=tzlocal()))[:-3]
