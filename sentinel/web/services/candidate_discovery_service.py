from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import requests
import yaml

from sentinel.config import AppSettings

EASTMONEY_CLIST_HOSTS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://29.push2.eastmoney.com/api/qt/clist/get",
    "https://17.push2.eastmoney.com/api/qt/clist/get",
    "https://44.push2.eastmoney.com/api/qt/clist/get",
)
EASTMONEY_CLIST_UT = "bd1d9ddb04089700cf9c27f6f7426281"
EASTMONEY_SUGGEST_URL = "https://searchapi.eastmoney.com/api/suggest/get"
EASTMONEY_SUGGEST_TOKEN = "44c9d251add88e27b65ed86506f6e5da"
FALLBACK_CONCEPT_BOARDS = {
    "低空经济": ("低空经济", "309115"),
    "无人机": ("无人机", "300889"),
    "eVTOL": ("飞行汽车(eVTOL)", "309113"),
    "飞行汽车": ("飞行汽车(eVTOL)", "309113"),
    "飞行汽车(eVTOL)": ("飞行汽车(eVTOL)", "309113"),
}


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

    def board_constituents(
        self,
        source: str,
        board_name: str,
        board_code: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


class AkshareBoardProvider:
    def list_concept_boards(self) -> list[dict[str, Any]]:
        rows = _try_direct_eastmoney_board_list("concept")
        if rows:
            return rows

        import akshare as ak

        try:
            return _records(ak.stock_board_concept_name_em())
        except Exception:
            return _normalize_ths_boards(_records(ak.stock_board_concept_name_ths()))

    def list_industry_boards(self) -> list[dict[str, Any]]:
        rows = _try_direct_eastmoney_board_list("industry")
        if rows:
            return rows

        import akshare as ak

        try:
            return _records(ak.stock_board_industry_name_em())
        except Exception:
            return _normalize_ths_boards(_records(ak.stock_board_industry_name_ths()))

    def board_constituents(
        self,
        source: str,
        board_name: str,
        board_code: str | None = None,
    ) -> list[dict[str, Any]]:
        if source == "concept" and _is_ths_board_code(board_code):
            rows = _try_ths_concept_constituents(str(board_code))
            if rows:
                return rows

        eastmoney_code = (
            str(board_code)
            if _is_eastmoney_board_code(board_code)
            else _resolve_eastmoney_board_code(board_name)
        )
        if eastmoney_code:
            rows = _try_direct_eastmoney_board_constituents(eastmoney_code)
            if rows:
                return rows

        import akshare as ak

        if source == "industry":
            return _records(
                ak.stock_board_industry_cons_em(symbol=eastmoney_code or board_name)
            )
        return _records(ak.stock_board_concept_cons_em(symbol=eastmoney_code or board_name))


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
                rows = self.provider.board_constituents(
                    source,
                    board_name,
                    board_code=str(board.get("board_code") or "") or None,
                )
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
        fallback_matches = _fallback_concept_boards_for_terms(search_terms)
        if fallback_matches:
            return fallback_matches[: self.max_boards_per_source], []

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


def _fallback_concept_boards_for_terms(search_terms: list[str]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for term in search_terms:
        board = FALLBACK_CONCEPT_BOARDS.get(term)
        if board is None:
            continue
        board_name, board_code = board
        if board_code in seen_codes:
            continue
        seen_codes.add(board_code)
        matched.append(
            {
                "source": "concept",
                "board_name": board_name,
                "board_code": board_code,
                "matched_terms": [term],
                "rank": len(matched) + 1,
            }
        )
    return matched


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


def _try_direct_eastmoney_board_list(source: str) -> list[dict[str, Any]]:
    try:
        return _fetch_eastmoney_board_list(source)
    except Exception:
        return []


def _try_direct_eastmoney_board_constituents(board_code: str) -> list[dict[str, Any]]:
    try:
        return _fetch_eastmoney_board_constituents(board_code)
    except Exception:
        return []


def _try_ths_concept_constituents(ths_code: str) -> list[dict[str, Any]]:
    try:
        return _fetch_ths_concept_constituents(ths_code)
    except Exception:
        return []


def _fetch_eastmoney_board_list(source: str) -> list[dict[str, Any]]:
    if source == "industry":
        params = _eastmoney_clist_params(
            fs="m:90 t:2 f:!50",
            fields="f12,f14",
            fid="f3",
            page_size=500,
        )
    else:
        params = _eastmoney_clist_params(
            fs="m:90 t:3 f:!50",
            fields="f12,f14",
            fid="f12",
            page_size=500,
        )
    rows = _fetch_eastmoney_clist_pages(params)
    normalized: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        name = row.get("f14")
        code = row.get("f12")
        if not name or not code:
            continue
        normalized.append(
            {
                "排名": rank,
                "板块名称": str(name),
                "板块代码": str(code),
            }
        )
    return normalized


def _fetch_eastmoney_board_constituents(board_code: str) -> list[dict[str, Any]]:
    if not _is_eastmoney_board_code(board_code):
        return []
    params = _eastmoney_clist_params(
        fs=f"b:{board_code}",
        fields="f12,f14",
        fid="f3",
        page_size=500,
    )
    rows = _fetch_eastmoney_clist_pages(params)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        symbol = row.get("f12")
        name = row.get("f14")
        if not symbol or not name:
            continue
        normalized.append({"代码": str(symbol), "名称": str(name)})
    return normalized


@lru_cache(maxsize=512)
def _fetch_ths_concept_constituents(ths_code: str) -> list[dict[str, Any]]:
    if not _is_ths_board_code(ths_code):
        return []
    response = requests.get(
        f"https://q.10jqka.com.cn/gn/detail/code/{ths_code}/",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Referer": "https://q.10jqka.com.cn/gn/",
        },
        timeout=10,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "gbk"
    pattern = re.compile(
        r'<td>\s*<a[^>]+stockpage\.10jqka\.com\.cn/(\d{6})/?[^>]*>\s*\1\s*</a>\s*</td>\s*'
        r'<td>\s*<a[^>]+stockpage\.10jqka\.com\.cn/\1/?[^>]*>\s*([^<]+?)\s*</a>\s*</td>',
        re.IGNORECASE | re.DOTALL,
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for symbol, name in pattern.findall(response.text):
        if symbol in seen:
            continue
        seen.add(symbol)
        rows.append({"代码": symbol, "名称": html.unescape(name).strip()})
    return rows


@lru_cache(maxsize=256)
def _resolve_eastmoney_board_code(board_name: str) -> str | None:
    clean_name = board_name.strip()
    if not clean_name:
        return None
    last_exc: Exception | None = None
    for trust_env in (True, False):
        session = requests.Session()
        session.trust_env = trust_env
        try:
            response = session.get(
                EASTMONEY_SUGGEST_URL,
                params={
                    "input": clean_name,
                    "type": "14",
                    "token": EASTMONEY_SUGGEST_TOKEN,
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0 Safari/537.36"
                    )
                },
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            rows = (
                payload.get("QuotationCodeTable", {}).get("Data", [])
                if isinstance(payload, dict)
                else []
            )
            exact: list[dict[str, Any]] = []
            loose: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict) or row.get("Classify") != "BK":
                    continue
                code = str(row.get("Code") or "")
                name = str(row.get("Name") or "")
                if not _is_eastmoney_board_code(code):
                    continue
                if name == clean_name:
                    exact.append(row)
                elif clean_name in name or name in clean_name:
                    loose.append(row)
            chosen = exact[0] if exact else (loose[0] if loose else None)
            if chosen is not None:
                return str(chosen["Code"])
        except Exception as exc:
            last_exc = exc
        finally:
            session.close()
    if last_exc is not None:
        return None
    return None


def _fetch_eastmoney_clist_pages(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = int(params.get("pz") or 500)
    for page in range(1, 8):
        payload = _fetch_eastmoney_clist_json({**params, "pn": page})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            break
        diff = data.get("diff") or []
        if not isinstance(diff, list) or not diff:
            break
        rows.extend(item for item in diff if isinstance(item, dict))
        total = _coerce_int(data.get("total")) or len(rows)
        if len(rows) >= total or len(diff) < page_size:
            break
    return rows


def _fetch_eastmoney_clist_json(params: dict[str, Any]) -> dict[str, Any]:
    last_exc: Exception | None = None
    for url in EASTMONEY_CLIST_HOSTS:
        for trust_env in (True, False):
            session = requests.Session()
            session.trust_env = trust_env
            try:
                response = session.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0 Safari/537.36"
                        ),
                        "Referer": "https://quote.eastmoney.com/",
                    },
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and int(payload.get("rc", 0)) == 0:
                    return payload
                last_exc = RuntimeError(f"Eastmoney rc={payload.get('rc')}")
            except Exception as exc:
                last_exc = exc
            finally:
                session.close()
    raise RuntimeError(f"Eastmoney clist request failed: {last_exc}")


def _eastmoney_clist_params(
    *,
    fs: str,
    fields: str,
    fid: str,
    page_size: int,
) -> dict[str, Any]:
    return {
        "pn": 1,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "ut": EASTMONEY_CLIST_UT,
        "fltt": 2,
        "invt": 2,
        "fid": fid,
        "fs": fs,
        "fields": fields,
    }


def _is_eastmoney_board_code(value: str | None) -> bool:
    text = str(value or "").strip()
    return len(text) >= 3 and text.startswith("BK") and text[2:].isdigit()


def _is_ths_board_code(value: str | None) -> bool:
    text = str(value or "").strip()
    return len(text) == 6 and text.isdigit()


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
