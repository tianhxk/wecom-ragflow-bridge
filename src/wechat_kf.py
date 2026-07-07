"""微信客服消息通道。"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import struct
import time
import uuid
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

import aiohttp
from aiohttp import web
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from chat_client import ChatClient
from session import SessionManager

logger = logging.getLogger("wechat-kf")


class DebugAccessLogger(web.AccessLogger):
    @property
    def enabled(self) -> bool:
        return self.logger.isEnabledFor(logging.DEBUG)

    def log(self, request, response, time) -> None:
        self.logger.debug(self._format_line(request, response, time))

WECOM_CALLBACK_PKCS7_BLOCK_SIZE = 32
MAX_SEEN_MSGIDS = 5000
DEFAULT_MAX_TEXT_MESSAGE_BYTES = 1500


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("%s=%s 无效，使用默认值 %s", name, value, default)
        return default


MAX_TEXT_MESSAGE_BYTES = _env_int("WECOM_KF_MAX_TEXT_MESSAGE_BYTES", DEFAULT_MAX_TEXT_MESSAGE_BYTES)


class WeChatKFAPIError(Exception):
    """微信客服 API 错误。"""


class WeChatKFCallbackCrypto:
    """企业微信回调验签和 AES-CBC 解密。"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self._token = token
        self._corp_id = corp_id
        normalized_key = encoding_aes_key.strip()
        normalized_key += "=" * ((4 - len(normalized_key) % 4) % 4)
        self._aes_key = base64.b64decode(normalized_key)
        if len(self._aes_key) != 32:
            raise ValueError("WECOM_KF_ENCODING_AES_KEY 无效，解码后必须为 32 字节")

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypted: str) -> bool:
        raw = "".join(sorted([self._token, timestamp, nonce, encrypted]))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest() == msg_signature

    def decrypt(self, encrypted: str) -> str:
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_key[:16])
        plain = unpad(
            cipher.decrypt(base64.b64decode(encrypted)),
            WECOM_CALLBACK_PKCS7_BLOCK_SIZE,
        )
        msg_len = struct.unpack("!I", plain[16:20])[0]
        xml_payload = plain[20 : 20 + msg_len].decode("utf-8")
        receive_id = plain[20 + msg_len :].decode("utf-8")
        if self._corp_id and receive_id and receive_id != self._corp_id:
            raise ValueError(f"回调 CorpID 不匹配: {receive_id}")
        return xml_payload

    def decrypt_from_query(self, encrypted: str, msg_signature: str, timestamp: str, nonce: str) -> str:
        if not self.verify_signature(msg_signature, timestamp, nonce, encrypted):
            raise ValueError("回调签名校验失败")
        return self.decrypt(encrypted)

    def decrypt_from_xml(self, raw_xml: str, msg_signature: str, timestamp: str, nonce: str) -> str:
        encrypted = _xml_text(raw_xml, "Encrypt")
        if not encrypted:
            raise ValueError("回调 XML 缺少 Encrypt")
        return self.decrypt_from_query(encrypted, msg_signature, timestamp, nonce)


class WeChatKFClient:
    """微信客服 API 封装。"""

    def __init__(self, http_session: aiohttp.ClientSession, corp_id: str, secret: str):
        self._session = http_session
        self._corp_id = corp_id
        self._secret = secret
        self._access_token: Optional[str] = None
        self._token_expires_at = 0.0

    async def get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {"corpid": self._corp_id, "corpsecret": self._secret}
        async with self._session.get(url, params=params) as resp:
            data = await resp.json(content_type=None)

        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise WeChatKFAPIError(f"获取微信客服 access_token 失败: {data.get('errmsg', 'unknown')}")

        self._access_token = data.get("access_token", "")
        self._token_expires_at = time.time() + max(int(data.get("expires_in", 7200)) - 300, 60)
        return self._access_token

    async def sync_messages(
        self,
        token: str,
        cursor: str = "",
        open_kfid: str = "",
        limit: int = 100,
    ) -> dict:
        access_token = await self.get_access_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg"
        params = {"access_token": access_token}
        payload = {
            "cursor": cursor,
            "token": token,
            "limit": limit,
            "voice_format": 0,
        }
        if open_kfid:
            payload["open_kfid"] = open_kfid

        async with self._session.post(url, params=params, json=payload) as resp:
            data = await resp.json(content_type=None)

        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise WeChatKFAPIError(f"sync_msg 失败: {data.get('errmsg', 'unknown')}")
        return data

    async def send_text(self, open_kfid: str, external_userid: str, content: str) -> None:
        access_token = await self.get_access_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg"
        params = {"access_token": access_token}
        safe_content = _truncate_utf8(content, MAX_TEXT_MESSAGE_BYTES)
        payload = {
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgid": uuid.uuid4().hex,
            "msgtype": "text",
            "text": {"content": safe_content},
        }

        async with self._session.post(url, params=params, json=payload) as resp:
            data = await resp.json(content_type=None)

        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise WeChatKFAPIError(f"send_msg 失败: {data.get('errmsg', 'unknown')}")


class WeChatKFBridge:
    """微信客服 <-> 聊天后端桥接器。"""

    def __init__(
        self,
        api: WeChatKFClient,
        chat_client: ChatClient,
        sessions: SessionManager,
        open_kfid: str = "",
        callback_token: str = "",
        encoding_aes_key: str = "",
        corp_id: str = "",
        webhook_host: str = "0.0.0.0",
        webhook_port: int = 8080,
        webhook_path: str = "/wechat-kf/callback",
    ):
        self._api = api
        self._chat_client = chat_client
        self._sessions = sessions
        self._open_kfid = open_kfid
        self._cursors: dict[str, str] = {}
        self._running = False
        self._stop_event = asyncio.Event()
        self._seen_msgids: set[str] = set()
        self._seen_msgids_order: list[str] = []
        self._processing_msgids: set[str] = set()
        self._state_file = Path(
            os.environ.get("WECOM_KF_STATE_FILE", str(Path.cwd() / "config" / "wechat_kf_state.json"))
        )
        self._sync_locks: dict[str, asyncio.Lock] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._crypto = WeChatKFCallbackCrypto(callback_token, encoding_aes_key, corp_id)
        self._webhook_host = webhook_host
        self._webhook_port = webhook_port
        self._webhook_path = webhook_path
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._sync_tasks: set[asyncio.Task] = set()
        self._load_state()

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get(self._webhook_path, self._handle_verify)
        app.router.add_post(self._webhook_path, self._handle_callback)

    async def run_forever(self) -> None:
        self._running = True
        self._stop_event.clear()
        await self._stop_event.wait()

    async def start(self) -> None:
        self._running = True
        self._app = web.Application()
        self.add_routes(self._app)
        self._runner = web.AppRunner(self._app, access_log_class=DebugAccessLogger)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await self._site.start()
        logger.info(
            "微信客服 webhook 已启动: http://%s:%s%s, open_kfid=%s",
            self._webhook_host,
            self._webhook_port,
            self._webhook_path,
            self._open_kfid or "all",
        )
        await self.run_forever()

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        for task in list(self._sync_tasks):
            task.cancel()
        if self._sync_tasks:
            await asyncio.gather(*self._sync_tasks, return_exceptions=True)
        if self._runner:
            await self._runner.cleanup()

    def _load_state(self) -> None:
        try:
            if not self._state_file.exists():
                return
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("加载微信客服状态文件失败，将从空状态启动: %s", e)
            return

        cursors = data.get("cursors", {})
        msgids = data.get("seen_msgids", [])
        if isinstance(cursors, dict):
            self._cursors = {str(key): str(value) for key, value in cursors.items() if value}
        if isinstance(msgids, list):
            self._seen_msgids_order = [str(msgid) for msgid in msgids[-MAX_SEEN_MSGIDS:] if msgid]
            self._seen_msgids = set(self._seen_msgids_order)
        logger.info(
            "已加载微信客服状态: cursors=%s, seen_msgids=%s, file=%s",
            len(self._cursors),
            len(self._seen_msgids),
            self._state_file,
        )

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self._state_file.with_suffix(self._state_file.suffix + ".tmp")
            payload = {
                "cursors": self._cursors,
                "seen_msgids": self._seen_msgids_order[-MAX_SEEN_MSGIDS:],
            }
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_file.replace(self._state_file)
        except Exception as e:
            logger.warning("保存微信客服状态文件失败: %s", e)

    def _set_cursor(self, cursor_key: str, cursor: str) -> None:
        if not cursor or self._cursors.get(cursor_key) == cursor:
            return
        self._cursors[cursor_key] = cursor
        self._save_state()

    def _claim_msgid(self, msgid: str) -> bool:
        if not msgid:
            return True
        if msgid in self._seen_msgids or msgid in self._processing_msgids:
            return False
        self._processing_msgids.add(msgid)
        return True

    def _mark_msgid_handled(self, msgid: str) -> None:
        if not msgid:
            return

        self._seen_msgids.add(msgid)
        self._seen_msgids_order.append(msgid)
        self._processing_msgids.discard(msgid)
        if len(self._seen_msgids_order) > MAX_SEEN_MSGIDS:
            self._seen_msgids_order = self._seen_msgids_order[-MAX_SEEN_MSGIDS:]
            self._seen_msgids = set(self._seen_msgids_order)
        self._save_state()

    def _release_msgid(self, msgid: str) -> None:
        if msgid:
            self._processing_msgids.discard(msgid)

    async def _handle_verify(self, request: web.Request) -> web.Response:
        try:
            echo = self._crypto.decrypt_from_query(
                request.query.get("echostr", ""),
                request.query.get("msg_signature", ""),
                request.query.get("timestamp", ""),
                request.query.get("nonce", ""),
            )
            return web.Response(text=echo)
        except Exception as e:
            logger.warning("微信客服 webhook 验证失败: %s", e)
            return web.Response(status=403, text="forbidden")

    async def _handle_callback(self, request: web.Request) -> web.Response:
        try:
            raw_xml = await request.text()
            decrypted_xml = self._crypto.decrypt_from_xml(
                raw_xml,
                request.query.get("msg_signature", ""),
                request.query.get("timestamp", ""),
                request.query.get("nonce", ""),
            )
            sync_token = _xml_text(decrypted_xml, "Token")
            open_kfid = _xml_text(decrypted_xml, "OpenKfId") or self._open_kfid
            event = _xml_text(decrypted_xml, "Event")
            if not sync_token:
                logger.info("微信客服回调未携带 Token: event=%s", event)
                return web.Response(text="success")

            task = asyncio.create_task(self.sync_from_token(sync_token, open_kfid))
            self._sync_tasks.add(task)
            task.add_done_callback(self._sync_tasks.discard)
            return web.Response(text="success")
        except Exception as e:
            logger.error("微信客服 webhook 处理失败: %s", e, exc_info=True)
            return web.Response(status=500, text="failed")

    async def sync_from_token(self, sync_token: str, open_kfid: str = "") -> None:
        lock_key = open_kfid or self._open_kfid or "all"
        lock = self._sync_locks.setdefault(lock_key, asyncio.Lock())
        try:
            async with lock:
                await self._poll_once(sync_token, open_kfid or self._open_kfid)
        except Exception as e:
            logger.error("微信客服消息同步失败: %s", e, exc_info=True)

    async def _poll_once(self, sync_token: str, open_kfid: str = "") -> None:
        cursor_key = open_kfid or "all"
        cursor = self._cursors.get(cursor_key, "")
        is_initial_sync = not cursor
        data = await self._api.sync_messages(
            token=sync_token,
            cursor=cursor,
            open_kfid=open_kfid,
        )

        messages = data.get("msg_list", [])
        if is_initial_sync:
            messages = messages[-1:]

        for message in messages:
            await self._handle_message(message)
        self._set_cursor(cursor_key, data.get("next_cursor", cursor))

        if is_initial_sync:
            return

        while data.get("has_more") == 1:
            cursor = self._cursors.get(cursor_key, "")
            data = await self._api.sync_messages(
                token=sync_token,
                cursor=cursor,
                open_kfid=open_kfid,
            )
            for message in data.get("msg_list", []):
                await self._handle_message(message)
            self._set_cursor(cursor_key, data.get("next_cursor", cursor))

    async def _handle_message(self, message: dict) -> None:
        msgid = message.get("msgid", "")
        if not self._claim_msgid(msgid):
            return

        handled = False
        try:
            external_userid = message.get("external_userid", "")
            open_kfid = message.get("open_kfid", self._open_kfid)
            msgtype = message.get("msgtype", "")
            if not external_userid or not open_kfid:
                handled = True
                return
            if msgtype == "event":
                handled = True
                return

            status_code, user_message = self._extract_text(message, msgtype)
            if status_code != 0:
                await self._api.send_text(open_kfid, external_userid, user_message)
                handled = True
                return
            if not user_message:
                handled = True
                return

            await self._api.send_text(open_kfid, external_userid, "已收到消息,处理中")

            conv_key = f"kf:{open_kfid}:{external_userid}"
            lock = self._conversation_locks.setdefault(conv_key, asyncio.Lock())
            async with lock:
                if user_message.strip() == "#reset":
                    self._sessions.clear_conversation(conv_key)
                    await self._api.send_text(open_kfid, external_userid, "已开启新对话，请开始新的提问吧。")
                    handled = True
                    return

                logger.info("收到微信客服消息: kfid=%s, user=%s, msg=%s", open_kfid, external_userid, user_message[:100])
                conv_id = self._sessions.get_conversation_id(conv_key)
                answer, new_conv_id = await self._chat_client.chat_blocking(
                    user_message,
                    external_userid,
                    conv_id,
                )
                if new_conv_id != conv_id:
                    self._sessions.set_conversation_id(conv_key, new_conv_id)

                await self._send_long_text(open_kfid, external_userid, answer or "没有获取到有效回复。")
                handled = True
        finally:
            if handled:
                self._mark_msgid_handled(msgid)
            else:
                self._release_msgid(msgid)

    def _extract_text(self, message: dict, msgtype: str) -> tuple[int, str]:
        if msgtype == "text":
            return 0, message.get("text", {}).get("content", "").strip()
        if msgtype == "image":
            return 1, "暂不支持直接识别微信客服图片，请发送文字消息。"
        if msgtype == "voice":
            return 1, "暂不支持微信客服语音识别，请发送文字消息。"
        return 1, f"暂不支持的微信客服消息类型: {msgtype}"

    async def _send_long_text(self, open_kfid: str, external_userid: str, content: str) -> None:
        for chunk in _split_utf8(content, MAX_TEXT_MESSAGE_BYTES):
            try:
                await self._api.send_text(open_kfid, external_userid, chunk)
            except WeChatKFAPIError as e:
                if "send msg count limit" in str(e):
                    logger.warning("微信客服 send_msg 次数限制，停止发送当前回复: %s", e)
                    return
                raise
            await asyncio.sleep(0.2)


def _xml_text(xml_payload: str, tag_name: str) -> str:
    try:
        root = ElementTree.fromstring(xml_payload)
    except ElementTree.ParseError:
        return ""
    node = root.find(tag_name)
    return node.text.strip() if node is not None and node.text else ""


def _split_utf8(content: str, max_bytes: int) -> list[str]:
    """按 UTF-8 字节数拆分文本，避免截断中文字符。"""
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
