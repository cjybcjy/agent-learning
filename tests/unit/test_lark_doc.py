import json
from pathlib import Path
import pytest
from heatmap.reporter.lark_doc import LarkPublisher


class FakeRunner:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.return_token = "doctok123"

    async def run(self, args: list[str]) -> dict:
        self.calls.append(args)
        if "+create" in args:
            return {"data": {"document": {"document_id": self.return_token}}}
        return {"ok": True}


@pytest.fixture
def state_file(tmp_path: Path):
    return tmp_path / "state.json"


async def test_first_run_creates_doc_and_persists_token(state_file):
    runner = FakeRunner()
    pub = LarkPublisher(state_file=state_file, runner=runner)
    await pub.publish_today(
        today_xml="<p>today</p>",
        archive_xml="<collapsible><heading2>2026-05-01</heading2></collapsible>",
    )
    assert any("+create" in a for a in runner.calls)
    saved = json.loads(state_file.read_text())
    assert saved["feishu_doc_token"] == "doctok123"
    assert saved["archive_history"][0]["date"] == "2026-05-01"


async def test_second_run_uses_persisted_token_only_updates(state_file):
    state_file.write_text(json.dumps({"feishu_doc_token": "tok"}))
    runner = FakeRunner()
    pub = LarkPublisher(state_file=state_file, runner=runner)
    await pub.publish_today(
        today_xml="<p>today</p>",
        archive_xml="<collapsible><heading2>2026-05-01</heading2></collapsible>",
    )
    flat = [" ".join(a) for a in runner.calls]
    assert not any("+create" in s for s in flat)
    assert any("overwrite" in s for s in flat)
    assert any("--doc-format xml" in s for s in flat)


def test_extract_document_id_supports_old_and_new_shapes():
    assert LarkPublisher._extract_document_id({"data": {"document_id": "old"}}) == "old"
    assert LarkPublisher._extract_document_id({"data": {"document": {"document_id": "new"}}}) == "new"
    assert LarkPublisher._extract_document_id({"document_id": "top"}) == "top"


def test_render_document_contains_today_and_archive_sections():
    rendered = LarkPublisher._render_document(
        "<p>today</p>",
        ["<collapsible><heading2>2026-05-01</heading2></collapsible>"],
    )
    assert "📊 今日榜单" in rendered
    assert "🗂 历史归档" in rendered
    assert "2026-05-01" in rendered
