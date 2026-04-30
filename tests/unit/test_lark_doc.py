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
            return {"data": {"document_id": self.return_token}}
        return {"ok": True}


@pytest.fixture
def state_file(tmp_path: Path):
    return tmp_path / "state.json"


async def test_first_run_creates_doc_and_persists_token(state_file):
    runner = FakeRunner()
    pub = LarkPublisher(state_file=state_file, runner=runner)
    await pub.publish_today(today_xml="<p>today</p>", archive_xml="<collapsible/>")
    assert any("+create" in a for a in runner.calls)
    saved = json.loads(state_file.read_text())
    assert saved["feishu_doc_token"] == "doctok123"


async def test_second_run_uses_persisted_token_only_updates(state_file):
    state_file.write_text(json.dumps({"feishu_doc_token": "tok"}))
    runner = FakeRunner()
    pub = LarkPublisher(state_file=state_file, runner=runner)
    await pub.publish_today(today_xml="<p>today</p>", archive_xml="<collapsible/>")
    flat = [" ".join(a) for a in runner.calls]
    assert not any("+create" in s for s in flat)
    assert any("block_replace" in s for s in flat)
    assert any("append" in s for s in flat)
