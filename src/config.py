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
    wecom_ws_url: str = field(default_factory=lambda: os.environ.get("WECOM_WS_URL", "wss://openws.work.weixin.qq.com"))
    ragflow_api_base: str = field(default_factory=lambda: os.environ.get("RAGFLOW_API_BASE", "http://localhost/v1"))
    ragflow_api_key: str = field(default_factory=lambda: os.environ.get("RAGFLOW_API_KEY", ""))
    ragflow_agent_id: str = field(default_factory=lambda: os.environ.get("RAGFLOW_AGENT_ID", ""))
    heartbeat_interval: int = field(default_factory=lambda: int(os.environ.get("HEARTBEAT_INTERVAL", "30")))
    stream_mode: bool = field(default_factory=lambda: os.environ.get("STREAM_MODE", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    def __post_init__(self) -> None:
        logger.info("wecom_bot_id: %s", self.wecom_bot_id[:8])
        logger.info("wecom_secret: %s", self.wecom_secret[:8])
        logger.info("ragflow_api_key: %s", self.ragflow_api_key[:8])

    def validate(self) -> list[str]:
        """验证必填配置，返回错误列表"""
        errors = []
        if not self.wecom_bot_id:
            errors.append("缺少环境变量 WECOM_BOT_ID")
        if not self.wecom_secret:
            errors.append("缺少环境变量 WECOM_SECRET")
        if not self.ragflow_api_key:
            errors.append("缺少环境变量 RAGFLOW_API_KEY")
        return errors