import asyncio
import logging
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from convert.pipeline import convert_file
from models import ConvertResult, Job

log = logging.getLogger(__name__)

Process = Callable[[Path, Path], Awaitable[ConvertResult]]


class JobQueue:
    """Runs conversions off the handler thread so a batch never blocks the bot."""

    def __init__(self, workers: int = 2, process: Process = convert_file):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._pending: list[Job] = []
        self._workers: list[asyncio.Task] = []
        self._count = workers
        self._process = process
        # one conversion at a time per user, so a batch finishes in the order it was sent
        self._locks: dict[int, asyncio.Lock] = {}

    async def start(self) -> None:
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self._count)]
        log.info("started %d conversion workers", self._count)

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def submit(self, job: Job) -> int:
        self._pending.append(job)
        await self._queue.put(job)
        return len(self._pending)

    async def drain(self) -> None:
        await self._queue.join()

    def depth(self) -> int:
        return sum(1 for job in self._pending if not job.cancelled)

    def pending_for(self, key: int) -> int:
        return sum(1 for job in self._pending if job.key == key and not job.cancelled)

    def cancel(self, key: int) -> int:
        dropped = [job for job in self._pending if job.key == key and not job.cancelled]
        for job in dropped:
            job.cancelled = True
        return len(dropped)

    async def _worker(self, index: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                if not job.cancelled:
                    async with self._lock_for(job.key):
                        await self._run(job)
            finally:
                self._forget(job)
                self._queue.task_done()

    def _lock_for(self, key: int) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    async def _run(self, job: Job) -> None:
        work_dir = Path(tempfile.mkdtemp(prefix="stickerloom_"))
        try:
            # cancelling cannot stop ffmpeg midway, but the answer is checked at every step
            await job.on_status("converting")
            source = await job.fetch(work_dir)
            if job.cancelled:
                return await self._give_up(job)
            result = await self._process(source, work_dir)
            if job.cancelled:
                return await self._give_up(job)
            await job.on_done(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("job %r failed", job.name)
            await job.on_error(exc)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _give_up(self, job: Job) -> None:
        log.info("job %r was cancelled, dropping its result", job.name)
        if job.on_cancel is not None:
            await job.on_cancel()

    def _forget(self, job: Job) -> None:
        try:
            self._pending.remove(job)
        except ValueError:
            pass
