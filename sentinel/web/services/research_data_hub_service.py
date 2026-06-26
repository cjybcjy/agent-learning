from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class DataFetchResult:
    def __init__(
        self,
        success: bool,
        *,
        data: Any = None,
        source: str = "",
        row_count: int = 0,
        watermark: str | None = None,
        error: str | None = None,
        fetched_at: datetime | None = None,
        from_cache: bool = False,
    ) -> None:
        self.success = success
        self.data = data
        self.source = source
        self.row_count = row_count
        self.watermark = watermark
        self.error = error
        self.fetched_at = fetched_at or datetime.now(tz=timezone.utc)
        self.from_cache = from_cache

    @classmethod
    def success(
        cls,
        *,
        data: Any = None,
        source: str = "",
        row_count: int = 0,
        watermark: str | None = None,
        fetched_at: datetime | None = None,
        from_cache: bool = False,
    ) -> DataFetchResult:
        return cls(
            True,
            data=data,
            source=source,
            row_count=row_count,
            watermark=watermark,
            fetched_at=fetched_at,
            from_cache=from_cache,
        )

    @classmethod
    def failure(
        cls,
        *,
        error: str,
        data: Any = None,
        source: str = "",
        row_count: int = 0,
        watermark: str | None = None,
        fetched_at: datetime | None = None,
    ) -> DataFetchResult:
        return cls(
            False,
            data=data,
            source=source,
            row_count=row_count,
            watermark=watermark,
            error=error,
            fetched_at=fetched_at,
        )


@dataclass(frozen=True, slots=True)
class TopicPolicy:
    ttl_seconds: int = 1800
    min_interval_seconds: int = 10


@dataclass(slots=True)
class TopicState:
    topic: str
    policy: TopicPolicy
    status: str = "idle"
    source: str = ""
    row_count: int = 0
    watermark: str | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str = ""
    last_attempt_at: datetime | None = None
    fetch_count: int = 0
    last_value: Any = None
    label: str = ""


FetchCallable = Callable[[], DataFetchResult | Any]


@dataclass(slots=True)
class _RegisteredTopic:
    fetcher: FetchCallable
    state: TopicState


class ResearchDataHub:
    """Small in-process data hub for topic status, TTL, and last-known-good data."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._topics: dict[str, _RegisteredTopic] = {}

    def register(
        self,
        topic: str,
        fetcher: FetchCallable,
        policy: TopicPolicy | None = None,
        *,
        label: str = "",
    ) -> None:
        existing = self._topics.get(topic)
        if existing is not None:
            existing.fetcher = fetcher
            if label:
                existing.state.label = label
            return
        resolved_policy = policy or TopicPolicy()
        self._topics[topic] = _RegisteredTopic(
            fetcher=fetcher,
            state=TopicState(topic=topic, policy=resolved_policy, label=label),
        )

    def get_or_fetch(self, topic: str, *, force: bool = False) -> DataFetchResult:
        registered = self._topics.get(topic)
        if registered is None:
            raise KeyError(f"research data topic is not registered: {topic}")

        now = self._clock()
        state = registered.state
        if not force and self._is_fresh(state, now):
            return DataFetchResult.success(
                data=state.last_value,
                source=state.source,
                row_count=state.row_count,
                watermark=state.watermark,
                fetched_at=state.last_success_at,
                from_cache=True,
            )
        if not force and self._too_soon(state, now):
            return DataFetchResult.failure(
                error="fetch skipped by min_interval",
                data=state.last_value,
                source=state.source,
                row_count=state.row_count,
                watermark=state.watermark,
                fetched_at=now,
            )

        state.status = "running"
        state.last_attempt_at = now
        state.fetch_count += 1
        try:
            raw_result = registered.fetcher()
            result = self._coerce_result(raw_result, now)
        except Exception as exc:  # pragma: no cover - exercised by public behavior
            result = DataFetchResult.failure(error=str(exc), fetched_at=now)

        if result.success:
            state.status = "success"
            state.source = result.source
            state.row_count = result.row_count
            state.watermark = result.watermark
            state.last_success_at = now
            state.last_error = ""
            state.last_value = result.data
            return DataFetchResult.success(
                data=result.data,
                source=result.source,
                row_count=result.row_count,
                watermark=result.watermark,
                fetched_at=now,
            )

        state.status = "error"
        state.last_error = result.error or "fetch failed"
        state.last_error_at = now
        return DataFetchResult.failure(
            error=state.last_error,
            data=state.last_value,
            source=state.source or result.source,
            row_count=state.row_count or result.row_count,
            watermark=state.watermark or result.watermark,
            fetched_at=now,
        )

    def state(self, topic: str) -> TopicState:
        registered = self._topics.get(topic)
        if registered is None:
            raise KeyError(f"research data topic is not registered: {topic}")
        return registered.state

    def stats(self) -> list[TopicState]:
        return [registered.state for registered in self._topics.values()]

    def _is_fresh(self, state: TopicState, now: datetime) -> bool:
        if state.last_success_at is None or state.last_value is None:
            return False
        age = (now - state.last_success_at).total_seconds()
        return age < state.policy.ttl_seconds

    def _too_soon(self, state: TopicState, now: datetime) -> bool:
        if state.last_attempt_at is None:
            return False
        age = (now - state.last_attempt_at).total_seconds()
        return age < state.policy.min_interval_seconds

    @staticmethod
    def _coerce_result(raw_result: DataFetchResult | Any, now: datetime) -> DataFetchResult:
        if isinstance(raw_result, DataFetchResult):
            return raw_result
        row_count = len(raw_result) if hasattr(raw_result, "__len__") else 1
        return DataFetchResult.success(
            data=raw_result,
            row_count=row_count,
            fetched_at=now,
        )
