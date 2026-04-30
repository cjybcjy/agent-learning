import json
from datetime import datetime
from pathlib import Path
import pytest
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry
from heatmap.aggregator.pipeline import run_daily_aggregation
from heatmap.reporter.templates import render_today_table, render_archive_collapsible
from heatmap.reporter.lark_doc import LarkPublisher

class FakeRunner:
    def __init__(self): self.calls = []
    async def run(self, args):
        self.calls.append(args)
        if "+create" in args: return {"data": {"document_id": "tok"}}
        return {"ok": True}

@pytest.mark.asyncio
async def test_end_to_end(tmp_path: Path):
    fixture = Path(__file__).parent.parent / "fixtures" / "sample_messages.jsonl"
    store = Store(tmp_path / "t.db"); await store.init()
    ext = AhoCorasickExtractor([
        AliasEntry("AAA", "AAA", False, "seed"),
        AliasEntry("BBB", "BBB", False, "seed"),
    ])
    for line in fixture.read_text().splitlines():
        rec = json.loads(line)
        dt = datetime.fromisoformat(rec["posted_at"])
        mid = await store.insert_message(RawMessage(
            platform=rec["platform"], channel=rec["channel"], author_id=rec["author"],
            content=rec["content"], posted_at=dt, fetched_at=dt,
        ))
        hits = ext.extract(rec["content"])
        if hits:
            await store.insert_mentions([
                Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0) for h in hits
            ])
    top = await run_daily_aggregation(store, "2026-04-30",
        alpha_min=0.5, beta_min=1.5, stage_a_top_n=50, stage_b_top_n=10)
    assert top and top[0].symbol == "AAA"

    today_xml = render_today_table(top, "2026-04-30")
    archive_xml = render_archive_collapsible(top, "2026-04-30")
    pub = LarkPublisher(state_file=tmp_path / "state.json", runner=FakeRunner())
    await pub.publish_today(today_xml=today_xml, archive_xml=archive_xml)
    await store.close()
