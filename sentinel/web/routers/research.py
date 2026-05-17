from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from sentinel.web.services.eval_service import evaluate_single

router = APIRouter()


@router.post("/eval/single", response_class=HTMLResponse)
async def eval_single(
    request: Request,
    symbol: str = Form(...),
    market: str = Form(...),
    policy: str = Form("neutral"),
):
    decision = evaluate_single(symbol=symbol, market=market, policy_rating=policy)
    from starlette.templating import _TemplateResponse
    template = request.app.state.templates.get_template("partials/decision_card.html")
    content = template.render({"request": request, "decision": decision})
    return HTMLResponse(content=content)
