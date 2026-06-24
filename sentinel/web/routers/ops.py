from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

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

router = APIRouter()
_pipeline_svc: PipelineService | None = None
_sl_monitor: StopLossMonitor | None = None
_repo_instance: MGFSRepository | None = None
_research_agent_svc: ResearchAgentService | None = None
_config_change_svc: ConfigChangeService | None = None
_signal_collector_svc: ResearchSignalCollectorService | None = None


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


def _reset_runtime_services() -> None:
    global _pipeline_svc, _sl_monitor, _repo_instance
    import sentinel.web.dependencies as deps

    deps._orchestrator = None
    deps._scanner = None
    _pipeline_svc = None
    _sl_monitor = None
    _repo_instance = None


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


# ------------------------------------------------------------------
# Daily Research Agent (read-only config suggestions)
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Paper Trading Dock (shadow position)
# ------------------------------------------------------------------

@router.post("/paper_trade", response_class=HTMLResponse)
async def paper_trade(
    request: Request,
    symbol: str = Form(...),
    name: str = Form(...),
    sector: str = Form(""),
    price: float = Form(...),
    weight: float = Form(...),
):
    if price <= 0:
        return HTMLResponse(
            "<span class='text-red-600 text-xs'>价格必须大于 0</span>",
            status_code=400,
        )
    repo = _get_repository()
    repo.save_active_holding(
        symbol=symbol,
        name=name,
        sector=sector or None,
        entry_price=price,
        current_price=price,
        highest_price=price,
        weight=weight,
        stop_loss_hard=-0.20,
        stop_loss_trailing=-0.15,
        portfolio_stop_loss=-0.10,
    )
    return request.app.state.templates.get_template(
        "partials/paper_trade_success.html"
    ).render(
        {
            "request": request,
            "symbol": symbol,
            "name": name,
            "price": price,
            "weight": weight,
        }
    )


# ------------------------------------------------------------------
# Bayes Calibration Reports
# ------------------------------------------------------------------

@router.get("/calibration/reports", response_class=HTMLResponse)
async def calibration_reports(
    request: Request,
    start_date: str = "2025-01-01",
    end_date: str = "2025-06-30",
    symbols: str = "300750,600519",
):
    from datetime import date as dt_date
    from pathlib import Path

    from sentinel.config import AppSettings
    from sentinel.mgfs.evolution.backtest_cli import _load_eastmoney_cache, _load_yaml_scores

    settings = AppSettings()
    score_path = settings.resolved_config_dir / "moat_static_base.yaml"
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
    if price_loaders:
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
        }
    )
