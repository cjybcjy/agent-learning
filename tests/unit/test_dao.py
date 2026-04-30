import pytest
from datetime import datetime, timezone
from heatmap.store.dao import Store, RawMessage, Mention

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_insert_and_query_message(store):
    msg = RawMessage(
        platform="telegram", channel="@x", author_id="u1",
        content="$DOGE to the moon", posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
        fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
    )
    msg_id = await store.insert_message(msg)
    assert msg_id > 0

async def test_insert_mentions_and_count(store):
    msg_id = await store.insert_message(RawMessage(
        platform="telegram", channel="@x", author_id="u1",
        content="DOGE", posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
        fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
    ))
    await store.insert_mentions([Mention(message_id=msg_id, symbol="DOGE",
        matched_alias="DOGE", is_ambiguous=False, confidence=1.0)])
    counts = await store.daily_mention_counts("2026-04-30")
    assert counts["DOGE"] == 1
