from pydantic import BaseModel, Field


class HeatmapItem(BaseModel):
    symbol: str
    rank: int
    mention_count: int
    weighted_score: float
    source_count: int = 0
    last_updated: str | None = None
    confidence_score: float | None = None
    instant_alpha: float | None = None
    anomaly_score: float | None = None
    sentiment_shift: str | None = None
    key_driver: str | None = None


class HeatmapResponse(BaseModel):
    items: list[HeatmapItem]
    next_cursor: str | None = None


class MarketStats(BaseModel):
    symbol_count: int
    total_mentions: int
    source_count: int
    sources: list[str]
    last_updated: str | None = None


class MarketStatsResponse(BaseModel):
    markets: dict[str, MarketStats]


class ChatRequest(BaseModel):
    question: str
    context: dict = Field(default_factory=dict)


class ModelSwitchRequest(BaseModel):
    provider: str
    model: str | None = None
