from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse

from sentinel.web.services.eval_service import evaluate_single
from sentinel.web.services.scan_service import (
    create_task,
    get_task,
    run_scan_task,
)

router = APIRouter()


@router.post("/eval/share-lark")
async def eval_share_lark(symbol: str = Form(...), market: str = Form(...)):
    return {"status": "ok", "message": f"已同步 {symbol} ({market}) 到飞书群"}


@router.post("/eval/single", response_class=HTMLResponse)
async def eval_single(
    request: Request,
    symbol: str = Form(...),
    market: str = Form(...),
    policy: str = Form("neutral"),
):
    try:
        decision = evaluate_single(symbol=symbol, market=market, policy_rating=policy)
    except KeyError as e:
        return HTMLResponse(
            f"<div class='text-red-600 p-4'>无效的市场类型: {market}</div>",
            status_code=400,
        )
    except Exception as e:
        return HTMLResponse(
            f"<div class='text-red-600 p-4'>评估失败: {str(e)}</div>",
            status_code=500,
        )
    template = request.app.state.templates.get_template("partials/decision_card.html")
    content = template.render({"request": request, "decision": decision})
    return HTMLResponse(content=content)


@router.post("/scan/start", response_class=HTMLResponse)
async def scan_start(
    request: Request,
    background: BackgroundTasks,
    theme: str = Form(...),
    roles: str = Form(""),
    policy: str = Form("neutral"),
):
    target_roles = [r.strip() for r in roles.split(",") if r.strip()] or None
    task_id = create_task(theme)
    background.add_task(run_scan_task, task_id, theme, target_roles, policy)
    return request.app.state.templates.get_template("partials/scan_task_started.html").render(
        {"request": request, "task_id": task_id}
    )


@router.get("/scan/progress/{task_id}", response_class=HTMLResponse)
async def scan_progress(request: Request, task_id: str):
    task = get_task(task_id)
    if task is None:
        return HTMLResponse("任务不存在", status_code=404)
    return request.app.state.templates.get_template("partials/scan_progress.html").render(
        {
            "request": request,
            "status": task.status.value,
            "completed": task.completed,
            "total": task.total,
            "error": task.error,
        }
    )


@router.get("/scan/result/{task_id}", response_class=HTMLResponse)
async def scan_result(request: Request, task_id: str):
    task = get_task(task_id)
    if task is None:
        return HTMLResponse("任务不存在", status_code=404)
    return request.app.state.templates.get_template("partials/scan_matrix.html").render(
        {
            "request": request,
            "reports": task.reports,
            "summary": task.summary,
        }
    )
