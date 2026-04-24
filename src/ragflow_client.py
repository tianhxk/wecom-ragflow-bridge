"""RAGFLOW API 客户端模块"""

import json
import logging
from typing import Optional, AsyncIterator

import aiohttp

logger = logging.getLogger("wecom-RAGFLOW-bridge")

class RAGFLOWError(Exception):
    """RAGFLOW API 错误"""


class RAGFLOWClient:
    """RAGFLOW API 调用封装"""

    def __init__(self, http_session: aiohttp.ClientSession, base_url: str, api_key: str,agent_id: str):
        self._session = http_session
        self._base_url = base_url
        self._api_key = api_key
        self._agent_id = agent_id
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def chat_stream(self, message: str) -> AsyncIterator[dict]:
        """流式聊天请求"""
        url = f"{self._base_url}/api/v1/agents_openai/{self._agent_id}/chat/completions"
        logger.info(f"流式请求url: {url}")
    
        payload = {
            "model": "deepseek-v3",
            "messages": [{"role": "user", "content": message}],
            "stream": "true",
        }

        async with self._session.post(url, json=payload, headers=self._headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RAGFLOWError(f"API 返回 {resp.status}: {error_text[:500]}")

            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if not line.startswith(":"):
                    continue

                try:
                    event_data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                yield event_data

    async def chat_blocking(
        self, message: str, user_id: str, conversation_id: Optional[str] = None
    ) -> tuple[str, Optional[str]]:
        """Todo,API存在错误待修正,阻塞式聊天请求，返回 (回答, 新会话ID)"""
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