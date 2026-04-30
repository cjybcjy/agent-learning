import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

INITIAL_DOC_XML = (
    "<title>币圈市场热度日报</title>"
    "<heading1>📊 今日榜单</heading1>"
    "<p id=\"cover-anchor\">（首次创建占位）</p>"
    "<heading1>🗂 历史归档</heading1>"
    "<p id=\"archive-anchor\">（每日 append 折叠块到此 anchor 之后）</p>"
)


class CommandRunner(Protocol):
    async def run(self, args: list[str]) -> dict: ...


class LarkCliRunner:
    async def run(self, args: list[str]) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"lark-cli failed: {err.decode()}")
        try:
            return json.loads(out.decode())
        except json.JSONDecodeError:
            return {"raw": out.decode()}


@dataclass
class LarkPublisher:
    state_file: Path
    runner: CommandRunner

    def _load_token(self) -> str | None:
        if not self.state_file.exists():
            return None
        return json.loads(self.state_file.read_text()).get("feishu_doc_token")

    def _save_token(self, token: str) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"feishu_doc_token": token}))

    async def _create_doc(self) -> str:
        result = await self.runner.run([
            "docs", "+create", "--api-version", "v2",
            "--content", INITIAL_DOC_XML,
        ])
        token = result.get("data", {}).get("document_id") or result.get("document_id")
        if not token:
            raise RuntimeError(f"cannot extract document_id from: {result}")
        self._save_token(token)
        return token

    async def publish_today(self, today_xml: str, archive_xml: str) -> None:
        token = self._load_token() or await self._create_doc()
        await self.runner.run([
            "docs", "+update", "--api-version", "v2",
            "--doc", token,
            "--command", "block_replace",
            "--target", "cover-anchor",
            "--content", today_xml,
        ])
        await self.runner.run([
            "docs", "+update", "--api-version", "v2",
            "--doc", token,
            "--command", "append",
            "--content", archive_xml,
        ])
