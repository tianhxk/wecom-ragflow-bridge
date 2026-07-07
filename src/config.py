"""Application configuration."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("Config")


def _load_env() -> None:
    """Load config/.env without overriding existing environment variables."""
    env_path = Path.cwd() / "config" / ".env"
    logger.info("Loading environment variables from %s", env_path)
    if not env_path.exists():
        logger.warning("No .env file found at %s, skipping environment variable loading", env_path)
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env()


def _env_int(*names: str, default: int) -> int:
    for name in names:
        value = os.environ.get(name, "")
        if not value:
            continue
        try:
            return int(value)
        except ValueError:
            logger.warning("%s=%s is invalid, trying next setting", name, value)
    return default


@dataclass
class Config:
    """Runtime configuration."""

    wecom_bot_id: str = field(default_factory=lambda: os.environ.get("WECOM_BOT_ID", ""))
    wecom_secret: str = field(default_factory=lambda: os.environ.get("WECOM_SECRET", ""))
    wecom_corp_id: str = field(default_factory=lambda: os.environ.get("WECOM_CORP_ID", ""))
    wecom_ws_url: str = field(default_factory=lambda: os.environ.get("WECOM_WS_URL", "wss://openws.work.weixin.qq.com"))
    wecom_bot_enabled: bool = field(default_factory=lambda: os.environ.get("WECOM_BOT_ENABLED", "true").lower() == "true")

    wecom_kf_enabled: bool = field(default_factory=lambda: os.environ.get("WECOM_KF_ENABLED", "false").lower() == "true")
    wecom_kf_secret: str = field(default_factory=lambda: os.environ.get("WECOM_KF_SECRET", os.environ.get("WECOM_SECRET", "")))
    wecom_kf_open_kfid: str = field(default_factory=lambda: os.environ.get("WECOM_KF_OPEN_KFID", ""))
    wecom_kf_callback_token: str = field(default_factory=lambda: os.environ.get("WECOM_KF_CALLBACK_TOKEN", ""))
    wecom_kf_encoding_aes_key: str = field(default_factory=lambda: os.environ.get("WECOM_KF_ENCODING_AES_KEY", ""))
    wecom_kf_webhook_host: str = field(default_factory=lambda: os.environ.get("WECOM_KF_WEBHOOK_HOST", "0.0.0.0"))
    wecom_kf_webhook_port: int = field(default_factory=lambda: _env_int("WECOM_KF_WEBHOOK_PORT", "WEBHOOK_PORT", default=8080))
    wecom_kf_webhook_path: str = field(default_factory=lambda: os.environ.get("WECOM_KF_WEBHOOK_PATH", "/wechat-kf/callback"))

    wecom_archive_enabled: bool = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_ENABLED", "false").lower() == "true")
    wecom_archive_secret: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_SECRET", ""))
    wecom_archive_private_key: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_PRIVATE_KEY", ""))
    wecom_archive_private_key_path: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_PRIVATE_KEY_PATH", ""))
    wecom_archive_private_key_map: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_PRIVATE_KEY_MAP", ""))
    wecom_archive_sdk_path: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_SDK_PATH", ""))
    wecom_archive_poll_interval: int = field(default_factory=lambda: _env_int("WECOM_ARCHIVE_POLL_INTERVAL", default=5))
    wecom_archive_limit: int = field(default_factory=lambda: _env_int("WECOM_ARCHIVE_LIMIT", default=1000))
    wecom_archive_timeout: int = field(default_factory=lambda: _env_int("WECOM_ARCHIVE_TIMEOUT", default=10))
    wecom_archive_start_seq: int = field(default_factory=lambda: _env_int("WECOM_ARCHIVE_START_SEQ", default=0))
    wecom_archive_proxy: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_PROXY", ""))
    wecom_archive_proxy_password: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_PROXY_PASSWORD", ""))
    wecom_archive_cursor_key: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_CURSOR_KEY", "default"))
    wecom_archive_webhook_host: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_WEBHOOK_HOST", "0.0.0.0"))
    wecom_archive_webhook_port: int = field(default_factory=lambda: _env_int("WECOM_ARCHIVE_WEBHOOK_PORT", "WEBHOOK_PORT", default=8090))
    wecom_archive_webhook_path: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_WEBHOOK_PATH", "/wecom/archive/callback"))
    wecom_archive_callback_token: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_CALLBACK_TOKEN", os.environ.get("WECOM_ARCHIVE_WEBHOOK_TOKEN", "")))
    wecom_archive_encoding_aes_key: str = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_ENCODING_AES_KEY", ""))
    wecom_archive_poll_enabled: bool = field(default_factory=lambda: os.environ.get("WECOM_ARCHIVE_POLL_ENABLED", "true").lower() == "true")

    workbot_enabled: bool = field(default_factory=lambda: os.environ.get("WORKBOT_ENABLED", "false").lower() == "true")
    workbot_base_url: str = field(default_factory=lambda: os.environ.get("WORKBOT_BASE_URL", "https://flowbot.feiliu.run"))
    workbot_robot_ids: str = field(default_factory=lambda: os.environ.get("WORKBOT_ROBOT_IDS", ""))
    workbot_callback_urls: str = field(default_factory=lambda: os.environ.get("WORKBOT_CALLBACK_URLS", ""))
    workbot_bot_nicknames: str = field(default_factory=lambda: os.environ.get("WORKBOT_BOT_NICKNAMES", ""))
    workbot_webhook_host: str = field(default_factory=lambda: os.environ.get("WORKBOT_WEBHOOK_HOST", "0.0.0.0"))
    workbot_webhook_port: int = field(default_factory=lambda: _env_int("WORKBOT_WEBHOOK_PORT", "WEBHOOK_PORT", "WECOM_KF_WEBHOOK_PORT", default=8080))
    workbot_webhook_path: str = field(default_factory=lambda: os.environ.get("WORKBOT_WEBHOOK_PATH", "/workbot/callback"))
    workbot_query_api_token: str = field(default_factory=lambda: os.environ.get("WORKBOT_QUERY_API_TOKEN", ""))
    workbot_query_api_path: str = field(default_factory=lambda: os.environ.get("WORKBOT_QUERY_API_PATH", "").strip() or "/api/workbot")
    workbot_query_max_range_days: int = field(default_factory=lambda: _env_int("WORKBOT_QUERY_MAX_RANGE_DAYS", default=31))

    chat_provider: str = field(default_factory=lambda: os.environ.get("CHAT_PROVIDER", "ragflow").lower())
    ragflow_api_base: str = field(default_factory=lambda: os.environ.get("RAGFLOW_API_BASE", "http://localhost/v1"))
    ragflow_api_key: str = field(default_factory=lambda: os.environ.get("RAGFLOW_API_KEY", ""))
    ragflow_agent_id: str = field(default_factory=lambda: os.environ.get("RAGFLOW_AGENT_ID", ""))
    dify_api_base: str = field(default_factory=lambda: os.environ.get("DIFY_API_BASE", "http://localhost/v1"))
    dify_api_key: str = field(default_factory=lambda: os.environ.get("DIFY_API_KEY", ""))
    mineru_api_base: str = field(default_factory=lambda: os.environ.get("MINERU_API_BASE", "https://mineru.net"))
    mineru_api_key: str = field(default_factory=lambda: os.environ.get("MINERU_API_KEY", ""))
    mineru_ocr_method: str = field(default_factory=lambda: os.environ.get("MINERU_OCR_METHOD", "file"))
    media_dir: str = field(default_factory=lambda: os.environ.get("MEDIA_DIR", str(Path.cwd() / "config" / "media")))
    heartbeat_interval: int = field(default_factory=lambda: _env_int("HEARTBEAT_INTERVAL", default=30))
    stream_mode: bool = field(default_factory=lambda: os.environ.get("STREAM_MODE", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())

    mysql_host: str = field(default_factory=lambda: os.environ.get("MYSQL_HOST", "127.0.0.1"))
    mysql_port: int = field(default_factory=lambda: _env_int("MYSQL_PORT", default=3306))
    mysql_user: str = field(default_factory=lambda: os.environ.get("MYSQL_USER", "root"))
    mysql_password: str = field(default_factory=lambda: os.environ.get("MYSQL_PASSWORD", ""))
    mysql_dbname: str = field(default_factory=lambda: os.environ.get("MYSQL_DBNAME", "workbot"))

    def __post_init__(self) -> None:
        logger.info("wecom_bot_id: %s", self.wecom_bot_id[:8] if self.wecom_bot_id else "empty")
        logger.info("wecom_secret: %s", self.wecom_secret[:8] if self.wecom_secret else "empty")
        logger.info("wecom_corp_id: %s", self.wecom_corp_id[:8] if self.wecom_corp_id else "empty")
        logger.info("wecom_bot_enabled: %s", self.wecom_bot_enabled)
        logger.info("wecom_kf_enabled: %s", self.wecom_kf_enabled)
        logger.info("wecom_archive_enabled: %s", self.wecom_archive_enabled)
        logger.info("workbot_enabled: %s", self.workbot_enabled)
        logger.info("workbot_query_api_enabled: %s", bool(self.workbot_query_api_token))
        logger.info("workbot_robot_ids: %s", self.workbot_robot_ids or "empty")
        logger.info("workbot_bot_nicknames: %s", self.workbot_bot_nicknames or "auto")
        logger.info("wecom_kf_open_kfid: %s", self.wecom_kf_open_kfid[:8] if self.wecom_kf_open_kfid else "empty")
        logger.info("chat_provider: %s", self.chat_provider)
        logger.info("ragflow_api_key: %s", self.ragflow_api_key[:8] if self.ragflow_api_key else "empty")
        logger.info("dify_api_key: %s", self.dify_api_key[:8] if self.dify_api_key else "empty")
        logger.info("mineru_api_key: %s", self.mineru_api_key[:8] if self.mineru_api_key else "empty")
        logger.info("mysql_host: %s:%s", self.mysql_host, self.mysql_port)
        logger.info("mysql_dbname: %s", self.mysql_dbname)

    def validate(self) -> list[str]:
        errors = []
        if not self.wecom_bot_enabled and not self.wecom_kf_enabled and not self.workbot_enabled and not self.wecom_archive_enabled:
            errors.append("WECOM_BOT_ENABLED, WECOM_KF_ENABLED, WORKBOT_ENABLED, WECOM_ARCHIVE_ENABLED cannot all be false")
        if self.wecom_bot_enabled and not self.wecom_bot_id:
            errors.append("missing environment variable WECOM_BOT_ID")
        if self.wecom_bot_enabled and not self.wecom_secret:
            errors.append("missing environment variable WECOM_SECRET")
        if self.wecom_kf_enabled and not self.wecom_kf_secret:
            errors.append("missing environment variable WECOM_KF_SECRET")
        if self.wecom_kf_enabled and not self.wecom_kf_callback_token:
            errors.append("missing environment variable WECOM_KF_CALLBACK_TOKEN")
        if self.wecom_kf_enabled and not self.wecom_kf_encoding_aes_key:
            errors.append("missing environment variable WECOM_KF_ENCODING_AES_KEY")
        if self.wecom_kf_enabled and not self.wecom_kf_webhook_path.startswith("/"):
            errors.append("WECOM_KF_WEBHOOK_PATH must start with /")
        if self.wecom_archive_enabled and not self.wecom_corp_id:
            errors.append("missing environment variable WECOM_CORP_ID")
        if self.wecom_archive_enabled and not self.wecom_archive_secret:
            errors.append("missing environment variable WECOM_ARCHIVE_SECRET")
        if self.wecom_archive_enabled and not (self.wecom_archive_private_key or self.wecom_archive_private_key_path or self.wecom_archive_private_key_map):
            errors.append("missing environment variable WECOM_ARCHIVE_PRIVATE_KEY, WECOM_ARCHIVE_PRIVATE_KEY_PATH, or WECOM_ARCHIVE_PRIVATE_KEY_MAP")
        if self.wecom_archive_enabled and not self.wecom_archive_webhook_path.startswith("/"):
            errors.append("WECOM_ARCHIVE_WEBHOOK_PATH must start with /")
        if self.wecom_archive_enabled and bool(self.wecom_archive_callback_token) != bool(self.wecom_archive_encoding_aes_key):
            errors.append("WECOM_ARCHIVE_CALLBACK_TOKEN and WECOM_ARCHIVE_ENCODING_AES_KEY must be configured together")
        if self.workbot_enabled and not self.workbot_robot_ids:
            errors.append("missing environment variable WORKBOT_ROBOT_IDS")
        if self.workbot_enabled and not self.workbot_webhook_path.startswith("/"):
            errors.append("WORKBOT_WEBHOOK_PATH must start with /")
        if self.workbot_query_api_token and not self.workbot_enabled:
            errors.append("WORKBOT_ENABLED=true is required when WORKBOT_QUERY_API_TOKEN is set")
        if self.workbot_query_api_token and not self.workbot_query_api_path.startswith("/"):
            errors.append("WORKBOT_QUERY_API_PATH must start with /")
        if self.chat_provider not in ("ragflow", "dify"):
            errors.append("CHAT_PROVIDER only supports ragflow or dify")
        if self.chat_provider == "ragflow" and not self.ragflow_api_key:
            errors.append("missing environment variable RAGFLOW_API_KEY")
        if self.chat_provider == "ragflow" and not self.ragflow_agent_id:
            errors.append("missing environment variable RAGFLOW_AGENT_ID")
        if self.chat_provider == "dify" and not self.dify_api_key:
            errors.append("missing environment variable DIFY_API_KEY")
        if (self.wecom_bot_enabled or self.wecom_kf_enabled) and not self.wecom_corp_id:
            errors.append("missing environment variable WECOM_CORP_ID")
        return errors
