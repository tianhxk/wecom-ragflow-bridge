"""媒体文件处理服务。"""

import base64
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from Crypto.Cipher import AES

logger = logging.getLogger("media-service")


@dataclass(frozen=True)
class DecryptedImage:
    """企业微信加密图片解密后的本地副本。"""

    path: str
    data: bytes


class WeComImageService:
    """企业微信图片下载、解密和临时文件维护。"""

    def __init__(self, http_session: aiohttp.ClientSession, media_dir: Optional[str] = None):
        self._session = http_session
        self._media_dir = Path(media_dir or os.environ.get("MEDIA_DIR", tempfile.gettempdir()))

    async def decrypt_image(self, image_info: dict) -> Optional[DecryptedImage]:
        """解密企业微信机器人图片并保存到本地媒体目录。"""
        image_url = image_info.get("url")
        aeskey = image_info.get("aeskey")
        if not image_url or not aeskey:
            logger.warning("图片信息缺少 url 或 aeskey")
            return None

        try:
            cipher_data = await self._download_encrypted_image(image_url)
            if cipher_data is None:
                return None

            image_data = self._decrypt_payload(cipher_data, aeskey)
            local_path = self._save_image(image_url, image_data)

            logger.info("解密并保存图片: %s, 大小: %s bytes", local_path, len(image_data))
            return DecryptedImage(str(local_path), image_data)
        except Exception as e:
            logger.error("解密图片失败: %s, URL: %s", e, image_url)
            return None

    async def cleanup_file(self, filename: str, max_age_days: int = 3) -> None:
        """清理媒体目录中指定天数之前的临时文件。"""
        local_path = Path(filename)
        if not local_path.is_absolute():
            local_path = self._media_dir / local_path

        try:
            if local_path.exists():
                file_age_days = (time.time() - local_path.stat().st_mtime) / 86400
                if file_age_days >= max_age_days:
                    local_path.unlink()
                    logger.debug("已清理过期临时文件: %s (年龄: %.1f天)", local_path, file_age_days)
                else:
                    logger.debug("临时文件未过期保留: %s (年龄: %.1f天)", local_path, file_age_days)
        except Exception as e:
            logger.warning("清理临时文件失败: %s", e)

    async def _download_encrypted_image(self, image_url: str) -> Optional[bytes]:
        async with self._session.get(image_url) as resp:
            if resp.status != 200:
                logger.error("下载加密图片失败: HTTP %s, URL: %s", resp.status, image_url)
                return None
            return await resp.read()

    def _decrypt_payload(self, cipher_data: bytes, aeskey: str) -> bytes:
        normalized_key = aeskey.replace("-", "+").replace("_", "/")
        padding = 4 - len(normalized_key) % 4
        if padding != 4:
            normalized_key += "=" * padding

        key = base64.b64decode(normalized_key)
        iv = key[:16]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        # 企业微信图片末尾不是标准 PKCS7 填充，直接交给 MinerU 处理解密后的内容。
        return cipher.decrypt(cipher_data)

    def _save_image(self, image_url: str, image_data: bytes) -> Path:
        self._media_dir.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(image_url)
        ext = os.path.splitext(parsed.path)[1] if parsed.path else ""
        if not ext:
            ext = ".jpeg"
        if not ext.startswith("."):
            ext = "." + ext

        local_path = self._media_dir / f"mineru_{os.urandom(8).hex()}{ext}"
        local_path.write_bytes(image_data)
        return local_path
