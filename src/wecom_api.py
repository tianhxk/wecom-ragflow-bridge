"""企业微信 API 调用模块"""

import logging
from typing import Optional

import aiohttp

logger = logging.getLogger("wecom-api")


class WeComAPIError(Exception):
    """企业微信 API 错误"""


class WeComAPIClient:
    """企业微信 API 调用封装"""

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        corp_id: str,
        bot_id: str,
        secret: str,
    ):
        self._session = http_session
        self._corp_id = corp_id
        self._bot_id = bot_id
        self._secret = secret
        self._access_token: Optional[str] = None

    async def get_access_token(self) -> str:
        """获取 access_token"""
        if self._access_token:
            return self._access_token

        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {"corpid": self._corp_id, "corpsecret": self._secret}

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise WeComAPIError(f"获取 access_token 失败: {resp.status} {text[:200]}")

            data = await resp.json()
            errcode = data.get("errcode", 0)
            if errcode != 0:
                raise WeComAPIError(f"获取 access_token 失败: {data.get('errmsg', 'unknown')}")

            self._access_token = data.get("access_token", "")
            logger.info("成功获取 access_token")
            return self._access_token

    async def download_media(self, media_id: str) -> bytes:
        """下载媒体文件"""
        token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get"
        params = {"access_token": token, "media_id": media_id}

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise WeComAPIError(f"下载媒体文件失败: {resp.status} {text[:200]}")

            # 检查是否返回错误 JSON
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data = await resp.json()
                errcode = data.get("errcode", 0)
                if errcode != 0:
                    raise WeComAPIError(f"下载媒体文件失败: {data.get('errmsg', 'unknown')}")

            return await resp.read()