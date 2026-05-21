from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from sentinel.mgfs.execution.stop_loss_monitor import StopLossMonitor
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.web.services.config_service import (
    load_config,
    save_config,
    validate_config,
)
from sentinel.web.services.pipeline_service import PipelineService

router = APIRouter()
_pipeline_svc: PipelineService | None = None
_sl_monitor: StopLossMonitor | None = None
_repo_instance: MGFSRepository | None = None


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
    is_valid, errors = validate_config(content)
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
