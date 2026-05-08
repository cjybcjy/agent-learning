from pydantic import BaseModel, Field


class HeatmapItem(BaseModel):
    symbol: str
    rank: int
    mention_count: int
    weighted_score: float
    instant_alpha: float | None = None
    anomaly_score: float | None = None
    sentiment_shift: str | None = None
    key_driver: str | None = None


class HeatmapResponse(BaseModel):
    items: list[HeatmapItem]
    next_cursor: str | None = None


class ChatRequest(BaseModel):
    question: str
    context: dict = Field(default_factory=dict)


class ModelSwitchRequest(BaseModel):
    provider: str
    model: str | None = None
