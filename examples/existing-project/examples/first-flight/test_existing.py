"""An existing behavior witness; not a mock controller/reviewer response."""

from product import normalize_label
import pytest


def test_normalization():
    assert normalize_label("  Alpha  ") == "Alpha"
    assert normalize_label("") == ""
    with pytest.raises(TypeError):
        normalize_label(42)
