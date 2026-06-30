from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from sentinel.domain.models import Market
from sentinel.mgfs.execution.stop_loss_monitor import StopLossMonitor
from sentinel.mgfs.evolution.backtest_cli import _run_backtest
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.mgfs.target_resolver import load_target_name_map
from sentinel.web.services.config_service import (
    load_config,
    save_score_composition,
    save_config,
    validate_config,
)
from sentinel.web.services.config_change_service import ConfigChangeService
from sentinel.web.services.pipeline_service import PipelineService
from sentinel.web.services.research_agent_service import ResearchAgentService
from sentinel.web.services.research_signal_collector_service import (
    ResearchSignalCollectorService,
)
from sentinel.web.services.shadow_position_service import (
    ManualShadowCandidate,
    ShadowPositionSimulatorService,
)

router = APIRouter()
DEFAULT_BACKTEST_START_DATE = "2025-01-01"
DEFAULT_BACKTEST_END_DATE = "2025-06-30"
_pipeline_svc: PipelineService | None = None
_sl_monitor: StopLossMonitor | None = None
_repo_instance: MGFSRepository | None = None
_research_agent_svc: ResearchAgentService | None = None
_config_change_svc: ConfigChangeService | None = None
_signal_collector_svc: ResearchSignalCollectorService | None = None
_shadow_position_svc: ShadowPositionSimulatorService | None = None


def _get_repository() -> MGFSRepository:
    global _repo_instance
    if _repo_instance is None:
        from sentinel.config import AppSettings
        from sentinel.storage.db import Database
        settings = AppSettings()
        _repo_instance = MGFSRepository(Database(settings.database_path))
        _repo_instance.bootstrap()
    return _repo_instance


def _get_pipeline_service() -> PipelineService:
    global _pipeline_svc
    if _pipeline_svc is None:
        _pipeline_svc = PipelineService()
    return _pipeline_svc


def _get_research_agent_service() -> ResearchAgentService:
    global _research_agent_svc
    if _research_agent_svc is None:
        _research_agent_svc = ResearchAgentService()
    return _research_agent_svc


def _get_config_change_service() -> ConfigChangeService:
    global _config_change_svc
    if _config_change_svc is None:
        _config_change_svc = ConfigChangeService()
    return _config_change_svc


def _get_signal_collector_service() -> ResearchSignalCollectorService:
    global _signal_collector_svc
    if _signal_collector_svc is None:
        _signal_collector_svc = ResearchSignalCollectorService()
    return _signal_collector_svc


def _get_shadow_position_service() -> ShadowPositionSimulatorService:
    global _shadow_position_svc
    if _shadow_position_svc is None:
        _shadow_position_svc = ShadowPositionSimulatorService()
    return _shadow_position_svc


def _reset_runtime_services() -> None:
    global _pipeline_svc, _sl_monitor, _repo_instance, _shadow_position_svc
    import sentinel.web.dependencies as deps

    deps._orchestrator = None
    deps._scanner = None
    _pipeline_svc = None
    _sl_monitor = None
    _repo_instance = None
    _shadow_position_svc = None


def _get_stop_loss_monitor() -> StopLossMonitor:
    global _sl_monitor
    if _sl_monitor is None:
        from sentinel.config import AppSettings
        from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
        from sentinel.storage.db import Database
        settings = AppSettings()
        repo = MGFSRepository(Database(settings.database_path))
        repo.bootstrap()
        _sl_monitor = StopLossMonitor(repo)
    return _sl_monitor


def _render_research_agent_panel(
    request: Request,
    run=None,
    message: str | None = None,
):
    return request.app.state.templates.get_template(
        "partials/research_agent_panel.html"
    ).render(
        {
            "request": request,
            "run": run,
            "message": message,
            "status_labels": {
                "pending": "待处理",
                "queued": "已加入待办",
                "watching": "观察中",
                "rejected": "已搁置",
            },
        }
    )


def _render_config_proposal_panel(
    request: Request,
    message: str | None = None,
):
    service = _get_config_change_service()
    return request.app.state.templates.get_template(
        "partials/config_proposal_panel.html"
    ).render(
        {
            "request": request,
            "proposals": service.scan_proposals(),
            "message": message,
            "action_labels": {
                "add": "添加",
                "delete": "删除",
            },
        }
    )


def _render_review_queue_panel(
    request: Request,
    run=None,
    message: str | None = None,
):
    if run is None:
        run = _get_research_agent_service().ensure_daily_review()
    return request.app.state.templates.get_template(
        "partials/review_queue_panel.html"
    ).render(
        {
            "request": request,
            "run": run,
            "suggestions": [
                item
                for item in (run.suggestions if run else [])
                if item.status != "rejected"
            ],
            "proposals": _get_config_change_service().scan_proposals(),
            "message": message,
            "status_labels": {
                "pending": "待处理",
                "queued": "已加入确认",
                "watching": "观察中",
                "rejected": "已搁置",
            },
            "action_labels": {
                "add": "添加",
                "delete": "删除",
            },
        }
    )


# ------------------------------------------------------------------
# Daily Research Agent (read-only config suggestions)
# ------------------------------------------------------------------


@router.get("/review-queue/panel", response_class=HTMLResponse)
async def review_queue_panel(request: Request):
    _get_signal_collector_service().ensure_daily_snapshot()
    return _render_review_queue_panel(request)


@router.post("/review-queue/run", response_class=HTMLResponse)
async def review_queue_run(request: Request):
    run = _get_research_agent_service().run_daily_review()
    return _render_review_queue_panel(
        request,
        run=run,
        message=f"已刷新 {len(run.suggestions)} 条 Agent 建议",
    )


@router.post("/review-queue/collect", response_class=HTMLResponse)
async def review_queue_collect(request: Request):
    snapshot = _get_signal_collector_service().collect()
    run = _get_research_agent_service().run_daily_review()
    return _render_review_queue_panel(
        request,
        run=run,
        message=f"外部信号已更新：{len(snapshot.get('items', []))} 条",
    )


@router.post(
    "/review-queue/suggestions/{suggestion_id}/status",
    response_class=HTMLResponse,
)
async def review_queue_update_suggestion_status(
    request: Request,
    suggestion_id: str,
    status: str = Form(...),
):
    service = _get_research_agent_service()
    try:
        updated = service.update_suggestion_status(suggestion_id, status)
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    return _render_review_queue_panel(
        request,
        run=service.load_latest_run(),
        message=f"{updated.title} 已更新为 {updated.status}",
    )


@router.post(
    "/review-queue/suggestions/{suggestion_id}/queue-confirmation",
    response_class=HTMLResponse,
)
async def review_queue_queue_confirmation(request: Request, suggestion_id: str):
    agent_service = _get_research_agent_service()
    run = agent_service.load_latest_run() or agent_service.ensure_daily_review()
    suggestion = next(
        (item for item in run.suggestions if item.id == suggestion_id),
        None,
    )
    if suggestion is None:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>未找到建议: {suggestion_id}</div>",
            status_code=404,
        )
    try:
        proposals = _get_config_change_service().queue_agent_suggestion(suggestion)
        agent_service.update_suggestion_status(suggestion_id, "queued")
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    return _render_review_queue_panel(
        request,
        run=agent_service.load_latest_run(),
        message=f"{suggestion.title} 已加入确认队列（{len(proposals)} 项）",
    )


@router.post("/review-queue/proposals/{proposal_id}/approve", response_class=HTMLResponse)
async def review_queue_proposal_approve(request: Request, proposal_id: str):
    service = _get_config_change_service()
    try:
        proposal = service.approve_proposal(proposal_id)
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    _reset_runtime_services()
    return _render_review_queue_panel(request, message=f"{proposal.title} 已应用")


@router.post("/review-queue/proposals/{proposal_id}/reject", response_class=HTMLResponse)
async def review_queue_proposal_reject(request: Request, proposal_id: str):
    service = _get_config_change_service()
    try:
        proposal = service.reject_proposal(proposal_id)
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    return _render_review_queue_panel(request, message=f"{proposal.title} 已搁置")


@router.get("/research-agent/panel", response_class=HTMLResponse)
async def research_agent_panel(request: Request):
    _get_signal_collector_service().ensure_daily_snapshot()
    service = _get_research_agent_service()
    return _render_research_agent_panel(request, run=service.ensure_daily_review())


@router.post("/research-agent/run", response_class=HTMLResponse)
async def research_agent_run(request: Request):
    service = _get_research_agent_service()
    run = service.run_daily_review()
    return _render_research_agent_panel(
        request,
        run=run,
        message=f"今日研究 Agent 已生成 {len(run.suggestions)} 条只读建议",
    )


@router.post("/research-agent/collect", response_class=HTMLResponse)
async def research_agent_collect(request: Request):
    snapshot = _get_signal_collector_service().collect()
    service = _get_research_agent_service()
    run = service.run_daily_review()
    return _render_research_agent_panel(
        request,
        run=run,
        message=f"外部信号已更新：{len(snapshot.get('items', []))} 条",
    )


@router.post(
    "/research-agent/suggestions/{suggestion_id}/status",
    response_class=HTMLResponse,
)
async def research_agent_update_suggestion_status(
    request: Request,
    suggestion_id: str,
    status: str = Form(...),
):
    service = _get_research_agent_service()
    try:
        updated = service.update_suggestion_status(suggestion_id, status)
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    run = service.load_latest_run()
    status_labels = {
        "pending": "待处理",
        "queued": "已加入待办",
        "watching": "观察中",
        "rejected": "已搁置",
    }
    return _render_research_agent_panel(
        request,
        run=run,
        message=f"{updated.title} {status_labels[updated.status]}",
    )


@router.post(
    "/research-agent/suggestions/{suggestion_id}/queue-confirmation",
    response_class=HTMLResponse,
)
async def research_agent_queue_confirmation(request: Request, suggestion_id: str):
    agent_service = _get_research_agent_service()
    run = agent_service.load_latest_run()
    if run is None:
        return HTMLResponse(
            "<div class='text-red-600 text-sm'>还没有可加入确认名单的 Agent 运行记录</div>",
            status_code=400,
        )

    suggestion = next(
        (item for item in run.suggestions if item.id == suggestion_id),
        None,
    )
    if suggestion is None:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>未找到建议: {suggestion_id}</div>",
            status_code=404,
        )

    change_service = _get_config_change_service()
    try:
        proposals = change_service.queue_agent_suggestion(suggestion)
        agent_service.update_suggestion_status(suggestion_id, "queued")
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    return _render_config_proposal_panel(
        request,
        message=f"{suggestion.title} 已加入半自动确认名单（{len(proposals)} 项）",
    )


@router.get("/config/proposals/panel", response_class=HTMLResponse)
async def config_proposals_panel(request: Request):
    return _render_config_proposal_panel(request)


@router.post("/config/proposals/{proposal_id}/approve", response_class=HTMLResponse)
async def config_proposal_approve(request: Request, proposal_id: str):
    service = _get_config_change_service()
    try:
        proposal = service.approve_proposal(proposal_id)
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    _reset_runtime_services()
    return _render_config_proposal_panel(request, message=f"{proposal.title} 已应用")


@router.post("/config/proposals/{proposal_id}/reject", response_class=HTMLResponse)
async def config_proposal_reject(request: Request, proposal_id: str):
    service = _get_config_change_service()
    try:
        proposal = service.reject_proposal(proposal_id)
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='text-red-600 text-sm'>{str(exc)}</div>",
            status_code=400,
        )
    return _render_config_proposal_panel(request, message=f"{proposal.title} 已搁置")


@router.get("/config/load/{filename}", response_class=HTMLResponse)
async def config_load(request: Request, filename: str):
    try:
        content = load_config(filename)
    except ValueError as e:
        return HTMLResponse(f"<div class='text-red-600'>{str(e)}</div>", status_code=400)
    return request.app.state.templates.get_template("partials/config_editor.html").render(
        {"request": request, "filename": filename, "content": content}
    )


@router.post("/config/validate", response_class=HTMLResponse)
async def config_validate(request: Request):
    body = await request.form()
    content = body.get("content", "")
    filename = body.get("filename")
    is_valid, errors = validate_config(
        str(content),
        str(filename) if filename else None,
    )
    return request.app.state.templates.get_template("partials/config_status.html").render(
        {
            "request": request,
            "is_valid": is_valid,
            "message": "\n".join(errors) if errors else "YAML 语法和 Schema 校验通过",
        }
    )


@router.post("/config/save", response_class=HTMLResponse)
async def config_save(
    request: Request,
    filename: str = Form(...),
    content: str = Form(...),
):
    try:
        success, message = save_config(filename, content)
    except Exception as e:
        success = False
        message = f"保存失败: {str(e)}"
    if success:
        _reset_runtime_services()
    return request.app.state.templates.get_template("partials/config_status.html").render(
        {
            "request": request,
            "is_valid": success,
            "message": message,
        }
    )


@router.post("/config/score-composition", response_class=HTMLResponse)
async def config_score_composition_save(
    request: Request,
    moat_weight: float = Form(...),
    valuation_weight: float = Form(...),
    policy_weight: float = Form(...),
    timing_weight: float = Form(...),
    strong_buy_min_score: float = Form(...),
    accumulate_min_score: float = Form(...),
    hold_watch_min_score: float = Form(...),
):
    try:
        success, message = save_score_composition(
            moat_weight=moat_weight,
            valuation_weight=valuation_weight,
            policy_weight=policy_weight,
            timing_weight=timing_weight,
            strong_buy_min_score=strong_buy_min_score,
            accumulate_min_score=accumulate_min_score,
            hold_watch_min_score=hold_watch_min_score,
        )
    except Exception as e:
        success = False
        message = f"保存失败: {str(e)}"
    if success:
        _reset_runtime_services()
    return request.app.state.templates.get_template("partials/config_status.html").render(
        {
            "request": request,
            "is_valid": success,
            "message": message,
        }
    )


@router.get("/pipeline/history", response_class=HTMLResponse)
async def pipeline_history(request: Request):
    svc = _get_pipeline_service()
    batches = svc.get_history(limit=50)
    return request.app.state.templates.get_template("partials/pipeline_history.html").render(
        {"request": request, "batches": batches}
    )


@router.post("/pipeline/trigger", response_class=HTMLResponse)
async def pipeline_trigger(request: Request, background_tasks: BackgroundTasks):
    svc = _get_pipeline_service()
    batch_id = svc.create_batch()
    background_tasks.add_task(svc.run_pipeline, batch_id)
    return request.app.state.templates.get_template("partials/pipeline_history.html").render(
        {
            "request": request,
            "batches": svc.get_history(limit=50),
            "message": f"批次 {batch_id} 已启动，后台扫描中...",
        }
    )


@router.get("/pipeline/detail/{batch_id}", response_class=HTMLResponse)
async def pipeline_detail(request: Request, batch_id: str):
    svc = _get_pipeline_service()
    results = svc.get_pipeline_results(batch_id)
    return request.app.state.templates.get_template("partials/pipeline_detail_table.html").render(
        {"request": request, "results": results, "batch_id": batch_id}
    )


@router.get("/pipeline/export/{batch_id}")
async def pipeline_export(batch_id: str):
    svc = _get_pipeline_service()
    csv_data = svc.export_csv(batch_id)
    return PlainTextResponse(
        csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={batch_id}.csv"},
    )


# ------------------------------------------------------------------
# Risk Alert Banner (StopLossMonitor)
# ------------------------------------------------------------------

@router.get("/risk/alerts", response_class=HTMLResponse)
async def risk_alerts(request: Request):
    monitor = _get_stop_loss_monitor()
    alerts = monitor.scan()
    return request.app.state.templates.get_template(
        "partials/risk_alert_banner.html"
    ).render({"request": request, "alerts": alerts})


@router.post("/risk/dismiss", response_class=HTMLResponse)
async def risk_dismiss(
    request: Request,
    symbol: str = Form(...),
    action: str = Form(...),  # "close" or "reset"
    new_price: float = Form(0.0),
):
    monitor = _get_stop_loss_monitor()
    if action == "close":
        monitor.dismiss_and_close_position(symbol)
    elif action == "reset" and new_price > 0:
        monitor.dismiss_and_reset_baseline(symbol, new_price)
    # Re-scan to return fresh banner state
    alerts = monitor.scan()
    return request.app.state.templates.get_template(
        "partials/risk_alert_banner.html"
    ).render({"request": request, "alerts": alerts})


def _form_values(form, key: str) -> list[str]:
    return [str(value) for value in form.getlist(key)]


def _float_or_none(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _market_from_form(value: str | None) -> Market:
    if value and value in Market.__members__:
        return Market[value]
    return Market.A_SHARE


def _shadow_candidates_from_form(form) -> list[ManualShadowCandidate]:
    symbols = _form_values(form, "symbol")
    names = _form_values(form, "name")
    sectors = _form_values(form, "sector")
    final_scores = _form_values(form, "final_score")
    payoff_ratios = _form_values(form, "payoff_ratio")
    prices = _form_values(form, "price")
    candidates: list[ManualShadowCandidate] = []
    row_count = max(
        len(symbols), len(names), len(sectors),
        len(final_scores), len(payoff_ratios), len(prices),
    )
    for idx in range(row_count):
        symbol = symbols[idx].strip() if idx < len(symbols) else ""
        name = names[idx].strip() if idx < len(names) else ""
        sector = sectors[idx].strip() if idx < len(sectors) else ""
        final_score = _float_or_none(final_scores[idx] if idx < len(final_scores) else None)
        payoff_ratio = _float_or_none(payoff_ratios[idx] if idx < len(payoff_ratios) else None)
        price = _float_or_none(prices[idx] if idx < len(prices) else None)
        if not any([symbol, name, sector, final_score is not None, payoff_ratio is not None, price is not None]):
            continue
        candidates.append(
            ManualShadowCandidate(
                symbol=symbol,
                name=name or symbol,
                sector=sector,
                final_score=final_score if final_score is not None else -1.0,
                payoff_ratio=payoff_ratio if payoff_ratio is not None else -1.0,
                price=price,
            )
        )
    return candidates


def _shadow_holdings(service: ShadowPositionSimulatorService) -> list[dict]:
    return service.repository.list_active_holdings()


def _shadow_alerts(service: ShadowPositionSimulatorService):
    return StopLossMonitor(service.repository).scan()


def _render_shadow_holdings(
    request: Request,
    service: ShadowPositionSimulatorService,
    *,
    message: str | None = None,
    refresh_result=None,
    status_code: int = 200,
) -> HTMLResponse:
    html = request.app.state.templates.get_template(
        "partials/shadow_position_holdings.html"
    ).render(
        {
            "request": request,
            "holdings": _shadow_holdings(service),
            "alerts": _shadow_alerts(service),
            "message": message,
            "refresh_result": refresh_result,
        }
    )
    return HTMLResponse(html, status_code=status_code)


@router.get("/shadow-positions/panel", response_class=HTMLResponse)
async def shadow_positions_panel(request: Request):
    service = _get_shadow_position_service()
    return request.app.state.templates.get_template(
        "partials/shadow_position_panel.html"
    ).render(
        {
            "request": request,
            "holdings": _shadow_holdings(service),
            "alerts": _shadow_alerts(service),
            "refresh_result": None,
        }
    )


@router.post("/shadow-positions/preview", response_class=HTMLResponse)
async def shadow_positions_preview(request: Request):
    form = await request.form()
    service = _get_shadow_position_service()
    preview = service.preview_candidates(
        _shadow_candidates_from_form(form),
        market=_market_from_form(str(form.get("market") or "")),
    )
    return request.app.state.templates.get_template(
        "partials/shadow_position_preview.html"
    ).render({"request": request, "preview": preview})


@router.post("/shadow-positions/confirm", response_class=HTMLResponse)
async def shadow_positions_confirm(request: Request):
    form = await request.form()
    service = _get_shadow_position_service()
    service.confirm_candidates(
        _shadow_candidates_from_form(form),
        market=_market_from_form(str(form.get("market") or "")),
    )
    return _render_shadow_holdings(
        request,
        service,
        message="已写入影子持仓",
    )


@router.post("/shadow-positions/{symbol}/cost", response_class=HTMLResponse)
async def shadow_positions_update_cost(
    request: Request,
    symbol: str,
    entry_price: float = Form(...),
):
    service = _get_shadow_position_service()
    try:
        service.update_holding_cost(symbol, entry_price)
    except ValueError as exc:
        return _render_shadow_holdings(
            request,
            service,
            message=str(exc),
            status_code=400,
        )
    return _render_shadow_holdings(
        request,
        service,
        message=f"{symbol} 成本价已更新",
    )


@router.post("/shadow-positions/{symbol}/delete", response_class=HTMLResponse)
async def shadow_positions_delete(request: Request, symbol: str):
    service = _get_shadow_position_service()
    service.delete_holding(symbol)
    return _render_shadow_holdings(
        request,
        service,
        message=f"{symbol} 已删除",
    )


@router.post("/shadow-positions/cleanup-legacy", response_class=HTMLResponse)
async def shadow_positions_cleanup_legacy(request: Request):
    service = _get_shadow_position_service()
    removed = service.cleanup_legacy_holdings()
    return _render_shadow_holdings(
        request,
        service,
        message=f"已清理旧影子持仓 {len(removed)} 条",
    )


@router.post("/shadow-positions/refresh", response_class=HTMLResponse)
async def shadow_positions_refresh(
    request: Request,
    source: str = Form("manual"),
):
    service = _get_shadow_position_service()
    result = service.refresh_active_holdings(source=source)
    return _render_shadow_holdings(request, service, refresh_result=result)


# ------------------------------------------------------------------
# Historical backtest reports
# ------------------------------------------------------------------

@router.get("/calibration/reports", response_class=HTMLResponse)
async def calibration_reports(
    request: Request,
    start_date: str = DEFAULT_BACKTEST_START_DATE,
    end_date: str = DEFAULT_BACKTEST_END_DATE,
    symbols: str = "300750,600519",
):
    from datetime import date as dt_date
    from pathlib import Path

    from sentinel.config import AppSettings
    from sentinel.mgfs.evolution.backtest_cli import _load_eastmoney_cache, _load_yaml_scores
    from sentinel.mgfs.evolution.research_artifacts import (
        file_content_hash,
        stable_json_hash,
        write_backtest_research_artifacts,
    )

    settings = AppSettings()
    score_path = settings.resolved_config_dir / "moat_static_base.yaml"
    config_hash = file_content_hash(score_path)
    external_signal_hash = file_content_hash(
        settings.database_path.parent / "research_external_signals.json"
    )
    static_scores = _load_yaml_scores(score_path)
    target_names = load_target_name_map(score_path)

    cache_dir = Path.home() / ".cache" / "sentinel" / "eastmoney"
    start = dt_date.fromisoformat(start_date)
    end = dt_date.fromisoformat(end_date)
    symbol_list = [s.strip() for s in symbols.split(",")]

    price_loaders: dict[str, dict[dt_date, float]] = {}
    evaluators: dict[str, dict[dt_date, float]] = {}
    names: dict[str, str] = {}

    for symbol in symbol_list:
        cache_files = sorted(cache_dir.glob(f"{symbol}_all_*.json"))
        if not cache_files:
            continue
        try:
            import json
            raw_data = json.loads(cache_files[-1].read_text(encoding="utf-8"))
        except Exception:
            continue
        prices = _load_eastmoney_cache(raw_data, start, end)
        if not prices:
            continue
        price_loaders[symbol] = prices
        score = static_scores.get(symbol, 50.0)
        evaluators[symbol] = {d: score for d in prices}
        names[symbol] = target_names.get(symbol, symbol)

    reports = []
    validation_report = None
    research_run_dir = None
    if price_loaders:
        artifact_slug = stable_json_hash(
            {
                "symbols": sorted(price_loaders),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "config_hash": config_hash,
                "external_signal_hash": external_signal_hash,
            }
        )
        research_run_dir = (
            settings.database_path.parent
            / "mgfs_research_runs"
            / f"historical_backtest_{artifact_slug}"
        )
        validation_report = write_backtest_research_artifacts(
            run_dir=research_run_dir,
            symbols=list(price_loaders.keys()),
            names=names,
            static_scores=static_scores,
            price_loaders=price_loaders,
            start_date=start,
            end_date=end,
            config_hash=config_hash,
            external_signal_hash=external_signal_hash,
        )
        reports = _run_backtest(
            symbols=list(price_loaders.keys()),
            price_loaders=price_loaders,
            evaluators=evaluators,
            static_scores=static_scores,
            names=names,
            start_date=start,
            end_date=end,
            min_samples=30,
        )

    return request.app.state.templates.get_template(
        "partials/calibration_report.html"
    ).render(
        {
            "request": request,
            "reports": reports,
            "start_date": start_date,
            "end_date": end_date,
            "validation_report": validation_report,
            "research_run_dir": research_run_dir,
        }
    )
