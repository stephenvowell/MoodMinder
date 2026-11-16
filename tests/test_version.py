"""Version number checks — single source of truth is mood_engine.VERSION."""

import re
import unittest

from mood_engine import VERSION

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(VERSION, SEMVER_RE)

    def test_version_is_current_release(self):
        self.assertEqual(VERSION, "1.0.1")


if __name__ == "__main__":
    unittest.main()
