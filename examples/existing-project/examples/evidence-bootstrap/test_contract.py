"""Owner's small new behavior, shared unchanged by original and new products."""

import unittest
from product import normalize_label


class LabelTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_label("  Alpha  "), "Alpha")
        self.assertEqual(normalize_label(""), "")
        with self.assertRaises(TypeError):
            normalize_label(42)
