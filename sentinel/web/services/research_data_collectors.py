from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.web.services.serenity_verification_service import _default_metric_targets


@dataclass(frozen=True, slots=True)
class CNInfoSyncResult:
    symbol: str
    row_count: int
    watermark: str | None
    records: list[dict[str, Any]]
    storage_path: Path
    source: str = "cninfo"
    classification_counts: dict[str, int] = field(default_factory=dict)
    risk_count: int = 0
    risk_records: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AShareEvidenceResult:
    symbol: str
    market: str
    inserted_metric_count: int
    trend_count: int
    safety_count: int
    metric_names: list[str]
    as_of: date
    source: str = "akshare_financial_indicators"


class CNInfoAnnouncementCollector:
    """Incrementally persist CNINFO announcements as traceable JSONL evidence."""

    SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
    ANNOUNCEMENT_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    DEFAULT_CATEGORIES = (
        "category_ndbg_szsh",
        "category_bndbg_szsh",
        "category_yjdbg_szsh",
        "category_qyfpxzcs_szsh",
    )

    def __init__(
        self,
        *,
        storage_dir: Path | None = None,
        post_json=None,
    ) -> None:
        settings = AppSettings()
        self.storage_dir = storage_dir or (
            settings.database_path.parent / "research_data" / "cninfo"
        )
        self._post_json = post_json or self._default_post_json

    def sync_stock(
        self,
        symbol: str,
        *,
        categories: list[str] | tuple[str, ...] | None = None,
    ) -> CNInfoSyncResult:
        clean_symbol = _clean_symbol(symbol)
        org_id = self.resolve_org_id(clean_symbol)
        existing_ids = self._read_existing_ids(clean_symbol)
        new_records: list[dict[str, Any]] = []
        watermark = self._read_watermark(clean_symbol)

        for category in categories or self.DEFAULT_CATEGORIES:
            payload = {
                "stock": f"{clean_symbol},{org_id}",
                "code": clean_symbol,
                "orgId": org_id,
                "category": category,
                "pageNum": 1,
                "pageSize": 30,
                "column": _cninfo_column(clean_symbol),
                "tabName": "fulltext",
                "sortName": "pubdate",
                "sortType": "desc",
                "seDate": "",
            }
            data = self._post_json(self.ANNOUNCEMENT_URL, payload)
            for record in _records_from_response(data, "announcements"):
                normalized = self._normalize_announcement(clean_symbol, record)
                announcement_id = normalized.get("announcement_id")
                if not announcement_id or announcement_id in existing_ids:
                    continue
                normalized.update(_classify_announcement(normalized["title"]))
                existing_ids.add(announcement_id)
                new_records.append(normalized)
                watermark = max(str(watermark or ""), announcement_id)

        storage_path = self._append_records(clean_symbol, new_records)
        self._write_watermark(clean_symbol, watermark)
        classification_counts = _classification_counts(new_records)
        risk_records = [
            record
            for record in new_records
            if record.get("risk_level") in {"high", "medium"}
        ]
        return CNInfoSyncResult(
            symbol=clean_symbol,
            row_count=len(new_records),
            watermark=watermark,
            records=new_records,
            storage_path=storage_path,
            classification_counts=classification_counts,
            risk_count=len(risk_records),
            risk_records=risk_records,
        )

    def resolve_org_id(self, symbol: str) -> str:
        clean_symbol = _clean_symbol(symbol)
        payload = {"stock": clean_symbol, "keyWord": clean_symbol, "maxNum": 10}
        try:
            data = self._post_json(self.SEARCH_URL, payload)
        except Exception:
            return _guess_cninfo_org_id(clean_symbol)
        for item in _records_from_response(data, "stockList"):
            if str(item.get("code", "")).strip() == clean_symbol and item.get("orgId"):
                return str(item["orgId"])
        return _guess_cninfo_org_id(clean_symbol)

    def _normalize_announcement(
        self,
        symbol: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        announcement_id = str(
            record.get("announcementId")
            or record.get("announcement_id")
            or record.get("id")
            or ""
        ).strip()
        adjunct_url = str(record.get("adjunctUrl") or record.get("adjunct_url") or "")
        full_url = adjunct_url
        if adjunct_url and not adjunct_url.startswith("http"):
            full_url = f"https://static.cninfo.com.cn/{adjunct_url.lstrip('/')}"
        return {
            "symbol": symbol,
            "announcement_id": announcement_id,
            "title": str(
                record.get("announcementTitle")
                or record.get("announcement_title")
                or record.get("title")
                or ""
            ).strip(),
            "published_at": _announcement_time(record.get("announcementTime")),
            "adjunct_url": full_url,
            "source": "cninfo",
            "raw": record,
        }

    def _append_records(self, symbol: str, records: list[dict[str, Any]]) -> Path:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        path = self.storage_dir / f"{symbol}.jsonl"
        if records:
            with path.open("a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            path.touch(exist_ok=True)
        return path

    def _read_existing_ids(self, symbol: str) -> set[str]:
        path = self.storage_dir / f"{symbol}.jsonl"
        if not path.exists():
            return set()
        ids: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("announcement_id"):
                    ids.add(str(record["announcement_id"]))
        return ids

    def _read_watermark(self, symbol: str) -> str | None:
        path = self.storage_dir / f"{symbol}.watermark"
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def _write_watermark(self, symbol: str, watermark: str | None) -> None:
        if not watermark:
            return
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir / f"{symbol}.watermark").write_text(
            watermark,
            encoding="utf-8",
        )

    @staticmethod
    def _default_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        import requests

        response = requests.post(
            url,
            data=payload,
            timeout=12,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "Chrome/126 Safari/537.36"
                ),
                "Referer": "https://www.cninfo.com.cn/new/index",
            },
        )
        response.raise_for_status()
        return response.json()


class AkShareAStockProvider:
    def financial_indicators(self, symbol: str):
        import akshare as ak

        clean_symbol = _clean_symbol(symbol)
        start_year = str(max(2000, date.today().year - 5))
        candidates = (
            lambda: ak.stock_financial_analysis_indicator(
                symbol=clean_symbol,
                start_year=start_year,
            ),
            lambda: ak.stock_financial_analysis_indicator_em(
                symbol=_akshare_em_symbol(clean_symbol)
            ),
            lambda: ak.stock_financial_abstract_ths(symbol=clean_symbol),
        )
        last_error: Exception | None = None
        for fetch in candidates:
            try:
                result = fetch()
            except Exception as exc:
                last_error = exc
                continue
            if _has_rows(result):
                return result
        if last_error is not None:
            raise last_error
        return []

    def governance_events(self, symbol: str):
        return []


class AShareEvidenceCollector:
    """Convert A-share financial evidence into MGFS dynamic metric scores."""

    def __init__(
        self,
        *,
        aggregator: MetricsAggregator,
        provider: Any | None = None,
    ) -> None:
        self.aggregator = aggregator
        self.provider = provider or AkShareAStockProvider()

    def collect(
        self,
        *,
        symbol: str,
        market: str = "A_SHARE",
        as_of: date | None = None,
    ) -> AShareEvidenceResult:
        clean_symbol = _clean_symbol(symbol)
        rows = _to_records(self.provider.financial_indicators(clean_symbol))
        if not rows:
            raise ValueError(f"no financial indicators returned for {clean_symbol}")
        latest = _latest_financial_row(rows)
        resolved_as_of = as_of or _infer_as_of(latest) or date.today()
        target = TargetInfo(
            symbol=clean_symbol,
            market=_parse_market(market),
            asset_class="equity",
        )
        metric_targets = {item.metric_name: item for item in _default_metric_targets()}
        scores = self._score_metrics(latest)
        recorded_at = datetime.now(tz=timezone.utc)

        trend_count = 0
        safety_count = 0
        metric_names: list[str] = []
        for metric_name, score in scores.items():
            metric_target = metric_targets[metric_name]
            if metric_target.target_table == "trend_metrics":
                self.aggregator.insert_trend_metric(target, metric_name, score, recorded_at)
                trend_count += 1
            else:
                self.aggregator.insert_safety_metric(target, metric_name, score, recorded_at)
                safety_count += 1
            self.aggregator.record_metric_source(
                target,
                metric_name=metric_name,
                target_table=metric_target.target_table,
                source="akshare_financial_indicators",
                as_of=resolved_as_of,
                source_url=None,
                financial_items=metric_target.financial_items,
                calculation_hint=metric_target.calculation_hint,
                recorded_at=recorded_at,
            )
            metric_names.append(metric_name)

        return AShareEvidenceResult(
            symbol=clean_symbol,
            market=market,
            inserted_metric_count=len(metric_names),
            trend_count=trend_count,
            safety_count=safety_count,
            metric_names=metric_names,
            as_of=resolved_as_of,
        )

    def _score_metrics(self, row: dict[str, Any]) -> dict[str, float]:
        roe = _extract_number(
            row,
            (
                "净资产收益率(%)",
                "加权净资产收益率(%)",
                "净资产收益率",
                "净资产收益率-摊薄",
                "ROE",
                "ROEJQ",
                "roe",
            ),
        )
        gross_margin = _extract_number(
            row,
            ("销售毛利率(%)", "销售毛利率", "毛利率(%)", "XSMLL", "gross_margin"),
        )
        rd_ratio = _extract_number(row, ("研发费用率(%)", "研发投入占营业收入比例", "rd_ratio"))
        debt_ratio = _extract_number(
            row,
            ("资产负债率(%)", "资产负债率", "ZCFZL", "debt_ratio"),
        )
        goodwill_ratio = _extract_number(
            row,
            ("商誉占总资产比例(%)", "商誉/总资产", "goodwill_ratio"),
        )
        cashflow_ratio = _extract_number(
            row,
            (
                "经营现金流量净额/净利润",
                "经营现金流净额/净利润",
                "经营现金净流量与净利润的比率(%)",
                "JYXJLYYSR",
                "operating_cashflow_ratio",
            ),
        )
        return {
            "roic_sustainability": _score_high_better(roe, weak=5.0, strong=20.0),
            "gmoat_stability": _score_high_better(
                gross_margin,
                weak=20.0,
                strong=60.0,
            ),
            "rd_efficiency": _score_rd_efficiency(rd_ratio),
            "debt_ratio_deterioration": _score_low_better(
                debt_ratio,
                good=35.0,
                bad=75.0,
            ),
            "goodwill_ratio": _score_low_better(
                goodwill_ratio,
                good=3.0,
                bad=20.0,
            ),
            "operating_cashflow_ratio": _score_high_better(
                cashflow_ratio,
                weak=0.3,
                strong=1.0,
            ),
        }


def _clean_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).strip() if ch.isalnum()).upper()


def _parse_market(market: str) -> Market:
    normalized = str(market).strip()
    if normalized in Market.__members__:
        return Market[normalized]
    return Market(normalized)


def _cninfo_column(symbol: str) -> str:
    return "sse" if symbol.startswith("6") else "szse"


def _guess_cninfo_org_id(symbol: str) -> str:
    return f"gssh0{symbol}" if symbol.startswith("6") else f"gssz0{symbol}"


def _announcement_time(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return str(value)
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def _classify_announcement(title: str) -> dict[str, str]:
    normalized = title.replace(" ", "")
    rules = (
        (
            "regulatory_penalty",
            "high",
            ("行政处罚", "立案调查", "纪律处分", "监管措施", "警示函"),
            "核验监管处罚、立案调查和整改影响",
        ),
        (
            "inquiry_letter",
            "medium",
            ("问询函", "关注函", "监管工作函", "年报问询"),
            "核验交易所问询事项和公司回复质量",
        ),
        (
            "litigation",
            "medium",
            ("诉讼", "仲裁"),
            "核验重大诉讼金额、进展和潜在负债",
        ),
        (
            "pledge",
            "medium",
            ("质押", "冻结"),
            "核验股权质押比例、平仓风险和控制权稳定性",
        ),
        (
            "guarantee",
            "medium",
            ("担保", "对外担保"),
            "核验担保对象、金额和连带责任风险",
        ),
        (
            "share_reduction",
            "medium",
            ("减持", "被动减持"),
            "核验重要股东减持原因和持续性",
        ),
        (
            "periodic_report",
            "low",
            ("年度报告", "年报", "半年度报告", "季度报告", "一季度报告", "三季度报告"),
            "提取盈利、现金流和治理证据",
        ),
        (
            "buyback",
            "positive",
            ("回购",),
            "核验回购规模、价格区间和执行进度",
        ),
        (
            "dividend",
            "low",
            ("分红", "权益分派", "利润分配"),
            "核验分红稳定性和现金流承载",
        ),
        (
            "equity_incentive",
            "low",
            ("股权激励", "员工持股"),
            "核验激励条件和业绩目标质量",
        ),
    )
    for category, risk_level, keywords, focus in rules:
        if any(keyword in normalized for keyword in keywords):
            return {
                "category": category,
                "risk_level": risk_level,
                "verification_focus": focus,
            }
    return {
        "category": "other",
        "risk_level": "low",
        "verification_focus": "人工判断是否与基本面、治理或政策传导相关",
    }


def _classification_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        category = str(record.get("category") or "other")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _to_records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        return list(data.to_dict(orient="records"))
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("data")
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
        return [data]
    return []


def _has_rows(data: Any) -> bool:
    if data is None:
        return False
    if hasattr(data, "empty"):
        return not bool(data.empty)
    if isinstance(data, (list, tuple)):
        return bool(data)
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("data")
        return bool(rows) if rows is not None else bool(data)
    return True


def _akshare_em_symbol(symbol: str) -> str:
    suffix = "SH" if symbol.startswith("6") else "SZ"
    return f"{symbol}.{suffix}"


def _records_from_response(data: Any, key: str) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        rows = data.get(key) or data.get("data") or data.get("rows") or []
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
        if isinstance(rows, dict):
            nested = rows.get(key) or rows.get("data") or rows.get("rows") or []
            if isinstance(nested, list):
                return [dict(item) for item in nested if isinstance(item, dict)]
    return []


def _latest_financial_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(rows, key=_row_date_key, reverse=True)[0]


def _row_date_key(row: dict[str, Any]) -> str:
    for key in ("报告期", "日期", "报表日期", "report_date", "date"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _infer_as_of(row: dict[str, Any]) -> date | None:
    raw = _row_date_key(row)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _extract_number(row: dict[str, Any], names: tuple[str, ...]) -> float | None:
    normalized = {_normalize_key(key): value for key, value in row.items()}
    for name in names:
        if name in row:
            return _to_float(row[name])
        value = normalized.get(_normalize_key(name))
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _normalize_key(value: str) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("（", "(")
        .replace("）", ")")
    )


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _score_high_better(value: float | None, *, weak: float, strong: float) -> float:
    if value is None:
        return 50.0
    if value >= strong:
        return 90.0
    if value <= weak:
        return 35.0
    ratio = (value - weak) / (strong - weak)
    return round(35.0 + ratio * 55.0, 2)


def _score_low_better(value: float | None, *, good: float, bad: float) -> float:
    if value is None:
        return 50.0
    if value <= good:
        return 90.0
    if value >= bad:
        return 25.0
    ratio = (bad - value) / (bad - good)
    return round(25.0 + ratio * 65.0, 2)


def _score_rd_efficiency(value: float | None) -> float:
    if value is None:
        return 50.0
    if value <= 0:
        return 45.0
    if value <= 2:
        return 65.0
    if value <= 8:
        return 82.0
    if value <= 15:
        return 72.0
    return 55.0
