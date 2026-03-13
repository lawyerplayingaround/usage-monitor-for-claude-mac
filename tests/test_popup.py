"""
Popup Tests
=============

Unit tests for popup bar color logic.

The bar turns red when ``pct > time_pct`` (usage ahead of elapsed time).
Since this is inlined in the popup code, these tests verify the condition
directly rather than calling a helper function.
"""
from __future__ import annotations

import unittest


def _bar_is_high(pct: float, time_pct: float | None) -> bool:
    """Mirror the inline bar color condition used in popup.py."""
    return time_pct is not None and pct > time_pct


class TestBarColor(unittest.TestCase):
    """Tests for the bar color logic (red when usage outpaces elapsed time)."""

    def test_no_time_info(self):
        """Without elapsed time info, never red."""
        self.assertFalse(_bar_is_high(95, None))

    def test_usage_ahead_of_time(self):
        """Usage ahead of elapsed time - red."""
        self.assertTrue(_bar_is_high(60, 50))

    def test_usage_behind_time(self):
        """Usage behind elapsed time - not red."""
        self.assertFalse(_bar_is_high(40, 50))

    def test_usage_equals_time(self):
        """Usage exactly at elapsed time - not red (strictly greater)."""
        self.assertFalse(_bar_is_high(50, 50))

    def test_zero_usage_at_zero_time(self):
        """Both at zero - not red."""
        self.assertFalse(_bar_is_high(0, 0))

    def test_any_usage_at_zero_time(self):
        """Any usage at zero time - red."""
        self.assertTrue(_bar_is_high(1, 0))


if __name__ == '__main__':
    unittest.main()
