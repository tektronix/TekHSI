"""Tests for the helpers subpackage."""

import datetime

from contextlib import redirect_stdout
from io import StringIO

import dateutil.parser

from dateutil.tz import tzlocal

from tekhsi.helpers import print_with_timestamp


def test_print_with_timestamp() -> None:
    """Test the print_with_timestamp helper function."""
    stdout = StringIO()
    with redirect_stdout(stdout):
        now = datetime.datetime.now(tz=tzlocal())
        print_with_timestamp("message")

    message = stdout.getvalue()
    message_parts = message.split(" - ")
    assert len(message_parts) == 2
    assert message_parts[1] == "message\n"
    parsed_datetime = dateutil.parser.parse(message_parts[0].strip())
    allowed_difference = datetime.timedelta(
        days=0,
        hours=0,
        minutes=0,
        seconds=1,
        microseconds=0,
    )
    calculated_difference = abs(parsed_datetime - now)
    assert calculated_difference <= allowed_difference
