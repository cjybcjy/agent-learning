from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AISignalResult(BaseModel):
    """Structured output from LLM anomaly analysis.

    All confidence scores are clamped to [0.0, 1.0].
    sentiment_shift is constrained to a closed vocabulary
    to prevent free-form hallucination.
    """

    anomaly_score: float = Field(
        ge=0.0, le=1.0,
        description="Overall anomaly strength, 0=normal, 1=extreme"
    )
    sentiment_shift: Literal["positive", "negative", "neutral", "mixed"] = Field(
        description="Direction of sentiment change"
    )
    sentiment_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in sentiment assessment"
    )
    key_driver: str = Field(
        max_length=200,
        description="Single-sentence summary of the primary driver"
    )
    key_driver_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in key driver identification"
    )
    driver_keywords: list[str] = Field(
        default_factory=list,
        description="Key terms extracted from discussion (max 10)"
    )
    reasoning: str = Field(
        max_length=2000,
        description="Brief chain-of-thought based ONLY on provided posts"
    )

    @field_validator("driver_keywords")
    @classmethod
    def _max_keywords(cls, v: list[str]) -> list[str]:
        return v[:10]

    @field_validator("key_driver")
    @classmethod
    def _strip_newlines(cls, v: str) -> str:
        return v.replace("\n", " ").replace("\r", "").strip()
