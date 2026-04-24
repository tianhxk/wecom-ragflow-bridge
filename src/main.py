"""
企业微信智能机器人长连接 <-> RAGFLOW 桥接服务

通过 WebSocket 长连接方式接收企业微信消息，转发到 RAGFLOW 应用获取回复，
再通过长连接回复给用户。支持流式消息。
"""

import asyncio
import json
import logging
import signal
import sys
import platform
import uuid
from typing import Optional

import aiohttp
import websockets

from config import Config
from protocol import WeComCmd, WeComEvent, MessageBuilder
from session import SessionManager
from ragflow_client import RAGFLOWClient
from animation import animate_waiting

# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("wecom-RAGFLOW-bridge")
logger.setLevel(logging.DEBUG)  # 默认日志级别为 INFO，调试时可改为 DEBUG

class WeComRAGFLOWBridge:
    """企业微信长连接 <-> RAGFLOW 桥接器"""

    def __init__(self, config: Config):
        self._config = config
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._sessions = SessionManager()
        self._ragflow: Optional[RAGFLOWClient] = None

    async def start(self):
        """启动桥接服务"""
        self._running = True
        self._http_session = aiohttp.ClientSession()
        self._ragflow = RAGFLOWClient(
            self._http_session,
            self._config.ragflow_api_base,
            self._config.ragflow_api_key,
            self._config.ragflow_agent_id
        )

        while self._running:
            try:
                await self._connect_and_subscribe()
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket 连接断开: {e}，5秒后重连...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"连接异常: {e}，10秒后重连...", exc_info=True)
                await asyncio.sleep(10)

        if self._http_session:
            await self._http_session.close()

    async def stop(self):
        """停止服务"""
        logger.info("正在停止服务...")
        self._running = False
        if self._ws:
            await self._ws.close()

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
        await self._ws.send(json.dumps(msg))
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
                await self._ws.send(json.dumps(msg))
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
                logger.info(f"收到消息: cmd={cmd}")
                logger.debug(f"消息详情: {json.dumps(data, ensure_ascii=False)[:500]}")

                if cmd == WeComCmd.MSG_CALLBACK:
                    asyncio.create_task(self._handle_message(data))
                elif cmd == WeComCmd.EVENT_CALLBACK:
                    asyncio.create_task(self._handle_event(data))
                elif cmd == WeComCmd.PONG:
                    logger.debug("收到心跳 pong")
                else:
                    logger.debug(f"未处理的命令: {cmd}")

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
            await self._ws.send(json.dumps(msg))

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

        user_message = self._extract_message(body, msg_type)
        if not user_message:
            logger.warning(f"无法提取消息内容: msg_type={msg_type}")
            return

        logger.info(f"用户消息: user={user_id}, chat={chat_id}, msg={user_message[:100]}")

        if user_message.strip() == "#reset":
            old_conv = self._sessions.clear_conversation(chat_id)
            logger.info(f"用户请求新对话: chat={chat_id}, 清除旧会话={old_conv}")
            msg = MessageBuilder.build_stream_message(
                req_id, uuid.uuid4().hex[:16],
                "✅ 已开启新对话，之前的聊天记录已清除。请开始新的提问吧！",
                finish=True
            )
            await self._ws.send(json.dumps(msg))
            return

        try:
            if self._config.stream_mode:
                await self._reply_stream(req_id, chat_id, user_message)
            else:
                await self._reply_blocking(req_id, chat_id, user_id, user_message)
        except Exception as e:
            logger.error(f"回复消息失败: {e}", exc_info=True)
            msg = MessageBuilder.build_error(req_id)
            await self._ws.send(json.dumps(msg))

    def _extract_message(self, body: dict, msg_type: str) -> str:
        """提取用户消息文本"""
        if msg_type == "text":
            return body.get("text", {}).get("content", "").strip()
        if msg_type == "mixed":
            items = body.get("mixed", {}).get("item", [])
            texts = [item.get("text", {}).get("content", "") for item in items if item.get("msgtype") == "text"]
            return " ".join(texts).strip()
        if msg_type == "voice":
            return "[语音消息] 暂不支持语音识别，请发送文字消息。"
        if msg_type == "image":
            return "[图片消息]"
        if msg_type == "file":
            return "[文件消息]"
        return ""

    async def _reply_stream(self, req_id: str, chat_id: str, message: str):
        """流式回复"""
        stream_id = uuid.uuid4().hex[:16]
        accumulated_text = ""
        chunk_count = 0

        # 启动等待动画
        animation_task = asyncio.create_task(animate_waiting(self._ws, req_id, stream_id))
        msg = MessageBuilder.build_waiting(req_id, stream_id, "正在思考...")
        await self._ws.send(json.dumps(msg))

        try:
            async for event_data in self._ragflow.chat_stream(message):
                if event_data == "[DONE]":
                    break

                choices = event_data.get("choices", [])
                if choices:
                    content = choices[0].get("delta", {}).get("content", "")
                    if content:
                        accumulated_text += content
                        chunk_count += 1
                        if chunk_count == 1 or chunk_count % 5 == 0 or len(accumulated_text) > 20:
                            msg = MessageBuilder.build_stream_message(req_id, stream_id, accumulated_text)
                            await self._ws.send(json.dumps(msg))

                elif event_data.get("event") == "message_end":
                    new_conv_id = event_data.get("conversation_id")
                    if new_conv_id:
                        self._sessions.set_conversation_id(chat_id, new_conv_id)
                        logger.debug(f"更新会话映射: {chat_id} -> {new_conv_id}")

                elif event_data.get("event") == "error":
                    error_msg = event_data.get("message", "未知错误")
                    logger.error(f"RAGFLOW 返回错误: {error_msg}")
                    accumulated_text += f"\n\n[错误: {error_msg}]"

        finally:
            animation_task.cancel()
            try:
                await animation_task
            except asyncio.CancelledError:
                pass

        if not accumulated_text:
            accumulated_text = "抱歉，我暂时无法回答这个问题。"

        msg = MessageBuilder.build_stream_message(req_id, stream_id, accumulated_text, finish=True)
        await self._ws.send(json.dumps(msg))
        logger.info(f"流式回复完成: stream_id={stream_id}, 长度={len(accumulated_text)}")

    async def _reply_blocking(self, req_id: str, chat_id: str, user_id: str, message: str):
        """阻塞式回复"""
        conv_id = self._sessions.get_conversation_id(chat_id)
        answer, new_conv_id = await self._ragflow.chat_blocking(message, user_id, conv_id)

        if new_conv_id:
            self._sessions.set_conversation_id(chat_id, new_conv_id)

        msg = MessageBuilder.build_text_message(req_id, answer)
        await self._ws.send(json.dumps(msg))
        logger.info(f"阻塞式回复完成: 长度={len(answer)}")


async def main():
    config = Config()

    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"❌ {e}")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("企业微信智能机器人 <-> RAGFLOW 桥接服务")
    logger.info(f"  BotID:     {config.wecom_bot_id[:8]}...")
    logger.info(f"  RAGFLOW API:  {config.ragflow_api_base}")
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