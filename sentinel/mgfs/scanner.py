from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision, MGFSOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    theme: str
    total_candidates: int
    filtered_count: int
    reports: list[InvestmentDecision] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class EcosystemScanner:
    def __init__(
        self,
        orchestrator: MGFSOrchestrator,
        moat_config_path: Path | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.moat_config_path = moat_config_path
        self._moat_data: dict | None = None

    def _load_moat_data(self) -> dict:
        if self._moat_data is not None:
            return self._moat_data
        if self.moat_config_path is None or not self.moat_config_path.exists():
            return {"companies": {}}
        with self.moat_config_path.open("r", encoding="utf-8") as handle:
            self._moat_data = yaml.safe_load(handle) or {}
        return self._moat_data

    def _get_candidates_by_theme(self, theme_name: str) -> list[TargetInfo]:
        data = self._load_moat_data()
        companies = data.get("companies", {})
        candidates: list[TargetInfo] = []
        for symbol, cfg in companies.items():
            if cfg.get("theme") == theme_name:
                candidates.append(
                    TargetInfo(
                        symbol=symbol,
                        market=Market.A_SHARE,
                        asset_class="equity",
                        name=cfg.get("name"),
                        sector=cfg.get("sector"),
                        theme=cfg.get("theme"),
                        ecosystem_role=cfg.get("ecosystem_role"),
                        fund_heavy_holding_count=_coerce_optional_int(
                            cfg.get("fund_heavy_holding_count")
                        ),
                    )
                )
        return candidates

    def preview_theme(
        self,
        *,
        theme_name: str,
        target_roles: list[str] | None = None,
        fund_rank_limit: int | None = None,
    ) -> dict[str, Any]:
        candidates = self._get_candidates_by_theme(theme_name)
        _, summary = self._prepare_candidates(
            candidates,
            target_roles=target_roles,
            fund_rank_limit=fund_rank_limit,
        )
        return summary

    def scan_theme(
        self,
        theme_name: str,
        target_roles: list[str] | None = None,
        min_moat_score: float = 60.0,
        allowed_zones: list[str] | None = None,
        policy_rating: str = "neutral",
        fund_rank_limit: int | None = None,
    ) -> ScanResult:
        if allowed_zones is None:
            allowed_zones = ["strong_buy", "accumulate"]

        candidates = self._get_candidates_by_theme(theme_name)
        reports: list[InvestmentDecision] = []
        skipped_moat = 0
        skipped_veto = 0
        skipped_zone = 0
        ranked_candidates, candidate_summary = self._prepare_candidates(
            candidates,
            target_roles=target_roles,
            fund_rank_limit=fund_rank_limit,
        )

        for target in ranked_candidates:
            try:
                report = self.orchestrator.evaluate(target, policy_rating=policy_rating)
            except Exception:
                logger.exception("Evaluation failed for %s", target.symbol)
                skipped_veto += 1
                continue

            moat_factor = report.factor_scores.get("moat")
            if moat_factor is None or moat_factor.score < min_moat_score:
                skipped_moat += 1
                continue

            if report.alert_level in (AlertLevel.HARD_VETO, AlertLevel.SOFT_VETO):
                skipped_veto += 1
                continue

            valuation_factor = report.factor_scores.get("valuation")
            zone = ""
            if valuation_factor is not None:
                zone = valuation_factor.details.get("zone", "")
            if zone not in allowed_zones:
                skipped_zone += 1
                continue

            reports.append(report)

        reports.sort(key=lambda r: r.final_score, reverse=True)

        return ScanResult(
            theme=theme_name,
            total_candidates=len(candidates),
            filtered_count=len(reports),
            reports=reports,
            summary={
                **candidate_summary,
                "passed_all_gates": len(reports),
                "skipped_by_moat": skipped_moat,
                "skipped_by_veto": skipped_veto,
                "skipped_by_zone": skipped_zone,
            },
        )

    def _prepare_candidates(
        self,
        candidates: list[TargetInfo],
        *,
        target_roles: list[str] | None = None,
        fund_rank_limit: int | None = None,
    ) -> tuple[list[TargetInfo], dict[str, Any]]:
        skipped_roles = 0
        ranked_candidates: list[TargetInfo] = []

        for target in candidates:
            if target_roles and target.ecosystem_role not in target_roles:
                skipped_roles += 1
                continue

            ranked_candidates.append(target)

        skipped_fund_rank = 0
        ranked_candidates = _rank_by_heavy_fund_count(ranked_candidates)
        if fund_rank_limit is not None and fund_rank_limit > 0:
            skipped_fund_rank = max(0, len(ranked_candidates) - fund_rank_limit)
            ranked_candidates = ranked_candidates[:fund_rank_limit]

        return ranked_candidates, {
            "total_candidates": len(candidates),
            "evaluated": len(ranked_candidates),
            "skipped_by_role": skipped_roles,
            "skipped_by_fund_rank": skipped_fund_rank,
            "fund_rank_limit": fund_rank_limit,
        }


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _rank_by_heavy_fund_count(targets: list[TargetInfo]) -> list[TargetInfo]:
    ranked = sorted(
        targets,
        key=lambda target: (-(target.fund_heavy_holding_count or 0), target.symbol),
    )
    return [
        TargetInfo(
            symbol=target.symbol,
            market=target.market,
            asset_class=target.asset_class,
            name=target.name,
            sector=target.sector,
            theme=target.theme,
            ecosystem_role=target.ecosystem_role,
            fund_heavy_holding_count=target.fund_heavy_holding_count,
            fund_heavy_holding_rank=index,
            tags=target.tags,
        )
        for index, target in enumerate(ranked, start=1)
    ]
