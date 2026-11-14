"""Small pure helpers for saved UI state. No Tk display needed for tests."""

def sidebar_width(value, minimum=180, maximum=350):
    try:
        width = int(value)
    except (TypeError, ValueError, OverflowError):
        width = 240
    return max(minimum, min(maximum, width))


def valid_column_filters(saved, available):
    if not isinstance(saved, dict):
        return {}
    return {key: term for key, term in saved.items()
            if key in available and isinstance(term, str) and len(term) <= 200}


def shortcut_conflicts(mapping):
    sequences = list(mapping.values())
    return len(sequences) != len(set(sequences))
