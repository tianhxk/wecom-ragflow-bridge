"""Application service construction helpers."""

import logging
from dataclasses import dataclass

import aiohttp

from chat_client import ChatClient, create_chat_client
from config import Config
from media_service import WeComImageService
from message_extractor import MessageExtractor
from mineru_client import MinerUClient
from session import SessionManager
from wechat_kf import WeChatKFBridge, WeChatKFClient
from wecom_api import WeComAPIClient
from wecom_archive import WeComArchiveConfig, WeComArchiveService, WeComArchiveStore
from workbot import WorkBotBridge, WorkBotClient
from workbot_query_api import WorkBotQueryApi
from workbot_storage import MySQLConfig, WorkBotMessageStore

logger = logging.getLogger("service-factory")


@dataclass
class ServiceBundle:
    http_session: aiohttp.ClientSession
    chat_client: ChatClient
    wecom_api: WeComAPIClient
    message_extractor: MessageExtractor
    kf_bridge: WeChatKFBridge | None = None
    workbot_bridge: WorkBotBridge | None = None
    archive_service: WeComArchiveService | None = None


class ServiceFactory:
    def __init__(self, config: Config, sessions: SessionManager):
        self._config = config
        self._sessions = sessions

    def create(self, http_session: aiohttp.ClientSession) -> ServiceBundle:
        chat_client = create_chat_client(self._config, http_session)
        mineru = self._create_mineru_client(http_session)
        message_extractor = MessageExtractor(
            mineru,
            WeComImageService(http_session, self._config.media_dir),
        )
        return ServiceBundle(
            http_session=http_session,
            chat_client=chat_client,
            wecom_api=self._create_wecom_api(http_session),
            message_extractor=message_extractor,
            kf_bridge=self._create_kf_bridge(http_session, chat_client),
            workbot_bridge=self._create_workbot_bridge(http_session, chat_client),
            archive_service=self._create_archive_service(),
        )

    def _create_wecom_api(self, http_session: aiohttp.ClientSession) -> WeComAPIClient:
        return WeComAPIClient(
            http_session,
            self._config.wecom_corp_id,
            self._config.wecom_bot_id,
            self._config.wecom_secret,
        )

    def _create_mineru_client(self, http_session: aiohttp.ClientSession) -> MinerUClient | None:
        if not self._config.mineru_api_key:
            logger.warning("MINERU_API_KEY is not configured; image OCR is disabled")
            return None
        return MinerUClient(
            http_session,
            self._config.mineru_api_base,
            self._config.mineru_api_key,
            self._config.mineru_ocr_method,
        )

    def _create_kf_bridge(
        self,
        http_session: aiohttp.ClientSession,
        chat_client: ChatClient,
    ) -> WeChatKFBridge | None:
        if not self._config.wecom_kf_enabled:
            return None
        return WeChatKFBridge(
            WeChatKFClient(
                http_session,
                self._config.wecom_corp_id,
                self._config.wecom_kf_secret,
            ),
            chat_client,
            self._sessions,
            self._config.wecom_kf_open_kfid,
            self._config.wecom_kf_callback_token,
            self._config.wecom_kf_encoding_aes_key,
            self._config.wecom_corp_id,
            self._config.wecom_kf_webhook_host,
            self._config.wecom_kf_webhook_port,
            self._config.wecom_kf_webhook_path,
        )

    def _create_workbot_bridge(
        self,
        http_session: aiohttp.ClientSession,
        chat_client: ChatClient,
    ) -> WorkBotBridge | None:
        if not self._config.workbot_enabled:
            return None
        workbot_store = WorkBotMessageStore(
            MySQLConfig.from_values(
                self._config.mysql_host,
                self._config.mysql_port,
                self._config.mysql_user,
                self._config.mysql_password,
                self._config.mysql_dbname,
            )
        )
        query_api = None
        if self._config.workbot_query_api_token:
            query_api = WorkBotQueryApi(
                workbot_store,
                self._config.workbot_query_api_token,
                self._config.workbot_query_api_path,
                self._config.workbot_query_max_range_days,
            )
        return WorkBotBridge(
            WorkBotClient(http_session, self._config.workbot_base_url),
            chat_client,
            self._sessions,
            self._config.workbot_webhook_host,
            self._config.workbot_webhook_port,
            self._config.workbot_webhook_path,
            self._config.workbot_robot_ids,
            self._config.workbot_callback_urls,
            self._config.workbot_bot_nicknames,
            workbot_store,
            query_api,
        )

    def _create_archive_service(self) -> WeComArchiveService | None:
        if not self._config.wecom_archive_enabled:
            return None
        store = WeComArchiveStore(
            MySQLConfig.from_values(
                self._config.mysql_host,
                self._config.mysql_port,
                self._config.mysql_user,
                self._config.mysql_password,
                self._config.mysql_dbname,
            )
        )
        archive_config = WeComArchiveConfig(
            enabled=self._config.wecom_archive_enabled,
            corp_id=self._config.wecom_corp_id,
            secret=self._config.wecom_archive_secret,
            private_key=self._config.wecom_archive_private_key,
            private_key_path=self._config.wecom_archive_private_key_path,
            private_key_map=self._config.wecom_archive_private_key_map,
            sdk_path=self._config.wecom_archive_sdk_path,
            poll_interval=self._config.wecom_archive_poll_interval,
            limit=self._config.wecom_archive_limit,
            timeout=self._config.wecom_archive_timeout,
            start_seq=self._config.wecom_archive_start_seq,
            proxy=self._config.wecom_archive_proxy,
            proxy_password=self._config.wecom_archive_proxy_password,
            cursor_key=self._config.wecom_archive_cursor_key,
            webhook_host=self._config.wecom_archive_webhook_host,
            webhook_port=self._config.wecom_archive_webhook_port,
            webhook_path=self._config.wecom_archive_webhook_path,
            webhook_token=self._config.wecom_archive_callback_token,
            encoding_aes_key=self._config.wecom_archive_encoding_aes_key,
            poll_enabled=self._config.wecom_archive_poll_enabled,
        )
        return WeComArchiveService(archive_config, store)

