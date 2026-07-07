"""MySQL persistence for WorkBot callback messages."""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("workbot-storage")


@dataclass
class MySQLConfig:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "workbot"
    charset: str = "utf8mb4"

    @classmethod
    def from_values(
        cls,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> "MySQLConfig":
        parsed_host = (host or "127.0.0.1").strip()
        parsed_port = port or 3306
        # Accept legacy values like "127.0.0.1 3306".
        if " " in parsed_host:
            host_part, _, port_part = parsed_host.partition(" ")
            parsed_host = host_part.strip() or parsed_host
            try:
                parsed_port = int(port_part.strip())
            except ValueError:
                logger.warning("MYSQL_HOST contains invalid port: %s", host)
        return cls(
            host=parsed_host,
            port=parsed_port,
            user=user or "root",
            password=password,
            database=database or "workbot",
        )


@dataclass
class WorkBotQueuedMessage:
    id: int
    robot_id: str
    search_text: str
    item: dict


@dataclass
class WorkBotCallbackRecord:
    id: int
    robot_id: str
    mode: str
    raw_json: str
    received_at: datetime


class WorkBotMessageStore:
    def __init__(self, config: MySQLConfig):
        self._config = config
        self._enabled = True
        try:
            import pymysql  # noqa: F401
        except ImportError:
            logger.error("PyMySQL is not installed; WorkBot message persistence is disabled")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def init(self) -> None:
        if not self._enabled:
            return
        await asyncio.to_thread(self._init_sync)

    async def save_log_item(self, payload: dict, item: dict, item_index: int) -> Optional[WorkBotQueuedMessage]:
        if not self._enabled:
            return None
        try:
            return await asyncio.to_thread(self._save_log_item_sync, payload, item, item_index)
        except Exception as e:
            logger.error("Persist WorkBot message failed: %s", e, exc_info=True)
            return None

    async def load_unprocessed_messages(self, limit: int) -> list[WorkBotQueuedMessage]:
        if not self._enabled:
            return []
        try:
            return await asyncio.to_thread(self._load_unprocessed_messages_sync, limit)
        except Exception as e:
            logger.error("Load unprocessed WorkBot messages failed: %s", e, exc_info=True)
            return []

    async def mark_processing(self, message_id: int) -> None:
        if not self._enabled:
            return
        try:
            await asyncio.to_thread(self._mark_processing_sync, message_id)
        except Exception as e:
            logger.error("Mark WorkBot message processing failed: id=%s error=%s", message_id, e, exc_info=True)

    async def mark_processed(self, message_id: int) -> None:
        if not self._enabled:
            return
        try:
            await asyncio.to_thread(self._mark_processed_sync, message_id)
        except Exception as e:
            logger.error("Mark WorkBot message processed failed: id=%s error=%s", message_id, e, exc_info=True)

    async def mark_failed(self, message_id: int, error: Exception) -> None:
        if not self._enabled:
            return
        try:
            await asyncio.to_thread(self._mark_failed_sync, message_id, str(error))
        except Exception as e:
            logger.error("Mark WorkBot message as failed failed: id=%s error=%s", message_id, e, exc_info=True)

    async def mark_skipped(self, message_id: int, reason: str) -> None:
        if not self._enabled:
            return
        try:
            await asyncio.to_thread(self._mark_skipped_sync, message_id, reason)
        except Exception as e:
            logger.error("Mark WorkBot message skipped failed: id=%s error=%s", message_id, e, exc_info=True)

    async def save_raw_callback(self, robot_id: str, mode: str, payload: dict) -> Optional[int]:
        """Persist the complete raw callback payload to the callback_log table."""
        if not self._enabled:
            return None
        try:
            return await asyncio.to_thread(self._save_raw_callback_sync, robot_id, mode, payload)
        except Exception as e:
            logger.error("Persist WorkBot raw callback failed: robotId=%s mode=%s error=%s", robot_id, mode, e, exc_info=True)
            return None

    async def query_messages(
        self,
        *,
        robot_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        before_id: Optional[int] = None,
        **filters,
    ) -> list[dict]:
        if not self._enabled:
            raise RuntimeError("WorkBot message persistence is disabled")
        return await asyncio.to_thread(
            self._query_messages_sync,
            robot_id,
            start_time,
            end_time,
            limit,
            before_id,
            filters,
        )

    async def query_callback_logs(
        self,
        *,
        robot_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        before_id: Optional[int] = None,
        mode: Optional[str] = None,
    ) -> list[dict]:
        if not self._enabled:
            raise RuntimeError("WorkBot message persistence is disabled")
        return await asyncio.to_thread(
            self._query_callback_logs_sync,
            robot_id,
            start_time,
            end_time,
            limit,
            before_id,
            mode,
        )

    def _connect(self, *, with_database: bool = True):
        import pymysql

        kwargs = {
            "host": self._config.host,
            "port": self._config.port,
            "user": self._config.user,
            "password": self._config.password,
            "charset": self._config.charset,
            "autocommit": True,
        }
        if with_database:
            kwargs["database"] = self._config.database
        return pymysql.connect(**kwargs)

    def _init_sync(self) -> None:
        database = _mysql_identifier(self._config.database)
        with self._connect(with_database=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS `message` (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        messageid VARCHAR(64) NOT NULL,
                        messagetime DATETIME(6) NOT NULL,
                        robotid VARCHAR(128) NOT NULL,
                        mode VARCHAR(32) NOT NULL,
                        groupname VARCHAR(255) NOT NULL,
                        messagetype VARCHAR(64) NOT NULL,
                        groupnickname VARCHAR(255) NULL,
                        corpsName VARCHAR(255) NULL,
                        role VARCHAR(32) NULL,
                        message TEXT NULL,
                        extra TEXT NULL,
                        raw_json JSON NULL,
                        dedupe_hash CHAR(64) NOT NULL,
                        process_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                        process_attempts INT UNSIGNED NOT NULL DEFAULT 0,
                        processing_started_at DATETIME(6) NULL,
                        processed_at DATETIME(6) NULL,
                        last_error TEXT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        UNIQUE KEY uk_messageid (messageid),
                        UNIQUE KEY uk_dedupe_hash (dedupe_hash),
                        KEY idx_messagetime (messagetime),
                        KEY idx_robot_time (robotid, messagetime),
                        KEY idx_group_time (groupname, groupnickname,messagetime),
                        KEY idx_mode_type_time (mode, messagetype, messagetime),
                        KEY idx_process_status_id (process_status, id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                )
                _ensure_column(cur, "message", "dedupe_hash", "ALTER TABLE `message` ADD COLUMN dedupe_hash CHAR(64) NULL AFTER raw_json")
                _ensure_index(cur, "message", "uk_dedupe_hash", "ALTER TABLE `message` ADD UNIQUE KEY uk_dedupe_hash (dedupe_hash)")
                cur.execute("UPDATE `message` SET dedupe_hash = SHA2(CONCAT(COALESCE(groupname, ''), '|', COALESCE(groupnickname, ''), '|', COALESCE(CAST(raw_json AS CHAR), '')), 256) WHERE dedupe_hash IS NULL")
                cur.execute("ALTER TABLE `message` MODIFY dedupe_hash CHAR(64) NOT NULL")
                _ensure_column(cur, "message", "process_status", "ALTER TABLE `message` ADD COLUMN process_status VARCHAR(32) NULL AFTER dedupe_hash")
                _ensure_column(cur, "message", "process_attempts", "ALTER TABLE `message` ADD COLUMN process_attempts INT UNSIGNED NOT NULL DEFAULT 0 AFTER process_status")
                _ensure_column(cur, "message", "processing_started_at", "ALTER TABLE `message` ADD COLUMN processing_started_at DATETIME(6) NULL AFTER process_attempts")
                _ensure_column(cur, "message", "processed_at", "ALTER TABLE `message` ADD COLUMN processed_at DATETIME(6) NULL AFTER processing_started_at")
                _ensure_column(cur, "message", "last_error", "ALTER TABLE `message` ADD COLUMN last_error TEXT NULL AFTER processed_at")
                cur.execute("UPDATE `message` SET process_status = 'done', processed_at = COALESCE(processed_at, messagetime) WHERE process_status IS NULL")
                cur.execute("ALTER TABLE `message` MODIFY process_status VARCHAR(32) NOT NULL DEFAULT 'pending'")
                _ensure_index(cur, "message", "idx_process_status_id", "ALTER TABLE `message` ADD KEY idx_process_status_id (process_status, id)")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS `callback_log` (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        robotid VARCHAR(128) NOT NULL,
                        mode VARCHAR(32) NOT NULL,
                        raw_json JSON NOT NULL,
                        received_at DATETIME(6) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        KEY idx_robotid (robotid),
                        KEY idx_mode (mode),
                        KEY idx_received_at (received_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                )
                _ensure_index(
                    cur,
                    "callback_log",
                    "idx_robot_received_at",
                    "ALTER TABLE `callback_log` ADD KEY idx_robot_received_at (robotid, received_at)",
                )
        logger.info(
            "WorkBot message persistence initialized: mysql://%s:%s/%s",
            self._config.host,
            self._config.port,
            self._config.database,
        )

    def _save_log_item_sync(self, payload: dict, item: dict, item_index: int) -> Optional[WorkBotQueuedMessage]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        data = item.get("data", {}) if isinstance(item.get("data", {}), dict) else {}
        robot_id = str(payload.get("robotId", "")).strip()
        mode = str(payload.get("mode", "")).strip()
        group_name = str(payload.get("searchText", "")).strip()
        msg_type = str(item.get("type", "")).strip()
        role = str(item.get("role", "")).strip()
        message = str(data.get("message", "")).strip()
        extra = str(data.get("extra", "")).strip()
        group_nickname = str(data.get("groupNickname", "")).strip() or None
        corps_name = str(data.get("corpsName", "")).strip() or None
        raw_json = json.dumps({"payload": payload, "item": item}, ensure_ascii=False, default=str)
        message_id = _build_message_id(robot_id, mode, group_name, item_index, role, msg_type, data, now)
        dedupe_hash = _build_dedupe_hash(group_name, group_nickname, raw_json)

        exists_sql = "SELECT id, process_status FROM `message` WHERE dedupe_hash = %s LIMIT 1"
        insert_sql = """
            INSERT INTO `message` (
                messageid, messagetime, robotid, mode, groupname, messagetype,
                groupnickname, corpsName, role, message, extra, raw_json, dedupe_hash,
                process_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """
        params = (
            message_id,
            now,
            robot_id,
            mode,
            group_name,
            msg_type,
            group_nickname,
            corps_name,
            role or None,
            message or None,
            extra or None,
            raw_json,
            dedupe_hash,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(exists_sql, (dedupe_hash,))
                existing = cur.fetchone()
                if existing:
                    return None
                try:
                    cur.execute(insert_sql, params)
                    db_id = cur.lastrowid
                except Exception as e:
                    if _is_duplicate_key_error(e):
                        return None
                    raise
        return WorkBotQueuedMessage(id=int(db_id), robot_id=robot_id, search_text=group_name, item=item)

    def _load_unprocessed_messages_sync(self, limit: int) -> list[WorkBotQueuedMessage]:
        sql = """
            SELECT id, robotid, groupname, raw_json
            FROM `message`
            WHERE process_status IN ('pending', 'failed', 'processing')
            ORDER BY id ASC
            LIMIT %s
        """
        messages = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (max(1, limit),))
                for db_id, robot_id, group_name, raw_json in cur.fetchall():
                    item = _extract_item_from_raw_json(raw_json)
                    if item is None:
                        logger.warning("Skip persisted WorkBot message with invalid raw_json: id=%s", db_id)
                        continue
                    messages.append(
                        WorkBotQueuedMessage(
                            id=int(db_id),
                            robot_id=str(robot_id or ""),
                            search_text=str(group_name or ""),
                            item=item,
                        )
                    )
        return messages

    def _mark_processing_sync(self, message_id: int) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE `message`
                    SET process_status = 'processing',
                        process_attempts = process_attempts + 1,
                        processing_started_at = %s,
                        last_error = NULL
                    WHERE id = %s
                    """,
                    (now, message_id),
                )

    def _mark_processed_sync(self, message_id: int) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE `message`
                    SET process_status = 'done',
                        processed_at = %s,
                        last_error = NULL
                    WHERE id = %s
                    """,
                    (now, message_id),
                )

    def _mark_failed_sync(self, message_id: int, error: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE `message`
                    SET process_status = 'failed',
                        last_error = %s
                    WHERE id = %s
                    """,
                    (error[:4000], message_id),
                )

    def _mark_skipped_sync(self, message_id: int, reason: str) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE `message`
                    SET process_status = 'skipped',
                        processed_at = %s,
                        last_error = %s
                    WHERE id = %s
                    """,
                    (now, reason[:4000], message_id),
                )

    def _save_raw_callback_sync(self, robot_id: str, mode: str, payload: dict) -> Optional[int]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        raw_json = json.dumps(payload, ensure_ascii=False, default=str)
        insert_sql = """
            INSERT INTO `callback_log` (robotid, mode, raw_json, received_at)
            VALUES (%s, %s, %s, %s)
        """
        db_id = None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(insert_sql, (robot_id, mode, raw_json, now))
                db_id = cur.lastrowid
        return int(db_id) if db_id else None

    def _query_messages_sync(
        self,
        robot_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        before_id: Optional[int],
        filters: dict,
    ) -> list[dict]:
        columns = {
            "messageid": "messageid",
            "mode": "mode",
            "groupname": "groupname",
            "groupnickname": "groupnickname",
            "messagetype": "messagetype",
            "process_status": "process_status",
        }
        conditions = ["robotid = %s", "messagetime >= %s", "messagetime < %s"]
        params = [robot_id, start_time, end_time]
        for name, column in columns.items():
            value = filters.get(name)
            if value is not None:
                conditions.append(f"`{column}` = %s")
                params.append(value)
        if before_id is not None:
            conditions.append("id < %s")
            params.append(before_id)
        params.append(limit)
        sql = (
            "SELECT id, messageid, messagetime, robotid, mode, groupname, "
            "messagetype, groupnickname, corpsName, role, message, extra, "
            "raw_json, process_status, process_attempts, processing_started_at, "
            "processed_at, last_error, created_at FROM `message` WHERE "
            + " AND ".join(conditions)
            + " ORDER BY id DESC LIMIT %s"
        )
        return self._fetch_dict_rows(sql, params)

    def _query_callback_logs_sync(
        self,
        robot_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int,
        before_id: Optional[int],
        mode: Optional[str],
    ) -> list[dict]:
        conditions = ["robotid = %s", "received_at >= %s", "received_at < %s"]
        params = [robot_id, start_time, end_time]
        if mode is not None:
            conditions.append("mode = %s")
            params.append(mode)
        if before_id is not None:
            conditions.append("id < %s")
            params.append(before_id)
        params.append(limit)
        sql = (
            "SELECT id, robotid, mode, raw_json, received_at, created_at "
            "FROM `callback_log` WHERE "
            + " AND ".join(conditions)
            + " ORDER BY id DESC LIMIT %s"
        )
        return self._fetch_dict_rows(sql, params)

    def _fetch_dict_rows(self, sql: str, params: list) -> list[dict]:
        import pymysql

        with self._connect() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())


def _extract_item_from_raw_json(raw_json) -> Optional[dict]:
    if isinstance(raw_json, (bytes, bytearray)):
        raw_json = raw_json.decode("utf-8")
    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw_json, dict):
        return None
    item = raw_json.get("item")
    return item if isinstance(item, dict) else None


def _is_duplicate_key_error(error: Exception) -> bool:
    return bool(getattr(error, "args", ())) and error.args[0] == 1062


def _ensure_column(cur, table_name: str, column_name: str, ddl: str) -> None:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
        """,
        (table_name, column_name),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(ddl)


def _ensure_index(cur, table_name: str, index_name: str, ddl: str) -> None:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s
        """,
        (table_name, index_name),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(ddl)


def _mysql_identifier(value: str) -> str:
    if not value or not value.replace("_", "").isalnum():
        raise ValueError(f"Invalid MySQL identifier: {value}")
    return value


def _build_dedupe_hash(group_name: str, group_nickname: Optional[str], raw_json: str) -> str:
    source = "|".join(
        (
            _dedupe_part(group_name),
            _dedupe_part(group_nickname),
            _dedupe_part(raw_json),
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _dedupe_part(value: Optional[str]) -> str:
    return "" if value is None else str(value)


def _build_message_id(
    robot_id: str,
    mode: str,
    group_name: str,
    item_index: int,
    role: str,
    msg_type: str,
    data: dict,
    received_at: datetime,
) -> str:
    source = json.dumps(
        {
            "robotId": robot_id,
            "mode": mode,
            "groupName": group_name,
            "itemIndex": item_index,
            "role": role,
            "type": msg_type,
            "data": data,
            "receivedAt": received_at.isoformat(timespec="microseconds"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
