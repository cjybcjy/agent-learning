from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class MoatEvidenceIssue:
    symbol: str
    dimension: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class MoatEvidenceReport:
    total_items: int
    required_fields: int
    missing_count: int
    invalid_count: int
    coverage: float
    issues: list[MoatEvidenceIssue]


class MoatEvidenceAuditor:
    required_fields = ("source", "as_of", "confidence", "bear_case")

    def audit_config(self, config: dict[str, Any]) -> MoatEvidenceReport:
        companies = config.get("companies", {})
        if not isinstance(companies, dict):
            return self._build_report(total_items=0, issues=[])

        issues: list[MoatEvidenceIssue] = []
        total_items = 0
        for symbol, company_cfg in companies.items():
            if not isinstance(company_cfg, dict):
                continue
            report = self.audit_base_scores(str(symbol), company_cfg.get("base_score", {}))
            total_items += report.total_items
            issues.extend(report.issues)

        return self._build_report(total_items=total_items, issues=issues)

    def audit_base_scores(
        self,
        symbol: str,
        base_scores: Any,
    ) -> MoatEvidenceReport:
        if not isinstance(base_scores, dict):
            return self._build_report(total_items=0, issues=[])

        issues: list[MoatEvidenceIssue] = []
        total_items = 0
        for dimension, item in base_scores.items():
            if not isinstance(item, dict):
                continue
            total_items += 1
            dimension_key = str(dimension)
            for field in self.required_fields:
                if field not in item:
                    issues.append(
                        MoatEvidenceIssue(
                            symbol=symbol,
                            dimension=dimension_key,
                            field=field,
                            message=f"{dimension_key} 缺少 {field} 证据字段",
                        )
                    )
                elif not self._is_valid_field(field, item[field]):
                    issues.append(
                        MoatEvidenceIssue(
                            symbol=symbol,
                            dimension=dimension_key,
                            field=field,
                            message=f"{dimension_key} 的 {field} 证据字段无效",
                        )
                    )

        return self._build_report(total_items=total_items, issues=issues)

    def _build_report(
        self,
        total_items: int,
        issues: list[MoatEvidenceIssue],
    ) -> MoatEvidenceReport:
        missing_count = sum(1 for issue in issues if "缺少" in issue.message)
        invalid_count = len(issues) - missing_count
        required_fields = total_items * len(self.required_fields)
        if required_fields == 0:
            coverage = 1.0
        else:
            valid_count = required_fields - missing_count - invalid_count
            coverage = round(max(valid_count, 0) / required_fields, 4)

        return MoatEvidenceReport(
            total_items=total_items,
            required_fields=required_fields,
            missing_count=missing_count,
            invalid_count=invalid_count,
            coverage=coverage,
            issues=issues,
        )

    @staticmethod
    def _is_valid_field(field: str, value: Any) -> bool:
        if field == "source":
            if isinstance(value, str):
                return bool(value.strip())
            if isinstance(value, list):
                return any(isinstance(item, str) and item.strip() for item in value)
            return False
        if field == "as_of":
            if isinstance(value, date):
                return True
            if isinstance(value, str):
                try:
                    date.fromisoformat(value)
                except ValueError:
                    return False
                return True
            return False
        if field == "confidence":
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0.0 <= float(value) <= 1.0
            )
        if field == "bear_case":
            return isinstance(value, str) and bool(value.strip())
        return True
