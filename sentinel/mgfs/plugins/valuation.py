from __future__ import annotations

from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class ValuationFactorPlugin(BaseFactorPlugin):
    factor_key = "valuation"
    factor_name = "估值水位"
    default_weight = 0.0

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=50.0,
            details={"note": "mock implementation — Step 2"},
        )
