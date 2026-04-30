"""Tests for the publisher layer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.publishers.lark_bitable import LarkBitablePublisher, _sentiment_polarity, _snapshot_to_fields
from sentinel.publishers.lark_doc import LarkDocPublisher, _build_report_xml
from sentinel.publishers.tokens import load_lark_docs_config, save_lark_docs_config


def _make_snapshot(symbol: str = "AAPL", directed_heat: float = 5.0, change_pct: float | None = 50.0) -> HeatSnapshot:
    return HeatSnapshot(
        timestamp=datetime(2026, 4, 30, 10, 0, 0),
        market=Market.US,
        symbol=symbol,
        base_heat=2.0,
        kol_multiplier=1.5,
        sentiment_score=0.7,
        directed_heat=directed_heat,
        change_pct=change_pct,
        top_source="reddit_stocks",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )


class TestSentimentPolarity:
    def test_strong_bullish(self) -> None:
        assert _sentiment_polarity(0.8) == "强看多"

    def test_bullish(self) -> None:
        assert _sentiment_polarity(0.3) == "偏多"

    def test_neutral(self) -> None:
        assert _sentiment_polarity(0.0) == "震荡"

    def test_bearish(self) -> None:
        assert _sentiment_polarity(-0.4) == "偏空"

    def test_panic(self) -> None:
        assert _sentiment_polarity(-0.9) == "恐慌"


class TestSnapshotToFields:
    def test_converts_snapshot_to_bitable_fields(self) -> None:
        s = _make_snapshot()
        fields = _snapshot_to_fields(s)
        assert fields["标的"] == "AAPL"
        assert fields["净热度分"] == 3.0  # 2.0 * 1.5
        assert fields["情绪极性"] == "强看多"
        assert fields["综合情绪得分"] == 5.0
        assert fields["环比变动"] == 50.0
        assert fields["预警类型"] == "机会挖掘"
        assert fields["排名"] == 1

    def test_new_symbol_has_none_change(self) -> None:
        s = _make_snapshot(change_pct=None)
        fields = _snapshot_to_fields(s)
        assert fields["环比变动"] is None


class TestBuildReportXml:
    def test_contains_market_info(self) -> None:
        snapshots = [_make_snapshot()]
        xml = _build_report_xml(Market.US, snapshots, snapshots[0].timestamp)
        assert "2026-04-30 10:00" in xml
        assert "AAPL" in xml
        assert "看多热度激增" in xml

    def test_bearish_section(self) -> None:
        s = _make_snapshot(directed_heat=-3.0)
        s.rank_bullish = None
        s.rank_bearish = 1
        xml = _build_report_xml(Market.US, [s], s.timestamp)
        assert "黑天鹅预警" in xml


class TestTokensConfig:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_lark_docs_config(tmp_path / "nonexistent.yaml") == {}

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "lark_docs.yaml"
        data = {"美股": {"bitable_token": "abc123", "doc_token": "def456"}}
        save_lark_docs_config(path, data)
        loaded = load_lark_docs_config(path)
        assert loaded == data


class TestLarkBitablePublisher:
    def test_publish_no_snapshots_does_nothing(self, tmp_path: Path) -> None:
        pub = LarkBitablePublisher(tmp_path)
        # Should not raise
        pub.publish(Market.US, [])

    @patch("sentinel.publishers.lark_bitable.run_lark_cli")
    def test_publish_creates_base_on_first_run(self, mock_cli, tmp_path: Path) -> None:
        mock_cli.side_effect = [
            {"app_token": "base_tok"},  # +base-create
            {"table_id": "tbl_123"},  # +table-create
            {},  # +record-batch-create
        ]
        pub = LarkBitablePublisher(tmp_path)
        pub.publish(Market.US, [_make_snapshot()])

        # Tokens persisted
        config = load_lark_docs_config(tmp_path / "lark_docs.yaml")
        assert config["美股"]["bitable_token"] == "base_tok"
        assert config["美股"]["bitable_table_id"] == "tbl_123"

    @patch("sentinel.publishers.lark_bitable.run_lark_cli")
    def test_publish_appends_on_subsequent_run(self, mock_cli, tmp_path: Path) -> None:
        # Pre-save tokens
        save_lark_docs_config(tmp_path / "lark_docs.yaml", {
            "美股": {"bitable_token": "existing_tok", "bitable_table_id": "tbl_existing"}
        })
        mock_cli.return_value = {}
        pub = LarkBitablePublisher(tmp_path)
        pub.publish(Market.US, [_make_snapshot()])

        # Only record-batch-create called (no base-create, no table-create)
        assert mock_cli.call_count == 1
        args = mock_cli.call_args[0][0]
        assert "+record-batch-create" in args


class TestLarkDocPublisher:
    @patch("sentinel.publishers.lark_doc.run_lark_cli")
    def test_publish_creates_doc_on_first_run(self, mock_cli, tmp_path: Path) -> None:
        mock_cli.return_value = {"document_id": "doc_abc"}
        pub = LarkDocPublisher(tmp_path)
        pub.publish(Market.US, [_make_snapshot()])

        config = load_lark_docs_config(tmp_path / "lark_docs.yaml")
        assert config["美股"]["doc_token"] == "doc_abc"

    @patch("sentinel.publishers.lark_doc.run_lark_cli")
    def test_publish_prepends_on_subsequent_run(self, mock_cli, tmp_path: Path) -> None:
        save_lark_docs_config(tmp_path / "lark_docs.yaml", {
            "美股": {"doc_token": "doc_existing"}
        })
        mock_cli.return_value = {}
        pub = LarkDocPublisher(tmp_path)
        pub.publish(Market.US, [_make_snapshot()])

        args = mock_cli.call_args[0][0]
        assert "+update" in args
        assert "block_insert_after" in args
