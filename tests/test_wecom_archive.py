import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wecom_archive import (  # noqa: E402
    WeComArchiveError,
    WeComArchiveService,
    WeComArchiveStore,
    _parse_private_key_map,
)


class WeComArchiveStoreTests(unittest.TestCase):
    def test_save_message_extracts_query_fields(self):
        store = object.__new__(WeComArchiveStore)
        captured = {}

        class Cursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        store._connect = lambda: Conn()
        saved = store._save_message_sync(
            42,
            {"seq": 42, "msgid": "encrypted-msg-id"},
            {
                "msgid": "msg-id",
                "action": "send",
                "msgtype": "text",
                "from": "zhangsan",
                "roomid": "room-1",
                "msgtime": 1780000000000,
                "text": {"content": "hello"},
            },
        )

        self.assertTrue(saved)
        self.assertIn("wecom_archive_message", captured["sql"])
        self.assertEqual(42, captured["params"][0])
        self.assertEqual("msg-id", captured["params"][1])
        self.assertEqual("send", captured["params"][2])
        self.assertEqual("text", captured["params"][3])
        self.assertEqual("zhangsan", captured["params"][4])
        self.assertEqual("room-1", captured["params"][5])
        self.assertEqual(1780000000000, captured["params"][6])

    def test_private_key_map_parser_accepts_versions(self):
        parsed = _parse_private_key_map("1=/keys/v1.pem;2=/keys/v2.pem")

        self.assertEqual({"1": "/keys/v1.pem", "2": "/keys/v2.pem"}, parsed)

    def test_select_rsa_key_uses_version_then_default(self):
        service = object.__new__(WeComArchiveService)
        service._rsa_keys = {"1": "key-v1", "": "default-key"}

        self.assertEqual("key-v1", service._select_rsa_key("1"))
        self.assertEqual("default-key", service._select_rsa_key("2"))

    def test_select_rsa_key_requires_matching_version_without_default(self):
        service = object.__new__(WeComArchiveService)
        service._rsa_keys = {"1": "key-v1"}

        with self.assertRaises(WeComArchiveError):
            service._select_rsa_key("2")


if __name__ == "__main__":
    unittest.main()