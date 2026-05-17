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
