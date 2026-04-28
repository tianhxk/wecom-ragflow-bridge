"""
企业微信智能机器人长连接 <-> RAGFLOW 桥接服务

通过 WebSocket 长连接方式接收企业微信消息，转发到 RAGFLOW 应用获取回复，
再通过长连接回复给用户。支持流式消息。
"""

import asyncio
import base64
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
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from config import Config
from protocol import WeComCmd, WeComEvent, MessageBuilder
from session import SessionManager
from ragflow_client import RAGFLOWClient
from wecom_api import WeComAPIClient
from mineru_client import MinerUClient
from animation import animate_waiting

# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("wecom-RAGFLOW-bridge")
#logger.setLevel(logging.DEBUG)  # 默认日志级别为 INFO，调试时可改为 DEBUG

class WeComRAGFLOWBridge:
    """企业微信长连接 <-> RAGFLOW 桥接器"""

    def __init__(self, config: Config):
        self._config = config
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._sessions = SessionManager()
        self._ragflow: Optional[RAGFLOWClient] = None
        self._wecom_api: Optional[WeComAPIClient] = None
        self._mineru: Optional[MinerUClient] = None

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

        start_time = time.time()
        status_code, user_message, image_data = await self._extract_message(body, msg_type)
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"_extract_message 耗时: {elapsed:.2f}ms")
        if status_code != 0:
            logger.warning(f"消息提取失败: msg_type={msg_type}")
            return

        if not user_message and not image_data:
            logger.warning(f"消息内容为空: msg_type={msg_type}")
            return

        logger.info(f"用户消息: user={user_id}, chat={chat_id}, msg={user_message[:100] if user_message else '[图片]'}, 含图片={image_data is not None}")
        if msg_type in ["mixed", "image"]:
           msg= MessageBuilder.build_stream_message(
               req_id, uuid.uuid4().hex[:16],
                 f"通过图片解析,您提问的问题是：{user_message}")
           await self._ws.send(json.dumps(msg))

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
                await self._reply_stream(req_id, chat_id, user_message, image_data)
            else:
                await self._reply_blocking(req_id, chat_id, user_id, user_message, image_data)
        except Exception as e:
            logger.error(f"回复消息失败: {e}", exc_info=True)
            msg = MessageBuilder.build_error(req_id)
            await self._ws.send(json.dumps(msg))

    async def _decrypt_wecom_image(self, image_info: dict) -> Optional[tuple[str, bytes]]:
        """解密企业微信机器人图片并保存到本地媒体目录

        Returns:
            (filename, image_data) 或 None（解密/保存失败时）
        """
        image_url = image_info.get("url")
        aeskey = image_info.get("aeskey")
        if not image_url or not aeskey:
            logger.warning("图片信息缺少 url 或 aeskey")
            return None
        try:
            # 下载加密图片
            async with self._http_session.get(image_url) as resp:
                if resp.status != 200:
                    logger.error(f"下载加密图片失败: HTTP {resp.status}, URL: {image_url}")
                    return None
                cipher_data = await resp.read()
            # 解密
            aeskey = aeskey.replace("-", "+").replace("_", "/")
            padding = 4 - len(aeskey) % 4
            if padding != 4:
                aeskey += "=" * padding
            key = base64.b64decode(aeskey)
            iv = key[:16]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            image_data = unpad(cipher.decrypt(cipher_data), AES.block_size)

            # 保存到本地媒体目录
            from urllib.parse import urlparse
            import os
            import tempfile
            from pathlib import Path
            parsed = urlparse(image_url)
            ext = os.path.splitext(parsed.path)[1] if parsed.path else ""
            if not ext:
                ext = ".jpeg"
            if not ext.startswith("."):
                ext = "." + ext
            media_dir = os.environ.get("MEDIA_DIR", tempfile.gettempdir())
            Path(media_dir).mkdir(parents=True, exist_ok=True)
            filename = f"mineru_{os.urandom(8).hex()}{ext}"
            local_path = os.path.join(media_dir, filename)
            with open(local_path, "wb") as f:
                f.write(image_data)

            logger.info(f"解密并保存图片: {local_path}, 大小: {len(image_data)} bytes")
            return local_path, image_data
        except Exception as e:
            logger.error(f"解密图片失败: {e}, URL: {image_url}")
            return None

    async def _cleanup_media_file(self, filename: str, max_age_days: int = 3) -> None:
        """清理媒体目录中指定天数之前的临时文件

        Args:
            filename: 要清理的文件名
            max_age_days: 仅清理超过此天数的文件，默认3天
        """
        import os
        import tempfile
        import time
        media_dir = os.environ.get("MEDIA_DIR", tempfile.gettempdir())
        local_path = os.path.join(media_dir, filename)
        try:
            if os.path.exists(local_path):
                file_mtime = os.path.getmtime(local_path)
                file_age_days = (time.time() - file_mtime) / 86400
                if file_age_days >= max_age_days:
                    os.remove(local_path)
                    logger.debug(f"已清理过期临时文件: {local_path} (年龄: {file_age_days:.1f}天)")
                else:
                    logger.debug(f"临时文件未过期保留: {local_path} (年龄: {file_age_days:.1f}天)")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")

    async def _ocr_image(self, image_info: dict) -> Optional[str]:
        """使用 MinerU OCR 识别图片内容（支持加密图片）"""
        if not self._mineru:
            return None
        try:
            image_url = image_info.get("url", "")
          
            # file 模式：解密后直接传二进制数据给 MinerU
            result = await self._decrypt_wecom_image(image_info)
            if not result:
                logger.error("图片解密失败，无法进行 OCR")
                return None
            filename, image_data = result   #filename包含全文件路径
            try:
                logger.info(f"开始 OCR 识别图片, 方式: file, 大小: {len(image_data)} bytes")
                text = await self._mineru.ocr(image_url, image_data, filename)
            finally:
                await self._cleanup_media_file(filename)
            
            logger.info(f"OCR 识别完成，提取文字长度: {len(text) if text else 0}")
            return text if text and text.strip() else None
        except Exception as e:
            logger.error(f"OCR 识别失败: {e}")
            return None

    async def _extract_message(self, body: dict, msg_type: str) -> tuple[int, str, Optional[bytes]]:
        """提取用户消息文本和图片数据（图片会通过 MinerU OCR 识别）
        返回 (状态码, 消息文本, 图片数据)
        状态码: 0=成功, 1=失败
        """
        if msg_type == "text":
            return 0, body.get("text", {}).get("content", "").strip(), None
        if msg_type == "mixed":
            items = body.get("mixed", {}).get("msg_item", [])
            texts = []
            image_info = None
            for item in items:
                item_type = item.get("msgtype", "")
                if item_type == "text":
                    content = item.get("text", {}).get("content", "")
                    if content:
                        texts.append(content)
                elif item_type == "image" :
                    image_info = item.get("image", {})
                    if image_info:
                        ocr_text = await self._ocr_image(image_info)
                        if ocr_text:
                            texts.append(f"{ocr_text}")
            return 0, " ".join(texts).strip(), None
        if msg_type == "voice":
            return 1, "[语音消息] 暂不支持语音识别，请发送文字消息。", None
        if msg_type == "image":
            image_info = body.get("image", {})
            if image_info.get("url"):
                ocr_text = await self._ocr_image(image_info)
                if ocr_text:
                    return 0, ocr_text, None
            return 1, "[图片消息] OCR 识别失败", None
        if msg_type == "file":
            return 1, "[文件消息]", None
        return 1, "", None

    async def _reply_stream(self, req_id: str, chat_id: str, message: str, image_data: Optional[bytes] = None):
        """流式回复"""
        stream_id = uuid.uuid4().hex[:16]
        accumulated_text = ""
        chunk_count = 0

        # 启动等待动画
        animation_task = asyncio.create_task(animate_waiting(self._ws, req_id, stream_id))
        msg = MessageBuilder.build_waiting(req_id, stream_id, "正在思考...")
        await self._ws.send(json.dumps(msg))

        try:
            async for event_data in self._ragflow.chat_stream(message, image_data):
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
            accumulated_text = "流式处理未返回结果"

        msg = MessageBuilder.build_stream_message(req_id, stream_id, accumulated_text, finish=True)
        await self._ws.send(json.dumps(msg))
        logger.info(f"流式回复完成: stream_id={stream_id}, 长度={len(accumulated_text)}")

    async def _reply_blocking(self, req_id: str, chat_id: str, user_id: str, message: str, image_data: Optional[bytes] = None):
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