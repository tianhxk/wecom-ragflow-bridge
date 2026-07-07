"""Small async scheduler for periodic background jobs."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger("scheduler")


@dataclass
class _PeriodicJob:
    name: str
    interval: float
    callback: Callable[[], Awaitable[None]]
    run_immediately: bool = False


class PeriodicTaskManager:
    """Owns periodic asyncio tasks and cancels them as one unit."""

    def __init__(self, owner: str):
        self._owner = owner
        self._jobs: list[_PeriodicJob] = []
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def add(
        self,
        name: str,
        interval: float,
        callback: Callable[[], Awaitable[None]],
        *,
        enabled: bool = True,
        run_immediately: bool = False,
    ) -> None:
        if not enabled:
            return
        if interval <= 0:
            raise ValueError(f"{name} interval must be positive")
        self._jobs.append(_PeriodicJob(name, interval, callback, run_immediately))

    def start(self) -> None:
        self._running = True
        for job in self._jobs:
            if job.name not in self._tasks:
                self._tasks[job.name] = asyncio.create_task(self._run_job(job))

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run_job(self, job: _PeriodicJob) -> None:
        logger.info("%s periodic task started: %s interval=%ss", self._owner, job.name, job.interval)
        try:
            if job.run_immediately:
                await job.callback()
            while self._running:
                await asyncio.sleep(job.interval)
                if self._running:
                    await job.callback()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s periodic task stopped after error: %s", self._owner, job.name)
