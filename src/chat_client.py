"""统一聊天客户端接口与工厂。"""

from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol

import aiohttp


@dataclass(frozen=True)
class ChatStreamEvent:
    """标准化后的流式聊天事件。"""

    event: str
    content: str = ""
    conversation_id: Optional[str] = None
    error: str = ""


class ChatClient(Protocol):
    """RAGFlow、Dify 等聊天后端的统一接口。"""

    async def chat_stream(
        self,
        message: str,
        image_data: Optional[bytes] = None,
        conversation_id: Optional[str] = None,
        user_id: str = "default",
    ) -> AsyncIterator[ChatStreamEvent]:
        ...

    async def chat_blocking(
        self,
        message: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        image_data: Optional[bytes] = None,
    ) -> tuple[str, Optional[str]]:
        ...


def create_chat_client(config, http_session: aiohttp.ClientSession) -> ChatClient:
    """根据配置创建聊天客户端。"""
    provider = config.chat_provider.lower()
    if provider == "ragflow":
        from ragflow_client import RAGFLOWClient

        return RAGFLOWClient(
            http_session,
            config.ragflow_api_base,
            config.ragflow_api_key,
            config.ragflow_agent_id,
        )
    if provider == "dify":
        from dify_client import DifyClient

        return DifyClient(
            http_session,
            config.dify_api_base,
            config.dify_api_key,
        )

    raise ValueError(f"不支持的聊天后端: {config.chat_provider}")
