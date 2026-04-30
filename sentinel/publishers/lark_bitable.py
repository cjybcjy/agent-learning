"""Feishu Bitable publisher — creates table and appends heat snapshot records."""

from __future__ import annotations

import logging
from pathlib import Path

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.publishers.cli import LarkCliError, run_lark_cli
from sentinel.publishers.tokens import load_lark_docs_config, save_lark_docs_config

logger = logging.getLogger(__name__)

# Sentiment polarity mapping
_POLARITY_MAP = [
    (0.6, "强看多"),
    (0.2, "偏多"),
    (-0.2, "震荡"),
    (-0.6, "偏空"),
]


def _sentiment_polarity(score: float) -> str:
    for threshold, label in _POLARITY_MAP:
        if score >= threshold:
            return label
    return "恐慌"


def _snapshot_to_fields(snapshot: HeatSnapshot) -> dict[str, object]:
    """Convert a HeatSnapshot to Bitable record fields."""
    direction = "看多" if snapshot.directed_heat > 0 else ("看空" if snapshot.directed_heat < 0 else "中性")
    alert_type = "机会挖掘" if snapshot.directed_heat > 0 else "黑天鹅预警"
    change_display = snapshot.change_pct if snapshot.change_pct is not None else None

    return {
        "记录时间": snapshot.timestamp.isoformat(),
        "标的": snapshot.symbol,
        "净热度分": round(snapshot.base_heat * snapshot.kol_multiplier, 2),
        "情绪极性": _sentiment_polarity(snapshot.sentiment_score),
        "综合情绪得分": round(snapshot.directed_heat, 2),
        "环比变动": change_display,
        "预警类型": alert_type,
        "热度来源": snapshot.top_source,
        "排名": snapshot.rank_bullish or snapshot.rank_bearish,
    }


class LarkBitablePublisher:
    """Publish heat snapshots to a Feishu Bitable.

    First run creates the base + table; subsequent runs append records.
    Tokens are persisted to config/lark_docs.yaml.
    """

    def __init__(self, config_dir: Path) -> None:
        self.config_path = config_dir / "lark_docs.yaml"

    def publish(self, market: Market, snapshots: list[HeatSnapshot]) -> None:
        """Publish ranked snapshots to the market's Bitable."""
        if not snapshots:
            logger.info("No snapshots to publish for %s", market.value)
            return

        config = load_lark_docs_config(self.config_path)
        market_cfg = config.get(market.value, {})

        app_token = market_cfg.get("bitable_token")
        table_id = market_cfg.get("bitable_table_id")

        if not app_token or not table_id:
            app_token, table_id = self._create_base_and_table(market)
            # Persist tokens
            if market.value not in config:
                config[market.value] = {}
            config[market.value]["bitable_token"] = app_token
            config[market.value]["bitable_table_id"] = table_id
            save_lark_docs_config(self.config_path, config)
            logger.info("Created Bitable for %s: app_token=%s, table_id=%s", market.value, app_token, table_id)

        self._append_records(app_token, table_id, snapshots)
        logger.info("Published %d records to Bitable for %s", len(snapshots), market.value)

    def _create_base_and_table(self, market: Market) -> tuple[str, str]:
        """Create a new Bitable base and return (app_token, table_id)."""
        name = f"{market.value}市场情绪异动追踪"
        result = run_lark_cli([
            "base", "+base-create",
            "--name", name,
        ])
        app_token = result.get("app_token") or result.get("data", {}).get("app_token")
        if not app_token:
            raise LarkCliError(f"Failed to create base: {result}")

        # Create a table with the required fields
        table_result = run_lark_cli([
            "base", "+table-create",
            "--app-token", app_token,
            "--name", "异动记录",
            "--fields", _table_fields_json(),
        ])
        table_id = table_result.get("table_id") or table_result.get("data", {}).get("table_id")
        if not table_id:
            raise LarkCliError(f"Failed to create table: {table_result}")

        return app_token, table_id

    def _append_records(self, app_token: str, table_id: str, snapshots: list[HeatSnapshot]) -> None:
        """Batch-append snapshot records to the Bitable table."""
        import json

        records = [_snapshot_to_fields(s) for s in snapshots]
        records_json = json.dumps(records, ensure_ascii=False)

        run_lark_cli([
            "base", "+record-batch-create",
            "--app-token", app_token,
            "--table-id", table_id,
            "--records", records_json,
        ])


def _table_fields_json() -> str:
    """Return JSON string defining Bitable table fields."""
    import json

    fields = [
        {"field_name": "记录时间", "type": "DateTime"},
        {"field_name": "标的", "type": "Text"},
        {"field_name": "净热度分", "type": "Number"},
        {"field_name": "情绪极性", "type": "Text"},
        {"field_name": "综合情绪得分", "type": "Number"},
        {"field_name": "环比变动", "type": "Number"},
        {"field_name": "预警类型", "type": "SingleSelect"},
        {"field_name": "热度来源", "type": "Text"},
        {"field_name": "排名", "type": "Number"},
    ]
    return json.dumps(fields, ensure_ascii=False)
