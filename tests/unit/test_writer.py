import pytest
import asyncio
from datetime import datetime, timezone
from heatmap.store.writer import BatchWriter
from heatmap.store.dao import Store, RawMessage


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


async def test_batch_writer_flushes_on_batch_size(store, tmp_path):
    queue = asyncio.Queue()
    writer = BatchWriter(batch_size=2, dlq_dir=tmp_path / "dlq")
    task = asyncio.create_task(writer.run(queue, store))

    msg = RawMessage(
        platform="test", channel="@x", author_id="u1",
        content="hello", posted_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc)
    )
    await queue.put(msg)
    await queue.put(msg)
    await asyncio.sleep(0.5)

    cur = await store._db.execute("SELECT COUNT(*) FROM raw_messages")
    row = await cur.fetchone()
    assert row[0] == 2

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_batch_writer_dlq_on_failure(store, tmp_path):
    queue = asyncio.Queue()
    writer = BatchWriter(batch_size=1, dlq_dir=tmp_path / "dlq")

    # Pass a fake store that always fails
    class FakeStore:
        async def insert_message(self, m):
            raise RuntimeError("db down")

    task = asyncio.create_task(writer.run(queue, FakeStore()))
    msg = RawMessage(
        platform="test", channel="@x", author_id="u1",
        content="hello", posted_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc)
    )
    await queue.put(msg)
    await asyncio.sleep(0.3)

    dlq_files = list((tmp_path / "dlq").glob("*.jsonl"))
    assert len(dlq_files) >= 1

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
