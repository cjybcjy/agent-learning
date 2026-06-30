from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sentinel.config import AppSettings
from sentinel.mgfs.moat_evidence import MoatEvidenceAuditor
from sentinel.web.services import config_service


@dataclass(slots=True)
class ConfigChangeProposal:
    id: str
    action: str
    title: str
    config_file: str
    path: str
    current_value: Any
    proposed_value: Any
    rationale: str
    status: str = "pending"


class ConfigChangeService:
    """Semi-automatic config proposal queue.

    The service only proposes deterministic add/delete operations. Human users
    still approve or reject each item before YAML is changed.
    """

    MAX_AGENT_CONFIRMATION_ITEMS = 24

    def __init__(
        self,
        config_dir: Path | str | None = None,
        store_path: Path | str | None = None,
    ) -> None:
        settings = AppSettings()
        self.config_dir = Path(config_dir) if config_dir is not None else settings.resolved_config_dir
        self.store_path = (
            Path(store_path)
            if store_path is not None
            else settings.database_path.parent / "config_change_decisions.json"
        )

    def scan_proposals(self) -> list[ConfigChangeProposal]:
        proposals = [
            *self._queued_agent_proposals(),
            *self._sector_mapping_proposals(),
            *self._invalid_company_theme_proposals(),
            *self._orphan_hot_theme_proposals(),
        ]
        decisions = self._read_decisions()
        pending = []
        seen_ids: set[str] = set()
        for proposal in proposals:
            if proposal.id in seen_ids:
                continue
            seen_ids.add(proposal.id)
            status = decisions.get(proposal.id)
            if status in {"approved", "rejected"}:
                continue
            pending.append(proposal)
        return sorted(pending, key=lambda item: (item.config_file, item.action, item.path))

    def queue_agent_suggestion(self, suggestion: Any) -> list[ConfigChangeProposal]:
        proposals = self._agent_suggestion_proposals(suggestion)
        if not proposals:
            raise ValueError("该 Agent 建议还不能生成可确认的 add/delete 项")
        self._record_queued_proposals(proposals)
        return proposals

    def approve_proposal(self, proposal_id: str) -> ConfigChangeProposal:
        proposal = self._find_pending_proposal(proposal_id)
        if proposal.action == "add":
            self._apply_add(proposal)
        elif proposal.action == "delete":
            self._apply_delete(proposal)
        else:
            raise ValueError(f"不支持的配置动作: {proposal.action}")
        proposal.status = "approved"
        self._record_decision(proposal.id, "approved")
        return proposal

    def reject_proposal(self, proposal_id: str) -> ConfigChangeProposal:
        proposal = self._find_pending_proposal(proposal_id)
        proposal.status = "rejected"
        self._record_decision(proposal.id, "rejected")
        return proposal

    def _find_pending_proposal(self, proposal_id: str) -> ConfigChangeProposal:
        for proposal in self.scan_proposals():
            if proposal.id == proposal_id:
                return proposal
        raise ValueError(f"未找到待确认配置变更: {proposal_id}")

    def _sector_mapping_proposals(self) -> list[ConfigChangeProposal]:
        moat_data = self._load_yaml("moat_static_base.yaml")
        valuation_data = self._load_yaml("valuation_sector_routing.yaml")
        companies = moat_data.get("companies", {})
        sector_map = valuation_data.get("sector_to_archetype", {})
        if not isinstance(companies, dict) or not isinstance(sector_map, dict):
            return []

        sectors = sorted(
            {
                str(cfg.get("sector"))
                for cfg in companies.values()
                if isinstance(cfg, dict) and cfg.get("sector")
            }
        )
        proposals: list[ConfigChangeProposal] = []
        for sector in sectors:
            if sector in sector_map:
                continue
            archetype = _guess_archetype_for_sector(sector)
            proposals.append(
                self._proposal(
                    action="add",
                    title=f"添加估值路由: {sector}",
                    config_file="valuation_sector_routing.yaml",
                    path=f"sector_to_archetype.{sector}",
                    current_value=None,
                    proposed_value=archetype,
                    rationale=(
                        f"股票池中存在 sector={sector}，但估值路由未显式配置；"
                        "确认后会把该行业加入 sector_to_archetype。"
                    ),
                )
            )
        return proposals

    def _invalid_company_theme_proposals(self) -> list[ConfigChangeProposal]:
        moat_data = self._load_yaml("moat_static_base.yaml")
        ecosystem_data = self._load_yaml("ecosystem_themes.yaml")
        companies = moat_data.get("companies", {})
        themes = {
            str(item.get("key"))
            for item in ecosystem_data.get("macro_themes", [])
            if isinstance(item, dict) and item.get("key")
        }
        if not isinstance(companies, dict) or not themes:
            return []

        proposals: list[ConfigChangeProposal] = []
        for symbol, cfg in sorted(companies.items()):
            if not isinstance(cfg, dict):
                continue
            theme = cfg.get("theme")
            if not theme or theme in themes:
                continue
            proposals.append(
                self._proposal(
                    action="delete",
                    title=f"删除无效主题标的: {symbol}",
                    config_file="moat_static_base.yaml",
                    path=f"companies.{symbol}",
                    current_value=cfg,
                    proposed_value=None,
                    rationale=(
                        f"{symbol} 使用未定义主题 {theme}；确认后会从基础股票池删除该条目。"
                    ),
                )
            )
        return proposals

    def _orphan_hot_theme_proposals(self) -> list[ConfigChangeProposal]:
        ecosystem_data = self._load_yaml("ecosystem_themes.yaml")
        macro_keys = {
            str(item.get("key"))
            for item in ecosystem_data.get("macro_themes", [])
            if isinstance(item, dict) and item.get("key")
        }
        hot_themes = ecosystem_data.get("hot_themes", [])
        if not isinstance(hot_themes, list) or not macro_keys:
            return []

        proposals: list[ConfigChangeProposal] = []
        for theme_key in sorted(str(item) for item in hot_themes):
            if theme_key in macro_keys:
                continue
            proposals.append(
                self._proposal(
                    action="delete",
                    title=f"删除孤儿 hot theme: {theme_key}",
                    config_file="ecosystem_themes.yaml",
                    path=f"hot_themes.{theme_key}",
                    current_value=theme_key,
                    proposed_value=None,
                    rationale=(
                        f"hot_themes 中的 {theme_key} 不存在于 macro_themes；"
                        "确认后会从 hot_themes 移除。"
                    ),
                )
            )
        return proposals

    def _apply_add(self, proposal: ConfigChangeProposal) -> None:
        data = self._load_yaml(proposal.config_file)
        if proposal.path.startswith("review_queue."):
            self._set_queue_item(data, "review_queue", proposal)
            self._save_yaml(proposal.config_file, data)
            return
        if (
            proposal.config_file == "moat_static_base.yaml"
            and proposal.path.startswith("evidence_review_queue.")
        ):
            self._set_queue_item(data, "evidence_review_queue", proposal)
            self._save_yaml(proposal.config_file, data)
            return
        if proposal.config_file == "valuation_sector_routing.yaml" and proposal.path.startswith("sector_to_archetype."):
            sector = proposal.path.split(".", 1)[1]
            data.setdefault("sector_to_archetype", {})[sector] = proposal.proposed_value
            self._save_yaml(proposal.config_file, data)
            return
        raise ValueError(f"无法应用添加变更: {proposal.path}")

    def _apply_delete(self, proposal: ConfigChangeProposal) -> None:
        data = self._load_yaml(proposal.config_file)
        if proposal.config_file == "moat_static_base.yaml" and proposal.path.startswith("companies."):
            symbol = proposal.path.split(".", 1)[1]
            data.get("companies", {}).pop(symbol, None)
            self._save_yaml(proposal.config_file, data)
            return
        if proposal.config_file == "ecosystem_themes.yaml" and proposal.path.startswith("hot_themes."):
            theme_key = proposal.path.split(".", 1)[1]
            hot_themes = data.get("hot_themes", [])
            if isinstance(hot_themes, list):
                data["hot_themes"] = [item for item in hot_themes if str(item) != theme_key]
            self._save_yaml(proposal.config_file, data)
            return
        raise ValueError(f"无法应用删除变更: {proposal.path}")

    def _proposal(
        self,
        *,
        action: str,
        title: str,
        config_file: str,
        path: str,
        current_value: Any,
        proposed_value: Any,
        rationale: str,
    ) -> ConfigChangeProposal:
        proposal_id = _stable_id(action, config_file, path, current_value, proposed_value)
        return ConfigChangeProposal(
            id=proposal_id,
            action=action,
            title=title,
            config_file=config_file,
            path=path,
            current_value=current_value,
            proposed_value=proposed_value,
            rationale=rationale,
        )

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        path = self.config_dir / filename
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _set_queue_item(
        self,
        data: dict[str, Any],
        queue_name: str,
        proposal: ConfigChangeProposal,
    ) -> None:
        queue = data.setdefault(queue_name, {})
        if not isinstance(queue, dict):
            raise ValueError(f"{queue_name} 必须是 mapping")
        queue_key = proposal.path.split(".", 1)[1]
        queue[queue_key] = proposal.proposed_value

    def _save_yaml(self, filename: str, data: dict[str, Any]) -> None:
        content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        if self.config_dir.resolve() == config_service.CONFIG_DIR.resolve():
            ok, message = config_service.save_config(filename, content)
            if not ok:
                raise ValueError(message)
            return

        path = self.config_dir / filename
        if path.exists():
            backup = path.with_name(
                f"{filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(content, encoding="utf-8")

    def _read_payload(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _read_decisions(self) -> dict[str, str]:
        payload = self._read_payload()
        decisions = payload.get("decisions", {})
        if not isinstance(decisions, dict):
            return {}
        return {str(key): str(value) for key, value in decisions.items()}

    def _record_decision(self, proposal_id: str, status: str) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._read_payload()
        decisions = self._read_decisions()
        decisions[proposal_id] = status
        payload["decisions"] = decisions
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _record_queued_proposals(self, proposals: list[ConfigChangeProposal]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._read_payload()
        queued = payload.get("queued_proposals", {})
        if not isinstance(queued, dict):
            queued = {}
        for proposal in proposals:
            queued[proposal.id] = _proposal_to_dict(proposal)
        payload["queued_proposals"] = queued
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _queued_agent_proposals(self) -> list[ConfigChangeProposal]:
        queued = self._read_payload().get("queued_proposals", {})
        if not isinstance(queued, dict):
            return []
        proposals: list[ConfigChangeProposal] = []
        for item in queued.values():
            if not isinstance(item, dict):
                continue
            proposal = _proposal_from_dict(item)
            if proposal is not None:
                proposals.append(proposal)
        return proposals

    def _agent_suggestion_proposals(self, suggestion: Any) -> list[ConfigChangeProposal]:
        filename = _suggestion_value(suggestion, "config_file")
        if filename not in config_service.ALLOWED_FILES:
            return []

        title = _suggestion_value(suggestion, "title")
        if filename == "moat_static_base.yaml" and "证据字段" in title:
            proposals = self._moat_evidence_review_proposals(suggestion)
            if proposals:
                return proposals

        return [self._generic_review_queue_proposal(suggestion)]

    def _generic_review_queue_proposal(self, suggestion: Any) -> ConfigChangeProposal:
        filename = _suggestion_value(suggestion, "config_file")
        target = _suggestion_value(suggestion, "target") or _suggestion_value(suggestion, "title")
        queue_key = _path_key(_suggestion_value(suggestion, "id") or _stable_id(filename, target))
        title_prefix = _agent_review_title_prefix(filename)
        return self._proposal(
            action="add",
            title=f"{title_prefix}: {target}",
            config_file=filename,
            path=f"review_queue.{queue_key}",
            current_value=None,
            proposed_value=_agent_review_payload(suggestion),
            rationale=(
                f"来自每日研究 Agent：{_suggestion_value(suggestion, 'rationale')}"
                "确认后只加入 YAML review_queue，不直接改评分、倍率或白名单结论。"
            ),
        )

    def _moat_evidence_review_proposals(self, suggestion: Any) -> list[ConfigChangeProposal]:
        moat_data = self._load_yaml("moat_static_base.yaml")
        report = MoatEvidenceAuditor().audit_config(moat_data)
        if not report.issues:
            return [self._generic_review_queue_proposal(suggestion)]

        companies = moat_data.get("companies", {})
        if not isinstance(companies, dict):
            companies = {}

        grouped: dict[tuple[str, str], set[str]] = {}
        for issue in report.issues:
            grouped.setdefault((issue.symbol, issue.dimension), set()).add(issue.field)

        proposals: list[ConfigChangeProposal] = []
        suggestion_id = _suggestion_value(suggestion, "id")
        for index, ((symbol, dimension), fields) in enumerate(sorted(grouped.items())):
            if index >= self.MAX_AGENT_CONFIRMATION_ITEMS:
                break
            company_cfg = companies.get(symbol, {})
            if not isinstance(company_cfg, dict):
                company_cfg = {}
            base_scores = company_cfg.get("base_score", {})
            score_item = base_scores.get(dimension, {}) if isinstance(base_scores, dict) else {}
            if not isinstance(score_item, dict):
                score_item = {}
            queue_key = _path_key(f"{suggestion_id}-{symbol}-{dimension}")
            payload = {
                **_agent_review_payload(suggestion),
                "symbol": symbol,
                "company_name": str(company_cfg.get("name") or ""),
                "dimension": dimension,
                "missing_or_invalid_fields": sorted(fields),
                "current_score": score_item.get("score"),
                "current_note": score_item.get("note"),
            }
            proposals.append(
                self._proposal(
                    action="add",
                    title=f"添加护城河证据复核项: {symbol} {dimension}",
                    config_file="moat_static_base.yaml",
                    path=f"evidence_review_queue.{queue_key}",
                    current_value=score_item,
                    proposed_value=payload,
                    rationale=(
                        f"{symbol}.{dimension} 缺少或存在无效证据字段："
                        f"{', '.join(sorted(fields))}。确认后只加入 evidence_review_queue，"
                        "不自动补写 source/as_of/confidence/bear_case。"
                    ),
                )
            )
        return proposals


def _guess_archetype_for_sector(sector: str) -> str:
    heavy_markers = ("银行", "保险", "煤", "有色", "钢", "化工", "地产", "矿", "金属")
    tech_markers = ("新能源", "半导体", "人工智能", "软件", "云计算", "芯片", "电动车")
    if any(marker in sector for marker in heavy_markers):
        return "heavy_asset_cyclical"
    if any(marker in sector for marker in tech_markers):
        return "saas_and_tech"
    return "traditional_growth"


def _stable_id(*parts: Any) -> str:
    normalized = yaml.safe_dump(list(parts), allow_unicode=True, sort_keys=False)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _proposal_to_dict(proposal: ConfigChangeProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "action": proposal.action,
        "title": proposal.title,
        "config_file": proposal.config_file,
        "path": proposal.path,
        "current_value": proposal.current_value,
        "proposed_value": proposal.proposed_value,
        "rationale": proposal.rationale,
        "status": proposal.status,
    }


def _proposal_from_dict(payload: dict[str, Any]) -> ConfigChangeProposal | None:
    required = ("id", "action", "title", "config_file", "path", "rationale")
    if any(key not in payload for key in required):
        return None
    return ConfigChangeProposal(
        id=str(payload["id"]),
        action=str(payload["action"]),
        title=str(payload["title"]),
        config_file=str(payload["config_file"]),
        path=str(payload["path"]),
        current_value=payload.get("current_value"),
        proposed_value=payload.get("proposed_value"),
        rationale=str(payload["rationale"]),
        status=str(payload.get("status", "pending")),
    )


def _suggestion_value(suggestion: Any, field: str) -> str:
    if isinstance(suggestion, dict):
        value = suggestion.get(field, "")
    else:
        value = getattr(suggestion, field, "")
    return str(value or "")


def _agent_review_payload(suggestion: Any) -> dict[str, Any]:
    return {
        "source": "daily_research_agent",
        "suggestion_id": _suggestion_value(suggestion, "id"),
        "title": _suggestion_value(suggestion, "title"),
        "target": _suggestion_value(suggestion, "target"),
        "rationale": _suggestion_value(suggestion, "rationale"),
        "proposed_change": _suggestion_value(suggestion, "proposed_change"),
        "confidence": _suggestion_numeric_value(suggestion, "confidence"),
        "impact": _suggestion_value(suggestion, "impact"),
        "evidence": _evidence_summaries(_suggestion_sequence(suggestion, "evidence")),
        "counter_evidence": _evidence_summaries(_suggestion_sequence(suggestion, "counter_evidence")),
    }


def _suggestion_numeric_value(suggestion: Any, field: str) -> float:
    if isinstance(suggestion, dict):
        value = suggestion.get(field, 0.0)
    else:
        value = getattr(suggestion, field, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _suggestion_sequence(suggestion: Any, field: str) -> list[Any]:
    if isinstance(suggestion, dict):
        value = suggestion.get(field, [])
    else:
        value = getattr(suggestion, field, [])
    return value if isinstance(value, list) else []


def _evidence_summaries(items: list[Any]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for item in items[:3]:
        if isinstance(item, dict):
            source = item.get("source", "")
            title = item.get("title", "")
            detail = item.get("detail", "")
        else:
            source = getattr(item, "source", "")
            title = getattr(item, "title", "")
            detail = getattr(item, "detail", "")
        summaries.append(
            {
                "source": str(source or ""),
                "title": str(title or ""),
                "detail": str(detail or ""),
            }
        )
    return summaries


def _agent_review_title_prefix(filename: str) -> str:
    labels = {
        "policy_whitelist.yaml": "添加政策复核项",
        "moat_static_base.yaml": "添加护城河复核项",
        "ecosystem_themes.yaml": "添加生态主题复核项",
        "valuation_sector_routing.yaml": "添加估值路由复核项",
    }
    return labels.get(filename, "添加配置复核项")


def _path_key(value: str) -> str:
    key = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
    if key:
        return key[:80]
    return _stable_id(value)
