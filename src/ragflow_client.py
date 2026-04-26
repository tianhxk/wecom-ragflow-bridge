"""RAGFLOW API 客户端模块"""

import base64
import json
import logging
from typing import Optional, AsyncIterator, Union

import aiohttp

logger = logging.getLogger("wecom-RAGFLOW-bridge")


class RAGFLOWError(Exception):
    """RAGFLOW API 错误"""


def _encode_image(image_data: bytes) -> str:
    """将图片数据编码为 base64 字符串"""
    return base64.b64encode(image_data).decode("utf-8")


class RAGFLOWClient:
    """RAGFLOW API 调用封装"""

    def __init__(self, http_session: aiohttp.ClientSession, base_url: str, api_key: str, agent_id: str):
        self._session = http_session
        self._base_url = base_url
        self._api_key = api_key
        self._agent_id = agent_id
        self._model = "deepseek-v3"  # 默认模型，可根据需要调整

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _build_messages(self, message: str, image_data: Optional[bytes] = None) -> list[dict]:
        """构建消息列表，支持图片输入"""
        if image_data:
            # 多模态消息：text + image
            image_content = {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(image_data)}"}
            }
            return [
                {"role": "user", "content": [
                    {"type": "text", "text": message},
                    image_content
                ]}
            ]
        return [{"role": "user", "content": message}]

    async def chat_stream(
        self,
        message: str,
        image_data: Optional[bytes] = None
    ) -> AsyncIterator[dict]:
        """流式聊天请求，支持图片输入"""
        url = f"{self._base_url}/api/v1/agents_openai/{self._agent_id}/chat/completions"
        logger.info(f"流式请求url: {url}, 含图片: {image_data is not None}")

        payload = {
            "model": self._model,
            "messages": self._build_messages(message, image_data),
            "stream": "true",
        }

        async with self._session.post(url, json=payload, headers=self._headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RAGFLOWError(f"API 返回 {resp.status}: {error_text[:500]}")

            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue

                try:
                    event_data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                yield event_data

    async def chat_blocking(
        self,
        message: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        image_data: Optional[bytes] = None
    ) -> tuple[str, Optional[str]]:
        """Todo,API存在错误待修正,阻塞式聊天请求，支持图片输入，返回 (回答, 新会话ID)"""
        # 注意：chat-messages API 可能不支持图片输入，这里只用文本消息
        url = f"{self._base_url}/chat-messages"
        payload = {
            "inputs": {},
            "query": message,
            "user": user_id,
            "response_mode": "blocking",
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        async with self._session.post(url, json=payload, headers=self._headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RAGFLOWError(f"API 返回 {resp.status}: {error_text[:500]}")

            result = await resp.json()
            return result.get("answer", "抱歉，我暂时无法回答这个问题。"), result.get("conversation_id")