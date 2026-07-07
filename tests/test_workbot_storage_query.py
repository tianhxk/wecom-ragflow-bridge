import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workbot_storage import WorkBotMessageStore  # noqa: E402


class WorkBotStorageQueryTests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(WorkBotMessageStore)
        self.captured = None

        def capture(sql, params):
            self.captured = (sql, params)
            return [{"id": 1}]

        self.store._fetch_dict_rows = capture
        self.start = datetime(2026, 7, 1)
        self.end = datetime(2026, 7, 2)

    def test_message_query_builds_parameterized_conditions(self):
        rows = self.store._query_messages_sync(
            "robot-1",
            self.start,
            self.end,
            50,
            100,
            {"groupname": "测试群", "process_status": "done"},
        )
        sql, params = self.captured

        self.assertEqual([{"id": 1}], rows)
        self.assertIn("groupname` = %s", sql)
        self.assertIn("process_status` = %s", sql)
        self.assertIn("id < %s", sql)
        self.assertNotIn("测试群", sql)
        self.assertEqual(["robot-1", self.start, self.end, "测试群", "done", 100, 50], params)

    def test_callback_query_builds_cursor_and_mode_conditions(self):
        self.store._query_callback_logs_sync(
            "robot-1",
            self.start,
            self.end,
            20,
            88,
            "logs",
        )
        sql, params = self.captured

        self.assertIn("mode = %s", sql)
        self.assertIn("id < %s", sql)
        self.assertEqual(["robot-1", self.start, self.end, "logs", 88, 20], params)


if __name__ == "__main__":
    unittest.main()
