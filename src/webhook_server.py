"""Shared aiohttp webhook server helpers."""

import logging
from typing import Protocol

from aiohttp import web

logger = logging.getLogger("webhook-server")


class RouteProvider(Protocol):
    def add_routes(self, app: web.Application) -> None:
        ...


class DebugAccessLogger(web.AccessLogger):
    @property
    def enabled(self) -> bool:
        return self.logger.isEnabledFor(logging.DEBUG)

    def log(self, request, response, time) -> None:
        self.logger.debug(self._format_line(request, response, time))


class SharedWebhookServer:
    def __init__(self, host: str, port: int, routes: list[RouteProvider]):
        self._host = host
        self._port = port
        self._routes = routes
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = web.Application()
        for route_provider in self._routes:
            route_provider.add_routes(app)
        self._runner = web.AppRunner(app, access_log_class=DebugAccessLogger)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        logger.info("Shared webhook server started at http://%s:%s", self._host, self._port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
