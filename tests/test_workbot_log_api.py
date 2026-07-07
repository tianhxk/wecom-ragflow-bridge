import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workbot_query_api import WorkBotQueryApi  # noqa: E402


class UnusedStore:
    pass


class WorkBotLogApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(self.temp_dir.name)
        self.log_file = directory / "bridge.log"
        self.log_file.write_bytes(b"one\ntwo\nthree\nfour\n")
        (directory / "bridge.log.2026-07-02").write_bytes(b"archive\n")
        (directory / "unrelated.log").write_bytes(b"private\n")

        app = web.Application()
        WorkBotQueryApi(
            UnusedStore(),
            "test-token",
            log_file=self.log_file,
        ).add_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer test-token"}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp_dir.cleanup()

    async def test_log_list_requires_authentication(self):
        response = await self.client.get("/api/workbot/logs")
        self.assertEqual(401, response.status)

    async def test_log_list_only_returns_configured_log_family(self):
        response = await self.client.get("/api/workbot/logs", headers=self.headers)
        body = await response.json()
        names = {item["name"] for item in body["data"]["items"]}

        self.assertEqual(200, response.status)
        self.assertEqual({"bridge.log", "bridge.log.2026-07-02"}, names)

    async def test_log_content_returns_bounded_tail(self):
        response = await self.client.get(
            "/api/workbot/logs/bridge.log/content?tail_lines=2",
            headers=self.headers,
        )
        body = await response.json()

        self.assertEqual(200, response.status)
        self.assertEqual("three\nfour\n", body["data"]["content"])
        self.assertTrue(body["data"]["truncated"])

    async def test_log_download_returns_original_file(self):
        response = await self.client.get(
            "/api/workbot/logs/bridge.log/download",
            headers=self.headers,
        )

        self.assertEqual(200, response.status)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual("one\ntwo\nthree\nfour\n", await response.text())

    async def test_unrelated_file_is_rejected(self):
        response = await self.client.get(
            "/api/workbot/logs/unrelated.log/content",
            headers=self.headers,
        )
        self.assertEqual(400, response.status)


if __name__ == "__main__":
    unittest.main()
