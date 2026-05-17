from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<script>window.location.href='/dashboard/research';</script>")


@router.get("/dashboard/research", response_class=HTMLResponse)
async def research_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "research.html", {"request": request, "active_nav": "research"}
    )


@router.get("/dashboard/ops", response_class=HTMLResponse)
async def ops_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "ops.html", {"request": request, "active_nav": "ops"}
    )
