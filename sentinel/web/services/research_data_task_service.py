from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sentinel.config import AppSettings
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.storage.db import Database
from sentinel.web.services.research_data_collectors import (
    AShareEvidenceCollector,
    CNInfoAnnouncementCollector,
)
from sentinel.web.services.research_data_hub_service import (
    DataFetchResult,
    ResearchDataHub,
    TopicPolicy,
    TopicState,
)


RISK_ANNOUNCEMENT_CATEGORIES = (
    "category_jjgg_szsh",
    "category_bcgz_szsh",
    "category_gddh_szsh",
)
PERIODIC_REPORT_CATEGORIES = (
    "category_ndbg_szsh",
    "category_bndbg_szsh",
    "category_yjdbg_szsh",
)
DEFAULT_TASK_KEYS = ("risk_announcements", "financial_metrics")


@dataclass(frozen=True, slots=True)
class ResearchTopicRun:
    topic: str
    label: str
    status: str
    row_count: int
    watermark: str | None
    source: str
    error: str


@dataclass(frozen=True, slots=True)
class ResearchDataTaskRun:
    task_key: str
    label: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class ResearchDataFillResult:
    symbol: str
    market: str
    inserted_metric_count: int
    trend_count: int
    safety_count: int
    announcement_count: int
    risk_announcement_count: int
    metric_names: list[str]
    warnings: list[str]
    task_keys: list[str]
    task_results: list[ResearchDataTaskRun]
    topics: list[ResearchTopicRun]
    hub_snapshot: list[TopicState]
    executed_at: datetime


class ResearchDataTaskService:
    def __init__(
        self,
        *,
        database_path: Path | None = None,
        storage_dir: Path | None = None,
        hub: ResearchDataHub | None = None,
        announcement_collector: CNInfoAnnouncementCollector | None = None,
        evidence_collector: AShareEvidenceCollector | None = None,
    ) -> None:
        settings = AppSettings()
        self.database_path = database_path or settings.database_path
        self.hub = hub or ResearchDataHub()
        aggregator = MetricsAggregator(Database(self.database_path))
        aggregator.bootstrap()
        self.announcement_collector = announcement_collector or CNInfoAnnouncementCollector(
            storage_dir=storage_dir
        )
        self.evidence_collector = evidence_collector or AShareEvidenceCollector(
            aggregator=aggregator
        )

    def fill_gaps(
        self,
        *,
        symbol: str,
        market: str = "A_SHARE",
        task_keys: list[str] | None = None,
    ) -> ResearchDataFillResult:
        clean_symbol = symbol.strip()
        clean_market = market.strip() or "A_SHARE"
        selected_task_keys = _normalize_task_keys(task_keys)
        executed_at = datetime.now(tz=timezone.utc)
        announcement_categories = _announcement_categories_for_tasks(selected_task_keys)
        announcement_topic = f"cninfo:{clean_symbol}:announcements"
        financial_topic = f"ashare:{clean_symbol}:financials"

        if announcement_categories:
            self.hub.register(
                announcement_topic,
                lambda: self._fetch_announcements(
                    clean_symbol,
                    categories=announcement_categories,
                ),
                TopicPolicy(ttl_seconds=3600, min_interval_seconds=30),
                label="巨潮公告",
            )
        if "financial_metrics" in selected_task_keys:
            self.hub.register(
                financial_topic,
                lambda: self._fetch_financials(clean_symbol, clean_market),
                TopicPolicy(ttl_seconds=3600, min_interval_seconds=30),
                label="财务指标",
            )

        announcement_result = (
            self.hub.get_or_fetch(announcement_topic, force=True)
            if announcement_categories
            else None
        )
        financial_result = (
            self.hub.get_or_fetch(financial_topic, force=True)
            if "financial_metrics" in selected_task_keys
            else None
        )
        warnings = [
            warning
            for warning in (
                _warning_from_result("巨潮公告", announcement_result),
                _warning_from_result("财务指标", financial_result),
            )
            if warning
        ]

        financial_data = (
            financial_result.data
            if financial_result is not None and financial_result.success
            else None
        )
        announcement_data = (
            announcement_result.data
            if announcement_result is not None and announcement_result.success
            else None
        )
        metric_names = list(getattr(financial_data, "metric_names", []) or [])
        task_results = _task_results(
            selected_task_keys,
            announcement_result,
            financial_result,
        )
        topics = []
        if announcement_result is not None:
            topics.append(_topic_run(announcement_topic, "巨潮公告", announcement_result))
        if financial_result is not None:
            topics.append(_topic_run(financial_topic, "财务指标", financial_result))
        return ResearchDataFillResult(
            symbol=clean_symbol,
            market=clean_market,
            inserted_metric_count=int(
                getattr(financial_data, "inserted_metric_count", 0) or 0
            ),
            trend_count=int(getattr(financial_data, "trend_count", 0) or 0),
            safety_count=int(getattr(financial_data, "safety_count", 0) or 0),
            announcement_count=int(getattr(announcement_data, "row_count", 0) or 0),
            risk_announcement_count=int(
                getattr(announcement_data, "risk_count", 0) or 0
            ),
            metric_names=metric_names,
            warnings=warnings,
            task_keys=selected_task_keys,
            task_results=task_results,
            topics=topics,
            hub_snapshot=self.hub.stats(),
            executed_at=executed_at,
        )

    def _fetch_announcements(
        self,
        symbol: str,
        *,
        categories: tuple[str, ...],
    ) -> DataFetchResult:
        result = self.announcement_collector.sync_stock(symbol, categories=categories)
        return DataFetchResult.success(
            data=result,
            source=result.source,
            row_count=result.row_count,
            watermark=result.watermark,
        )

    def _fetch_financials(self, symbol: str, market: str) -> DataFetchResult:
        result = self.evidence_collector.collect(
            symbol=symbol,
            market=market,
            as_of=date.today(),
        )
        return DataFetchResult.success(
            data=result,
            source=result.source,
            row_count=result.inserted_metric_count,
            watermark=result.as_of.isoformat(),
        )


def _warning_from_result(label: str, result: DataFetchResult | None) -> str:
    if result is None or result.success:
        return ""
    return f"{label}读取失败: {result.error or 'unknown error'}"


def _topic_run(topic: str, label: str, result: DataFetchResult) -> ResearchTopicRun:
    return ResearchTopicRun(
        topic=topic,
        label=label,
        status="success" if result.success else "error",
        row_count=result.row_count,
        watermark=result.watermark,
        source=result.source,
        error=result.error or "",
    )


def _normalize_task_keys(task_keys: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for key in task_keys or list(DEFAULT_TASK_KEYS):
        normalized = key.strip()
        if normalized in {
            "risk_announcements",
            "periodic_reports",
            "financial_metrics",
        } and normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned or list(DEFAULT_TASK_KEYS)


def _announcement_categories_for_tasks(task_keys: list[str]) -> tuple[str, ...]:
    categories: list[str] = []
    if "risk_announcements" in task_keys:
        categories.extend(RISK_ANNOUNCEMENT_CATEGORIES)
    if "periodic_reports" in task_keys:
        categories.extend(PERIODIC_REPORT_CATEGORIES)
    return tuple(dict.fromkeys(categories))


def _task_results(
    task_keys: list[str],
    announcement_result: DataFetchResult | None,
    financial_result: DataFetchResult | None,
) -> list[ResearchDataTaskRun]:
    results: list[ResearchDataTaskRun] = []
    announcement_data = (
        announcement_result.data
        if announcement_result is not None and announcement_result.success
        else None
    )
    financial_data = (
        financial_result.data
        if financial_result is not None and financial_result.success
        else None
    )
    for task_key in task_keys:
        if task_key == "risk_announcements":
            status = _status_from_result(announcement_result)
            risk_count = int(getattr(announcement_data, "risk_count", 0) or 0)
            results.append(
                ResearchDataTaskRun(
                    task_key=task_key,
                    label="巨潮风险公告核验",
                    status=status,
                    summary=f"发现 {risk_count} 条风险公告",
                )
            )
        elif task_key == "periodic_reports":
            status = _status_from_result(announcement_result)
            counts = getattr(announcement_data, "classification_counts", {}) or {}
            report_count = int(counts.get("periodic_report", 0) or 0)
            results.append(
                ResearchDataTaskRun(
                    task_key=task_key,
                    label="巨潮定期报告证据",
                    status=status,
                    summary=f"同步 {report_count} 条定期报告公告",
                )
            )
        elif task_key == "financial_metrics":
            status = _status_from_result(financial_result)
            inserted_count = int(
                getattr(financial_data, "inserted_metric_count", 0) or 0
            )
            results.append(
                ResearchDataTaskRun(
                    task_key=task_key,
                    label="AkShare 财务指标补齐",
                    status=status,
                    summary=f"写入 {inserted_count} 项动态指标",
                )
            )
    return results


def _status_from_result(result: DataFetchResult | None) -> str:
    if result is None:
        return "skipped"
    return "success" if result.success else "error"
