"""Dify API 客户端模块。"""

import json
import logging
import re
from typing import AsyncIterator, Optional

import aiohttp

from chat_client import ChatStreamEvent

logger = logging.getLogger("wecom-RAGFLOW-bridge")

THINK_TAG_PATTERN = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)


class DifyError(Exception):
    """Dify API 错误。"""


class DifyClient:
    """Dify Chat Messages API 调用封装。"""

    def __init__(self, http_session: aiohttp.ClientSession, base_url: str, api_key: str):
        self._session = http_session
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def chat_stream(
        self,
        message: str,
        image_data: Optional[bytes] = None,
        conversation_id: Optional[str] = None,
        user_id: str = "default",
    ) -> AsyncIterator[ChatStreamEvent]:
        """流式聊天请求。"""
        url = f"{self._base_url}/chat-messages"
        logger.info("Dify 流式请求url: %s, 含图片: %s", url, image_data is not None)

        payload = self._build_payload(message, user_id, "streaming", conversation_id)

        async with self._session.post(url, json=payload, headers=self._headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise DifyError(f"API 返回 {resp.status}: {error_text[:500]}")
            #logger.info(f"dify chatstream resp {resp.status}: {(await resp.text())[:500]}")
            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()
                if data == "[DONE]":
                    yield ChatStreamEvent(event="done")
                    continue

                try:
                    event_data = json.loads(data)
                except json.JSONDecodeError:
                    continue

                event = event_data.get("event", "")
                logger.debug(f"Dify 流式事件: event={event},event_data.={event_data.get("conversation_id")}")

                if event == "message":
                    yield ChatStreamEvent(
                        event="message",
                        content=event_data.get("answer", ""),
                        conversation_id=event_data.get("conversation_id"),
                    )
                elif event == "message_end":
                    yield ChatStreamEvent(
                        event="message_end",
                        conversation_id=event_data.get("conversation_id"),
                    )
                elif event == "error":
                    yield ChatStreamEvent(
                        event="error",
                        error=event_data.get("message", "未知错误"),
                    )
    async def chat_blocking(
        self,
        message: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        image_data: Optional[bytes] = None,
    ) -> tuple[str, Optional[str]]:
        """阻塞式聊天请求。"""
        url = f"{self._base_url}/chat-messages"
        payload = self._build_payload(message, user_id, "blocking", conversation_id)
        logger.info(f"Dify 阻塞式请求url: %s, 含图片: %s,payload: %s", url, image_data is not None, payload)
        async with self._session.post(url, json=payload, headers=self._headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise DifyError(f"API 返回 {resp.status}: {error_text[:500]}")

            result = await resp.json()
            answer = _remove_think_tags(result.get("answer", "抱歉，我暂时无法回答这个问题。"))
            return answer, result.get("conversation_id")

    def _build_payload(
        self,
        message: str,
        user_id: str,
        response_mode: str,
        conversation_id: Optional[str] = None,
    ) -> dict:
        payload = {
            "inputs": {},
            "query": message,
            "response_mode": response_mode,
            "user": user_id,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return payload


def _remove_think_tags(content: str) -> str:
    return THINK_TAG_PATTERN.sub("", content).strip()
