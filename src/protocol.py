"""企业微信协议定义"""

import json
import uuid


class WeComCmd:
    """企业微信命令类型"""
    SUBSCRIBE = "aibot_subscribe"
    PING = "ping"
    PONG = "pong"
    MSG_CALLBACK = "aibot_msg_callback"
    EVENT_CALLBACK = "aibot_event_callback"
    RESPOND_MSG = "aibot_respond_msg"
    RESPOND_WELCOME = "aibot_respond_welcome_msg"


class WeComEvent:
    """企业微信事件类型"""
    ENTER_CHAT = "enter_chat"
    DISCONNECTED = "disconnected_event"
    FEEDBACK = "feedback_event"


class MessageBuilder:
    """构建企业微信协议消息"""

    @staticmethod
    def build_subscribe(bot_id: str, secret: str) -> dict:
        return {
            "cmd": WeComCmd.SUBSCRIBE,
            "headers": {"req_id": uuid.uuid4().hex[:16]},
            "body": {"bot_id": bot_id, "secret": secret},
        }

    @staticmethod
    def build_ping() -> dict:
        return {
            "cmd": WeComCmd.PING,
            "headers": {"req_id": uuid.uuid4().hex[:16]},
        }

    @staticmethod
    def build_stream_message(req_id: str, stream_id: str, content: str, finish: bool = False) -> dict:
        return {
            "cmd": WeComCmd.RESPOND_MSG,
            "headers": {"req_id": req_id},
            "body": {
                "msgtype": "stream",
                "stream": {"id": stream_id, "finish": finish, "content": content},
            },
        }

    @staticmethod
    def build_text_message(req_id: str, content: str) -> dict:
        return {
            "cmd": WeComCmd.RESPOND_MSG,
            "headers": {"req_id": req_id},
            "body": {"msgtype": "text", "text": {"content": content}},
        }

    @staticmethod
    def build_welcome(req_id: str, content: str) -> dict:
        return {
            "cmd": WeComCmd.RESPOND_WELCOME,
            "headers": {"req_id": req_id},
            "body": {"msgtype": "text", "text": {"content": content}},
        }

    @staticmethod
    def build_waiting(req_id: str, stream_id: str, content: str) -> dict:
        return MessageBuilder.build_stream_message(req_id, stream_id, content, finish=False)

    @staticmethod
    def build_error(req_id: str, content: str = "抱歉，处理消息时出现了错误，请稍后重试。") -> dict:
        return MessageBuilder.build_text_message(req_id, content)

    @staticmethod
    def to_json(msg: dict) -> str:
        return json.dumps(msg)