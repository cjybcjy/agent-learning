from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from sentinel.web.routers.ops import (
    DEFAULT_BACKTEST_END_DATE,
    DEFAULT_BACKTEST_START_DATE,
)
from sentinel.web.services.config_service import load_score_composition
from sentinel.web.services.theme_service import load_macro_themes

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<script>window.location.href='/dashboard/research';</script>")


@router.get("/dashboard/research", response_class=HTMLResponse)
async def research_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="research.html",
        context={
            "active_nav": "research",
            "macro_themes": load_macro_themes(),
            "score_composition": load_score_composition(),
        },
    )


@router.get("/dashboard/ops", response_class=HTMLResponse)
async def ops_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="ops.html",
        context={
            "active_nav": "ops",
            "default_backtest_start_date": DEFAULT_BACKTEST_START_DATE,
            "default_backtest_end_date": DEFAULT_BACKTEST_END_DATE,
        },
    )
