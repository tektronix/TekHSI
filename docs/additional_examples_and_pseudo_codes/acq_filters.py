def any_horizontal_change(previous_header, current_header):
    """Prebuilt acq acceptance filter that accepts only acqs with
    changes to horizontal settings.
    """
    for key, cur in current_header.items():
        if key not in previous_header:
            return True
        prev = previous_header[key]
        if prev is None and cur != None:
            return True
        if prev is not None and (
            prev.noofsamples != cur.noofsamples
            or prev.horizontalspacing != cur.horizontalspacing
            or prev.horizontalzeroindex != cur.horizontalzeroindex
        ):
            return True
    return False
