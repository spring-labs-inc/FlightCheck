"""Proposed new behavior for the disposable adoption example."""


def normalize_label(value):
    if not isinstance(value, str):
        raise TypeError("A label must be text")
    return value.strip()
