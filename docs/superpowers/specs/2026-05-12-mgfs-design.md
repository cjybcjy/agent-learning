# MGFS (护城河与增量因子评分系统) —— 设计文档

> 日期：2026-05-12
> 状态：设计完成，待实现计划

## 1. 概述

MGFS (Moat & Growth Factor Scoring) 是 Sentinel 系统的上层价值投资评估模块。它通过插件化的因子评分架构，将护城河分析、Token/流量消耗量评估、财务估值三大维度聚合为统一的投资决策说明书。

**与 Sentinel 的关系**：MGFS 作为独立领域模块嵌入现有 CLI，复用 Sentinel 的 DuckDB 连接、配置加载和飞书发布通道，但拥有独立的领域模型和评分引擎。

**构建策略**：
- Step 0：铸骨架 —— 定义接口契约、配置模板、编排器、CLI 入口，用 Mock 数据跑通全流程
- Step 1：砌碉堡 —— 实现模块 A（护城河与国策因子库）
- Step 2（远期）：模块 B（估值水位）与模块 C（量化择时）按序解锁

## 2. 核心设计理念

### 2.1 价值投资纪律优先

模块 A（护城河与国策）必须在模块 C（择时）之前落地。没有护城河过滤的择时工具，会让团队退化为短线交易者。

### 2.2 配置即代码 (Config-as-Code)

政策白名单、赛道定义等低频定性数据采用 Git 版本控制的 YAML 文件维护，而非 DuckDB 表。投研人员直接编辑 YAML 并提交 PR，天然获得时间旅行与审计能力。

### 2.3 安全执行

熔断规则的表达式解析使用 `simpleeval` 库，禁止原生 `eval()`，杜绝代码注入风险。

## 3. 技术栈

- 语言：Python 3.11+
- 规则引擎：`simpleeval==1.0.0`（轻量级安全表达式求值）
- 配置格式：YAML（与现有 Sentinel 配置体系一致）
- 存储：DuckDB（复用现有连接，仅存储评分结果时序数据）
- 输出：Typer CLI + 飞书 Doc（复用现有发布通道）

## 4. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  CLI 入口                                                    │
│  python main.py evaluate <symbol> --market A股 --asset-class equity │
└──────────────────────┬──────────────────────────────────────┘
                       │
           ┌───────────▼────────────┐
           │   MGFSOrchestrator      │  评分编排器：加载插件 → 执行评估 → 聚合分数
           └───────────┬────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ MoatPlugin  │ │ TokenPlugin │ │ Financials  │  模块 A 范畴
│ (护城河)     │ │ (Token消耗) │ │ (财务估值)  │  Step 0 启用
└─────────────┘ └─────────────┘ └─────────────┘
       ▲               ▲               ▲
       │               │               │
       └───────────────┴───────────────┘
              TargetInfo (统一输入契约)
                       │
           ┌───────────▼────────────┐
           │  熔断规则引擎            │  simpleeval 解析 YAML 规则
           │  (Circuit Breakers)     │
           └───────────┬────────────┘
                       │
           ┌───────────▼────────────┐
           │  InvestmentDecision     │  《投资权衡与决策说明书》
           │  (输出模型)              │
           └───────────┬────────────┘
                       │
           ┌───────────▼────────────┐
           │  飞书 Doc Publisher     │  复用 sentinel.publishers.lark_doc
           └────────────────────────┘
```

数据流：CLI 输入 → 构建 TargetInfo → 各因子插件并行评估 → 加权聚合 → 政策乘数修正 → 熔断规则检查 → 评级判定 → 输出决策说明书 → 可选推送飞书。

## 5. 接口契约 (Section 1)

### 5.1 输入契约：TargetInfo

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sentinel.domain.models import Market


@dataclass(frozen=True, slots=True)
class TargetInfo:
    symbol: str
    market: Market
    asset_class: str
    name: str | None = None
    sector: str | None = None
    tags: list[str] = field(default_factory=list)
```

`asset_class` 字段用于下游插件路由：
- `'equity'` → Wind / 东方财富 API
- `'crypto'` → CoinGecko / Dune Analytics API
- `'bond'` / `'commodity'` → 预留扩展

### 5.2 告警级别枚举：AlertLevel

```python
from enum import StrEnum


class AlertLevel(StrEnum):
    HARD_VETO = "hard_veto"
    SOFT_VETO = "soft_veto"
    YELLOW_WARNING = "yellow_warning"
    GREEN_PASS = "green_pass"
```

与飞书告警颜色映射：
- `hard_veto` → 红色警报
- `soft_veto` → 橙色提示
- `yellow_warning` → 黄色提示
- `green_pass` → 绿色通过

### 5.3 输出契约：FactorScore

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class FactorScore:
    factor_key: str
    factor_name: str
    score: float
    max_score: float = 100.0
    weight: float = 0.0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    is_veto: bool = False
    veto_reason: str | None = None

    @property
    def normalized_score(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return self.score / self.max_score
```

`timestamp` 记录打分精确生成时间，用于排查数据源延迟导致的评分异常。

### 5.4 插件抽象基类：BaseFactorPlugin

```python
from abc import ABC, abstractmethod


class BaseFactorPlugin(ABC):
    factor_key: str
    factor_name: str
    default_weight: float = 0.0

    @abstractmethod
    def evaluate(self, target: TargetInfo) -> FactorScore:
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        return {"ready": True, "missing_dependencies": []}
```

Step 0 阶段允许返回 Mock 数据，但接口必须保持稳定。

## 6. 评分编排器 (Section 3)

### 6.1 决策输出模型

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class InvestmentDecision:
    target: TargetInfo
    generated_at: datetime
    factor_scores: dict[str, FactorScore]
    raw_total: float
    policy_multiplier: float
    final_score: float
    rating: str
    action: str
    circuit_breakers_triggered: list[dict[str, Any]]
    alert_level: AlertLevel
    report_sections: dict[str, Any] = field(default_factory=dict)
```

### 6.2 编排器核心逻辑

```python
from simpleeval import simple_eval


class MGFSOrchestrator:
    def __init__(
        self,
        plugins: list[BaseFactorPlugin],
        scoring_weights: dict[str, float],
        policy_multipliers: dict[str, float],
        circuit_breakers: list[dict[str, Any]],
        rating_thresholds: list[dict[str, Any]],
    ) -> None:
        self.plugins = {p.factor_key: p for p in plugins}
        self.scoring_weights = scoring_weights
        self.policy_multipliers = policy_multipliers
        self.circuit_breakers = circuit_breakers
        self.rating_thresholds = sorted(
            rating_thresholds, key=lambda x: x["min_score"], reverse=True
        )

    def evaluate(
        self, target: TargetInfo, policy_rating: str = "neutral"
    ) -> InvestmentDecision:
        factor_scores = self._run_plugins(target)
        raw_total = self._compute_raw_total(factor_scores)
        multiplier = self.policy_multipliers.get(policy_rating, 1.0)
        final_score = raw_total * multiplier
        triggered, alert_level = self._check_circuit_breakers(
            factor_scores, policy_rating
        )
        rating, action = self._classify_rating(final_score, alert_level)

        return InvestmentDecision(
            target=target,
            generated_at=datetime.now(tz=timezone.utc),
            factor_scores=factor_scores,
            raw_total=round(raw_total, 2),
            policy_multiplier=multiplier,
            final_score=round(final_score, 2),
            rating=rating,
            action=action,
            circuit_breakers_triggered=triggered,
            alert_level=alert_level,
        )

    def _run_plugins(self, target: TargetInfo) -> dict[str, FactorScore]:
        scores: dict[str, FactorScore] = {}
        for key, plugin in self.plugins.items():
            try:
                scores[key] = plugin.evaluate(target)
            except Exception:
                scores[key] = FactorScore(
                    factor_key=key,
                    factor_name=plugin.factor_name,
                    score=0.0,
                    confidence=0.0,
                    warnings=[f"{plugin.factor_name} 评估失败，使用兜底分数"],
                )
        return scores

    def _compute_raw_total(
        self, factor_scores: dict[str, FactorScore]
    ) -> float:
        total = 0.0
        weight_sum = 0.0
        for key, score in factor_scores.items():
            w = self.scoring_weights.get(key, 0.0)
            total += score.normalized_score * 100 * w
            weight_sum += w
        return total / weight_sum if weight_sum > 0 else 0.0

    def _check_circuit_breakers(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> tuple[list[dict[str, Any]], AlertLevel]:
        triggered: list[dict[str, Any]] = []
        alert_level = AlertLevel.GREEN_PASS
        context = self._build_eval_context(factor_scores, policy_rating)

        for cb in self.circuit_breakers:
            if not cb.get("enabled", False):
                continue
            try:
                if simple_eval(cb["rule"], names=context):
                    triggered.append(cb)
                    cb_level = AlertLevel(
                        cb.get("alert_level", "yellow_warning")
                    )
                    if cb_level in (AlertLevel.HARD_VETO, AlertLevel.SOFT_VETO):
                        alert_level = cb_level
                    elif alert_level == AlertLevel.GREEN_PASS:
                        alert_level = cb_level
            except Exception:
                pass
        return triggered, alert_level

    def _classify_rating(
        self, final_score: float, alert_level: AlertLevel
    ) -> tuple[str, str]:
        if alert_level == AlertLevel.HARD_VETO:
            return "Avoid", "一票否决：禁止买入"

        for threshold in self.rating_thresholds:
            if final_score >= threshold["min_score"]:
                return threshold["label"], threshold["action"]

        return "Avoid", "回避"

    def _build_eval_context(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {"policy_rating": policy_rating}
        for key, score in factor_scores.items():
            ctx[f"{key}_score"] = score.score
            ctx[f"{key}_normalized"] = score.normalized_score
            for detail_key, detail_val in score.details.items():
                if isinstance(detail_val, (int, float, bool, str)):
                    ctx[f"{key}_{detail_key}"] = detail_val
        return ctx
```

**执行顺序**（不可跳过）：
1. 执行所有已启用插件
2. 计算加权原始分
3. 应用政策乘数
4. 检查熔断规则（simpleeval）
5. 确定评级（若触发 hard_veto 则强制降级为 Avoid）

**容错设计**：单个因子插件失败不阻断整体流程，记录日志后使用兜底分数。

## 7. 配置体系

### 7.1 MGFS 主配置：`mgfs_config.yaml`

```yaml
version: "1.0"
description: "护城河与增量因子评分系统 (Moat & Growth Factor Scoring)"

modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.moat.MoatFactorPlugin"
    config:
      dimensions:
        intangible_assets: { weight: 25, enabled: true }
        switching_costs:   { weight: 25, enabled: true }
        network_effects:   { weight: 30, enabled: true }
        cost_advantage:    { weight: 20, enabled: true }
      token_decline_threshold_quarters: 2

  token_metrics:
    enabled: true
    class_path: "sentinel.mgfs.plugins.token.TokenFactorPlugin"
    config:
      dimensions:
        velocity:       { weight: 40, enabled: true }
        intensity:      { weight: 30, enabled: true }
        sustainability: { weight: 30, enabled: true }

  financials:
    enabled: true
    class_path: "sentinel.mgfs.plugins.financials.FinancialsFactorPlugin"
    config:
      dimensions:
        pb_ratio:      { weight: 25, enabled: true }
        pe_ratio:      { weight: 25, enabled: true }
        ps_ratio:      { weight: 25, enabled: true }
        dcf_valuation: { weight: 25, enabled: true }

  valuation:
    enabled: false
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}

  timing:
    enabled: false
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}

scoring_formula:
  moat:          { weight: 0.50, min_confidence: 0.6 }
  token_metrics: { weight: 0.30, min_confidence: 0.6 }
  financials:    { weight: 0.20, min_confidence: 0.6 }

policy_multiplier:
  core_support:   { label: "核心支持",   multiplier: 1.2 }
  encouraged:     { label: "鼓励发展",   multiplier: 1.0 }
  neutral:        { label: "维持现状",   multiplier: 1.0 }
  strict_control: { label: "严控/收缩",  multiplier: 0.8 }
  veto:           { label: "一票否决",   multiplier: 0.5, triggers_veto: true }

circuit_breakers:
  policy_veto:
    enabled: true
    rule: "policy_rating == 'veto'"
    action: "hard_veto"
    alert_level: "hard_veto"
    message: "该标的所属赛道处于强监管整改期或产能过剩名单，触发一票否决"

  token_decline_warning:
    enabled: true
    rule: "token_consecutive_decline_quarters >= 2"
    action: "yellow_warning"
    alert_level: "yellow_warning"
    message: "核心业务数据连续两个季度下滑，暂缓买入评级"

  min_moat_threshold:
    enabled: true
    rule: "moat_score < 30"
    action: "soft_veto"
    alert_level: "soft_veto"
    message: "护城河评分过低，缺乏核心壁垒"

rating_thresholds:
  strong_buy: { min_score: 90.0, label: "Strong Buy", action: "重仓出击" }
  accumulate: { min_score: 75.0, label: "Accumulate", action: "支撑位分批建仓" }
  hold_watch: { min_score: 60.0, label: "Hold/Watch", action: "等待拐点" }
  avoid:      { min_score:  0.0, label: "Avoid",      action: "回避" }

output_template:
  sections:
    - summary
    - moat_analysis
    - token_metrics
    - financials_valuation
    - policy_alignment
    - timing_assessment
    - circuit_breaker_status
    - final_rating
    - action_recommendation
```

### 7.2 政策白名单：`policy_whitelist.yaml`

投研组直接维护的 Git 版本控制文件，极低频变更，支持时间旅行审计。

```yaml
last_updated: "2026-05-12"
reviewer: "Research Team"
review_cycle: "monthly"

sectors:
  ai_and_compute:
    label: "算力与人工智能基础设施"
    policy_level: "core_support"
    effective_from: "2026-01-01"
    logic_summary: "十五五规划明确指出适度超前建设智算中心，国产替代逻辑强硬。"

  semiconductor:
    label: "半导体与先进制程"
    policy_level: "core_support"
    effective_from: "2026-01-01"
    logic_summary: "解决卡脖子技术，大基金三期持续注资。"

  new_energy:
    label: "新能源与储能"
    policy_level: "encouraged"
    effective_from: "2026-01-01"
    logic_summary: "绿色转型大方向，但需区分出海能力与内需饱和标的。"

  digital_economy_web3:
    label: "数字经济与合规数据要素"
    policy_level: "encouraged"
    effective_from: "2026-01-01"
    logic_summary: "香港Web3合规框架落地，重点关注具备真实数据资产流转的标的。"

  traditional_real_estate:
    label: "传统高杠杆房地产"
    policy_level: "strict_control"
    effective_from: "2026-01-01"
    logic_summary: "存量去化周期，非核心资产坚决规避。"

  high_pollution_heavy_industry:
    label: "高污染高耗能重工业"
    policy_level: "veto"
    effective_from: "2026-01-01"
    logic_summary: "属于产能过剩、双碳目标下的清退对象。"
```

**维护纪律**：投研组按月审视，会议上直接修改 YAML 并提交 Git，变更即生效。

## 8. CLI 集成 (Section 4)

新增 `evaluate` 子命令：

```python
@app.command()
def evaluate(
    symbol: str = typer.Argument(..., help="标的代码"),
    market: Market = typer.Option(..., "--market"),
    asset_class: str = typer.Option("equity", "--asset-class"),
    policy: str = typer.Option("neutral", "--policy"),
    sector: str | None = typer.Option(None, "--sector"),
    publish: bool = typer.Option(False, "--publish"),
) -> None:
    from sentinel.mgfs.orchestrator import MGFSOrchestrator
    from sentinel.mgfs.factor_plugin import TargetInfo
    from sentinel.mgfs.config_loader import load_mgfs_config, build_orchestrator

    settings = AppSettings()
    config = load_mgfs_config(settings.resolved_config_dir / "mgfs_config.yaml")
    orchestrator = build_orchestrator(config)

    target = TargetInfo(
        symbol=symbol,
        market=market,
        asset_class=asset_class,
        sector=sector,
    )
    decision = orchestrator.evaluate(target, policy_rating=policy)

    # 终端输出
    _print_decision(decision)

    if publish:
        from sentinel.publishers.lark_doc import LarkDocPublisher
        doc_pub = LarkDocPublisher(settings.resolved_config_dir)
        doc_pub.publish_mgfs_decision(decision)
        typer.echo("已推送至飞书文档")
```

## 9. 数据库存储

MGFS 评分结果存入 DuckDB 新表，与现有 `heat_metrics` 隔离：

```sql
CREATE TABLE mgfs_decisions (
    id INTEGER PRIMARY KEY,
    evaluated_at TIMESTAMP NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    asset_class VARCHAR(20) NOT NULL,
    sector VARCHAR(50),
    moat_score REAL,
    token_score REAL,
    financials_score REAL,
    raw_total REAL,
    policy_multiplier REAL,
    final_score REAL,
    rating VARCHAR(20),
    alert_level VARCHAR(20),
    circuit_breakers_triggered JSON,
    factor_details JSON,
    UNIQUE(evaluated_at, symbol, market)
);
```

支持按标的查询历史评分变化（动态更新：每两周自动重新计算一次）。

## 10. 错误处理

| 场景 | 行为 |
|------|------|
| 单个因子插件崩溃 | 记录日志，使用兜底分数（0分，confidence=0），继续执行其余插件 |
| 全部因子插件崩溃 | 返回 InvestmentDecision，rating = "Error"，action = "系统异常，人工复核" |
| simpleeval 规则解析失败 | 跳过该条熔断规则，记录警告日志，不阻断流程 |
| 配置 YAML 语法错误 | CLI 启动时通过 Pydantic 校验报错，拒绝启动 |
| 飞书发布失败 | 重试 3 次，仍失败则输出本地 JSON 备份 |

## 11. 项目结构

```
sentinel/
├── mgfs/
│   ├── __init__.py
│   ├── factor_plugin.py          # BaseFactorPlugin, TargetInfo, FactorScore, AlertLevel
│   ├── orchestrator.py           # MGFSOrchestrator
│   ├── config_loader.py          # load_mgfs_config, build_orchestrator
│   ├── registry.py               # FactorPluginRegistry (类比 CollectorRegistry)
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── moat.py               # Step 1 实现：护城河评分插件
│   │   ├── token.py              # Step 1 实现：Token 消耗量评分插件
│   │   ├── financials.py         # Step 1 实现：财务估值评分插件
│   │   ├── valuation.py          # Step 2 占位：估值水位（Mock）
│   │   └── timing.py             # Step 2 占位：量化择时（Mock）
│   └── storage/
│       └── mgfs_repository.py    # MGFS 评分结果 DuckDB 读写
├── publishers/
│   ├── lark_doc.py               # 扩展 publish_mgfs_decision 方法
│   └── lark_bitable.py           # 可选：MGFS 评分历史存入 Bitable
└── ...
```

## 12. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 插件架构 | Registry 模式（类比 CollectorRegistry） | 复用现有成功模式，模块边界清晰，Mock/Stub 友好 |
| 熔断规则引擎 | simpleeval（非原生 eval） | 安全执行 YAML 中的字符串表达式，杜绝代码注入 |
| 政策白名单存储 | Git 版本控制的 YAML（非 DuckDB） | 低频变更、可读性、时间旅行审计 |
| 评分公式固化位置 | YAML 配置（非代码硬编码） | 投研组可调整权重而无需发版 |
| 插件默认执行模式 | 同步（非 async） | Step 0 降低复杂度，模块 C 的 I/O 密集场景可后续升级为 async |
| 失败处理策略 | 单插件失败降级，不阻断整体流程 | 系统韧性优先，确保任何情况下都能产出决策说明书 |
