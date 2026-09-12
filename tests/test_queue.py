import asyncio
from pathlib import Path

import pytest

from convert.queue import JobQueue
from models import ConvertResult, Job


def result_for(path: Path) -> ConvertResult:
    return ConvertResult(path=path, width=512, height=512, duration=1.0, size=1024, attempts=1)


def make_job(key: int, name: str, log: list, fail: bool = False) -> Job:
    async def fetch(work_dir: Path) -> Path:
        target = work_dir / name
        target.write_bytes(b"source")
        return target

    async def on_status(text: str) -> None:
        log.append((name, "status", text))

    async def on_done(result: ConvertResult) -> None:
        log.append((name, "done", result.size))

    async def on_error(exc: Exception) -> None:
        log.append((name, "error", type(exc).__name__))

    job = Job(key=key, name=name, fetch=fetch, on_status=on_status,
              on_done=on_done, on_error=on_error)
    job.fail = fail
    return job


async def fake_process(src: Path, work_dir: Path) -> ConvertResult:
    await asyncio.sleep(0)
    return result_for(src)


async def exploding_process(src: Path, work_dir: Path) -> ConvertResult:
    raise RuntimeError("boom")


@pytest.fixture
async def queue():
    q = JobQueue(workers=1, process=fake_process)
    await q.start()
    yield q
    await q.stop()


async def test_jobs_run_in_submission_order(queue):
    log = []
    for i in range(4):
        await queue.submit(make_job(1, f"file{i}", log))
    await queue.drain()

    assert [name for name, kind, _ in log if kind == "done"] == [f"file{i}" for i in range(4)]


async def test_position_grows_with_the_backlog(queue):
    log = []
    positions = [await queue.submit(make_job(1, f"file{i}", log)) for i in range(3)]
    await queue.drain()

    assert positions == sorted(positions)
    assert positions[0] == 1


async def test_failure_is_reported_and_the_pool_survives():
    q = JobQueue(workers=1, process=exploding_process)
    await q.start()
    log = []
    await q.submit(make_job(1, "bad", log))
    await q.drain()

    q._process = fake_process
    await q.submit(make_job(1, "good", log))
    await q.drain()
    await q.stop()

    assert ("bad", "error", "RuntimeError") in log
    assert ("good", "done", 1024) in log


async def test_cancelled_jobs_never_run(queue):
    log = []
    for i in range(3):
        await queue.submit(make_job(7, f"file{i}", log))
    dropped = queue.cancel(7)
    await queue.drain()

    assert dropped > 0
    assert len([1 for _, kind, _ in log if kind == "done"]) == 3 - dropped


async def test_cancel_leaves_other_users_alone(queue):
    log = []
    await queue.submit(make_job(1, "mine", log))
    await queue.submit(make_job(2, "theirs", log))
    queue.cancel(1)
    await queue.drain()

    assert ("theirs", "done", 1024) in log


async def test_pending_counts_only_that_user(queue):
    log = []
    await queue.submit(make_job(1, "a", log))
    await queue.submit(make_job(1, "b", log))
    await queue.submit(make_job(2, "c", log))

    assert queue.pending_for(1) == 2
    assert queue.pending_for(2) == 1
    await queue.drain()
    assert queue.pending_for(1) == 0


async def test_work_directory_is_removed_after_the_job(queue):
    seen = []

    async def watching_process(src: Path, work_dir: Path):
        seen.append(work_dir)
        return result_for(src)

    queue._process = watching_process
    await queue.submit(make_job(1, "x", []))
    await queue.drain()

    assert seen and not seen[0].exists()
