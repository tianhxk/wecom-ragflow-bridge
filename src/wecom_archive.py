"""WeCom conversation archive polling and persistence."""

import asyncio
import ctypes
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiohttp import web
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from wechat_kf import WeChatKFCallbackCrypto, _xml_text
from workbot_storage import MySQLConfig

logger = logging.getLogger("wecom-archive")


class WeComArchiveError(Exception):
    """Base error for WeCom conversation archive."""


class WeComArchiveSDKError(WeComArchiveError):
    """Official SDK returned an error."""


@dataclass
class WeComArchiveConfig:
    enabled: bool
    corp_id: str
    secret: str
    private_key: str
    private_key_path: str = ""
    private_key_map: str = ""
    sdk_path: str = ""
    poll_interval: int = 5
    limit: int = 1000
    timeout: int = 10
    start_seq: int = 0
    proxy: str = ""
    proxy_password: str = ""
    cursor_key: str = "default"
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8090
    webhook_path: str = "/wecom/archive/callback"
    webhook_token: str = ""
    encoding_aes_key: str = ""
    poll_enabled: bool = True

    def load_private_key(self) -> str:
        if self.private_key:
            return self.private_key.replace("\\n", "\n")
        if self.private_key_path:
            return Path(self.private_key_path).read_text(encoding="utf-8")
        return ""

    def load_private_keys(self) -> dict[str, str]:
        keys = {}
        for version, path in _parse_private_key_map(self.private_key_map).items():
            keys[version] = Path(path).read_text(encoding="utf-8")
        default_key = self.load_private_key()
        if default_key:
            keys.setdefault("", default_key)
        return keys


class _FinanceSlice:
    def __init__(self, sdk: "WeComFinanceSDK"):
        self._sdk = sdk
        self._ptr = sdk.new_slice()

    @property
    def ptr(self):
        return self._ptr

    def content(self) -> str:
        return self._sdk.get_slice_content(self._ptr)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._sdk.free_slice(self._ptr)
        self._ptr = None


class WeComFinanceSDK:
    """ctypes wrapper for the official WeWorkFinanceSdk C library."""

    def __init__(self, sdk_path: str, corp_id: str, secret: str):
        if not sdk_path:
            sdk_path = _default_sdk_path()
        self._lib = ctypes.cdll.LoadLibrary(sdk_path)
        self._configure_signatures()
        self._sdk = self._lib.NewSdk()
        if not self._sdk:
            raise WeComArchiveSDKError("NewSdk returned NULL")
        ret = self._lib.Init(self._sdk, corp_id.encode("utf-8"), secret.encode("utf-8"))
        if ret != 0:
            self.destroy()
            raise WeComArchiveSDKError(f"Init failed: ret={ret}")
        logger.info("WeCom archive SDK initialized: path=%s", sdk_path)

    def _configure_signatures(self) -> None:
        self._lib.NewSdk.restype = ctypes.c_void_p
        self._lib.DestroySdk.argtypes = [ctypes.c_void_p]
        self._lib.Init.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self._lib.Init.restype = ctypes.c_int
        self._lib.NewSlice.restype = ctypes.c_void_p
        self._lib.FreeSlice.argtypes = [ctypes.c_void_p]
        self._lib.GetContentFromSlice.argtypes = [ctypes.c_void_p]
        self._lib.GetContentFromSlice.restype = ctypes.c_char_p
        self._lib.GetChatData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulonglong,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self._lib.GetChatData.restype = ctypes.c_int
        self._lib.DecryptData.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
        self._lib.DecryptData.restype = ctypes.c_int

    def new_slice(self):
        ptr = self._lib.NewSlice()
        if not ptr:
            raise WeComArchiveSDKError("NewSlice returned NULL")
        return ptr

    def free_slice(self, ptr) -> None:
        if ptr:
            self._lib.FreeSlice(ptr)

    def get_slice_content(self, ptr) -> str:
        raw = self._lib.GetContentFromSlice(ptr)
        return raw.decode("utf-8") if raw else ""

    def get_chat_data(self, seq: int, limit: int, proxy: str, proxy_password: str, timeout: int) -> dict:
        with _FinanceSlice(self) as chat_data:
            ret = self._lib.GetChatData(
                self._sdk,
                int(seq),
                int(limit),
                proxy.encode("utf-8"),
                proxy_password.encode("utf-8"),
                int(timeout),
                chat_data.ptr,
            )
            content = chat_data.content()
        if ret != 0:
            raise WeComArchiveSDKError(f"GetChatData failed: ret={ret} body={content[:500]}")
        try:
            return json.loads(content or "{}")
        except json.JSONDecodeError as e:
            raise WeComArchiveSDKError(f"GetChatData returned invalid json: {content[:500]}") from e

    def decrypt_data(self, random_key: str, encrypted_msg: str) -> dict:
        with _FinanceSlice(self) as message:
            ret = self._lib.DecryptData(
                self._sdk,
                random_key.encode("utf-8"),
                encrypted_msg.encode("utf-8"),
                message.ptr,
            )
            content = message.content()
        if ret != 0:
            raise WeComArchiveSDKError(f"DecryptData failed: ret={ret} body={content[:500]}")
        try:
            return json.loads(content or "{}")
        except json.JSONDecodeError as e:
            raise WeComArchiveSDKError(f"DecryptData returned invalid json: {content[:500]}") from e

    def destroy(self) -> None:
        sdk = getattr(self, "_sdk", None)
        if sdk:
            self._lib.DestroySdk(sdk)
            self._sdk = None


class WeComArchiveStore:
    def __init__(self, config: MySQLConfig):
        self._config = config
        self._enabled = True
        try:
            import pymysql  # noqa: F401
        except ImportError:
            logger.error("PyMySQL is not installed; WeCom archive persistence is disabled")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def init(self) -> None:
        if self._enabled:
            await asyncio.to_thread(self._init_sync)

    async def get_cursor(self, cursor_key: str, default_seq: int) -> int:
        if not self._enabled:
            return default_seq
        return await asyncio.to_thread(self._get_cursor_sync, cursor_key, default_seq)

    async def save_message(self, seq: int, encrypted: dict, decrypted: dict) -> bool:
        if not self._enabled:
            return False
        return await asyncio.to_thread(self._save_message_sync, seq, encrypted, decrypted)

    async def save_cursor(self, cursor_key: str, seq: int) -> None:
        if self._enabled:
            await asyncio.to_thread(self._save_cursor_sync, cursor_key, seq)

    def _connect(self, *, with_database: bool = True):
        import pymysql

        kwargs = {
            "host": self._config.host,
            "port": self._config.port,
            "user": self._config.user,
            "password": self._config.password,
            "charset": self._config.charset,
            "autocommit": True,
        }
        if with_database:
            kwargs["database"] = self._config.database
        return pymysql.connect(**kwargs)

    def _init_sync(self) -> None:
        database = _mysql_identifier(self._config.database)
        with self._connect(with_database=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS `wecom_archive_message` (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        seq BIGINT UNSIGNED NOT NULL,
                        msgid VARCHAR(128) NOT NULL,
                        action VARCHAR(32) NULL,
                        msgtype VARCHAR(64) NULL,
                        sender VARCHAR(128) NULL,
                        roomid VARCHAR(128) NULL,
                        msgtime BIGINT UNSIGNED NULL,
                        decrypted_json JSON NOT NULL,
                        encrypted_json JSON NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        UNIQUE KEY uk_seq (seq),
                        UNIQUE KEY uk_msgid (msgid),
                        KEY idx_msgtime (msgtime),
                        KEY idx_sender_time (sender, msgtime),
                        KEY idx_room_time (roomid, msgtime),
                        KEY idx_msgtype_time (msgtype, msgtime)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS `wecom_archive_cursor` (
                        cursor_key VARCHAR(128) NOT NULL,
                        seq BIGINT UNSIGNED NOT NULL,
                        updated_at DATETIME(6) NOT NULL,
                        PRIMARY KEY (cursor_key)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                )
        logger.info("WeCom archive persistence initialized: mysql://%s:%s/%s", self._config.host, self._config.port, self._config.database)

    def _get_cursor_sync(self, cursor_key: str, default_seq: int) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT seq FROM `wecom_archive_cursor` WHERE cursor_key = %s", (cursor_key,))
                row = cur.fetchone()
        return int(row[0]) if row else int(default_seq)

    def _save_message_sync(self, seq: int, encrypted: dict, decrypted: dict) -> bool:
        msgid = str(decrypted.get("msgid") or encrypted.get("msgid") or seq)
        params = (
            int(seq),
            msgid,
            _nullable_str(decrypted.get("action")),
            _nullable_str(decrypted.get("msgtype")),
            _nullable_str(decrypted.get("from")),
            _nullable_str(decrypted.get("roomid")),
            _nullable_int(decrypted.get("msgtime")),
            json.dumps(decrypted, ensure_ascii=False, default=str),
            json.dumps(encrypted, ensure_ascii=False, default=str),
        )
        sql = """
            INSERT INTO `wecom_archive_message` (
                seq, msgid, action, msgtype, sender, roomid, msgtime,
                decrypted_json, encrypted_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, params)
                    return True
                except Exception as e:
                    if _is_duplicate_key_error(e):
                        return False
                    raise

    def _save_cursor_sync(self, cursor_key: str, seq: int) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO `wecom_archive_cursor` (cursor_key, seq, updated_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE seq = GREATEST(seq, VALUES(seq)), updated_at = VALUES(updated_at)
                    """,
                    (cursor_key, int(seq), now),
                )


class WeComArchiveService:
    def __init__(self, config: WeComArchiveConfig, store: WeComArchiveStore):
        self._config = config
        self._store = store
        self._stop_event = asyncio.Event()
        self._trigger_event = asyncio.Event()
        self._sdk: Optional[WeComFinanceSDK] = None
        self._rsa_keys = {}
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._owns_webhook_server = True
        self._callback_crypto = (
            WeChatKFCallbackCrypto(config.webhook_token, config.encoding_aes_key, config.corp_id)
            if config.webhook_token and config.encoding_aes_key
            else None
        )

    @property
    def webhook_host(self) -> str:
        return self._config.webhook_host

    @property
    def webhook_port(self) -> int:
        return self._config.webhook_port

    @property
    def webhook_path(self) -> str:
        return self._config.webhook_path

    def use_external_webhook_server(self) -> None:
        self._owns_webhook_server = False

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get(self._config.webhook_path, self._handle_callback)
        app.router.add_post(self._config.webhook_path, self._handle_callback)

    async def run_forever(self) -> None:
        await self._store.init()
        await asyncio.to_thread(self._init_crypto)
        seq = await self._store.get_cursor(self._config.cursor_key, self._config.start_seq)
        if self._owns_webhook_server:
            await self._start_webhook_server()
        logger.info(
            "WeCom archive fetcher started: cursor_key=%s seq=%s limit=%s callback=%s poll_enabled=%s",
            self._config.cursor_key,
            seq,
            self._config.limit,
            self._config.webhook_path,
            self._config.poll_enabled,
        )
        try:
            while not self._stop_event.is_set():
                try:
                    next_seq, count = await self._poll_once(seq)
                    seq = next_seq
                    if count == 0:
                        await self._wait_for_next_trigger()
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("WeCom archive polling failed: %s", e, exc_info=True)
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=max(1, self._config.poll_interval))
                    except asyncio.TimeoutError:
                        pass
        finally:
            await self._stop_webhook_server()
            await asyncio.to_thread(self._destroy_sdk)

    async def stop(self) -> None:
        self._stop_event.set()
        self._trigger_event.set()
        await self._stop_webhook_server()
        await asyncio.to_thread(self._destroy_sdk)

    async def _wait_for_next_trigger(self) -> None:
        self._trigger_event.clear()
        if self._config.poll_enabled:
            await asyncio.wait_for(self._wait_until_triggered_or_stopped(), timeout=self._config.poll_interval)
            return
        await self._wait_until_triggered_or_stopped()

    async def _wait_until_triggered_or_stopped(self) -> None:
        trigger_task = asyncio.create_task(self._trigger_event.wait())
        stop_task = asyncio.create_task(self._stop_event.wait())
        try:
            done, pending = await asyncio.wait(
                {trigger_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        finally:
            for task in (trigger_task, stop_task):
                if not task.done():
                    task.cancel()

    async def _start_webhook_server(self) -> None:
        app = web.Application()
        self.add_routes(app)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._config.webhook_host, self._config.webhook_port)
        await self._site.start()
        logger.info(
            "WeCom archive callback server started at http://%s:%s%s",
            self._config.webhook_host,
            self._config.webhook_port,
            self._config.webhook_path,
        )

    async def _stop_webhook_server(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def _handle_callback(self, request: web.Request) -> web.Response:
        if self._callback_crypto:
            return await self._handle_encrypted_callback(request)
        return await self._handle_plain_callback(request)

    async def _handle_encrypted_callback(self, request: web.Request) -> web.Response:
        try:
            if request.method == "GET":
                echo = self._callback_crypto.decrypt_from_query(
                    request.query.get("echostr", ""),
                    request.query.get("msg_signature", ""),
                    request.query.get("timestamp", ""),
                    request.query.get("nonce", ""),
                )
                return web.Response(text=echo)

            raw_xml = await request.text()
            decrypted_xml = self._callback_crypto.decrypt_from_xml(
                raw_xml,
                request.query.get("msg_signature", ""),
                request.query.get("timestamp", ""),
                request.query.get("nonce", ""),
            )
            event = _xml_text(decrypted_xml, "Event")
            token = _xml_text(decrypted_xml, "Token")
            logger.info(
                "WeCom archive encrypted callback received: event=%s token_present=%s",
                event or "unknown",
                bool(token),
            )
            self._trigger_event.set()
            return web.Response(text="success")
        except Exception as e:
            logger.warning("WeCom archive encrypted callback verification failed: %s", e, exc_info=True)
            return web.Response(status=403, text="forbidden")

    async def _handle_plain_callback(self, request: web.Request) -> web.Response:
        echo = request.query.get("echostr") or request.query.get("echo") or request.query.get("challenge")
        if request.method == "GET" and echo:
            return web.Response(text=echo)
        body = {}
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = {"raw": await request.text()}
        logger.info(
            "WeCom archive plain callback received: method=%s query=%s body=%s",
            request.method,
            dict(request.query),
            body,
        )
        self._trigger_event.set()
        return web.json_response({"errcode": 0, "errmsg": "ok"})

    async def _poll_once(self, seq: int) -> tuple[int, int]:
        payload = await asyncio.to_thread(
            self._get_chat_data,
            seq,
            self._config.limit,
            self._config.proxy,
            self._config.proxy_password,
            self._config.timeout,
        )
        if payload.get("errcode", 0) not in (0, "0"):
            raise WeComArchiveSDKError(f"GetChatData returned error: {payload}")
        chat_data = payload.get("chatdata", [])
        if not isinstance(chat_data, list):
            raise WeComArchiveSDKError(f"GetChatData chatdata is not a list: {payload}")
        max_seq = seq
        saved = 0
        for item in chat_data:
            if not isinstance(item, dict):
                continue
            item_seq = int(item.get("seq") or max_seq)
            max_seq = max(max_seq, item_seq)
            decrypted = await asyncio.to_thread(self._decrypt_chat_item, item)
            if await self._store.save_message(item_seq, item, decrypted):
                saved += 1
        if max_seq > seq:
            await self._store.save_cursor(self._config.cursor_key, max_seq)
        if chat_data:
            logger.info("WeCom archive batch processed: from_seq=%s max_seq=%s fetched=%s saved=%s", seq, max_seq, len(chat_data), saved)
        return max_seq, len(chat_data)

    def _init_crypto(self) -> None:
        private_keys = self._config.load_private_keys()
        if not private_keys:
            raise WeComArchiveError("WECOM_ARCHIVE_PRIVATE_KEY, WECOM_ARCHIVE_PRIVATE_KEY_PATH, or WECOM_ARCHIVE_PRIVATE_KEY_MAP is required")
        self._rsa_keys = {version: RSA.import_key(private_key) for version, private_key in private_keys.items()}
        self._sdk = WeComFinanceSDK(self._config.sdk_path, self._config.corp_id, self._config.secret)

    def _destroy_sdk(self) -> None:
        if self._sdk:
            self._sdk.destroy()
            self._sdk = None

    def _get_chat_data(self, seq: int, limit: int, proxy: str, proxy_password: str, timeout: int) -> dict:
        if not self._sdk:
            raise WeComArchiveError("WeCom archive SDK is not initialized")
        return self._sdk.get_chat_data(seq, limit, proxy, proxy_password, timeout)

    def _decrypt_chat_item(self, item: dict) -> dict:
        if not self._sdk or not self._rsa_keys:
            raise WeComArchiveError("WeCom archive crypto is not initialized")
        encrypted_key = str(item.get("encrypt_random_key", ""))
        encrypted_msg = str(item.get("encrypt_chat_msg", ""))
        if not encrypted_key or not encrypted_msg:
            raise WeComArchiveError(f"Archive item missing encrypted fields: seq={item.get('seq')}")
        public_key_version = str(item.get("publickey_ver", "")).strip()
        rsa_key = self._select_rsa_key(public_key_version)
        random_key = _decrypt_random_key(rsa_key, encrypted_key)
        return self._sdk.decrypt_data(random_key, encrypted_msg)

    def _select_rsa_key(self, public_key_version: str):
        if public_key_version in self._rsa_keys:
            return self._rsa_keys[public_key_version]
        if "" in self._rsa_keys:
            return self._rsa_keys[""]
        display_version = public_key_version or "unknown"
        raise WeComArchiveError(f"No private key configured for publickey_ver={display_version}")



def _parse_private_key_map(value: str) -> dict[str, str]:
    result = {}
    for part in str(value or "").replace(",", ";").split(";"):
        item = part.strip()
        if not item:
            continue
        version, sep, path = item.partition("=")
        if not sep:
            version, sep, path = item.partition(":")
        if not sep:
            raise WeComArchiveError(f"Invalid WECOM_ARCHIVE_PRIVATE_KEY_MAP item: {item}")
        version = version.strip()
        path = path.strip()
        if not version or not path:
            raise WeComArchiveError(f"Invalid WECOM_ARCHIVE_PRIVATE_KEY_MAP item: {item}")
        result[version] = path
    return result


def _decrypt_random_key(rsa_key, encrypted_key: str) -> str:
    import base64

    cipher = PKCS1_v1_5.new(rsa_key)
    sentinel = object()
    decrypted = cipher.decrypt(base64.b64decode(encrypted_key), sentinel)
    if decrypted is sentinel:
        raise WeComArchiveError("RSA decrypt encrypt_random_key failed")
    return decrypted.decode("utf-8")


def _default_sdk_path() -> str:
    return os.environ.get("WECOM_ARCHIVE_SDK_PATH", "").strip() or {
        "nt": "WeWorkFinanceSdk.dll",
        "posix": "libWeWorkFinanceSdk_C.so",
    }.get(os.name, "libWeWorkFinanceSdk_C.so")


def _nullable_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nullable_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_duplicate_key_error(error: Exception) -> bool:
    return bool(getattr(error, "args", ())) and error.args[0] == 1062


def _mysql_identifier(value: str) -> str:
    if not value or not value.replace("_", "").isalnum():
        raise ValueError(f"Invalid MySQL identifier: {value}")
    return value

