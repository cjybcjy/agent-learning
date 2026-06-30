from datetime import date

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse

from sentinel.web.services.candidate_discovery_service import CandidateDiscoveryService
from sentinel.web.services.eval_service import evaluate_single
from sentinel.web.services.fundamental_advice_service import FundamentalAdviceService
from sentinel.web.services.judgment_ticket_service import build_judgment_ticket
from sentinel.web.services.research_data_task_service import ResearchDataTaskService
from sentinel.web.services.moat_service import build_moat_radar_data
from sentinel.web.services.serenity_metric_backfill_service import (
    SerenityMetricBackfillService,
)
from sentinel.web.services.serenity_verification_service import (
    SerenityVerificationService,
)
from sentinel.web.services.valuation_chart_service import build_valuation_band_data
from sentinel.web.services.scan_service import (
    create_task,
    get_task,
    run_scan_task,
)

router = APIRouter()
_fundamental_advice_svc: FundamentalAdviceService | None = None
_serenity_verification_svc: SerenityVerificationService | None = None
_serenity_metric_backfill_svc: SerenityMetricBackfillService | None = None
_research_data_task_svc: ResearchDataTaskService | None = None


def _get_fundamental_advice_service() -> FundamentalAdviceService:
    global _fundamental_advice_svc
    if _fundamental_advice_svc is None:
        _fundamental_advice_svc = FundamentalAdviceService()
    return _fundamental_advice_svc


def _get_serenity_verification_service() -> SerenityVerificationService:
    global _serenity_verification_svc
    if _serenity_verification_svc is None:
        _serenity_verification_svc = SerenityVerificationService()
    return _serenity_verification_svc


def _get_serenity_metric_backfill_service() -> SerenityMetricBackfillService:
    global _serenity_metric_backfill_svc
    if _serenity_metric_backfill_svc is None:
        _serenity_metric_backfill_svc = SerenityMetricBackfillService()
    return _serenity_metric_backfill_svc


def _get_research_data_task_service() -> ResearchDataTaskService:
    global _research_data_task_svc
    if _research_data_task_svc is None:
        _research_data_task_svc = ResearchDataTaskService()
    return _research_data_task_svc


def _reset_runtime_services_after_metric_backfill() -> None:
    import sentinel.web.dependencies as deps

    deps._orchestrator = None
    deps._scanner = None


@router.post("/candidates/discover", response_class=HTMLResponse)
async def discover_candidates(
    request: Request,
    background: BackgroundTasks,
    theme: str = Form(""),
    roles: str = Form(""),
    policy: str = Form("neutral"),
    fund_rank_limit: str = Form(""),
    discovery_mode: str = Form("objective"),
):
    if not theme.strip():
        return HTMLResponse("<div class='empty-state min-h-[120px]'>请先选择宏观主题</div>")
    if discovery_mode == "scan":
        target_roles = [r.strip() for r in roles.split(",") if r.strip()] or None
        parsed_fund_rank_limit = _parse_optional_positive_int(fund_rank_limit)
        task_id = create_task(theme)
        background.add_task(
            run_scan_task,
            task_id,
            theme,
            target_roles,
            policy,
            parsed_fund_rank_limit,
        )
        return request.app.state.templates.get_template(
            "partials/scan_task_started.html"
        ).render({"request": request, "task_id": task_id})
    result = CandidateDiscoveryService().discover_theme(theme)
    return request.app.state.templates.get_template(
        "partials/candidate_discovery.html"
    ).render(
        {
            "request": request,
            "result": result,
            "source_labels": {
                "concept": "概念板块",
                "industry": "行业板块",
            },
        }
    )


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
    moat_radar_data = build_moat_radar_data(symbol)
    valuation_band_data = build_valuation_band_data(
        symbol=symbol,
        market=decision.target.market,
        sector=decision.target.sector,
    )
    template = request.app.state.templates.get_template("partials/decision_card.html")
    content = template.render(
        {
            "request": request,
            "decision": decision,
            "judgment_ticket": build_judgment_ticket(decision),
            "moat_radar_data": moat_radar_data,
            "valuation_band_data": valuation_band_data,
        }
    )
    return HTMLResponse(content=content)


@router.post("/fundamental-advice", response_class=HTMLResponse)
async def fundamental_advice(
    request: Request,
    symbol: str = Form(...),
    market: str = Form("A_SHARE"),
):
    advice = _get_fundamental_advice_service().generate(
        symbol=symbol,
        market=market,
    )
    return request.app.state.templates.get_template(
        "partials/fundamental_advice.html"
    ).render({"request": request, "advice": advice})


@router.post("/serenity-verification-plan", response_class=HTMLResponse)
async def serenity_verification_plan(
    request: Request,
    symbol: str = Form(...),
    market: str = Form("A_SHARE"),
):
    plan = _get_serenity_verification_service().build_plan(
        symbol=symbol,
        market=market,
    )
    return request.app.state.templates.get_template(
        "partials/serenity_verification_plan.html"
    ).render({"request": request, "plan": plan})


@router.post("/serenity-metric-backfill", response_class=HTMLResponse)
async def serenity_metric_backfill(request: Request):
    form = await request.form()
    symbol = str(form.get("symbol", "")).strip()
    market = str(form.get("market", "A_SHARE")).strip() or "A_SHARE"
    source = str(form.get("source", "")).strip()
    source_url = str(form.get("source_url", "")).strip() or None
    as_of_raw = str(form.get("as_of", "")).strip()

    try:
        as_of = date.fromisoformat(as_of_raw)
        values = _extract_metric_values(form)
        result = _get_serenity_metric_backfill_service().backfill(
            symbol=symbol,
            market=market,
            values=values,
            source=source,
            as_of=as_of,
            source_url=source_url,
        )
    except ValueError as exc:
        return HTMLResponse(
            (
                "<div class='rounded-md border border-red-200 bg-red-50 px-3 py-2 "
                f"text-sm text-red-700'>回填失败: {exc}</div>"
            ),
            status_code=400,
        )

    _reset_runtime_services_after_metric_backfill()
    return request.app.state.templates.get_template(
        "partials/serenity_metric_backfill_result.html"
    ).render({"request": request, "result": result})


@router.post("/research-data/fill-gaps", response_class=HTMLResponse)
async def research_data_fill_gaps(request: Request):
    form = await request.form()
    symbol = str(form.get("symbol", "")).strip()
    market = str(form.get("market", "A_SHARE")).strip() or "A_SHARE"
    task_keys = [str(value).strip() for value in form.getlist("task_keys") if str(value).strip()]
    kwargs = {"symbol": symbol, "market": market}
    if task_keys:
        kwargs["task_keys"] = task_keys
    result = _get_research_data_task_service().fill_gaps(**kwargs)
    if result.inserted_metric_count > 0:
        _reset_runtime_services_after_metric_backfill()
    return request.app.state.templates.get_template(
        "partials/research_data_fill_result.html"
    ).render({"request": request, "result": result})


def _extract_metric_values(form) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, raw_value in form.items():
        if not key.startswith("metric_"):
            continue
        value_text = str(raw_value).strip()
        if not value_text:
            continue
        values[key.removeprefix("metric_")] = float(value_text)
    if not values:
        raise ValueError("请至少填写一个动态指标")
    return values


@router.post("/scan/start", response_class=HTMLResponse)
async def scan_start(
    request: Request,
    background: BackgroundTasks,
    theme: str = Form(...),
    roles: str = Form(""),
    policy: str = Form("neutral"),
    fund_rank_limit: str = Form(""),
):
    target_roles = [r.strip() for r in roles.split(",") if r.strip()] or None
    parsed_fund_rank_limit = _parse_optional_positive_int(fund_rank_limit)
    task_id = create_task(theme)
    background.add_task(
        run_scan_task,
        task_id,
        theme,
        target_roles,
        policy,
        parsed_fund_rank_limit,
    )
    return request.app.state.templates.get_template(
        "partials/scan_task_started.html"
    ).render({"request": request, "task_id": task_id})


def _parse_optional_positive_int(value: str) -> int | None:
    if not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
