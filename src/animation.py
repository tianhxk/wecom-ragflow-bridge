"""动画效果模块"""

import asyncio
import json

from protocol import MessageBuilder


async def animate_waiting(ws, req_id: str, stream_id: str):
    """等待回复动画效果"""
    dots = ["", ".", "..", "..."]
    index = 0
    while True:
        try:
            await asyncio.sleep(0.5)
            index = (index + 1) % 4
            msg = MessageBuilder.build_waiting(req_id, stream_id, f"正在思考{dots[index]}")
            await ws.send(json.dumps(msg))
        except asyncio.CancelledError:
            break
        except Exception:
            break