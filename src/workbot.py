"""WorkBot callback channel."""

import asyncio
import logging
import os
import time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
from aiohttp import web

from chat_client import ChatClient
from scheduler import PeriodicTaskManager
from session import SessionManager
from workbot_storage import WorkBotMessageStore, WorkBotQueuedMessage
from workbot_query_api import WorkBotQueryApi

logger = logging.getLogger("workbot")


class DebugAccessLogger(web.AccessLogger):
    @property
    def enabled(self) -> bool:
        return self.logger.isEnabledFor(logging.DEBUG)

    def log(self, request, response, time) -> None:
        self.logger.debug(self._format_line(request, response, time))

DEFAULT_MAX_TEXT_MESSAGE_BYTES = 3500
DEFAULT_HEALTH_CHECK_INTERVAL = 60
DEFAULT_HEALTH_CHECK_TIMEOUT = 5
DEFAULT_HEALTH_CHECK_FAILURES = 3
DEFAULT_BOT_NICKNAME_REFRESH_INTERVAL = 3600
DEFAULT_MESSAGE_WORKERS = 4
DEFAULT_MESSAGE_QUEUE_SIZE = 1000
DEFAULT_MESSAGE_RECOVER_LIMIT = 1000
DEFAULT_MESSAGE_DRAIN_TIMEOUT = 10


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("%s=%s is invalid, using default %s", name, value, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "")
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


MAX_TEXT_MESSAGE_BYTES = _env_int("WORKBOT_MAX_TEXT_MESSAGE_BYTES", DEFAULT_MAX_TEXT_MESSAGE_BYTES)


class WorkBotAPIError(Exception):
    """WorkBot API error."""


class WorkBotClient:
    """FlowBot/WorkBot HTTP API wrapper."""

    def __init__(self, http_session: aiohttp.ClientSession, base_url: str):
        self._session = http_session
        self._base_url = base_url.rstrip("/")

    async def configure_callback(self, robot_id: str, callback_url: str) -> None:
        url = f"{self._base_url}/api/updateCallBackUrl"
        params = {"robotId": robot_id}
        payload = {"callBackUrl": callback_url}
        logger.info("Configuring WorkBot callback url: %s robotId=%s callbackUrl=%s", url, robot_id, callback_url)
        async with self._session.post(url, params=params, json=payload, headers=_headers()) as resp:
            data = await resp.json(content_type=None)
        if not _is_success(data):
            raise WorkBotAPIError(f"configure callback failed: {data}")

    async def request_robot_info(self, robot_id: str) -> None:
        await self._send_task(robot_id, {"type": 100003})

    async def send_text(self, robot_id: str, search_text: str, message: str) -> None:
        await self._send_task(
            robot_id,
            {
                "type": 10001,
                "searchText": search_text,
                "message": _truncate_utf8(message, MAX_TEXT_MESSAGE_BYTES),
            },
        )

    async def send_group_at(self, robot_id: str, search_text: str, at_list: list[str], message: str) -> None:
        task = {
            "type": 50009,
            "searchText": search_text,
            "message": _truncate_utf8(message, MAX_TEXT_MESSAGE_BYTES),
        }
        if at_list:
            task["atList"] = at_list
        await self._send_task(robot_id, task)

    async def _send_task(self, robot_id: str, task: dict) -> None:
        if not robot_id:
            raise WorkBotAPIError("robot_id is required")
        url = f"{self._base_url}/api/sendTask"
        params = {"robotId": robot_id}
        payload = {"taskList": [task]}
        async with self._session.post(url, params=params, json=payload, headers=_headers()) as resp:
            data = await resp.json(content_type=None)
        if not _is_success(data):
            raise WorkBotAPIError(f"send task failed: {data}")


class WorkBotBridge:
    """WorkBot callback <-> chat backend bridge."""

    def __init__(
        self,
        api: WorkBotClient,
        chat_client: ChatClient,
        sessions: SessionManager,
        webhook_host: str = "0.0.0.0",
        webhook_port: int = 8090,
        webhook_path: str = "/workbot/callback",
        robot_ids: str = "",
        callback_urls: str = "",
        bot_nicknames: str = "",
        message_store: Optional[WorkBotMessageStore] = None,
        query_api: Optional[WorkBotQueryApi] = None,
    ):
        self._api = api
        self._chat_client = chat_client
        self._sessions = sessions
        self._webhook_host = webhook_host
        self._webhook_port = webhook_port
        self._webhook_path = webhook_path.rstrip("/") or "/workbot/callback"
        self._message_store = message_store
        self._query_api = query_api
        self._bot_ids = _parse_bot_ids(robot_ids)
        self._callback_urls = _parse_robot_value_map(callback_urls, self._bot_ids)
        nickname_values = _parse_robot_value_map(bot_nicknames, self._bot_ids)
        self._configured_bot_nicknames = {
            robot_id: _split_bot_nicknames(nickname_values.get(robot_id, ""))
            for robot_id in self._bot_ids
        }
        self._bot_nicknames = {
            robot_id: list(names)
            for robot_id, names in self._configured_bot_nicknames.items()
        }
        self._bot_nickname_refresh_interval = max(
            60,
            _env_int("WORKBOT_BOT_NICKNAME_REFRESH_INTERVAL", DEFAULT_BOT_NICKNAME_REFRESH_INTERVAL),
        )
        self._running = False
        self._stop_event = asyncio.Event()
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._tasks: set[asyncio.Task] = set()
        self._message_queue: asyncio.Queue[WorkBotQueuedMessage] = asyncio.Queue(
            maxsize=max(1, _env_int("WORKBOT_MESSAGE_QUEUE_SIZE", DEFAULT_MESSAGE_QUEUE_SIZE))
        )
        self._message_workers_count = max(1, _env_int("WORKBOT_MESSAGE_WORKERS", DEFAULT_MESSAGE_WORKERS))
        self._message_recover_limit = max(1, _env_int("WORKBOT_MESSAGE_RECOVER_LIMIT", DEFAULT_MESSAGE_RECOVER_LIMIT))
        self._message_drain_timeout = max(0, _env_int("WORKBOT_MESSAGE_DRAIN_TIMEOUT", DEFAULT_MESSAGE_DRAIN_TIMEOUT))
        self._message_workers: set[asyncio.Task] = set()
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._health_check_enabled = _env_bool("WORKBOT_HEALTH_CHECK_ENABLED", True)
        self._health_check_interval = max(
            5,
            _env_int("WORKBOT_HEALTH_CHECK_INTERVAL", DEFAULT_HEALTH_CHECK_INTERVAL),
        )
        self._health_check_timeout = max(
            1,
            _env_int("WORKBOT_HEALTH_CHECK_TIMEOUT", DEFAULT_HEALTH_CHECK_TIMEOUT),
        )
        self._health_check_failures = max(
            1,
            _env_int("WORKBOT_HEALTH_CHECK_FAILURES", DEFAULT_HEALTH_CHECK_FAILURES),
        )
        self._health_check_url = os.environ.get("WORKBOT_HEALTH_CHECK_URL", "").strip()
        self._health_check_failure_count = 0
        self._periodic_tasks = PeriodicTaskManager("WorkBot")
        #定时刷新机器人昵称
        #self._periodic_tasks.add(
        #    "bot_nickname_refresh",
        #    self._bot_nickname_refresh_interval,
        #    self._load_bot_nickname,
        #    enabled=any(not names for names in self._configured_bot_nicknames.values()),
        #)
        self._periodic_tasks.add(
            "callback_health",
            self._health_check_interval,
            self._check_callback_health_once,
            enabled=self._health_check_enabled,
        )

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get(self._webhook_path, self._handle_health)
        app.router.add_get(f"{self._webhook_path}/{{botid}}", self._handle_health)
        app.router.add_post(self._webhook_path, self._handle_callback)
        app.router.add_post(f"{self._webhook_path}/{{botid}}", self._handle_callback)
        if self._query_api:
            self._query_api.add_routes(app)

    async def run_forever(self) -> None:
        self._running = True
        self._stop_event.clear()
        if self._message_store:
            await self._message_store.init()
        self._start_message_workers()
        await self._load_unprocessed_messages()
        await self._load_bot_nickname()
        await self._configure_callbacks()
        self._periodic_tasks.start()
        await self._stop_event.wait()

    async def _configure_callbacks(self) -> None:
        for robot_id in self._bot_ids:
            callback_url = self._callback_urls.get(robot_id, "")
            if not callback_url:
                continue
            try:
                await self._api.configure_callback(robot_id, _callback_url_for_robot(callback_url, robot_id))
                logger.info("WorkBot callback url configured: robotId=%s", robot_id)
            except Exception as e:
                logger.warning("WorkBot callback url configure failed, service keeps running: robotId=%s error=%s", robot_id, e)
    def _start_message_workers(self) -> None:
        if self._message_workers:
            return
        for index in range(self._message_workers_count):
            task = asyncio.create_task(self._message_worker(index + 1))
            self._message_workers.add(task)
            task.add_done_callback(self._message_workers.discard)
        logger.info("WorkBot message workers started: workers=%s queue_size=%s", self._message_workers_count, self._message_queue.maxsize)

    async def _stop_message_workers(self) -> None:
        if self._message_drain_timeout and not self._message_queue.empty():
            try:
                await asyncio.wait_for(self._message_queue.join(), timeout=self._message_drain_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "WorkBot message queue drain timed out: timeout=%ss remaining=%s",
                    self._message_drain_timeout,
                    self._message_queue.qsize(),
                )
        for task in list(self._message_workers):
            task.cancel()
        if self._message_workers:
            await asyncio.gather(*self._message_workers, return_exceptions=True)
        self._message_workers.clear()

    async def _load_unprocessed_messages(self) -> None:
        if not self._message_store:
            return
        messages = await self._message_store.load_unprocessed_messages(self._message_recover_limit)
        for message in messages:
            await self._enqueue_message(message)
        if messages:
            logger.info("WorkBot recovered unprocessed messages: count=%s", len(messages))

    async def _enqueue_message(self, message: WorkBotQueuedMessage) -> None:
        await self._message_queue.put(message)
        logger.debug(
            "WorkBot message queued: id=%s robotId=%s searchText=%s queue=%s",
            message.id,
            message.robot_id,
            message.search_text,
            self._message_queue.qsize(),
        )

    async def _message_worker(self, worker_id: int) -> None:
        logger.info("WorkBot message worker started: worker=%s", worker_id)
        try:
            while True:
                message = await self._message_queue.get()
                try:
                    skip_reason = self._get_skip_reason(message.robot_id, message.search_text, message.item)
                    if skip_reason:
                        logger.info(
                            "Skip WorkBot queued message: id=%s reason=%s searchText=%s",
                            message.id,
                            skip_reason,
                            message.search_text,
                        )
                        if self._message_store:
                            await self._message_store.mark_skipped(message.id, skip_reason)
                        continue
                    if self._message_store:
                        await self._message_store.mark_processing(message.id)
                    logger.info("WorkBot message handling: id=%s worker=%s searchText=%s", message.id, worker_id, message.search_text)
                    await self._handle_log_item(message.robot_id, message.search_text, message.item)
                    if self._message_store:
                        await self._message_store.mark_processed(message.id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if self._message_store:
                        await self._message_store.mark_failed(message.id, e)
                    logger.error("WorkBot queued message handling failed: id=%s worker=%s error=%s", message.id, worker_id, e, exc_info=True)
                finally:
                    self._message_queue.task_done()
        except asyncio.CancelledError:
            logger.info("WorkBot message worker stopped: worker=%s", worker_id)
            raise

    async def _load_bot_nickname(self) -> None:
        for robot_id in self._bot_ids:
            if self._configured_bot_nicknames.get(robot_id):
                logger.info("WorkBot bot nicknames configured: robotId=%s nicknames=%s", robot_id, self._configured_bot_nicknames[robot_id])
                continue
            try:
                await self._api.request_robot_info(robot_id)
                logger.info("WorkBot robot info request sent; waiting for async callback: robotId=%s", robot_id)
            except Exception as e:
                logger.warning("WorkBot request robot info failed; group mentions may be ignored: robotId=%s error=%s", robot_id, e)

    async def start(self) -> None:
        self._running = True
        await self._start_webhook_server()
        await self.run_forever()

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        await self._periodic_tasks.stop()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._stop_message_workers()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def _start_webhook_server(self) -> None:
        self._app = web.Application()
        self.add_routes(self._app)
        self._runner = web.AppRunner(self._app, access_log_class=DebugAccessLogger)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await self._site.start()
        logger.info(
            "WorkBot webhook started at http://%s:%s%s",
            self._webhook_host,
            self._webhook_port,
            self._webhook_path,
        )

    async def _restart_webhook_server(self) -> None:
        if not self._runner:
            logger.error("WorkBot callback health check failed, but this bridge does not own the webhook server")
            self._restart_process()
            return
        logger.warning("Restarting WorkBot webhook server after failed health checks")
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        await self._start_webhook_server()

    async def _check_callback_health_once(self) -> None:
        url = self._get_health_check_url()
        ok = await self._check_callback_health(url)
        if ok:
            if self._health_check_failure_count:
                logger.info(
                    "WorkBot callback health recovered after %s failed check(s)",
                    self._health_check_failure_count,
                )
            self._health_check_failure_count = 0
            if any(not self._bot_nicknames.get(robot_id) for robot_id in self._bot_ids):
                logger.info("WorkBot bot nicknames not configured for all bots, loading...")
                await self._load_bot_nickname()
            return

        self._health_check_failure_count += 1
        logger.warning(
            "WorkBot callback health check failed: %s/%s url=%s",
            self._health_check_failure_count,
            self._health_check_failures,
            url,
        )
        if self._health_check_failure_count >= self._health_check_failures:
            self._health_check_failure_count = 0
            try:
                await self._restart_webhook_server()
            except Exception as e:
                logger.error("WorkBot webhook restart failed: %s", e, exc_info=True)
                self._restart_process()

    async def _check_callback_health(self, url: str) -> bool:
        timeout = aiohttp.ClientTimeout(total=self._health_check_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=_headers()) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json(content_type=None)
                    return _is_success(data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("WorkBot callback health request failed: %s", e)
            return False

    def _get_health_check_url(self) -> str:
        if self._health_check_url:
            return self._health_check_url
        host = self._webhook_host
        if host in ("", "0.0.0.0", "::"):
            host = "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self._webhook_port}{self._webhook_path}"

    def _restart_process(self) -> None:
        logger.critical("WorkBot callback service is unhealthy; exiting process for supervisor restart")
        os._exit(1)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return _callback_success()

    async def _handle_callback(self, request: web.Request) -> web.Response:
        
        try:
            payload = await request.json()
        except Exception:
            logger.warning("WorkBot callback received invalid json")
            return _callback_success()
        logger.info("WorkBot callback received: payload=%s", payload)
        robot_id = self._resolve_request_robot_id(request, payload)
        if not robot_id:
            logger.warning("WorkBot callback missing botid/robotId: payload=%s", payload)
            return _callback_success()
        if not self._is_known_bot(robot_id):
            logger.warning("WorkBot callback ignored for unknown robotId=%s", robot_id)
            return _callback_success()
        payload["robotId"] = robot_id

        # Persist raw callback payload first
        if self._message_store and self._message_store.enabled:
            mode = payload.get("mode", "")
            await self._message_store.save_raw_callback(robot_id, mode, payload)

        mode = payload.get("mode", "")
        if mode == "callBack":
            await self._handle_task_callback(robot_id, payload)
            return _callback_success()

        if mode in ("init", "online", "offline", "receipt"):
            logger.info("WorkBot callback ignored: robotId=%s mode=%s", robot_id, mode)
            return _callback_success()

        if mode != "logs":
            logger.info("WorkBot callback ignored: robotId=%s unknown mode=%s", robot_id, mode)
            return _callback_success()

        task = asyncio.create_task(self._handle_logs(robot_id, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return _callback_success()

    def _resolve_request_robot_id(self, request: web.Request, payload: dict) -> str:
        robot_id = str(request.match_info.get("botid", "")).strip()
        if not robot_id:
            robot_id = str(request.query.get("botid", request.query.get("robotId", ""))).strip()
        if not robot_id:
            robot_id = str(payload.get("botid", payload.get("robotId", ""))).strip()
        if not robot_id and len(self._bot_ids) == 1:
            robot_id = self._bot_ids[0]
        return robot_id

    def _is_known_bot(self, robot_id: str) -> bool:
        return bool(robot_id) and robot_id in self._bot_ids

    async def _handle_task_callback(self, robot_id: str, payload: dict) -> None:
        response = _extract_task_response(payload)
        #logger.info("WorkBot task callback received: status=%s data=%s", payload.get("status", ""), payload.get("data", {}))
        if not response:
            logger.info("WorkBot task callback ignored: robotId=%s status=%s data=%s", robot_id, payload.get("status", ""), payload.get("data", {}))
            return
        bot_nicknames = _extract_bot_nicknames(response)
        if not bot_nicknames:
            logger.warning("WorkBot robot info callback has no nickName field: robotId=%s response=%s", robot_id, response)
            return
        if bot_nicknames != self._bot_nicknames.get(robot_id, []):
            logger.info("WorkBot bot nicknames refreshed from callback: robotId=%s %s -> %s", robot_id, self._bot_nicknames.get(robot_id, []), bot_nicknames)
        self._bot_nicknames[robot_id] = bot_nicknames

    async def _handle_logs(self, robot_id: str, payload: dict) -> None:
        search_text = str(payload.get("searchText", "")).strip()
        if not search_text:
            logger.warning("WorkBot logs callback missing searchText: robotId=%s", robot_id)
            return

        for index, item in enumerate(payload.get("data", [])):
            if self._message_store and self._message_store.enabled:
                queued_message = await self._message_store.save_log_item(payload, item, index)
                if not queued_message:
                    data = item.get("data", {}) if isinstance(item.get("data", {}), dict) else {}
                    logger.info(
                        "WorkBot message already processed or queued, skip: robotId=%s groupname=%s groupnickname=%s raw=%s",
                        robot_id,
                        search_text,
                        str(data.get("groupNickname", "")).strip(),
                        item,
                    )
                    continue
            else:
                queued_message = WorkBotQueuedMessage(id=0, robot_id=robot_id, search_text=search_text, item=item)
            skip_reason = self._get_skip_reason(robot_id, search_text, item)
            if skip_reason:
                logger.info(
                    "Skip WorkBot message before queue: id=%s robotId=%s reason=%s searchText=%s raw=%s",
                    queued_message.id,
                    robot_id,
                    skip_reason,
                    search_text,
                    item,
                )
                if self._message_store and queued_message.id:
                    await self._message_store.mark_skipped(queued_message.id, skip_reason)
                continue
            await self._enqueue_message(queued_message)

    def _get_skip_reason(self, robot_id: str, search_text: str, item: dict) -> str:
        role = item.get("role", "")
        msg_type = item.get("type", "")
        data = item.get("data", {}) if isinstance(item.get("data", {}), dict) else {}
        if role != "user":
            return "not_user_message"
        user_message = _extract_message_text(msg_type, data)
        if not user_message:
            return "empty_message"
        group_nickname = str(data.get("groupNickname", "")).strip()
        is_group = bool(group_nickname or data.get("corpsName"))
        if is_group:
            bot_nicknames = self._bot_nicknames.get(robot_id, [])
            if not bot_nicknames:
                return ""
            mentioned, _ = _extract_mentioned_message(user_message, bot_nicknames)
            if not mentioned:
                return "group_message_without_bot_mention"
        return ""

    async def _handle_log_item(self, robot_id: str, search_text: str, item: dict) -> None:
        role = item.get("role", "")
        msg_type = item.get("type", "")
        data = item.get("data", {}) if isinstance(item.get("data", {}), dict) else {}
        logger.info(
            "WorkBot log item received: robotId=%s searchText=%s role=%s type=%s data=%s raw=%s",
            robot_id,
            search_text,
            role,
            msg_type,
            data,
            item,
        )
        if role != "user":
            return

        user_message = _extract_message_text(msg_type, data)
        group_nickname = str(data.get("groupNickname", "")).strip()
        is_group = bool(group_nickname or data.get("corpsName"))
        sender = group_nickname or search_text

        if not user_message:
            return

        if is_group:
            bot_nicknames = self._bot_nicknames.get(robot_id, [])
            if not bot_nicknames:
                logger.warning("Ignore WorkBot group message because bot nicknames are unknown: robotId=%s group=%s sender=%s", robot_id, search_text, sender)
                return
            mentioned, cleaned_message = _extract_mentioned_message(user_message, bot_nicknames)
            if not mentioned:
                logger.info("Ignore WorkBot group message without bot mention %s: robotId=%s group=%s sender=%s", bot_nicknames, robot_id, search_text, sender)
                return
            user_message = cleaned_message or user_message

        conv_key = f"workbot:{robot_id}:{search_text}:{sender}"
        lock = self._conversation_locks.setdefault(conv_key, asyncio.Lock())
        async with lock:
            if user_message.strip() == "#reset":
                self._sessions.clear_conversation(conv_key)
                await self._send_reply(robot_id, search_text, group_nickname, is_group, "已开启新对话，请开始新的提问吧。")
                return

            if msg_type != "text":
                await self._send_reply(robot_id, search_text, group_nickname, is_group, user_message)
                return

            await self._send_reply(robot_id, search_text, group_nickname, is_group, "消息已收到，处理中。")
            start = time.time()
            logger.info(
                "WorkBot message received: searchText=%s sender=%s msg=%s data=%s",
                search_text,
                sender,
                user_message[:100],
                data
            )
            conv_id = self._sessions.get_conversation_id(conv_key)
            answer, new_conv_id = await self._chat_client.chat_blocking(
                user_message,
                sender,
                conv_id,
            )
            if new_conv_id != conv_id:
                self._sessions.set_conversation_id(conv_key, new_conv_id)

            elapsed_ms = (time.time() - start) * 1000
            logger.info("WorkBot message handled: searchText=%s elapsed=%.0fms", search_text, elapsed_ms)
            await self._send_long_reply(robot_id, search_text, group_nickname, is_group, answer or "没有获取到有效回复。")

    async def _send_long_reply(self, robot_id: str, search_text: str, group_nickname: str, is_group: bool, content: str) -> None:
        for chunk in _split_utf8(content, MAX_TEXT_MESSAGE_BYTES):
            await self._send_reply(robot_id, search_text, group_nickname, is_group, chunk)
            await asyncio.sleep(0.2)

    async def _send_reply(self, robot_id: str, search_text: str, group_nickname: str, is_group: bool, content: str) -> None:
        if is_group:
            at_list = [group_nickname] if group_nickname else []
            await self._api.send_group_at(robot_id, search_text, at_list, content)
        else:
            await self._api.send_text(robot_id, search_text, content)


def _extract_task_response(payload: dict) -> dict:
    if str(payload.get("status", "")).lower() not in ("", "success"):
        return {}
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return {}
    response = data.get("response", {})
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        try:
            import json

            parsed = json.loads(response)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _callback_success() -> web.Response:
    return web.json_response({"code": 200, "message": "回调接收成功"})


def _headers() -> dict:
    return {
        "User-Agent": "wecom-ragflow-bridge/WorkBot",
        "Content-Type": "application/json",
    }


def _is_success(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("success") is True:
        return True
    code = data.get("code", data.get("errcode"))
    return code in (0, "0", 200, "200", None) and not data.get("error")



def _parse_bot_ids(value: str) -> list[str]:
    ids = []
    for part in str(value or "").replace("；", ",").replace(";", ",").replace("|", ",").split(","):
        robot_id = part.strip()
        if robot_id and robot_id not in ids:
            ids.append(robot_id)
    return ids


def _parse_robot_value_map(value: str, robot_ids: list[str]) -> dict[str, str]:
    result = {}
    if not value:
        return result
    for part in str(value).replace("；", ";").split(";"):
        item = part.strip()
        if not item:
            continue
        key, sep, raw_value = item.partition("=")
        if not sep:
            key, sep, raw_value = item.partition(":")
        if sep and key.strip() in robot_ids:
            result[key.strip()] = raw_value.strip()
    return result


def _callback_url_for_robot(callback_url: str, robot_id: str) -> str:
    if "{botid}" in callback_url:
        return callback_url.replace("{botid}", robot_id)
    if "{robotId}" in callback_url:
        return callback_url.replace("{robotId}", robot_id)
    parts = urlsplit(callback_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["botid"] = robot_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

def _split_bot_nicknames(value: str) -> list[str]:
    if not value:
        return []
    names = []
    for part in value.replace("；", ",").replace(";", ",").replace("|", ",").split(","):
        name = part.strip().lstrip("@").strip()
        if name and name not in names:
            names.append(name)
    return names


def _extract_bot_nicknames(info: dict) -> list[str]:
    value = info.get("nickName")
    return _split_bot_nicknames(str(value)) if value else []


def _extract_mentioned_message(message: str, bot_nicknames: list[str]) -> tuple[bool, str]:
    text = message.strip()
    for raw_name in bot_nicknames:
        nickname = raw_name.strip().lstrip("@").strip()
        if not nickname:
            continue
        mention_tokens = (f"@{nickname}", f"＠{nickname}")
        for token in mention_tokens:
            if token in text:
                cleaned = text.replace(token, "", 1).strip()
                cleaned = cleaned.lstrip(":：,， ").strip()
                return True, cleaned
    return False, text

def _extract_message_text(msg_type: str, data: dict) -> str:
    message = str(data.get("message", "")).strip()
    extra = str(data.get("extra", "")).strip()
    if msg_type == "text":
        return message
    if msg_type == "voice" and message:
        return message
    if msg_type == "map":
        return f"暂不支持直接处理地图消息：{message} {extra}".strip()
    if msg_type == "file":
        return f"暂不支持直接处理文件消息：{message} {extra}".strip()
    if msg_type == "image":
        return "暂不支持直接识别 WorkBot 图片，请发送文字消息。"
    if msg_type == "video":
        return "暂不支持直接处理 WorkBot 视频，请发送文字消息。"
    if msg_type == "url":
        return f"暂不支持直接读取链接内容：{message}".strip()
    if msg_type:
        return f"暂不支持的 WorkBot 消息类型：{msg_type}"
    return message


def _split_utf8(content: str, max_bytes: int) -> list[str]:
    if not content:
        return [""]

    chunks = []
    current = []
    current_size = 0
    for char in content:
        char_size = len(char.encode("utf-8"))
        if current and current_size + char_size > max_bytes:
            chunks.append("".join(current))
            current = []
            current_size = 0
        if char_size > max_bytes:
            continue
        current.append(char)
        current_size += char_size

    if current:
        chunks.append("".join(current))
    return chunks or [""]


def _truncate_utf8(content: str, max_bytes: int) -> str:
    return _split_utf8(content, max_bytes)[0]
