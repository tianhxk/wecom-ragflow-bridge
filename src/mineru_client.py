"""MinerU OCR 客户端模块"""

import asyncio
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger("mineru-client")


class MinerUError(Exception):
    """MinerU API 错误"""


class MinerUClient:
    """MinerU OCR 调用封装"""

    def __init__(self, http_session: aiohttp.ClientSession, api_base: str, api_key: str, ocr_method: str = "file"):
        self._session = http_session
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._ocr_method = ocr_method  # file / url / batch

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _json_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def ocr_image_url(self, filename: str, image_data: bytes, timeout: int = 120) -> str:
        """通过本地文件进行 OCR 识别(agent/parse/file 方式)

        Args:
            filename: 本地文件名（含扩展名，如 xxx.jpg）
            timeout: 超时时间（秒）

        流程:
        1. 调用 api/v1/agent/parse/file 获取上传签名 URL
        2. PUT 上传文件到签名 URL
        3. 轮询任务状态，当 state=done 时下载 markdown_url 内容并返回
        """
        # 获取上传签名 URL
        task_id, file_url = await self._get_upload_url(filename)
        logger.info(f"已获取上传URL: {file_url}, task_id: {task_id}")
        # 上传文件到 OSS
        await self._upload_to_oss(file_url, filename,image_data)
        logger.info(f"上传完成: {filename}")
        # 轮询任务状态并获取 markdown_url
        return await self._poll_task_result(task_id, timeout)
        logger.info(f"解析任务完成: {task_id}")
        
    async def _get_upload_url(self, local_filename: str) -> tuple[str, str]:
        """调用 api/v1/agent/parse/file 获取 task_id 和上传签名 URL"""
        parse_url = f"{self._api_base}/api/v1/agent/parse/file"
        payload = {
            "file_name": local_filename,
            "language": "ch",
            "is_ocr": True
        }

        async with self._session.post(parse_url, json=payload, headers=self._json_headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise MinerUError(f"MinerU 获取上传URL失败: {resp.status}: {error_text[:500]}")

            result = await resp.json()
            task_id = result.get("data", {}).get("task_id")
            file_url = result.get("data", {}).get("file_url")
            if not task_id or not file_url:
                raise MinerUError(f"MinerU 未返回 task_id 或 file_url: {result}")

        return task_id, file_url

    async def _upload_to_oss(self, file_url: str, filename: str, image_data: bytes) -> None:
        """PUT 上传文件到 OSS"""
        headers = {
        "Content-Type": "",  # 图片就用这个，不要加任何其他头！
        }
        logger.info(f"开始上传文件: {filename}")
        async with self._session.put(file_url, data=image_data, headers=headers) as put_resp:
            if put_resp.status not in (200, 201):
                error_text = await put_resp.text()
                raise MinerUError(f"MinerU 文件上传到 OSS 失败:URL: {file_url}, HTTP {put_resp.status}, 响应: {error_text}")
    
    def _cleanup_temp_file(self, local_path: str) -> None:
        """清理临时文件"""
        if os.path.exists(local_path):
            os.remove(local_path)

    async def ocr_image_batch(self, image_url: str, timeout: int = 120) -> str:
        """通过图片 URL 进行 OCR 识别(v4/batch 方式)

        流程:
        1. 调用 /api/v4/file-urls/batch 获取 batch_id 和 file_urls(上传链接)
        2. 上传文件到 file_urls
        3. 轮询 batch_id 获取解析结果
        """
        batch_url = f"{self._api_base}/api/v4/file-urls/batch"

        payload = {
            "batch_size": 1,
            "file_url_list": [image_url]
        }

        async with self._session.post(batch_url, json=payload, headers=self._json_headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise MinerUError(f"MinerU batch API 返回 {resp.status}: {error_text[:500]}")

            result = await resp.json()
            if result.get("code") != 0:
                raise MinerUError(f"MinerU batch API 错误: {result.get('msg', 'unknown')}")

            data = result.get("data", {})
            batch_id = data.get("batch_id")
            file_urls = data.get("file_urls", [])

            if not batch_id:
                raise MinerUError(f"MinerU batch 未返回 batch_id: {result}")
            if not file_urls:
                raise MinerUError(f"MinerU batch 未返回 file_urls: {result}")

            return await self._poll_batch_result(batch_id, timeout)

    async def ocr_image_bytes(self, image_data: bytes, filename: str = "image.jpg", timeout: int = 120) -> str:
        """通过图片二进制数据进行 OCR 识别,返回提取的文本"""
        # 第一步:获取签名上传 URL
        upload_url = f"{self._api_base}/api/v1/agent/parse/file"
        payload = {
            "file_name": filename,
            "language": "ch",
            "is_ocr": True
        }

        async with self._session.post(upload_url, json=payload, headers=self._json_headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise MinerUError(f"MinerU 获取上传URL失败: {resp.status}: {error_text[:500]}")

            upload_result = await resp.json()
            task_id = upload_result.get("data", {}).get("task_id")
            file_url = upload_result.get("data", {}).get("file_url")
            if not task_id or not file_url:
                raise MinerUError(f"MinerU 未返回 task_id 或 file_url: {upload_result}")

        # 第二步:PUT 上传文件到 OSS(file_url 已包含签名,直接上传即可)
        headers = {"Content-Type": "application/octet-stream"}
        async with self._session.put(file_url, data=image_data, headers=headers) as put_resp:
            if put_resp.status not in (200, 201):
                raise MinerUError(f"MinerU 文件上传到 OSS 失败: HTTP {put_resp.status}")

        # 第三步:提交解析任务
        parse_url = f"{self._api_base}/api/v1/agent/parse/url"
        parse_payload = {"task_id": task_id}

        async with self._session.post(parse_url, json=parse_payload, headers=self._json_headers()) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise MinerUError(f"MinerU 解析请求失败: {resp.status}: {error_text[:500]}")

            parse_result = await resp.json()
            parse_task_id = parse_result.get("task_id")
            if not parse_task_id:
                raise MinerUError(f"MinerU 未返回 task_id: {parse_result}")

        return await self._poll_task_result(parse_task_id, timeout)

    async def ocr(self, image_url: str, image_data: Optional[bytes] = None, filename: str = "image.jpg", timeout: int = 120) -> str:
        """统一的 OCR 入口,根据配置选择方式"""
        if self._ocr_method == "V1parse":
            return await self.ocr_image_url(filename, image_data,timeout)
        elif self._ocr_method == "V4batch":
            return await self.ocr_image_batch(image_url, timeout)
        else:  # default file
            if image_data is None:
                raise MinerUError("file 模式需要提供 image_data(二进制)")
            return await self.ocr_image_bytes(image_data, filename, timeout)

    async def _poll_task_result(self, task_id: str, timeout: int = 120) -> str:
        """轮询任务结果

        状态: waiting-file, uploading, pending, running, done, failed
        当 state=done 时，获取 markdown_url 内容并返回
        """
        status_url = f"{self._api_base}/api/v1/agent/parse/{task_id}"
        poll_interval = 1
        elapsed = 0

        while elapsed < timeout:
            

            async with self._session.get(status_url, headers=self._headers()) as resp:
                if resp.status != 200:
                    continue

                data = await resp.json()
                state = data.get("data", {}).get("state", "")

                if state == "done":
                    markdown_url = data.get("data", {}).get("markdown_url")
                    if not markdown_url:
                        raise MinerUError(f"MinerU 任务完成但未返回 markdown_url: {data}")

                    # 下载 markdown 内容
                    async with self._session.get(markdown_url, headers=self._headers()) as md_resp:
                        if md_resp.status != 200:
                            raise MinerUError(f"下载 markdown 结果失败: HTTP {md_resp.status}")
                        content = await md_resp.text()
                        return content
                elif state == "failed":
                    err_msg = data.get("data", {}).get("err_msg", "unknown")
                    raise MinerUError(f"MinerU 任务失败: {err_msg}")
                elif state in ("waiting-file", "uploading", "pending", "running"):
                    # 继续等待
                    continue
                else:
                    # 未知状态，继续轮询
                    logger.warning(f"未知任务状态: {state}, 继续等待")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise MinerUError(f"MinerU 任务超时 ({timeout}s,task_id={task_id})")

    async def _poll_batch_result(self, batch_id: str, timeout: int = 120) -> str:
        """轮询 batch 任务结果"""
        status_url = f"{self._api_base}/api/v4/file-urls/batch/{batch_id}"
        poll_interval = 0.1
        elapsed = 0

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            async with self._session.get(status_url, headers=self._headers()) as resp:
                if resp.status != 200:
                    continue

                data = await resp.json()
                status = data.get("status", "")

                if status == "success":
                    content = data.get("data", {}).get("content", "")
                    return content
                elif status == "failed":
                    raise MinerUError(f"MinerU batch 任务失败: {data.get('error', 'unknown')}")

        raise MinerUError(f"MinerU batch 任务超时 ({timeout}s)")