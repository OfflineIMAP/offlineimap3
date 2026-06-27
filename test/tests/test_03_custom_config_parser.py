# Copyright (C) 2012- Sebastian Spaeth & contributors
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
import unittest
import tempfile
import shutil
import os
from unittest.mock import patch

from offlineimap.CustomConfig import CustomConfigParser


class TestCustomConfigParser(unittest.TestCase):
    """Unit tests for CustomConfigParser class

    These tests directly invoke internal helper functions to guarantee that
    they deliver results as expected."""

    def setUp(self):
        """Create a temporary directory for each test."""
        self.test_dir = tempfile.mkdtemp(prefix="offlineimap_test_")

    def tearDown(self):
        """Remove the temporary directory after each test."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_default_metadatadir(self):
        """Test getmetadatadir() with no metadata config set

        When no metadata directory is specified in config, it should
        default to ~/.offlineimap and create it if it doesn't exist."""
        with patch.dict("os.environ", {"HOME": self.test_dir}, clear=False):
            config = CustomConfigParser()
            config.add_section("general")

            metadatadir = config.getmetadatadir()

            expected = os.path.join(self.test_dir, ".offlineimap")
            self.assertEqual(metadatadir, expected)
            self.assertTrue(os.path.exists(metadatadir))
            self.assertTrue(os.path.isdir(expected))
            self.assertEqual(os.stat(metadatadir).st_mode & 0o777, 0o700)

    def test_02_custom_metadatadir(self):
        """Test getmetadatadir() with custom metadata config

        When a custom metadata directory is specified in config,
        it should use that path."""
        custom_dir = os.path.join(self.test_dir, "custom_metadata")
        config = CustomConfigParser()
        config.add_section("general")
        config.set("general", "metadata", custom_dir)

        metadatadir = config.getmetadatadir()

        self.assertEqual(metadatadir, custom_dir)
        self.assertTrue(os.path.exists(metadatadir))

    def test_03_tilde_expansion(self):
        """Test getmetadatadir() expands tilde in config value

        When metadata directory contains ~, it should be expanded
        to the user's home directory."""
        with patch.dict("os.environ", {"HOME": self.test_dir}, clear=False):
            config = CustomConfigParser()
            config.add_section("general")
            config.set("general", "metadata", "~/my_offlineimap")

            metadatadir = config.getmetadatadir()

            expected = os.path.join(self.test_dir, "my_offlineimap")
            self.assertEqual(metadatadir, expected)
            self.assertTrue(os.path.isdir(expected))

    def test_04_env_var_expansion(self):
        """Test getmetadatadir() expands environment variables

        When metadata directory contains environment variables,
        they should be expanded."""
        with patch.dict("os.environ", {
            "HOME": self.test_dir,
            "OFFLINEIMAP_TEST_DIR": self.test_dir
        }, clear=False):
            config = CustomConfigParser()
            config.add_section("general")
            config.set("general", "metadata", "$OFFLINEIMAP_TEST_DIR/env_metadata")

            metadatadir = config.getmetadatadir()

            expected = os.path.join(self.test_dir, "env_metadata")
            self.assertEqual(metadatadir, expected)
            self.assertTrue(os.path.exists(metadatadir))
            self.assertTrue(os.path.isdir(expected))

    def test_05_directory_not_recreated(self):
        """Test getmetadatadir() doesn't fail if directory already exists

        Calling getmetadatadir() multiple times should not cause errors
        even if the directory already exists."""
        with patch.dict("os.environ", {"HOME": self.test_dir}, clear=False):
            config = CustomConfigParser()
            config.add_section("general")

            # First call creates the directory
            metadatadir1 = config.getmetadatadir()

            # Second call should return the same path without error
            metadatadir2 = config.getmetadatadir()

            self.assertEqual(metadatadir1, metadatadir2)
            self.assertTrue(os.path.exists(metadatadir1))

    def test_06_creates_metadata_directory_when_parent_exists(self):
        """Create the metadata directory if its parent already exists.
        
        The original implementation uses os.mkdir() which only
        creates a single directory level. The parent must exist.
        This test verifies the current behavior."""
        nested_dir = os.path.join(self.test_dir, "level1", "level2", "metadata")
        # Ensure parent exists
        os.makedirs(os.path.dirname(nested_dir), exist_ok=True)

        with patch.dict("os.environ", {"HOME": self.test_dir}, clear=False):
            config = CustomConfigParser()
            config.add_section("general")
            config.set("general", "metadata", nested_dir)

            metadatadir = config.getmetadatadir()

            self.assertEqual(metadatadir, nested_dir)
            self.assertTrue(os.path.exists(metadatadir))

    def test_07_fail_when_parent_directory_does_not_exist(self):
        """The metadata directory's parent must already exist."""
        metadata_dir = os.path.join(
            self.test_dir,
            "level1",
            "level2",
            "metadata",
        )

        config = CustomConfigParser()
        config.add_section("general")
        config.set("general", "metadata", metadata_dir)

        with self.assertRaises(OSError):
            config.getmetadatadir()
