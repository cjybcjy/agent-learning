from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.data.multi_source_fetcher import MultiSourceFetcher
from sentinel.mgfs.data.price_fetcher import PriceFetcher
from sentinel.mgfs.execution.position_sizing import PositionSizingEngine
from sentinel.mgfs.execution.stop_loss_monitor import RiskAlert, StopLossMonitor
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.storage.db import Database

MARKET_REFRESH_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ManualShadowCandidate:
    symbol: str
    name: str
    sector: str
    final_score: float
    payoff_ratio: float
    price: float | None = None


@dataclass(frozen=True, slots=True)
class ShadowPreviewRow:
    symbol: str
    name: str
    sector: str
    final_score: float
    payoff_ratio: float
    price: float | None
    weight: float = 0.0
    kelly_fraction: float = 0.0
    win_prob: float = 0.0
    stop_loss_hard: float = PositionSizingEngine.STOP_LOSS_HARD
    stop_loss_trailing: float = PositionSizingEngine.STOP_LOSS_TRAILING
    portfolio_stop_loss: float = PositionSizingEngine.STOP_LOSS_PORTFOLIO
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ShadowPortfolioPreview:
    rows: list[ShadowPreviewRow]
    total_weight: float
    cash_reserve: float
    portfolio_stop_loss: float


@dataclass(frozen=True, slots=True)
class ShadowRefreshFailure:
    symbol: str
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ShadowRefreshResult:
    updated_count: int
    failures: list[ShadowRefreshFailure] = field(default_factory=list)
    alerts: list[RiskAlert] = field(default_factory=list)
    source: str = "manual"


class ShadowPositionSimulatorService:
    def __init__(
        self,
        *,
        repository: MGFSRepository | None = None,
        price_fetcher: PriceFetcher | None = None,
        sizing_engine: PositionSizingEngine | None = None,
        stop_monitor: StopLossMonitor | None = None,
        sector_limits: dict[str, float] | None = None,
    ) -> None:
        self.repository = repository or _default_repository()
        self.price_fetcher = price_fetcher or MultiSourceFetcher.default_chain(
            request_timeout=MARKET_REFRESH_TIMEOUT_SECONDS,
            max_retries=1,
            delay_scale=0.0,
        )
        self.sizing_engine = sizing_engine or PositionSizingEngine(
            sector_limits=sector_limits or _default_sector_limits()
        )
        self.stop_monitor = stop_monitor or StopLossMonitor(self.repository)

    def preview_candidates(
        self,
        candidates: list[ManualShadowCandidate],
        *,
        market: Market = Market.A_SHARE,
    ) -> ShadowPortfolioPreview:
        prepared: list[ManualShadowCandidate] = []
        error_rows: list[ShadowPreviewRow] = []

        for candidate in candidates:
            normalized = _normalize_candidate(candidate)
            error = _candidate_error(normalized)
            if error:
                error_rows.append(_error_row(normalized, error))
                continue
            prepared.append(
                ManualShadowCandidate(
                    symbol=normalized.symbol,
                    name=normalized.name,
                    sector=normalized.sector,
                    final_score=normalized.final_score,
                    payoff_ratio=normalized.payoff_ratio,
                    price=normalized.price,
                )
            )

        if not prepared:
            return ShadowPortfolioPreview(
                rows=error_rows,
                total_weight=0.0,
                cash_reserve=1.0,
                portfolio_stop_loss=PositionSizingEngine.STOP_LOSS_PORTFOLIO,
            )

        portfolio = self.sizing_engine.build_portfolio(
            [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "final_score": item.final_score,
                    "payoff_ratio": item.payoff_ratio,
                }
                for item in prepared
            ]
        )
        holdings_by_symbol = {
            str(holding["symbol"]): holding for holding in portfolio["holdings"]
        }

        rows: list[ShadowPreviewRow] = []
        for item in prepared:
            holding = holdings_by_symbol.get(item.symbol)
            if holding is None:
                rows.append(
                    ShadowPreviewRow(
                        symbol=item.symbol,
                        name=item.name,
                        sector=item.sector,
                        final_score=item.final_score,
                        payoff_ratio=item.payoff_ratio,
                        price=item.price,
                        error="Kelly 结果为 0，未进入影子组合",
                    )
                )
                continue
            rows.append(
                ShadowPreviewRow(
                    symbol=item.symbol,
                    name=item.name,
                    sector=item.sector,
                    final_score=item.final_score,
                    payoff_ratio=item.payoff_ratio,
                    price=item.price,
                    weight=float(holding["weight"]),
                    kelly_fraction=float(holding["kelly_fraction"]),
                    win_prob=float(holding["win_prob"]),
                    stop_loss_hard=float(holding["stop_loss_hard"]),
                    stop_loss_trailing=float(holding["stop_loss_trailing"]),
                    portfolio_stop_loss=float(portfolio["portfolio_stop_loss"]),
                )
            )

        all_rows = rows + error_rows
        total_weight = sum(row.weight for row in all_rows)
        return ShadowPortfolioPreview(
            rows=all_rows,
            total_weight=total_weight,
            cash_reserve=float(portfolio["cash_reserve"]),
            portfolio_stop_loss=float(portfolio["portfolio_stop_loss"]),
        )

    def confirm_candidates(
        self,
        candidates: list[ManualShadowCandidate],
        *,
        market: Market = Market.A_SHARE,
    ) -> ShadowPortfolioPreview:
        preview = self.preview_candidates(candidates, market=market)
        for row in preview.rows:
            if row.error or row.weight <= 0.0 or row.price is None:
                continue
            self.repository.save_active_holding(
                symbol=row.symbol,
                name=row.name,
                sector=row.sector or None,
                entry_price=row.price,
                current_price=row.price,
                highest_price=row.price,
                weight=row.weight,
                stop_loss_hard=row.stop_loss_hard,
                stop_loss_trailing=row.stop_loss_trailing,
                portfolio_stop_loss=row.portfolio_stop_loss,
                kelly_fraction=row.kelly_fraction,
                win_prob=row.win_prob,
                payoff_ratio=row.payoff_ratio,
            )
        return preview

    def refresh_active_holdings(
        self,
        *,
        source: str = "manual",
        market: Market = Market.A_SHARE,
    ) -> ShadowRefreshResult:
        source = source if source in {"manual", "pipeline"} else "manual"
        holdings = self.repository.list_active_holdings()
        refreshed: list[dict] = []
        failures: list[ShadowRefreshFailure] = []

        for holding in holdings:
            try:
                latest = self._latest_price(str(holding["symbol"]), market)
            except Exception as exc:
                failures.append(
                    ShadowRefreshFailure(
                        symbol=str(holding["symbol"]),
                        name=str(holding.get("name") or holding["symbol"]),
                        reason=str(exc),
                    )
                )
                refreshed.append(dict(holding))
                continue

            updated = dict(holding)
            updated["current_price"] = latest
            updated["highest_price"] = max(float(holding["highest_price"]), latest)
            refreshed.append(updated)

        portfolio_stop_triggered = _portfolio_stop_triggered(refreshed)
        updated_count = 0
        for holding in refreshed:
            if any(failure.symbol == holding["symbol"] for failure in failures):
                continue
            current_price = float(holding["current_price"])
            highest_price = float(holding["highest_price"])
            self.repository.update_holding_price(str(holding["symbol"]), current_price)
            self.repository.save_shadow_position_snapshot(
                snapshot_id=uuid4().hex,
                symbol=str(holding["symbol"]),
                name=str(holding["name"]),
                sector=holding.get("sector"),
                entry_price=float(holding["entry_price"]),
                current_price=current_price,
                highest_price=highest_price,
                weight=float(holding["weight"]),
                kelly_fraction=float(holding.get("kelly_fraction") or holding["weight"]),
                win_prob=float(holding.get("win_prob") or 0.0),
                payoff_ratio=float(holding.get("payoff_ratio") or 0.0),
                unrealized_return=_return_from_entry(holding),
                drawdown_from_entry=_return_from_entry(holding),
                drawdown_from_high=_drawdown_from_high(holding),
                stop_loss_hard=float(holding.get("stop_loss_hard", -0.20)),
                stop_loss_trailing=float(holding.get("stop_loss_trailing", -0.15)),
                portfolio_stop_loss=float(holding.get("portfolio_stop_loss", -0.10)),
                hard_stop_triggered=_hard_stop_triggered(holding),
                trailing_stop_triggered=_trailing_stop_triggered(holding),
                portfolio_stop_triggered=portfolio_stop_triggered,
                refresh_source=source,
            )
            updated_count += 1

        return ShadowRefreshResult(
            updated_count=updated_count,
            failures=failures,
            alerts=self.stop_monitor.scan(),
            source=source,
        )

    def update_holding_cost(self, symbol: str, entry_price: float) -> None:
        if entry_price <= 0.0:
            raise ValueError("成本价必须大于 0")
        self.repository.update_holding_cost(symbol, entry_price)

    def delete_holding(self, symbol: str) -> None:
        self.repository.delete_active_holding(symbol)

    def cleanup_legacy_holdings(self) -> list[str]:
        removed: list[str] = []
        for holding in self.repository.list_active_holdings():
            if _is_legacy_fixed_weight_holding(holding):
                symbol = str(holding["symbol"])
                self.repository.delete_active_holding(symbol)
                removed.append(symbol)
        return removed

    def _latest_price(self, symbol: str, market: Market) -> float:
        bars = self.price_fetcher.fetch_ohlcv(symbol, market, days=120)
        if not bars:
            raise RuntimeError("没有可用价格")
        price = float(bars[-1].close)
        if price <= 0.0:
            raise RuntimeError("最新价无效")
        return price


def _default_repository() -> MGFSRepository:
    settings = AppSettings()
    repo = MGFSRepository(Database(settings.database_path))
    repo.bootstrap()
    return repo


def _default_sector_limits() -> dict[str, float]:
    return {
        "白酒": 0.25,
        "新能源": 0.30,
        "家电": 0.25,
        "半导体": 0.30,
        "医疗": 0.25,
    }


def _normalize_candidate(candidate: ManualShadowCandidate) -> ManualShadowCandidate:
    price = candidate.price
    if price is not None and price <= 0.0:
        price = None
    return ManualShadowCandidate(
        symbol=candidate.symbol.strip(),
        name=(candidate.name or candidate.symbol).strip(),
        sector=(candidate.sector or "").strip(),
        final_score=float(candidate.final_score),
        payoff_ratio=float(candidate.payoff_ratio),
        price=price,
    )


def _candidate_error(candidate: ManualShadowCandidate) -> str | None:
    if not candidate.symbol:
        return "股票代码不能为空"
    if candidate.price is None or candidate.price <= 0.0:
        return "成本价必须手动输入且大于 0"
    if candidate.final_score < 0.0 or candidate.final_score > 100.0:
        return "MGFS 分数必须在 0 到 100 之间"
    if candidate.payoff_ratio <= 0.0:
        return "赔率假设必须大于 0"
    return None


def _error_row(candidate: ManualShadowCandidate, error: str) -> ShadowPreviewRow:
    return ShadowPreviewRow(
        symbol=candidate.symbol,
        name=candidate.name,
        sector=candidate.sector,
        final_score=candidate.final_score,
        payoff_ratio=candidate.payoff_ratio,
        price=candidate.price,
        error=error,
    )


def _return_from_entry(holding: dict) -> float:
    entry = float(holding["entry_price"])
    if entry <= 0.0:
        return 0.0
    return float(holding["current_price"]) / entry - 1.0


def _drawdown_from_high(holding: dict) -> float:
    highest = float(holding["highest_price"])
    if highest <= 0.0:
        return 0.0
    return float(holding["current_price"]) / highest - 1.0


def _hard_stop_triggered(holding: dict) -> bool:
    entry = float(holding["entry_price"])
    current = float(holding["current_price"])
    limit = float(holding.get("stop_loss_hard", -0.20))
    return current <= entry * (1.0 + limit)


def _trailing_stop_triggered(holding: dict) -> bool:
    highest = float(holding["highest_price"])
    current = float(holding["current_price"])
    limit = float(holding.get("stop_loss_trailing", -0.15))
    return current <= highest * (1.0 + limit)


def _portfolio_stop_triggered(holdings: list[dict]) -> bool:
    if not holdings:
        return False
    total_entry_value = 0.0
    total_current_value = 0.0
    for holding in holdings:
        entry = float(holding["entry_price"])
        if entry <= 0.0:
            continue
        weight = float(holding.get("weight", 0.0))
        total_entry_value += weight
        total_current_value += weight * (float(holding["current_price"]) / entry)
    if total_entry_value <= 0.0:
        return False
    limit = abs(float(holdings[0].get("portfolio_stop_loss", -0.10)))
    drawdown = 1.0 - (total_current_value / total_entry_value)
    return drawdown >= limit


def _is_legacy_fixed_weight_holding(holding: dict) -> bool:
    symbol = str(holding.get("symbol") or "")
    name = str(holding.get("name") or "")
    sector = holding.get("sector")
    if not symbol or name != symbol or sector:
        return False
    if float(holding.get("entry_price") or 0.0) != 100.0:
        return False
    if float(holding.get("current_price") or 0.0) != 100.0:
        return False
    if float(holding.get("highest_price") or 0.0) != 100.0:
        return False
    if abs(float(holding.get("weight") or 0.0) - 0.20) > 1e-9:
        return False
    return float(holding.get("payoff_ratio") or 0.0) == 0.0
