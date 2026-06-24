from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from sentinel.config import AppSettings


@dataclass(slots=True)
class BoardEvidence:
    source: str
    board_name: str
    board_code: str
    matched_terms: list[str]


@dataclass(slots=True)
class DiscoveredCandidate:
    symbol: str
    name: str
    evidence: list[BoardEvidence] = field(default_factory=list)
    in_static_pool: bool = False
    static_theme: str | None = None
    fund_heavy_holding_count: int | None = None

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


@dataclass(slots=True)
class CandidateDiscoveryResult:
    theme_key: str
    theme_label: str
    search_terms: list[str]
    matched_board_count: int
    source_mix: dict[str, int]
    candidates: list[DiscoveredCandidate]
    warnings: list[str] = field(default_factory=list)


class BoardProvider(Protocol):
    def list_concept_boards(self) -> list[dict[str, Any]]:
        ...

    def list_industry_boards(self) -> list[dict[str, Any]]:
        ...

    def board_constituents(self, source: str, board_name: str) -> list[dict[str, Any]]:
        ...


class AkshareBoardProvider:
    def list_concept_boards(self) -> list[dict[str, Any]]:
        import akshare as ak

        try:
            return _records(ak.stock_board_concept_name_em())
        except Exception:
            return _normalize_ths_boards(_records(ak.stock_board_concept_name_ths()))

    def list_industry_boards(self) -> list[dict[str, Any]]:
        import akshare as ak

        try:
            return _records(ak.stock_board_industry_name_em())
        except Exception:
            return _normalize_ths_boards(_records(ak.stock_board_industry_name_ths()))

    def board_constituents(self, source: str, board_name: str) -> list[dict[str, Any]]:
        import akshare as ak

        if source == "industry":
            return _records(ak.stock_board_industry_cons_em(symbol=board_name))
        return _records(ak.stock_board_concept_cons_em(symbol=board_name))


class CandidateDiscoveryService:
    """Discover A-share candidates from objective board membership evidence."""

    def __init__(
        self,
        config_dir: Path | str | None = None,
        provider: BoardProvider | None = None,
        max_boards_per_source: int = 8,
        max_candidates: int = 40,
    ) -> None:
        settings = AppSettings()
        self.config_dir = Path(config_dir) if config_dir is not None else settings.resolved_config_dir
        self.provider = provider or AkshareBoardProvider()
        self.max_boards_per_source = max_boards_per_source
        self.max_candidates = max_candidates

    def discover_theme(self, theme_key: str) -> CandidateDiscoveryResult:
        ecosystem_data = self._load_yaml("ecosystem_themes.yaml")
        moat_data = self._load_yaml("moat_static_base.yaml")
        theme = self._theme_by_key(ecosystem_data, theme_key)
        if theme is None:
            return CandidateDiscoveryResult(
                theme_key=theme_key,
                theme_label=theme_key,
                search_terms=[],
                matched_board_count=0,
                source_mix={},
                candidates=[],
                warnings=[f"未找到主题配置: {theme_key}"],
            )

        search_terms = _theme_terms(theme)
        static_pool = _static_pool_by_symbol(moat_data)
        matched_boards, warnings = self._matched_boards(search_terms)
        candidates: dict[str, DiscoveredCandidate] = {}
        source_mix = {"concept": 0, "industry": 0}

        for board in matched_boards:
            source = str(board["source"])
            board_name = str(board["board_name"])
            try:
                rows = self.provider.board_constituents(source, board_name)
            except Exception as exc:
                warnings.append(
                    f"{_source_label(source)}板块 {board_name} 成分股读取失败: {_short_error(exc)}"
                )
                continue

            source_mix[source] = source_mix.get(source, 0) + 1
            evidence = BoardEvidence(
                source=source,
                board_name=board_name,
                board_code=str(board.get("board_code") or ""),
                matched_terms=list(board["matched_terms"]),
            )
            for row in rows:
                symbol = _clean_symbol(_first_value(row, "代码", "股票代码", "symbol"))
                if not symbol:
                    continue
                name = str(_first_value(row, "名称", "股票名称", "name") or symbol)
                candidate = candidates.setdefault(
                    symbol,
                    DiscoveredCandidate(symbol=symbol, name=name),
                )
                candidate.evidence.append(evidence)

        for symbol, candidate in candidates.items():
            static_cfg = static_pool.get(symbol)
            if static_cfg is not None:
                candidate.in_static_pool = True
                candidate.static_theme = static_cfg.get("theme")
                candidate.fund_heavy_holding_count = _coerce_int(
                    static_cfg.get("fund_heavy_holding_count")
                )

        ranked_candidates = sorted(
            candidates.values(),
            key=lambda item: (
                -item.evidence_count,
                item.in_static_pool,
                item.symbol,
            ),
        )[: self.max_candidates]

        return CandidateDiscoveryResult(
            theme_key=theme_key,
            theme_label=str(theme.get("label") or theme_key),
            search_terms=search_terms,
            matched_board_count=len(matched_boards),
            source_mix=source_mix,
            candidates=ranked_candidates,
            warnings=warnings,
        )

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        path = self.config_dir / filename
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _theme_by_key(ecosystem_data: dict[str, Any], theme_key: str) -> dict[str, Any] | None:
        for item in ecosystem_data.get("macro_themes", []):
            if isinstance(item, dict) and item.get("key") == theme_key:
                return item
        return None

    def _matched_boards(self, search_terms: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        matched: list[dict[str, Any]] = []
        warnings: list[str] = []
        for source, loader in (
            ("concept", self.provider.list_concept_boards),
            ("industry", self.provider.list_industry_boards),
        ):
            try:
                boards = loader()
            except Exception as exc:
                warnings.append(f"{_source_label(source)}列表读取失败: {_short_error(exc)}")
                continue

            source_matches = []
            for board in boards:
                board_name = str(_first_value(board, "板块名称", "名称", "board_name") or "")
                if not board_name:
                    continue
                matched_terms = [term for term in search_terms if term in board_name]
                if not matched_terms:
                    continue
                source_matches.append(
                    {
                        "source": source,
                        "board_name": board_name,
                        "board_code": str(_first_value(board, "板块代码", "代码", "board_code") or ""),
                        "matched_terms": matched_terms,
                        "rank": _coerce_int(_first_value(board, "排名", "rank")) or 9999,
                    }
                )

            source_matches.sort(
                key=lambda item: (-len(item["matched_terms"]), item["rank"], item["board_name"])
            )
            matched.extend(source_matches[: self.max_boards_per_source])
        return matched, warnings


def _theme_terms(theme: dict[str, Any]) -> list[str]:
    raw_terms: list[str] = []
    for key in ("label", "policy_anchor"):
        value = theme.get(key)
        if isinstance(value, str):
            raw_terms.extend(_split_term_phrase(value))
    for item in theme.get("a_share_chain", []):
        if isinstance(item, str):
            raw_terms.append(item)
            raw_terms.extend(_derived_terms(item))

    seen: set[str] = set()
    terms: list[str] = []
    stop_terms = {"未来产业", "新质生产力", "产业链", "主题", "概念", "智能"}
    for term in raw_terms:
        clean = term.strip()
        if len(clean) < 2 or clean in stop_terms or clean in seen:
            continue
        seen.add(clean)
        terms.append(clean)
    return terms


def _split_term_phrase(value: str) -> list[str]:
    terms = [value]
    for sep in ("与", "/", "／", "、", ",", "，", " "):
        pieces: list[str] = []
        for term in terms:
            pieces.extend(part.strip() for part in term.split(sep))
        terms = pieces
    return [term for term in terms if term]


def _derived_terms(value: str) -> list[str]:
    terms = []
    for suffix in ("系统", "整机", "概念"):
        if value.endswith(suffix) and len(value) > len(suffix) + 1:
            terms.append(value[: -len(suffix)])
    return terms


def _static_pool_by_symbol(moat_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    companies = moat_data.get("companies", {})
    if not isinstance(companies, dict):
        return {}
    return {
        _clean_symbol(str(symbol)): cfg
        for symbol, cfg in companies.items()
        if isinstance(cfg, dict) and _clean_symbol(str(symbol))
    }


def _records(data: Any) -> list[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        return data.to_dict(orient="records")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _normalize_ths_boards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        name = _first_value(row, "板块名称", "name", "名称")
        code = _first_value(row, "板块代码", "code", "代码")
        if not name:
            continue
        normalized.append(
            {
                "板块名称": str(name),
                "板块代码": str(code or ""),
            }
        )
    return normalized


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _clean_symbol(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".")[-1] if text[:2].isalpha() else text.split(".")[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else ""


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_label(source: str) -> str:
    return "行业" if source == "industry" else "概念"


def _short_error(exc: Exception, limit: int = 120) -> str:
    text = str(exc).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
