from typing import Dict

from tekhsi import WaveformHeader


def any_horizontal_change(
    previous_header: Dict[str, WaveformHeader],
    current_header: Dict[str, WaveformHeader],
) -> bool:
    """Acq acceptance filter that accepts only acqs with changes to horizontal settings.

    Args:
        previous_header (dict[str, WaveformHeader]): Previous header dictionary.
        current_header (dict[str, WaveformHeader]): Current header dictionary.

    Returns:
        True if the acquisition is accepted, False otherwise.
    """
    for key, cur in current_header.items():
        if key not in previous_header:
            return True
        prev = previous_header[key]
        if prev is None and cur is not None:
            return True
        if prev is not None and (
            prev.noofsamples != cur.noofsamples
            or prev.horizontalspacing != cur.horizontalspacing
            or prev.horizontalzeroindex != cur.horizontalzeroindex
        ):
            return True
    return False
