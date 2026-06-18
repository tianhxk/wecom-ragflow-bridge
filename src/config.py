"""配置模块"""

import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
import sys

# ============ 日志 ============
logger = logging.getLogger("Config")

def _load_env() -> None:
    """从项目根目录的 .env 文件加载环境变量（如果尚未设置）"""
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


@dataclass
class Config:
    """应用配置"""
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
    wecom_kf_webhook_port: int = field(default_factory=lambda: int(os.environ.get("WECOM_KF_WEBHOOK_PORT", "8080")))
    wecom_kf_webhook_path: str = field(default_factory=lambda: os.environ.get("WECOM_KF_WEBHOOK_PATH", "/wechat-kf/callback"))
    chat_provider: str = field(default_factory=lambda: os.environ.get("CHAT_PROVIDER", "ragflow").lower())
    ragflow_api_base: str = field(default_factory=lambda: os.environ.get("RAGFLOW_API_BASE", "http://localhost/v1"))
    ragflow_api_key: str = field(default_factory=lambda: os.environ.get("RAGFLOW_API_KEY", ""))
    ragflow_agent_id: str = field(default_factory=lambda: os.environ.get("RAGFLOW_AGENT_ID", ""))
    dify_api_base: str = field(default_factory=lambda: os.environ.get("DIFY_API_BASE", "http://localhost/v1"))
    dify_api_key: str = field(default_factory=lambda: os.environ.get("DIFY_API_KEY", ""))
    mineru_api_base: str = field(default_factory=lambda: os.environ.get("MINERU_API_BASE", "https://mineru.net"))
    mineru_api_key: str = field(default_factory=lambda: os.environ.get("MINERU_API_KEY", ""))
    mineru_ocr_method: str = field(default_factory=lambda: os.environ.get("MINERU_OCR_METHOD", "file"))  # file / url / batch
    media_dir: str = field(default_factory=lambda: os.environ.get("MEDIA_DIR", str(Path.cwd() / "config" / "media")))
    heartbeat_interval: int = field(default_factory=lambda: int(os.environ.get("HEARTBEAT_INTERVAL", "30")))
    stream_mode: bool = field(default_factory=lambda: os.environ.get("STREAM_MODE", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    def __post_init__(self) -> None:
        logger.info("wecom_bot_id: %s", self.wecom_bot_id[:8] if self.wecom_bot_id else "empty")
        logger.info("wecom_secret: %s", self.wecom_secret[:8] if self.wecom_secret else "empty")
        logger.info("wecom_corp_id: %s", self.wecom_corp_id[:8] if self.wecom_corp_id else "empty")
        logger.info("wecom_bot_enabled: %s", self.wecom_bot_enabled)
        logger.info("wecom_kf_enabled: %s", self.wecom_kf_enabled)
        logger.info("wecom_kf_open_kfid: %s", self.wecom_kf_open_kfid[:8] if self.wecom_kf_open_kfid else "empty")
        logger.info("chat_provider: %s", self.chat_provider)
        logger.info("ragflow_api_key: %s", self.ragflow_api_key[:8] if self.ragflow_api_key else "empty")
        logger.info("dify_api_key: %s", self.dify_api_key[:8] if self.dify_api_key else "empty")
        logger.info("mineru_api_key: %s", self.mineru_api_key[:8] if self.mineru_api_key else "empty")

    def validate(self) -> list[str]:
        """验证必填配置，返回错误列表"""
        errors = []
        if not self.wecom_bot_enabled and not self.wecom_kf_enabled:
            errors.append("WECOM_BOT_ENABLED 与 WECOM_KF_ENABLED 不能同时关闭")
        if self.wecom_bot_enabled and not self.wecom_bot_id:
            errors.append("缺少环境变量 WECOM_BOT_ID")
        if self.wecom_bot_enabled and not self.wecom_secret:
            errors.append("缺少环境变量 WECOM_SECRET")
        if self.wecom_kf_enabled and not self.wecom_kf_secret:
            errors.append("缺少环境变量 WECOM_KF_SECRET（微信客服 Secret）")
        if self.wecom_kf_enabled and not self.wecom_kf_callback_token:
            errors.append("缺少环境变量 WECOM_KF_CALLBACK_TOKEN（微信客服回调 Token）")
        if self.wecom_kf_enabled and not self.wecom_kf_encoding_aes_key:
            errors.append("缺少环境变量 WECOM_KF_ENCODING_AES_KEY（微信客服回调 EncodingAESKey）")
        if self.wecom_kf_enabled and not self.wecom_kf_webhook_path.startswith("/"):
            errors.append("WECOM_KF_WEBHOOK_PATH 必须以 / 开头")
        if self.chat_provider not in ("ragflow", "dify"):
            errors.append("CHAT_PROVIDER 仅支持 ragflow 或 dify")
        if self.chat_provider == "ragflow" and not self.ragflow_api_key:
            errors.append("缺少环境变量 RAGFLOW_API_KEY")
        if self.chat_provider == "ragflow" and not self.ragflow_agent_id:
            errors.append("缺少环境变量 RAGFLOW_AGENT_ID")
        if self.chat_provider == "dify" and not self.dify_api_key:
            errors.append("缺少环境变量 DIFY_API_KEY")
        if (self.wecom_bot_enabled or self.wecom_kf_enabled) and not self.wecom_corp_id:
            errors.append("缺少环境变量 WECOM_CORP_ID")
        return errors
