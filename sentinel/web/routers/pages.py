from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return HTMLResponse("<script>window.location.href='/dashboard/research';</script>")


@router.get("/dashboard/research", response_class=HTMLResponse)
async def research_page(request: Request):
    return HTMLResponse("research page placeholder")


@router.get("/dashboard/ops", response_class=HTMLResponse)
async def ops_page(request: Request):
    return HTMLResponse("ops page placeholder")
