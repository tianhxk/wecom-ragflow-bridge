"""企业微信消息内容提取。"""

import logging
from typing import Optional

from media_service import WeComImageService
from mineru_client import MinerUClient

logger = logging.getLogger("message-extractor")


class MessageExtractor:
    """将企业微信消息体转换为可发送给 RAGFLOW 的文本和图片数据。"""

    def __init__(self, mineru: Optional[MinerUClient], image_service: WeComImageService):
        self._mineru = mineru
        self._image_service = image_service

    async def extract(self, body: dict, msg_type: str) -> tuple[int, str, Optional[bytes]]:
        """返回 (状态码, 消息文本, 图片数据)，状态码 0 表示成功。"""
        if msg_type == "text":
            return 0, body.get("text", {}).get("content", "").strip(), None

        if msg_type == "mixed":
            return await self._extract_mixed(body)

        if msg_type == "voice":
            return 1, "[语音消息] 暂不支持语音识别，请发送文字消息。", None

        if msg_type == "image":
            image_info = body.get("image", {})
            if image_info.get("url"):
                ocr_text = await self._ocr_image(image_info)
                if ocr_text:
                    return 0, ocr_text, None
            return 1, "[图片消息] OCR 识别失败", None

        if msg_type == "file":
            return 1, "[文件消息]", None

        return 1, "", None

    async def _extract_mixed(self, body: dict) -> tuple[int, str, Optional[bytes]]:
        items = body.get("mixed", {}).get("msg_item", [])
        texts = []

        for item in items:
            item_type = item.get("msgtype", "")
            if item_type == "text":
                content = item.get("text", {}).get("content", "")
                if content:
                    texts.append(content)
            elif item_type == "image":
                image_info = item.get("image", {})
                if image_info:
                    ocr_text = await self._ocr_image(image_info)
                    if ocr_text:
                        texts.append(ocr_text)

        return 0, " ".join(texts).strip(), None

    async def _ocr_image(self, image_info: dict) -> Optional[str]:
        """使用 MinerU OCR 识别图片内容。"""
        if not self._mineru:
            return None

        try:
            image_url = image_info.get("url", "")
            result = await self._image_service.decrypt_image(image_info)
            if not result:
                logger.error("图片解密失败，无法进行 OCR")
                return None

            try:
                logger.info("开始 OCR 识别图片, 方式: file, 大小: %s bytes", len(result.data))
                text = await self._mineru.ocr(image_url, result.data, result.path)
            finally:
                await self._image_service.cleanup_file(result.path)

            logger.info("OCR 识别完成，提取文字长度: %s", len(text) if text else 0)
            return text if text and text.strip() else None
        except Exception as e:
            logger.error("OCR 识别失败: %s", e)
            return None
