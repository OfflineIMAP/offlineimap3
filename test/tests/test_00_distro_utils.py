#!/usr/bin/env python
"""Regression tests for CA bundle search-path handling."""

import unittest
from unittest import mock

from offlineimap.utils import distro_utils


_DEFAULT_LOCATIONS = getattr(distro_utils, "__DEF_OS_LOCATIONS")


class TestGetOsSslcertfileSearchpath(unittest.TestCase):
    def test_does_not_mutate_default_locations(self):
        _DEFAULT_LOCATIONS["test-os"] = ["/x-ca-bundle.crt"]
        try:
            with mock.patch.object(
                distro_utils, "get_os_name", return_value="test-os"
            ):
                distro_utils.get_os_sslcertfile_searchpath()
            self.assertEqual(
                _DEFAULT_LOCATIONS["test-os"],
                ["/x-ca-bundle.crt"],
            )
        finally:
            del _DEFAULT_LOCATIONS["test-os"]

    def test_repeated_calls_are_stable(self):
        _DEFAULT_LOCATIONS["test-os"] = ["/x-ca-bundle.crt"]
        try:
            with mock.patch.object(
                distro_utils, "get_os_name", return_value="test-os"
            ):
                first = list(distro_utils.get_os_sslcertfile_searchpath())
                second = list(distro_utils.get_os_sslcertfile_searchpath())
            self.assertEqual(first, second)
        finally:
            del _DEFAULT_LOCATIONS["test-os"]


if __name__ == "__main__":
    unittest.main()
