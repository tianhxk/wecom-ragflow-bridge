import sys
import unittest
from datetime import datetime
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workbot_query_api import WorkBotQueryApi  # noqa: E402


class FakeStore:
    def __init__(self):
        self.message_query = None
        self.callback_query = None

    async def query_messages(self, **query):
        self.message_query = query
        return [
            {
                "id": 10,
                "robotid": query["robot_id"],
                "message": "123",
                "raw_json": '{"type":"text"}',
                "messagetime": datetime(2026, 7, 1, 8, 0, 0),
            }
        ]

    async def query_callback_logs(self, **query):
        self.callback_query = query
        return [{"id": 20, "robotid": query["robot_id"], "raw_json": '{"mode":"logs"}'}]


class WorkBotQueryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = FakeStore()
        app = web.Application()
        WorkBotQueryApi(self.store, "test-token").add_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.query = {
            "robotid": "robot-1",
            "start_time": "2026-07-01T00:00:00Z",
            "end_time": "2026-07-02T00:00:00Z",
        }
        self.headers = {"Authorization": "Bearer test-token"}

    async def asyncTearDown(self):
        await self.client.close()

    async def test_message_query_requires_authentication(self):
        response = await self.client.get("/api/workbot/messages", params=self.query)
        self.assertEqual(401, response.status)

    async def test_empty_base_path_uses_default_path(self):
        api = WorkBotQueryApi(self.store, "test-token", base_path="")
        self.assertEqual("/api/workbot", api._base_path)

    async def test_message_query_requires_bounded_conditions(self):
        response = await self.client.get(
            "/api/workbot/messages",
            params={"robotid": "robot-1"},
            headers=self.headers,
        )
        self.assertEqual(400, response.status)
        self.assertIn("start_time", (await response.json())["message"])

    async def test_message_query_returns_json_and_passes_filters(self):
        params = {**self.query, "process_status": "done", "limit": "1"}
        response = await self.client.get(
            "/api/workbot/messages",
            params=params,
            headers=self.headers,
        )
        body = await response.json()

        self.assertEqual(200, response.status)
        self.assertEqual("123", body["data"]["items"][0]["message"])
        self.assertEqual({"type": "text"}, body["data"]["items"][0]["raw_json"])
        self.assertEqual(10, body["data"]["next_before_id"])
        self.assertEqual("done", self.store.message_query["process_status"])

    async def test_callback_query_passes_mode(self):
        response = await self.client.get(
            "/api/workbot/callback-logs",
            params={**self.query, "mode": "logs"},
            headers=self.headers,
        )

        self.assertEqual(200, response.status)
        self.assertEqual("logs", self.store.callback_query["mode"])


if __name__ == "__main__":
    unittest.main()
