from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ProgressBus:
    """Pub/sub bus for streaming job progress events to SSE clients."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(job_id, [])
        try:
            subs.remove(queue)
        except ValueError:
            pass
        if not subs:
            self._subscribers.pop(job_id, None)

    async def publish(self, job_id: str, event: dict) -> None:
        for q in list(self._subscribers.get(job_id, [])):
            await q.put(event)

    def publish_sync(self, job_id: str, event: dict, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.run_coroutine_threadsafe(self.publish(job_id, event), loop)


class JobRunner:
    """Async job runner with configurable concurrency limit."""

    def __init__(self, max_concurrent: int, progress_bus: ProgressBus) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue: asyncio.Queue[tuple[str, Coroutine]] = asyncio.Queue()
        self._bus = progress_bus
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker(), name="job-runner")
        logger.debug("Job runner started")

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.debug("Job runner stopped")

    async def submit(self, job_id: str, coro: Coroutine) -> None:
        await self._queue.put((job_id, coro))
        logger.debug(f"Job {job_id} queued")

    async def _worker(self) -> None:
        while True:
            job_id, coro = await self._queue.get()
            asyncio.create_task(self._run(job_id, coro), name=f"job-{job_id}")
            self._queue.task_done()

    async def _run(self, job_id: str, coro: Coroutine) -> None:
        async with self._semaphore:
            logger.debug(f"Job {job_id} started")
            try:
                await coro
            except Exception as exc:
                logger.error(f"Job {job_id} failed with unhandled error: {exc}", exc_info=True)
                await self._bus.publish(job_id, {
                    "type": "error",
                    "message": str(exc),
                    "percent": 0,
                })
            logger.debug(f"Job {job_id} finished")


# Module-level singletons — initialized in app lifespan
_progress_bus: ProgressBus = ProgressBus()
_job_runner: JobRunner | None = None


def get_progress_bus() -> ProgressBus:
    return _progress_bus


def get_job_runner() -> JobRunner:
    if _job_runner is None:
        raise RuntimeError("JobRunner not initialized. Call init_job_runner() first.")
    return _job_runner


def init_job_runner(max_concurrent: int) -> JobRunner:
    global _job_runner
    _job_runner = JobRunner(max_concurrent, _progress_bus)
    return _job_runner
