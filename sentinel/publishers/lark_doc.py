"""Feishu Doc publisher — creates document and prepends anomaly reports."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.publishers.cli import LarkCliError, run_lark_cli
from sentinel.publishers.tokens import load_lark_docs_config, save_lark_docs_config

logger = logging.getLogger(__name__)


def _sentiment_polarity(score: float) -> str:
    if score >= 0.6:
        return "强看多"
    if score >= 0.2:
        return "偏多"
    if score > -0.2:
        return "震荡"
    if score > -0.6:
        return "偏空"
    return "恐慌"


def _build_report_xml(market: Market, snapshots: list[HeatSnapshot], ts: datetime) -> str:
    """Build DocxXML content for a single report section."""
    bullish = [s for s in snapshots if s.directed_heat > 0]
    bearish = [s for s in snapshots if s.directed_heat < 0]

    ts_str = ts.strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append(f"<h2>{ts_str} 盘中异动</h2>")

    # Summary
    total = len(snapshots)
    avg_sent = sum(s.sentiment_score for s in snapshots) / total if total else 0
    polarity = _sentiment_polarity(avg_sent)
    lines.append(f"<p>📊 有效标的数：{total} | 市场整体情绪：{polarity}（均值 {avg_sent:+.2f}）</p>")

    # Bullish table
    if bullish:
        lines.append("<p>🟢 <b>看多热度激增 Top 10</b></p>")
        lines.append(_build_table(bullish))

    # Bearish table
    if bearish:
        lines.append("<p>🔴 <b>看空热度激增 Top 10（黑天鹅预警）</b></p>")
        lines.append(_build_table(bearish))

    return "\n".join(lines)


def _build_table(items: list[HeatSnapshot]) -> str:
    """Build an XML table for a list of snapshots."""
    rows: list[str] = []
    rows.append("<table>")
    rows.append("<tr><th>排名</th><th>标的</th><th>净热度</th><th>情绪极性</th>"
                "<th>综合得分</th><th>环比变动</th><th>来源</th></tr>")
    for s in items:
        rank = s.rank_bullish or s.rank_bearish or "-"
        net_heat = round(s.base_heat * s.kol_multiplier, 1)
        polarity = _sentiment_polarity(s.sentiment_score)
        change = f"{s.change_pct:+.0f}%" if s.change_pct is not None else "NEW"
        rows.append(
            f"<tr><td>{rank}</td><td>{s.symbol}</td><td>{net_heat}</td>"
            f"<td>{polarity}</td><td>{s.directed_heat:+.1f}</td>"
            f"<td>{change}</td><td>{s.top_source}</td></tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


class LarkDocPublisher:
    """Publish heat snapshots as a formatted report to a Feishu Doc.

    First run creates the doc; subsequent runs prepend new sections at the top.
    """

    def __init__(self, config_dir: Path) -> None:
        self.config_path = config_dir / "lark_docs.yaml"

    def publish(self, market: Market, snapshots: list[HeatSnapshot]) -> None:
        """Publish a report section to the market's Doc."""
        if not snapshots:
            logger.info("No snapshots to publish for %s", market.value)
            return

        config = load_lark_docs_config(self.config_path)
        market_cfg = config.get(market.value, {})
        doc_token = market_cfg.get("doc_token")

        ts = snapshots[0].timestamp

        if not doc_token:
            doc_token = self._create_doc(market, snapshots, ts)
            if market.value not in config:
                config[market.value] = {}
            config[market.value]["doc_token"] = doc_token
            save_lark_docs_config(self.config_path, config)
            logger.info("Created Doc for %s: token=%s", market.value, doc_token)
        else:
            self._prepend_section(doc_token, market, snapshots, ts)
            logger.info("Prepended report to Doc for %s", market.value)

    def _create_doc(self, market: Market, snapshots: list[HeatSnapshot], ts: datetime) -> str:
        """Create a new Doc with initial report content."""
        title = f"{market.value}市场情绪异动日报"
        body = _build_report_xml(market, snapshots, ts)
        content = f"<title>{title}</title>\n{body}"

        result = run_lark_cli([
            "docs", "+create",
            "--api-version", "v2",
            "--content", content,
        ])
        doc_token = result.get("document_id") or result.get("data", {}).get("document_id")
        if not doc_token:
            raise LarkCliError(f"Failed to create doc: {result}")
        return doc_token

    def _prepend_section(
        self, doc_token: str, market: Market, snapshots: list[HeatSnapshot], ts: datetime
    ) -> None:
        """Prepend a new report section at the top of existing doc."""
        body = _build_report_xml(market, snapshots, ts)
        run_lark_cli([
            "docs", "+update",
            "--api-version", "v2",
            "--doc", doc_token,
            "--command", "block_insert_after",
            "--location", "title",
            "--content", body,
        ])
