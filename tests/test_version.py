import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import version  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_repository_version_is_1_0(self):
        self.assertEqual("1.0", version.APP_VERSION)

    def test_environment_version_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"APP_VERSION": "2.0"}), patch(
                "version.Path.cwd",
                return_value=Path(temp_dir),
            ):
                self.assertEqual("2.0", version._load_version())


if __name__ == "__main__":
    unittest.main()
