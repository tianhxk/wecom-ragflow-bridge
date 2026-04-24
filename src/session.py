"""会话管理模块"""

from typing import Optional


class SessionManager:
    """管理多轮对话会话"""

    def __init__(self):
        self._conversations: dict[str, str] = {}

    def get_conversation_id(self, chat_id: str) -> Optional[str]:
        """获取会话ID"""
        return self._conversations.get(chat_id)

    def set_conversation_id(self, chat_id: str, conv_id: str):
        """设置会话ID"""
        self._conversations[chat_id] = conv_id

    def clear_conversation(self, chat_id: str) -> Optional[str]:
        """清除会话，返回被清除的会话ID"""
        return self._conversations.pop(chat_id, None)