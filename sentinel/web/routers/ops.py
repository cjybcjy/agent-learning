from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from sentinel.web.services.config_service import (
    load_config,
    save_config,
    validate_config,
)
from sentinel.web.services.pipeline_service import export_csv, get_history, trigger_pipeline

router = APIRouter()


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
async def config_save(request: Request, filename: str, content: str):
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
    return request.app.state.templates.get_template("partials/pipeline_history.html").render(
        {"request": request}
    )


@router.post("/pipeline/trigger")
async def pipeline_trigger():
    result = trigger_pipeline()
    return result


@router.get("/pipeline/export/{batch_id}")
async def pipeline_export(batch_id: str):
    csv_data = export_csv(batch_id)
    return PlainTextResponse(
        csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={batch_id}.csv"},
    )
