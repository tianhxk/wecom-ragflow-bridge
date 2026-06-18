"""动画效果模块"""

import asyncio
import json
import logging
from protocol import MessageBuilder

logger= logging.getLogger("wecom-RAGFLOW-bridge")
async def animate_waiting(ws, req_id: str, stream_id: str, timeout: int = 100):
    """等待回复动画效果，超时后发送提示并退出"""
    frames = ["", ".", "..", "..."]
    index = 0
    elapsed = 0
    interval = 1
    while True:
        try:
            content = f"正在处理，请稍候 {frames[index]}"
            msg = MessageBuilder.build_waiting(req_id, stream_id, content)
            await ws.send(json.dumps(msg))
            index = (index + 1) % 4
            await asyncio.sleep(interval)
            if index == 0:
                logger.info(f"等待动画: req_id={req_id}, stream_id={stream_id}, elapsed={elapsed}s")
            elapsed += interval
            if elapsed >= timeout:
                msg = MessageBuilder.build_waiting(req_id, stream_id, "处理时间较长，请稍候...")
                await ws.send(json.dumps(msg))
                break
        except asyncio.CancelledError:
            break
        except Exception:
            break
3