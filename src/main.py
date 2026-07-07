"""
?<-> RAGFLOW 

?WebSocket ?RAGFLOW ?
?
"""

import asyncio
import json
import logging
import signal
import sys
import platform
import time
import uuid
from typing import Optional

import aiohttp
import websockets

from config import Config
from protocol import WeComCmd, WeComEvent, MessageBuilder
from scheduler import PeriodicTaskManager
from session import SessionManager
from service_factory import ServiceBundle, ServiceFactory
from webhook_server import SharedWebhookServer
from animation import animate_waiting
from logging_config import configure_logging
from version import APP_VERSION

# ============ ?============
_LOG_LEVEL, _LOG_FILE = configure_logging()
logger = logging.getLogger("wecom-RAGFLOW-bridge")
logging.getLogger("aiohttp.access").setLevel(_LOG_LEVEL)
logger.info(
    "?%s?%s",
    logging.getLevelName(_LOG_LEVEL).lower(),
    _LOG_FILE,
)


class WeComRAGFLOWBridge:
    """WeCom websocket and webhook bridge."""

    def __init__(self, config: Config):
        self._config = config
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._services: Optional[ServiceBundle] = None
        self._sessions = SessionManager()
        self._chat_client = None
        self._wecom_api = None
        self._message_extractor = None
        self._kf_bridge = None
        self._workbot_bridge = None
        self._archive_service = None
        self._shared_webhook_servers: list[SharedWebhookServer] = []
        self._ws_send_locks: dict[str, asyncio.Lock] = {}
        self._ws_locks_lock = asyncio.Lock()

    async def start(self):
        """Start bridge services."""
        self._running = True
        self._http_session = aiohttp.ClientSession()
        self._services = ServiceFactory(self._config, self._sessions).create(self._http_session)
        self._chat_client = self._services.chat_client
        self._wecom_api = self._services.wecom_api
        self._message_extractor = self._services.message_extractor
        self._kf_bridge = self._services.kf_bridge
        self._workbot_bridge = self._services.workbot_bridge
        self._archive_service = self._services.archive_service
        tasks = []
        shared_providers = await self._start_shared_webhook_servers()
        if self._archive_service:
            tasks.append(asyncio.create_task(self._archive_service.run_forever()))
        if self._config.wecom_bot_enabled:
            tasks.append(asyncio.create_task(self._run_wecom_bot()))
        if self._kf_bridge:
            runner = self._kf_bridge.run_forever if self._kf_bridge in shared_providers else self._kf_bridge.start
            tasks.append(asyncio.create_task(runner()))
        if self._workbot_bridge:
            runner = self._workbot_bridge.run_forever if self._workbot_bridge in shared_providers else self._workbot_bridge.start
            tasks.append(asyncio.create_task(runner()))

        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for server in self._shared_webhook_servers:
                await server.stop()
            self._shared_webhook_servers.clear()
            if self._http_session:
                await self._http_session.close()

    async def _start_shared_webhook_servers(self) -> set[object]:
        groups: dict[tuple[str, int], list[tuple[str, object]]] = {}
        for host, port, path, provider in self._webhook_bindings():
            groups.setdefault((host, port), []).append((path, provider))

        shared_providers: set[object] = set()
        for (host, port), entries in groups.items():
            if len(entries) <= 1:
                continue
            paths = [path for path, _ in entries]
            if len(paths) != len(set(paths)):
                raise ValueError(f"Webhook paths on {host}:{port} must be unique: {paths}")
            providers = [provider for _, provider in entries]
            for provider in providers:
                if hasattr(provider, "use_external_webhook_server"):
                    provider.use_external_webhook_server()
            server = SharedWebhookServer(host, port, providers)
            await server.start()
            self._shared_webhook_servers.append(server)
            shared_providers.update(providers)
            logger.info("Shared webhook started: http://%s:%s paths=%s", host, port, paths)
        return shared_providers

    def _webhook_bindings(self) -> list[tuple[str, int, str, object]]:
        bindings = []
        if self._kf_bridge:
            bindings.append((
                self._config.wecom_kf_webhook_host,
                self._config.wecom_kf_webhook_port,
                self._config.wecom_kf_webhook_path,
                self._kf_bridge,
            ))
        if self._workbot_bridge:
            bindings.append((
                self._config.workbot_webhook_host,
                self._config.workbot_webhook_port,
                self._config.workbot_webhook_path,
                self._workbot_bridge,
            ))
        if self._archive_service:
            bindings.append((
                self._archive_service.webhook_host,
                self._archive_service.webhook_port,
                self._archive_service.webhook_path,
                self._archive_service,
            ))
        return bindings


    async def _run_wecom_bot(self):
        """Run WeCom websocket channel."""
        while self._running:
            try:
                await self._connect_and_subscribe()
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket disconnected: {e}; reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Connection error: {e}; reconnecting in 10 seconds", exc_info=True)
                await asyncio.sleep(10)

    async def stop(self):
        """Stop bridge services."""
        logger.info("Stopping services...")
        self._running = False
        if self._kf_bridge:
            await self._kf_bridge.stop()
        if self._workbot_bridge:
            await self._workbot_bridge.stop()
        if self._archive_service:
            await self._archive_service.stop()
        if self._ws:
            await self._ws.close()
        for server in self._shared_webhook_servers:
            await server.stop()
        self._shared_webhook_servers.clear()

    async def safe_ws_send(self, msg: dict):
        """Send a websocket message with per-request locking."""
        req_id = msg.get("headers", {}).get("req_id", "default")
        async with self._ws_locks_lock:
            if req_id not in self._ws_send_locks:
                self._ws_send_locks[req_id] = asyncio.Lock()
            lock = self._ws_send_locks[req_id]

        async with lock:
            await self._ws.send(json.dumps(msg))
            await asyncio.sleep(0.5)  # ?

    async def _connect_and_subscribe(self):
        """Connect and subscribe."""
        logger.info(f"?WebSocket: {self._config.wecom_ws_url}")
        async with websockets.connect(
            self._config.wecom_ws_url,
            ping_interval=None,
            close_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            logger.info("WebSocket ?..")

            if not await self._subscribe():
                logger.error("?0...")
                await asyncio.sleep(10)
                return

            logger.info("Subscribe succeeded; receiving messages")

            periodic_tasks = PeriodicTaskManager("WeCom websocket")
            periodic_tasks.add("heartbeat", self._config.heartbeat_interval, self._send_heartbeat_once)
            periodic_tasks.start()
            try:
                await self._message_loop()
            finally:
                await periodic_tasks.stop()

    async def _subscribe(self) -> bool:
        """Send subscribe auth request."""
        msg = MessageBuilder.build_subscribe(self._config.wecom_bot_id, self._config.wecom_secret)
        await self.safe_ws_send(msg)
        logger.debug("Subscribe request sent")

        try:
            response = await asyncio.wait_for(self._ws.recv(), timeout=15)
            data = json.loads(response)
            errcode = data.get("errcode", -1)
            errmsg = data.get("errmsg", "unknown")

            if errcode == 0:
                return True
            logger.error(f": errcode={errcode}, errmsg={errmsg}")
            return False
        except asyncio.TimeoutError:
            logger.error("Subscribe response timed out")
            return False

    async def _send_heartbeat_once(self) -> None:
        """Send one websocket heartbeat ping."""
        try:
            msg = MessageBuilder.build_ping()
            await self.safe_ws_send(msg)
            logger.debug("Sent websocket heartbeat ping")
        except Exception as e:
            logger.warning(f"Websocket heartbeat failed: {e}")
            if self._ws:
                await self._ws.close()
            raise

    async def _message_loop(self):
        """Receive websocket messages."""
        async for raw_message in self._ws:
            try:
                data = json.loads(raw_message)
                cmd = data.get("cmd", "")
                if cmd:
                    logger.info(f" cmd={cmd}")
                    logger.debug(f": {json.dumps(data, ensure_ascii=False)[:500]}")

                if cmd == WeComCmd.MSG_CALLBACK:
                    asyncio.create_task(self._handle_message(data))
                elif cmd == WeComCmd.EVENT_CALLBACK:
                    asyncio.create_task(self._handle_event(data))
                elif cmd == WeComCmd.PONG:
                    logger.debug("?pong")
                #else:
                #    logger.debug(f"? {cmd},: {json.dumps(data, ensure_ascii=False)}")

            except json.JSONDecodeError:
                logger.warning(f": {raw_message[:200]}")
            except Exception as e:
                logger.error(f"? {e}", exc_info=True)

    async def _handle_event(self, data: dict):
        """Handle event callback."""
        body = data.get("body", {})
        req_id = data.get("headers", {}).get("req_id", "")
        event_type = body.get("event_type", "")

        if event_type == WeComEvent.ENTER_CHAT:
            logger.info(f"? chatid={body.get('chatid')}")
            msg = MessageBuilder.build_welcome(req_id, "")
            await self.safe_ws_send(msg)

        elif event_type == WeComEvent.DISCONNECTED:
            logger.warning("Disconnected event received; reconnecting")

        elif event_type == WeComEvent.FEEDBACK:
            logger.info(f"? {body.get('feedback', {})}")

    async def _handle_message(self, data: dict):
        """Handle user message."""
        body = data.get("body", {})
        req_id = data.get("headers", {}).get("req_id", "")
        chat_id = body.get("chatid", "")
        msg_type = body.get("msgtype", "")
        user_id = body.get("from", {}).get("userid", "unknown")

        start_time = time.time()
        status_code, user_message, image_data = await self._message_extractor.extract(body, msg_type)
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"_extract_message elapsed: {elapsed:.2f}ms")
        if status_code != 0:
            logger.warning(f"Message extraction failed: msg_type={msg_type}")
            msg= MessageBuilder.build_stream_message(
               req_id, uuid.uuid4().hex[:16],
                 f"Message parse failed, please contact support: {user_message}")
            await self.safe_ws_send(msg)
            return

        if not user_message and not image_data:
            logger.warning(f"Empty message content: msg_type={msg_type}")
            return

        logger.info(f"User message: user={user_id}, chat={chat_id}, msg={user_message[:100] if user_message else '[image]'}, has_image={image_data is not None}")
        if msg_type in ["mixed", "image"]:
           msg= MessageBuilder.build_stream_message(
               req_id, uuid.uuid4().hex[:16],
                 f"Image parsed question: {user_message}")
           await self.safe_ws_send(msg)

        if user_message.strip() == "#reset":
            conv_key = f"{chat_id}:{user_id}"
            old_conv = self._sessions.clear_conversation(conv_key)
            logger.info(f"User requested reset: chat={conv_key}, old_conversation={old_conv}")
            msg = MessageBuilder.build_stream_message(
                req_id, uuid.uuid4().hex[:16],
                "Conversation reset. Please start a new question.",
                finish=True
            )
            await self.safe_ws_send(msg)
            return

        total_start = time.time()
        try:
            if self._config.stream_mode:
                await self._reply_stream(req_id, chat_id, user_id, user_message, image_data)
            else:
                await self._reply_blocking(req_id, chat_id, user_id, user_message, image_data)

            total_elapsed = (time.time() - total_start) * 1000
            logger.info(f"Message handled: {total_elapsed:.2f}ms")
            total_msg = MessageBuilder.build_stream_message(
                req_id, uuid.uuid4().hex[:16],
                f"\n\nElapsed: {total_elapsed:.0f}ms",
                finish=True
            )
            await self.safe_ws_send(total_msg)
        except Exception as e:
            logger.error(f"Reply message failed: {e}", exc_info=True)
            msg = MessageBuilder.build_error(req_id)
            await self.safe_ws_send(msg)

    async def _reply_stream(self, req_id: str, chat_id: str, user_id: str, message: str, image_data: Optional[bytes] = None):
        """Send streaming reply."""
        stream_id = uuid.uuid4().hex[:16]
        accumulated_text = ""
        chunk_count = 0

        # 
        animation_task = asyncio.create_task(animate_waiting(self._ws, req_id, stream_id))
        #msg = MessageBuilder.build_waiting(req_id, stream_id, "?..")
        #await self._ws.send(json.dumps(msg))

        try:
            conv_key = f"{chat_id}:{user_id}"
            conv_id = self._sessions.get_conversation_id(conv_key)
            async for event_data in self._chat_client.chat_stream(message, image_data, conv_id, user_id):
                if event_data.event == "done":
                    break

                if event_data.event == "message":
                    content = event_data.content
                    accumulated_text += content
                    chunk_count += 1
                    if chunk_count == 1 or chunk_count % 5 == 0 :
                        if not animation_task.cancelled():
                            animation_task.cancel()
                        msg = MessageBuilder.build_stream_message(req_id, stream_id, accumulated_text)
                        await self.safe_ws_send(msg)
                        logger.info(f"? req_id={req_id}, chunk_count={chunk_count}, stream_id={stream_id}, ={len(accumulated_text)}")

                elif event_data.event == "message_end":
                    new_conv_id = event_data.conversation_id
                    if new_conv_id != conv_id:
                        self._sessions.set_conversation_id( conv_key, new_conv_id)
                        logger.debug(f"? {conv_key} -> {new_conv_id}")

                elif event_data.event == "error":
                    error_msg = event_data.error or ""
                    logger.error(f": {error_msg}")
                    accumulated_text += f"\n\n[: {error_msg}]"

        finally:
            
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        if not accumulated_text:
            accumulated_text = "No streaming result returned"
            
        if logger.level <= logging.DEBUG:
            accumulated_text += f"\nReply chars: {len(accumulated_text)}"
        msg = MessageBuilder.build_stream_message(req_id, stream_id, accumulated_text, finish=True)
        await self.safe_ws_send(msg)
        logger.info(f"? req_id={req_id}, stream_id={stream_id}, ={len(accumulated_text)}")

    async def _reply_blocking(self, req_id: str, chat_id: str, user_id: str, message: str, image_data: Optional[bytes] = None):
        """Send blocking reply."""
        stream_id = uuid.uuid4().hex[:16]
        animation_task = asyncio.create_task(animate_waiting(self._ws, req_id, stream_id))
        conv_key = f"{chat_id}:{user_id}"
        try:
            conv_id = self._sessions.get_conversation_id(conv_key)
            answer, new_conv_id = await self._chat_client.chat_blocking(message, user_id, conv_id, image_data)

            if new_conv_id !=  conv_id:
                logger.info(f"Update conversation mapping {conv_key}: {conv_id} -> {new_conv_id}")
                self._sessions.set_conversation_id(conv_key, new_conv_id)
        finally:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        msg = MessageBuilder.build_stream_message(req_id, stream_id, answer, finish=True)
        await self.safe_ws_send(msg)
        logger.info(f"? ={len(answer)}")


async def main():
    config = Config()

    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"?{e}")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("WeCom bot <-> chat backend bridge v%s", APP_VERSION)
    logger.info(f"  BotID:     {config.wecom_bot_id[:8]}...")
    logger.info(f"  Chat backend:  {config.chat_provider}")
    logger.info(f"  Stream mode:  {'on' if config.stream_mode else 'off'}")
    logger.info(f"  Heartbeat:  {config.heartbeat_interval}s")
    logger.info("=" * 50)

    bridge = WeComRAGFLOWBridge(config)

    loop = asyncio.get_event_loop()
    if platform.system() != "Windows":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))

    await bridge.start()


if __name__ == "__main__":
    asyncio.run(main())

