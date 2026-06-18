"""
企业微信智能机器人长连接 <-> RAGFLOW 桥接服务

通过 WebSocket 长连接方式接收企业微信消息，转发到 RAGFLOW 应用获取回复，
再通过长连接回复给用户。支持流式消息。
"""

import asyncio
import json
import logging
import os
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
from session import SessionManager
from chat_client import ChatClient, create_chat_client
from wecom_api import WeComAPIClient
from mineru_client import MinerUClient
from media_service import WeComImageService
from message_extractor import MessageExtractor
from wechat_kf import WeChatKFBridge, WeChatKFClient
from animation import animate_waiting

# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("wecom-RAGFLOW-bridge")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())  # 日志级别从环境变量读取
logger.info("日志级别设置为: %s", logging.getLevelName(logger.level).lower())
class WeComRAGFLOWBridge:
    """企业微信长连接 <-> RAGFLOW 桥接器"""

    def __init__(self, config: Config):
        self._config = config
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._sessions = SessionManager()
        self._chat_client: Optional[ChatClient] = None
        self._wecom_api: Optional[WeComAPIClient] = None
        self._mineru: Optional[MinerUClient] = None
        self._message_extractor: Optional[MessageExtractor] = None
        self._kf_bridge: Optional[WeChatKFBridge] = None
        self._ws_send_locks: dict[str, asyncio.Lock] = {}
        self._ws_locks_lock = asyncio.Lock()

    async def start(self):
        """启动桥接服务"""
        self._running = True
        self._http_session = aiohttp.ClientSession()
        self._chat_client = create_chat_client(self._config, self._http_session)
        self._wecom_api = WeComAPIClient(
            self._http_session,
            self._config.wecom_corp_id,
            self._config.wecom_bot_id,
            self._config.wecom_secret
        )
        if self._config.mineru_api_key:
            self._mineru = MinerUClient(
                self._http_session,
                self._config.mineru_api_base,
                self._config.mineru_api_key,
                self._config.mineru_ocr_method
            )
        else:
            self._mineru = None
            logger.warning("未配置 MINERU_API_KEY，图片 OCR 识别将不可用")
        self._message_extractor = MessageExtractor(
            self._mineru,
            WeComImageService(self._http_session, self._config.media_dir),
        )
        if self._config.wecom_kf_enabled:
            self._kf_bridge = WeChatKFBridge(
                WeChatKFClient(
                    self._http_session,
                    self._config.wecom_corp_id,
                    self._config.wecom_kf_secret,
                ),
                self._chat_client,
                self._sessions,
                self._config.wecom_kf_open_kfid,
                self._config.wecom_kf_callback_token,
                self._config.wecom_kf_encoding_aes_key,
                self._config.wecom_corp_id,
                self._config.wecom_kf_webhook_host,
                self._config.wecom_kf_webhook_port,
                self._config.wecom_kf_webhook_path,
            )

        tasks = []
        if self._config.wecom_bot_enabled:
            tasks.append(asyncio.create_task(self._run_wecom_bot()))
        if self._kf_bridge:
            tasks.append(asyncio.create_task(self._kf_bridge.start()))

        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._http_session:
                await self._http_session.close()

    async def _run_wecom_bot(self):
        """运行企业微信智能机器人长连接通道。"""
        while self._running:
            try:
                await self._connect_and_subscribe()
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket 连接断开: {e}，5秒后重连...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"连接异常: {e}，10秒后重连...", exc_info=True)
                await asyncio.sleep(10)

    async def stop(self):
        """停止服务"""
        logger.info("正在停止服务...")
        self._running = False
        if self._kf_bridge:
            await self._kf_bridge.stop()
        if self._ws:
            await self._ws.close()

    async def safe_ws_send(self, msg: dict):
        """基于 req_id 的线程安全 WebSocket 发送方法，按请求隔离锁"""
        req_id = msg.get("headers", {}).get("req_id", "default")
        async with self._ws_locks_lock:
            if req_id not in self._ws_send_locks:
                self._ws_send_locks[req_id] = asyncio.Lock()
            lock = self._ws_send_locks[req_id]

        async with lock:
            await self._ws.send(json.dumps(msg))
            await asyncio.sleep(0.5)  # 小延迟，避免同一请求的消息过快发送导致顺序问题

    async def _connect_and_subscribe(self):
        """连接并订阅"""
        logger.info(f"正在连接企业微信 WebSocket: {self._config.wecom_ws_url}")
        async with websockets.connect(
            self._config.wecom_ws_url,
            ping_interval=None,
            close_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            logger.info("WebSocket 连接成功，开始订阅认证...")

            if not await self._subscribe():
                logger.error("订阅认证失败，10秒后重试...")
                await asyncio.sleep(10)
                return

            logger.info("✅ 订阅认证成功，开始接收消息")

            heartbeat_task = asyncio.create_task(self._heartbeat())
            try:
                await self._message_loop()
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _subscribe(self) -> bool:
        """发送订阅认证请求"""
        msg = MessageBuilder.build_subscribe(self._config.wecom_bot_id, self._config.wecom_secret)
        await self.safe_ws_send(msg)
        logger.debug("已发送订阅请求")

        try:
            response = await asyncio.wait_for(self._ws.recv(), timeout=15)
            data = json.loads(response)
            errcode = data.get("errcode", -1)
            errmsg = data.get("errmsg", "unknown")

            if errcode == 0:
                return True
            logger.error(f"订阅失败: errcode={errcode}, errmsg={errmsg}")
            return False
        except asyncio.TimeoutError:
            logger.error("订阅响应超时")
            return False

    async def _heartbeat(self):
        """心跳保活"""
        while True:
            try:
                await asyncio.sleep(self._config.heartbeat_interval)
                msg = MessageBuilder.build_ping()
                await self.safe_ws_send(msg)
                logger.debug("已发送心跳 ping")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"心跳发送失败: {e}")
                break

    async def _message_loop(self):
        """消息接收循环"""
        async for raw_message in self._ws:
            try:
                data = json.loads(raw_message)
                cmd = data.get("cmd", "")
                if cmd:
                    logger.info(f" cmd={cmd}")
                    logger.debug(f"消息详情: {json.dumps(data, ensure_ascii=False)[:500]}")

                if cmd == WeComCmd.MSG_CALLBACK:
                    asyncio.create_task(self._handle_message(data))
                elif cmd == WeComCmd.EVENT_CALLBACK:
                    asyncio.create_task(self._handle_event(data))
                elif cmd == WeComCmd.PONG:
                    logger.debug("收到心跳 pong")
                #else:
                #    logger.debug(f"未处理的命令: {cmd},消息详情: {json.dumps(data, ensure_ascii=False)}")

            except json.JSONDecodeError:
                logger.warning(f"无法解析消息: {raw_message[:200]}")
            except Exception as e:
                logger.error(f"处理消息异常: {e}", exc_info=True)

    async def _handle_event(self, data: dict):
        """处理事件回调"""
        body = data.get("body", {})
        req_id = data.get("headers", {}).get("req_id", "")
        event_type = body.get("event_type", "")

        if event_type == WeComEvent.ENTER_CHAT:
            logger.info(f"用户进入会话: chatid={body.get('chatid')}")
            msg = MessageBuilder.build_welcome(req_id, "你好！我是智能助手，有什么可以帮助你的？")
            await self.safe_ws_send(msg)

        elif event_type == WeComEvent.DISCONNECTED:
            logger.warning("收到断开连接事件，将尝试重连")

        elif event_type == WeComEvent.FEEDBACK:
            logger.info(f"用户反馈: {body.get('feedback', {})}")

    async def _handle_message(self, data: dict):
        """处理用户消息"""
        body = data.get("body", {})
        req_id = data.get("headers", {}).get("req_id", "")
        chat_id = body.get("chatid", "")
        msg_type = body.get("msgtype", "")
        user_id = body.get("from", {}).get("userid", "unknown")

        start_time = time.time()
        status_code, user_message, image_data = await self._message_extractor.extract(body, msg_type)
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"_extract_message 耗时: {elapsed:.2f}ms")
        if status_code != 0:
            logger.warning(f"消息提取失败: msg_type={msg_type}")
            msg= MessageBuilder.build_stream_message(
               req_id, uuid.uuid4().hex[:16],
                 f"消息解析失败,请联系我们：{user_message}")
            await self.safe_ws_send(msg)
            return

        if not user_message and not image_data:
            logger.warning(f"消息内容为空: msg_type={msg_type}")
            return

        logger.info(f"用户消息: user={user_id}, chat={chat_id}, msg={user_message[:100] if user_message else '[图片]'}, 含图片={image_data is not None}")
        if msg_type in ["mixed", "image"]:
           msg= MessageBuilder.build_stream_message(
               req_id, uuid.uuid4().hex[:16],
                 f"通过图片解析,您提问的问题是：{user_message}")
           await self.safe_ws_send(msg)

        if user_message.strip() == "#reset":
            conv_key = f"{chat_id}:{user_id}"
            old_conv = self._sessions.clear_conversation(conv_key)
            logger.info(f"用户请求新对话: chat={conv_key}, 清除旧会话={old_conv}")
            msg = MessageBuilder.build_stream_message(
                req_id, uuid.uuid4().hex[:16],
                "✅ 已开启新对话，之前的聊天记录已清除。请开始新的提问吧！",
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
            logger.info(f"消息处理完成，总耗时: {total_elapsed:.2f}ms")
            total_msg = MessageBuilder.build_stream_message(
                req_id, uuid.uuid4().hex[:16],
                f"\n\n⏱️ 本次处理耗时: {total_elapsed:.0f}ms",
                finish=True
            )
            await self.safe_ws_send(total_msg)
        except Exception as e:
            logger.error(f"回复消息失败: {e}", exc_info=True)
            msg = MessageBuilder.build_error(req_id)
            await self.safe_ws_send(msg)

    async def _reply_stream(self, req_id: str, chat_id: str, user_id: str, message: str, image_data: Optional[bytes] = None):
        """流式回复"""
        stream_id = uuid.uuid4().hex[:16]
        accumulated_text = ""
        chunk_count = 0

        # 启动等待动画
        animation_task = asyncio.create_task(animate_waiting(self._ws, req_id, stream_id))
        #msg = MessageBuilder.build_waiting(req_id, stream_id, "正在思考...")
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
                        logger.info(f"发送流式消息: req_id={req_id}, chunk_count={chunk_count}, stream_id={stream_id}, 长度={len(accumulated_text)}")

                elif event_data.event == "message_end":
                    new_conv_id = event_data.conversation_id
                    if new_conv_id != conv_id:
                        self._sessions.set_conversation_id( conv_key, new_conv_id)
                        logger.debug(f"更新会话映射: {conv_key} -> {new_conv_id}")

                elif event_data.event == "error":
                    error_msg = event_data.error or "未知错误"
                    logger.error(f"聊天后端返回错误: {error_msg}")
                    accumulated_text += f"\n\n[错误: {error_msg}]"

        finally:
            
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        if not accumulated_text:
            accumulated_text = "流式处理未返回结果"
            
        if logger.level <= logging.DEBUG:
            accumulated_text += f"\n本次回复字数：{len(accumulated_text)}"
        msg = MessageBuilder.build_stream_message(req_id, stream_id, accumulated_text, finish=True)
        await self.safe_ws_send(msg)
        logger.info(f"流式回复完成: req_id={req_id}, stream_id={stream_id}, 长度={len(accumulated_text)}")

    async def _reply_blocking(self, req_id: str, chat_id: str, user_id: str, message: str, image_data: Optional[bytes] = None):
        """阻塞式回复"""
        stream_id = uuid.uuid4().hex[:16]
        animation_task = asyncio.create_task(animate_waiting(self._ws, req_id, stream_id))
        conv_key = f"{chat_id}:{user_id}"
        try:
            conv_id = self._sessions.get_conversation_id(conv_key)
            answer, new_conv_id = await self._chat_client.chat_blocking(message, user_id, conv_id, image_data)

            if new_conv_id !=  conv_id:
                logger.info(f"更新{conv_key}会话映射: {conv_id} -> {new_conv_id}")
                self._sessions.set_conversation_id(conv_key, new_conv_id)
        finally:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        msg = MessageBuilder.build_stream_message(req_id, stream_id, answer, finish=True)
        await self.safe_ws_send(msg)
        logger.info(f"阻塞式回复完成: 长度={len(answer)}")


async def main():
    config = Config()

    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"❌ {e}")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("企业微信智能机器人 <-> 聊天后端 桥接服务")
    logger.info(f"  BotID:     {config.wecom_bot_id[:8]}...")
    logger.info(f"  聊天后端:  {config.chat_provider}")
    logger.info(f"  流式模式:  {'开启' if config.stream_mode else '关闭'}")
    logger.info(f"  心跳间隔:  {config.heartbeat_interval}s")
    logger.info("=" * 50)

    bridge = WeComRAGFLOWBridge(config)

    loop = asyncio.get_event_loop()
    if platform.system() != "Windows":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))

    await bridge.start()


if __name__ == "__main__":
    asyncio.run(main())
