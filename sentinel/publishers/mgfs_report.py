"""MGFS Investment Decision report publisher — generates Feishu card messages."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sentinel.mgfs.factor_plugin import AlertLevel
from sentinel.mgfs.orchestrator import InvestmentDecision

logger = logging.getLogger(__name__)

# Color mapping for alert levels
_ALERT_COLORS = {
    AlertLevel.HARD_VETO: "red",
    AlertLevel.SOFT_VETO: "orange",
    AlertLevel.YELLOW_WARNING: "yellow",
    AlertLevel.GREEN_PASS: "green",
}

# Emoji mapping for ratings
_RATING_EMOJI = {
    "Strong Buy": "🟢",
    "Accumulate": "🔵",
    "Hold/Watch": "🟡",
    "Avoid": "🔴",
    "Error": "⚫",
}


def _zone_emoji(zone: str | None) -> str:
    if zone == "strong_buy":
        return "🟢"
    if zone == "accumulate":
        return "🔵"
    if zone == "hold":
        return "🟡"
    if zone == "avoid":
        return "🔴"
    return "⚪"


def build_feishu_card(decision: InvestmentDecision) -> dict[str, Any]:
    """Build a Feishu interactive card payload from an InvestmentDecision."""
    alert_color = _ALERT_COLORS.get(decision.alert_level, "grey")
    rating_emoji = _RATING_EMOJI.get(decision.rating, "⚪")

    # Factor score lines
    factor_lines = []
    for key, score in decision.factor_scores.items():
        zone = score.details.get("zone", "")
        emoji = _zone_emoji(zone)
        factor_lines.append(
            f"{emoji} **{score.factor_name}**: {score.score:.1f}/100 "
            f"(置信度: {score.confidence:.0%})"
        )

    # Circuit breaker lines
    cb_lines = []
    for cb in decision.circuit_breakers_triggered:
        level = cb.get("alert_level", "unknown")
        emoji = "🔴" if level == "hard_veto" else "🟠" if level == "soft_veto" else "🟡"
        cb_lines.append(f"{emoji} [{level.upper()}] {cb['message']}")

    # Watermark
    watermark = decision.report_sections.get("watermark", "")
    watermark_line = f"\n⚠️ **{watermark}**" if watermark else ""

    # Main content
    content = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": alert_color,
            "title": {
                "tag": "plain_text",
                "content": f"{rating_emoji} {decision.target.symbol} — {decision.rating}",
            },
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**标的**: {decision.target.symbol} ({decision.target.market.value})\n"
                        f"**行业**: {decision.target.sector or '未指定'}\n"
                        f"**最终得分**: {decision.final_score:.2f}\n"
                        f"**政策乘数**: {decision.policy_multiplier:.2f}\n"
                        f"**综合置信度**: {decision.report_sections.get('overall_confidence', 0):.0%}\n"
                        f"**建议动作**: {decision.action}"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**因子得分**\n" + "\n".join(factor_lines),
                },
            },
        ],
    }

    if cb_lines:
        content["elements"].append({"tag": "hr"})
        content["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**触发熔断**\n" + "\n".join(cb_lines),
                },
            }
        )

    if watermark:
        content["elements"].append({"tag": "hr"})
        content["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"⚠️ **{watermark}**",
                },
            }
        )

    # Footer with timestamp
    content["elements"].append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"评估时间: {decision.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
                }
            ],
        }
    )

    return content


_ROLE_LABELS = {
    "symbiotic_infra": "共生基础设施",
    "upstream_resource": "上游资源/设备",
    "downstream_app": "下游应用",
    "core_arena": "核心竞技场",
}

_ROLE_EMOJI = {
    "symbiotic_infra": "🟢",
    "upstream_resource": "🔵",
    "downstream_app": "🟡",
    "core_arena": "🔴",
}


def build_ecosystem_scan_report(scan_result) -> dict[str, Any]:
    """Build a Feishu interactive card payload from an Ecosystem ScanResult."""
    from sentinel.mgfs.scanner import ScanResult
    from sentinel.mgfs.orchestrator import InvestmentDecision

    assert isinstance(scan_result, ScanResult)

    elements: list[dict[str, Any]] = []

    # Theme info block
    theme_info = (
        f"**主题**: {scan_result.theme}\n"
        f"**扫描策略**: 产业链全角色扫描\n"
        f"**候选标的**: {scan_result.total_candidates} 家\n"
        f"**通过筛选**: {scan_result.filtered_count} 家"
    )
    elements.append(
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": theme_info},
        }
    )
    elements.append({"tag": "hr"})

    # Per-report blocks
    for decision in scan_result.reports:
        assert isinstance(decision, InvestmentDecision)
        role = decision.target.ecosystem_role or "unknown"
        role_label = _ROLE_LABELS.get(role, role)
        role_emoji = _ROLE_EMOJI.get(role, "⚪")
        rating_emoji = _RATING_EMOJI.get(decision.rating, "⚪")

        # Moat score
        moat_score = decision.factor_scores.get("moat")
        moat_line = ""
        if moat_score:
            moat_line = f"**护城河**: {moat_score.score:.1f} (置信度: {moat_score.confidence:.0%})\n"

        # Valuation zone
        valuation_score = decision.factor_scores.get("valuation")
        zone = ""
        if valuation_score:
            zone = valuation_score.details.get("zone", "")
        zone_emoji = _zone_emoji(zone)

        report_text = (
            f"{role_emoji} **{decision.target.symbol}** — {decision.target.name} ({role_label})\n"
            f"{moat_line}"
            f"{zone_emoji} **估值区间**: {zone or 'N/A'}\n"
            f"**最终得分**: {decision.final_score:.2f}\n"
            f"{rating_emoji} **评级**: {decision.rating}\n"
            f"**建议动作**: {decision.action}"
        )

        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": report_text},
            }
        )
        elements.append({"tag": "hr"})

    # Summary notes
    summary = scan_result.summary or {}
    skipped_by_veto = summary.get("skipped_by_veto", 0)
    skipped_by_zone = summary.get("skipped_by_zone", 0)
    skipped_by_moat = summary.get("skipped_by_moat", 0)

    if skipped_by_veto or skipped_by_zone or skipped_by_moat:
        summary_lines = ["**筛选统计**"]
        if skipped_by_veto:
            summary_lines.append(f"- 熔断跳过: {skipped_by_veto} 家")
        if skipped_by_zone:
            summary_lines.append(f"- 估值区间跳过: {skipped_by_zone} 家")
        if skipped_by_moat:
            summary_lines.append(f"- 护城河不足跳过: {skipped_by_moat} 家")
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(summary_lines)},
            }
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {
                "tag": "plain_text",
                "content": "📊 MGFS 产业链价值扫描报告",
            },
        },
        "elements": elements,
    }


def build_text_report(decision: InvestmentDecision) -> str:
    """Build a plain-text report suitable for CLI or simple messaging."""
    lines = [
        f"{'=' * 50}",
        f"《投资权衡与决策说明书》",
        f"{'=' * 50}",
        f"标的: {decision.target.symbol} ({decision.target.market.value})",
        f"行业: {decision.target.sector or '未指定'}",
        f"评估时间: {decision.generated_at}",
        f"{'-' * 30}",
    ]

    for key, score in decision.factor_scores.items():
        lines.append(f"{score.factor_name}: {score.score:.1f}/{score.max_score}")

    lines.extend([
        f"{'-' * 30}",
        f"原始加权分: {decision.raw_total}",
        f"政策乘数: {decision.policy_multiplier}",
        f"最终得分: {decision.final_score}",
        f"评级: {decision.rating}",
        f"建议动作: {decision.action}",
    ])

    if decision.report_sections.get("watermark"):
        lines.append(f"⚠️  {decision.report_sections['watermark']}")

    lines.append(f"综合置信度: {decision.report_sections.get('overall_confidence', 'N/A')}")
    lines.append(f"告警级别: {decision.alert_level.value}")

    if decision.circuit_breakers_triggered:
        lines.append("触发熔断:")
        for cb in decision.circuit_breakers_triggered:
            action_label = cb.get("action") or cb.get("alert_level", "unknown")
            lines.append(f"  - [{action_label}] {cb['message']}")

    lines.append(f"{'=' * 50}")
    return "\n".join(lines)


class MGFSReportPublisher:
    """Publish MGFS InvestmentDecision reports to Feishu.

    Supports two modes:
    1. Webhook mode: POST card JSON to a Feishu bot webhook
    2. CLI mode: Use lark-cli to send messages (future)
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url

    def publish(self, decision: InvestmentDecision) -> None:
        """Publish a single decision report."""
        card = build_feishu_card(decision)
        text = build_text_report(decision)

        if self.webhook_url:
            self._send_webhook(card)
        else:
            # Fallback: print to console
            print(text)

    def _send_webhook(self, card: dict[str, Any]) -> None:
        """Send card to Feishu webhook."""
        import urllib.request

        payload = json.dumps({"msg_type": "interactive", "card": card}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info("Webhook response: %s", resp.status)
        except Exception:
            logger.exception("Failed to send webhook")
