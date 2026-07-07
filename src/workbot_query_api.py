"""Authenticated read-only HTTP API for WorkBot data and application logs."""

import asyncio
import hmac
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import web

from workbot_storage import WorkBotMessageStore

logger = logging.getLogger("workbot-query-api")

DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 200
DEFAULT_LOG_TAIL_LINES = 500
MAX_LOG_TAIL_LINES = 5000
MAX_LOG_PREVIEW_BYTES = 2 * 1024 * 1024


class WorkBotQueryApi:
    """Expose bounded, authenticated queries for message and callback_log."""

    def __init__(
        self,
        store: WorkBotMessageStore,
        token: str,
        base_path: str = "/api/workbot",
        max_range_days: int = 31,
        log_file: str | Path | None = None,
    ):
        self._store = store
        self._token = token.strip()
        normalized_path = base_path.strip("/") or "api/workbot"
        self._base_path = "/" + normalized_path
        self._max_range = timedelta(days=max(1, max_range_days))
        configured_log_file = log_file or os.environ.get("LOG_FILE") or "logs/wecom-ragflow-bridge.log"
        self._log_file = Path(configured_log_file).expanduser().resolve()
        self._log_name_pattern = re.compile(
            rf"^{re.escape(self._log_file.name)}(?:\.\d+|\.\d{{4}}-\d{{2}}-\d{{2}})?$"
        )

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get(f"{self._base_path}/messages", self._handle_messages)
        app.router.add_get(f"{self._base_path}/callback-logs", self._handle_callback_logs)
        app.router.add_get(f"{self._base_path}/logs", self._handle_log_files)
        app.router.add_get(f"{self._base_path}/logs/{{filename}}/content", self._handle_log_content)
        app.router.add_get(f"{self._base_path}/logs/{{filename}}/download", self._handle_log_download)

    async def _handle_log_files(self, request: web.Request) -> web.Response:
        unauthorized = self._authorize(request)
        if unauthorized:
            return unauthorized
        try:
            items = await asyncio.to_thread(self._list_log_files_sync)
            return web.json_response({"code": 0, "message": "ok", "data": {"items": items}})
        except Exception:
            logger.exception("List application log files failed")
            return _error(500, "读取日志文件列表失败")

    async def _handle_log_content(self, request: web.Request) -> web.Response:
        unauthorized = self._authorize(request)
        if unauthorized:
            return unauthorized
        try:
            path = self._resolve_log_file(request.match_info["filename"])
            tail_lines = _parse_int(request, "tail_lines", DEFAULT_LOG_TAIL_LINES, 1, MAX_LOG_TAIL_LINES)
            content, truncated = await asyncio.to_thread(_read_log_tail, path, tail_lines)
            return web.json_response(
                {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "filename": path.name,
                        "content": content,
                        "tail_lines": tail_lines,
                        "truncated": truncated,
                    },
                }
            )
        except FileNotFoundError:
            return _error(404, "日志文件不存在")
        except ValueError as e:
            return _error(400, str(e))
        except Exception:
            logger.exception("Read application log content failed")
            return _error(500, "读取日志内容失败")

    async def _handle_log_download(self, request: web.Request) -> web.StreamResponse:
        unauthorized = self._authorize(request)
        if unauthorized:
            return unauthorized
        try:
            path = self._resolve_log_file(request.match_info["filename"])
            return web.FileResponse(
                path,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}",
                },
            )
        except FileNotFoundError:
            return _error(404, "日志文件不存在")
        except ValueError as e:
            return _error(400, str(e))

    def _list_log_files_sync(self) -> list[dict]:
        parent = self._log_file.parent
        if not parent.is_dir():
            return []
        items = []
        for path in parent.iterdir():
            if not path.is_file() or not self._log_name_pattern.fullmatch(path.name):
                continue
            try:
                resolved = path.resolve(strict=True)
                if resolved.parent != parent:
                    continue
                stat = resolved.stat()
            except (OSError, RuntimeError):
                continue
            items.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "current": path.name == self._log_file.name,
                }
            )
        items.sort(key=lambda item: item["modified_at"], reverse=True)
        return items

    def _resolve_log_file(self, filename: str) -> Path:
        if Path(filename).name != filename or not self._log_name_pattern.fullmatch(filename):
            raise ValueError("无效的日志文件名")
        try:
            path = (self._log_file.parent / filename).resolve(strict=True)
        except (OSError, RuntimeError) as e:
            raise FileNotFoundError(filename) from e
        if path.parent != self._log_file.parent or not path.is_file():
            raise ValueError("无效的日志文件路径")
        return path

    async def _handle_messages(self, request: web.Request) -> web.Response:
        unauthorized = self._authorize(request)
        if unauthorized:
            return unauthorized
        try:
            common = self._parse_common_query(request)
            filters = _optional_filters(
                request,
                "messageid",
                "mode",
                "groupname",
                "groupnickname",
                "messagetype",
                "process_status",
            )
            rows = await self._store.query_messages(**common, **filters)
            return _success(rows, common["limit"])
        except ValueError as e:
            return _error(400, str(e))
        except Exception:
            logger.exception("Query message table failed")
            return _error(500, "查询 message 表失败")

    async def _handle_callback_logs(self, request: web.Request) -> web.Response:
        unauthorized = self._authorize(request)
        if unauthorized:
            return unauthorized
        try:
            common = self._parse_common_query(request)
            mode = request.query.get("mode", "").strip() or None
            rows = await self._store.query_callback_logs(**common, mode=mode)
            return _success(rows, common["limit"])
        except ValueError as e:
            return _error(400, str(e))
        except Exception:
            logger.exception("Query callback_log table failed")
            return _error(500, "查询 callback_log 表失败")

    def _authorize(self, request: web.Request) -> web.Response | None:
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied_token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(self._token, supplied_token.strip()):
            return _error(401, "未授权")
        return None

    def _parse_common_query(self, request: web.Request) -> dict[str, Any]:
        robot_id = _required(request, "robotid")
        start_time = _parse_datetime(_required(request, "start_time"), "start_time")
        end_time = _parse_datetime(_required(request, "end_time"), "end_time")
        if start_time >= end_time:
            raise ValueError("start_time 必须早于 end_time")
        if end_time - start_time > self._max_range:
            raise ValueError(f"查询时间范围不能超过 {self._max_range.days} 天")
        return {
            "robot_id": robot_id,
            "start_time": start_time,
            "end_time": end_time,
            "limit": _parse_int(request, "limit", DEFAULT_QUERY_LIMIT, 1, MAX_QUERY_LIMIT),
            "before_id": _parse_optional_positive_int(request, "before_id"),
        }


def _required(request: web.Request, name: str) -> str:
    value = request.query.get(name, "").strip()
    if not value:
        raise ValueError(f"缺少必要查询参数: {name}")
    return value


def _parse_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"{name} 必须是 ISO 8601 时间，例如 2026-07-01T00:00:00Z") from e
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_int(request: web.Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.query.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{name} 必须是整数") from e
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _parse_optional_positive_int(request: web.Request, name: str) -> int | None:
    raw = request.query.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{name} 必须是正整数") from e
    if value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def _optional_filters(request: web.Request, *names: str) -> dict[str, str | None]:
    return {name: request.query.get(name, "").strip() or None for name in names}


def _success(rows: list[dict], limit: int) -> web.Response:
    items = [_json_safe_row(row) for row in rows]
    next_before_id = items[-1]["id"] if len(items) == limit and items else None
    return web.json_response(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "items": items,
                "limit": limit,
                "next_before_id": next_before_id,
            },
        }
    )


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"code": status, "message": message}, status=status)


def _json_safe_row(row: dict) -> dict:
    result = {}
    for key, value in row.items():
        if key == "raw_json" and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        result[key] = _json_safe(value)
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _read_log_tail(path: Path, tail_lines: int) -> tuple[str, bool]:
    """Read a bounded number of lines from the end of a potentially large log."""
    file_size = path.stat().st_size
    position = file_size
    remaining_bytes = MAX_LOG_PREVIEW_BYTES
    newline_count = 0
    chunks = []

    with path.open("rb") as stream:
        while position > 0 and remaining_bytes > 0 and newline_count <= tail_lines:
            block_size = min(64 * 1024, position, remaining_bytes)
            position -= block_size
            remaining_bytes -= block_size
            stream.seek(position)
            chunk = stream.read(block_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    content = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    selected = "".join(lines[-tail_lines:])
    return selected, position > 0 or len(lines) > tail_lines
