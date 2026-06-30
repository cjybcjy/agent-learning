from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.execution.stop_loss_monitor import StopLossMonitor
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.orchestrator import MGFSOrchestrator
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.mgfs.target_resolver import TargetResolver, load_target_name_map
from sentinel.web.dependencies import get_orchestrator

logger = logging.getLogger(__name__)
settings = AppSettings()


def _get_repository() -> MGFSRepository:
    from sentinel.storage.db import Database
    return MGFSRepository(Database(settings.database_path))


class PipelineService:
    """Full-market pipeline scanning with async background execution."""

    def __init__(
        self,
        orchestrator: MGFSOrchestrator | None = None,
        repository: MGFSRepository | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._repository = repository

    # -- lazy deps --------------------------------------------------------

    @property
    def orchestrator(self) -> MGFSOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = get_orchestrator()
        return self._orchestrator

    @property
    def repository(self) -> MGFSRepository:
        if self._repository is None:
            self._repository = _get_repository()
            self._repository.bootstrap()
        return self._repository

    # -- public API -------------------------------------------------------

    def create_batch(self) -> str:
        """Create a running batch record and return batch_id.

        The caller (FastAPI router) is responsible for scheduling
        ``run_pipeline(batch_id)`` via BackgroundTasks.
        """
        batch_id = f"B_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.repository.create_pipeline_batch(batch_id, "running")
        return batch_id

    def run_pipeline(self, batch_id: str) -> None:
        """Execute the full-market scan synchronously.

        Intended to run inside a BackgroundTask thread.
        """
        self._execute_pipeline_core(batch_id)

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.repository.list_pipeline_batches(limit=limit)

    def get_pipeline_results(self, batch_id: str) -> list[dict[str, Any]]:
        return self._enrich_result_names(self.repository.get_pipeline_results(batch_id))

    def _run_stop_loss_scan(self) -> None:
        """Post-pipeline stop-loss scan on active holdings."""
        try:
            monitor = StopLossMonitor(self.repository)
            alerts = monitor.scan()
            if alerts:
                for alert in alerts:
                    logger.warning(
                        "StopLoss Alert [%s] %s %s: current=%.2f trigger=%.2f action=%s",
                        alert.alert_type,
                        alert.symbol,
                        alert.name,
                        alert.current_price,
                        alert.trigger_price,
                        alert.suggested_action,
                    )
        except Exception:
            logger.exception("Stop-loss scan failed")

    def _refresh_shadow_positions(self, *, source: str) -> None:
        """Refresh shadow holding prices and write optimization snapshots."""
        try:
            from sentinel.web.services.shadow_position_service import (
                ShadowPositionSimulatorService,
            )

            result = ShadowPositionSimulatorService(
                repository=self.repository
            ).refresh_active_holdings(source=source)
            if result.failures:
                for failure in result.failures:
                    logger.warning(
                        "Shadow position refresh failed for %s %s: %s",
                        failure.symbol,
                        failure.name,
                        failure.reason,
                    )
        except Exception:
            logger.exception("Shadow position refresh failed")

    def export_csv(self, batch_id: str) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "symbol", "name", "moat_score", "valuation_percentile",
            "timing_score", "final_score", "rating", "action",
        ])
        for row in self.get_pipeline_results(batch_id):
            writer.writerow([
                row["symbol"],
                row["name"],
                row["moat_score"],
                row["valuation_percentile"],
                row["timing_score"],
                row["final_score"],
                row["rating"],
                row["action"],
            ])
        return output.getvalue()

    # -- internal ---------------------------------------------------------

    def _enrich_result_names(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        names = load_target_name_map(settings.resolved_config_dir / "moat_static_base.yaml")
        enriched: list[dict[str, Any]] = []
        for row in rows:
            symbol = str(row.get("symbol", ""))
            current_name = row.get("name")
            resolved_name = names.get(symbol)
            if resolved_name and (not current_name or current_name == symbol):
                row = {**row, "name": resolved_name}
            enriched.append(row)
        return enriched

    def _load_stock_pool(self) -> list[TargetInfo]:
        """Load active stock pool from moat config."""
        import yaml
        moat_path = settings.resolved_config_dir / "moat_static_base.yaml"
        if not moat_path.exists():
            return []
        data = yaml.safe_load(moat_path.read_text(encoding="utf-8")) or {}
        companies = data.get("companies", {})
        targets: list[TargetInfo] = []
        resolver = TargetResolver(moat_path)
        for symbol, cfg in companies.items():
            cfg = cfg or {}
            targets.append(
                resolver.resolve(
                    symbol=symbol,
                    market=Market.A_SHARE,
                    asset_class="equity",
                    name=cfg.get("name"),
                    sector=cfg.get("sector"),
                    theme=cfg.get("theme"),
                    ecosystem_role=cfg.get("ecosystem_role"),
                )
            )
        return targets

    def _execute_pipeline_core(self, batch_id: str) -> None:
        try:
            targets = self._load_stock_pool()
            strong_buy_count = 0

            for target in targets:
                try:
                    decision = self.orchestrator.evaluate(target, policy_rating="neutral")
                    moat = decision.factor_scores.get("moat")
                    valuation = decision.factor_scores.get("valuation")
                    timing = decision.factor_scores.get("timing")

                    self.repository.save_pipeline_result(
                        batch_id=batch_id,
                        symbol=target.symbol,
                        name=target.name or target.symbol,
                        moat_score=moat.score if moat else 0.0,
                        valuation_percentile=(
                            valuation.details.get("primary_percentile", 50.0)
                            if valuation and valuation.details else 50.0
                        ),
                        timing_score=timing.score if timing else 0.0,
                        final_score=decision.final_score,
                        rating=decision.rating,
                        action=decision.action,
                    )
                    if decision.rating == "Strong Buy":
                        strong_buy_count += 1
                except Exception:
                    logger.exception("Pipeline evaluation failed for %s", target.symbol)
                    continue

            self.repository.update_pipeline_batch_status(
                batch_id,
                status="completed",
                total_count=len(targets),
                strong_buy_count=strong_buy_count,
            )
            self._refresh_shadow_positions(source="pipeline")
            self._run_stop_loss_scan()
        except Exception as exc:
            logger.exception("Pipeline execution failed for batch %s", batch_id)
            self.repository.update_pipeline_batch_status(
                batch_id, status="failed", error_log=str(exc)
            )
