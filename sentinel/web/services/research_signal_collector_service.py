from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

import yaml

from sentinel.config import AppSettings


class ResearchSignalCollectorService:
    """Collect external research signals into the Agent snapshot format."""

    def __init__(
        self,
        config_dir: Path | str | None = None,
        output_path: Path | str | None = None,
        source_config_path: Path | str | None = None,
        fetch_text: Callable[[str], str] | None = None,
        today: date | str | None = None,
    ) -> None:
        settings = AppSettings()
        self.config_dir = Path(config_dir) if config_dir is not None else settings.resolved_config_dir
        self.output_path = (
            Path(output_path)
            if output_path is not None
            else settings.database_path.parent / "research_external_signals.json"
        )
        self.source_config_path = (
            Path(source_config_path)
            if source_config_path is not None
            else self.config_dir / "research_signal_sources.yaml"
        )
        self.fetch_text = fetch_text or _fetch_url_text
        self.today = _coerce_date(today)

    def ensure_daily_snapshot(self) -> dict[str, Any]:
        existing = self._read_existing_snapshot()
        if existing is not None:
            generated_at = _parse_date(str(existing.get("generated_at", ""))[:10])
            if generated_at == self.today:
                return existing
        if not self.source_config_path.exists():
            return existing or self._empty_snapshot()
        return self.collect()

    def collect(self) -> dict[str, Any]:
        source_config = self._load_source_config()
        sources = source_config.get("sources", [])
        if not isinstance(sources, list):
            sources = []

        items: list[dict[str, Any]] = []
        source_count = 0
        for source in sources:
            if not isinstance(source, dict) or not source.get("enabled", True):
                continue
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            source_count += 1
            try:
                raw_text = self.fetch_text(url)
            except Exception as exc:
                items.append(_error_item(source, str(exc)))
                continue
            items.extend(self._parse_source_items(source, raw_text))

        snapshot = {
            "generated_at": datetime.combine(
                self.today, datetime.now().time()
            ).isoformat(timespec="seconds"),
            "source_count": source_count,
            "items": _dedupe_items(items),
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snapshot

    def _load_source_config(self) -> dict[str, Any]:
        if not self.source_config_path.exists():
            return {}
        data = yaml.safe_load(self.source_config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _read_existing_snapshot(self) -> dict[str, Any] | None:
        if not self.output_path.exists():
            return None
        try:
            payload = json.loads(self.output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.combine(
                self.today, datetime.now().time()
            ).isoformat(timespec="seconds"),
            "source_count": 0,
            "items": [],
        }

    def _parse_source_items(self, source: dict[str, Any], raw_text: str) -> list[dict[str, Any]]:
        kind = str(source.get("kind") or "rss").lower()
        if kind == "json":
            records = _parse_json_records(raw_text, str(source.get("items_path") or ""))
        else:
            records = _parse_rss_records(raw_text)
        items = [self._normalize_record(source, record) for record in records]
        return [item for item in items if item]

    def _normalize_record(
        self,
        source: dict[str, Any],
        record: dict[str, Any],
    ) -> dict[str, Any]:
        fields = source.get("fields", {})
        fields = fields if isinstance(fields, dict) else {}
        title = _field(record, fields.get("title"), "title")
        url = _field(record, fields.get("url"), "url")
        published_at = _field(record, fields.get("published_at"), "published_at")
        symbol = _field(record, fields.get("symbol"), "symbol")

        text = " ".join(
            str(part)
            for part in [
                title,
                record.get("summary"),
                record.get("description"),
                record.get("secName"),
            ]
            if part
        )
        rule = _match_rule(source.get("keyword_rules", []), text)
        if source.get("require_keyword_match") and not rule:
            return {}
        category = str(source.get("category") or rule.get("category") or "policy")
        item: dict[str, Any] = {
            "category": category,
            "source": str(source.get("name") or source.get("key") or "外部信号源"),
            "title": title,
            "published_at": _normalize_date(published_at),
            "url": url,
            "polarity": str(rule.get("polarity") or source.get("polarity") or "supporting"),
            "impact": str(rule.get("impact") or source.get("impact") or "中"),
        }
        sectors = rule.get("sectors") or source.get("sectors")
        themes = rule.get("themes") or source.get("themes")
        symbols = rule.get("symbols")
        if symbol:
            symbols = [symbol]
        if sectors:
            item["sectors"] = [str(value) for value in sectors]
        if themes:
            item["themes"] = [str(value) for value in themes]
        if symbols:
            item["symbols"] = [str(value).zfill(6) for value in symbols]
        return item


def _fetch_url_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MGFS-ResearchSignalCollector/1.0",
            "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _parse_json_records(raw_text: str, items_path: str) -> list[dict[str, Any]]:
    payload = json.loads(raw_text)
    node: Any = payload
    for part in [p for p in items_path.split(".") if p]:
        if isinstance(node, dict):
            node = node.get(part, [])
        else:
            node = []
    if isinstance(node, dict):
        node = node.get("items", [])
    if not isinstance(node, list):
        return []
    return [item for item in node if isinstance(item, dict)]


def _parse_rss_records(raw_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(raw_text)
    records: list[dict[str, Any]] = []
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{*}entry")
    for item in items:
        records.append(
            {
                "title": _xml_text(item, "title"),
                "url": _xml_text(item, "link") or _xml_attr(item, "link", "href"),
                "published_at": (
                    _xml_text(item, "pubDate")
                    or _xml_text(item, "published")
                    or _xml_text(item, "updated")
                ),
                "summary": _xml_text(item, "description") or _xml_text(item, "summary"),
            }
        )
    return records


def _xml_text(node: ElementTree.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None:
        child = node.find(f"{{*}}{tag}")
    return (child.text or "").strip() if child is not None else ""


def _xml_attr(node: ElementTree.Element, tag: str, attr: str) -> str:
    child = node.find(tag)
    if child is None:
        child = node.find(f"{{*}}{tag}")
    return str(child.attrib.get(attr, "")).strip() if child is not None else ""


def _field(record: dict[str, Any], configured: object, fallback: str) -> str:
    keys = [configured, fallback]
    for key in keys:
        if isinstance(key, str) and key in record and record[key] is not None:
            return str(record[key]).strip()
    return ""


def _match_rule(raw_rules: object, text: str) -> dict[str, Any]:
    if not isinstance(raw_rules, list):
        return {}
    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        needles = rule.get("contains", [])
        if isinstance(needles, str):
            needles = [needles]
        if any(str(needle) and str(needle) in text for needle in needles):
            return rule
    return {}


def _normalize_date(value: str) -> str:
    if not value:
        return ""
    parsed = _parse_date(value)
    if parsed is not None:
        return parsed.isoformat()
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return value


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _coerce_date(value: date | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("category", "")),
            str(item.get("title", "")),
            str(item.get("url", "")),
            str(item.get("published_at", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _error_item(source: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "category": "collector_error",
        "source": str(source.get("name") or source.get("key") or "外部信号源"),
        "title": "外部信号源读取失败",
        "published_at": "",
        "url": str(source.get("url") or ""),
        "polarity": "counter",
        "impact": "中",
        "error": error,
    }
