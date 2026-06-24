from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sentinel.config import AppSettings
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
            *self._sector_mapping_proposals(),
            *self._invalid_company_theme_proposals(),
            *self._orphan_hot_theme_proposals(),
        ]
        decisions = self._read_decisions()
        pending = []
        for proposal in proposals:
            status = decisions.get(proposal.id)
            if status in {"approved", "rejected"}:
                continue
            pending.append(proposal)
        return sorted(pending, key=lambda item: (item.config_file, item.action, item.path))

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

    def _read_decisions(self) -> dict[str, str]:
        if not self.store_path.exists():
            return {}
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        decisions = payload.get("decisions", {})
        if not isinstance(decisions, dict):
            return {}
        return {str(key): str(value) for key, value in decisions.items()}

    def _record_decision(self, proposal_id: str, status: str) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        decisions = self._read_decisions()
        decisions[proposal_id] = status
        self.store_path.write_text(
            json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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
