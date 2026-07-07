import logging
import os
import sys
import tempfile
import unittest
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from logging_config import configure_logging  # noqa: E402


class LoggingConfigTests(unittest.TestCase):
    def test_daily_rotation_keeps_thirty_days_including_current_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "bridge.log"
            with patch.dict(
                os.environ,
                {
                    "LOG_FILE": str(log_file),
                    "LOG_LEVEL": "INFO",
                    "LOG_RETENTION_DAYS": "30",
                },
            ):
                configure_logging()

            handlers = [
                handler
                for handler in logging.getLogger().handlers
                if isinstance(handler, TimedRotatingFileHandler)
            ]
            self.assertEqual(1, len(handlers))
            self.assertEqual("MIDNIGHT", handlers[0].when)
            self.assertEqual(1, handlers[0].interval // (24 * 60 * 60))
            self.assertEqual(29, handlers[0].backupCount)
            logging.basicConfig(
                level=logging.WARNING,
                handlers=[logging.NullHandler()],
                force=True,
            )


if __name__ == "__main__":
    unittest.main()
