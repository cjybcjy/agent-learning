from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sentinel.web.routers import health, ops, pages, research


def create_app() -> FastAPI:
    app = FastAPI(title="MGFS Web Dashboard", version="1.0")

    # Templates
    template_dir = Path(__file__).parent / "templates"
    app.state.templates = Jinja2Templates(directory=str(template_dir))

    # Routers
    app.include_router(pages.router)
    app.include_router(research.router, prefix="/api")
    app.include_router(ops.router, prefix="/api")
    app.include_router(health.router, prefix="/api")

    return app


app = create_app()
