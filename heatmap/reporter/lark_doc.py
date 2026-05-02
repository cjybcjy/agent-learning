import asyncio
import json
import re
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

    def _load_state(self) -> dict:
        if not self.state_file.exists():
            return {}
        return json.loads(self.state_file.read_text())

    def _load_token(self) -> str | None:
        return self._load_state().get("feishu_doc_token")

    def _save_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False))

    def _save_token(self, token: str) -> None:
        state = self._load_state()
        state["feishu_doc_token"] = token
        self._save_state(state)

    @staticmethod
    def _extract_document_id(result: dict) -> str | None:
        data = result.get("data", {})
        return (
            data.get("document_id")
            or data.get("document", {}).get("document_id")
            or result.get("document_id")
        )

    @staticmethod
    def _extract_archive_date(archive_xml: str) -> str:
        match = re.search(r"<heading2>([^<]+)</heading2>", archive_xml)
        if not match:
            raise RuntimeError(f"cannot extract archive date from: {archive_xml}")
        return match.group(1)

    @staticmethod
    def _render_document(today_xml: str, archive_xmls: list[str]) -> str:
        archive_body = "".join(archive_xmls) or '<p id="archive-anchor">（暂无历史归档）</p>'
        return (
            "<title>币圈市场热度日报</title>"
            "<heading1>📊 今日榜单</heading1>"
            f"{today_xml}"
            "<heading1>🗂 历史归档</heading1>"
            f"{archive_body}"
        )

    def _merge_archive(self, date: str, archive_xml: str) -> list[dict[str, str]]:
        state = self._load_state()
        existing = [entry for entry in state.get("archive_history", []) if entry.get("date") != date]
        existing.append({"date": date, "xml": archive_xml})
        existing.sort(key=lambda entry: entry["date"], reverse=True)
        state["archive_history"] = existing
        self._save_state(state)
        return existing

    async def _create_doc(self) -> str:
        result = await self.runner.run([
            "docs", "+create", "--api-version", "v2",
            "--content", INITIAL_DOC_XML,
        ])
        token = self._extract_document_id(result)
        if not token:
            raise RuntimeError(f"cannot extract document_id from: {result}")
        self._save_token(token)
        return token

    async def publish_today(self, today_xml: str, archive_xml: str) -> None:
        token = self._load_token() or await self._create_doc()
        date = self._extract_archive_date(archive_xml)
        history = self._merge_archive(date, archive_xml)
        full_doc_xml = self._render_document(today_xml, [entry["xml"] for entry in history])
        await self.runner.run([
            "docs", "+update", "--api-version", "v2",
            "--doc", token,
            "--command", "overwrite",
            "--doc-format", "xml",
            "--content", full_doc_xml,
        ])
