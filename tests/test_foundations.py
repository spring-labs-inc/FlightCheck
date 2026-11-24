"""Bounded shared-foundation acceptance witnesses."""
import unittest

from foundation_config_cases import ConfigurationCases
from foundation_flight_cases import FlightCases


class FoundationTests(ConfigurationCases, FlightCases, unittest.TestCase):
    """One native identity per frozen criterion; detailed assertions use subcases."""


if __name__ == "__main__":
    unittest.main()
