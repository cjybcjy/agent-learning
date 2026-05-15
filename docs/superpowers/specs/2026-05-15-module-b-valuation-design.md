# Module B — 估值水位监控表 (Valuation Dashboard)

> **状态：** 设计完成，待实现计划  
> **前置依赖：** MGFS Step 0 框架骨架 + Module A 护城河与国策因子库  
> **版本：** 1.0  
> **批准日期：** 2026-05-15

---

## 1. 设计目标

Module B 负责回答 MGFS 的第二个核心问题：**"这只股票现在买得贵不贵？"**

它通过以下机制建立"价格安全边际"防线：

1. **估值范式路由**：根据资产类型自动选择正确的估值指标（PE、PB、PS、EV/Sales 等）
2. **历史百分位计算**：拉取近 5 年估值序列，计算当前位置
3. **范式校准评分**：不同资产类型有不同的击球区阈值
4. **一票否决熔断**：估值极端高估时强制降级评级

**核心纪律：** 即使 Module A 护城河评分 95 分（极好公司），如果 Module B 估值百分位 > 90%，仍然触发 `hard_veto`。好公司 ≠ 好股票。

---

## 2. 核心设计理念

### 2.1 估值范式（Valuation Archetype）

"行业（Sector）描述公司做什么，估值范式（Archetype）描述公司怎么赚钱。"

传统量化模型最大的陷阱是"一刀切"——全市场用同一套 30%/70% 分位线。这会导致：
- **买入周期股顶点**：钢铁股周期顶峰时 PE 极低，系统误判为"便宜"
- **错失伟大企业**：顶奢品牌常年 PE 30 倍以上，系统误判为"昂贵"

**解决方案：** 把全市场资产抽象为 4-5 种估值范式，每种范式有独立的指标体系和击球区阈值。

| 范式 | 核心指标 | 适用资产 | 估值特征 |
|------|---------|---------|---------|
| **traditional_growth** | PE_TTM, PEG | 白酒、医药、消费 | 盈利稳定，PE 有效 |
| **heavy_asset_cyclical** | PB, ROE | 银行、煤炭、有色 | 周期波动，PE 失效，PB 可靠 |
| **saas_and_tech** | PS, EV/Sales | 新能源、AI、SaaS | 高研发投入，尚未盈利 |
| **crypto_and_utility** | MarketCap/TVL | Layer1、DeFi | 链上经济，传统指标不适用 |

### 2.2 强制覆盖机制（override_archetypes）

对于转型期公司（如紫金矿业从矿企向电池材料转型），允许投研总监在 YAML 中强行指定估值范式，并设置 `effective_until` 有效期。到期后系统自动剥夺特殊待遇，强制复盘。

### 2.3 负值指标清洗（防御性编程）

当公司亏损时，PE_TTM 会变成负数。负数 PE **不应**被视为"极其便宜（0%分位）"，而应作为异常值处理：

- **策略**：负值指标在百分位计算前被标记为 `invalid`，不参与排序
- **结果**：触发 `warning`，`confidence` 降级，评分进入 `avoid` 区
- **目的**：防止系统买入亏损扩大的"价值陷阱"

---

## 3. 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  CLI: python main.py evaluate 600519 --market A股 --sector 白酒   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────▼────────────────┐
           │    ValuationFactorPlugin        │
           │  ┌──────────────────────────┐   │
           │  │ 1. Archetype Router      │   │  sector / override → archetype
           │  └──────────────────────────┘   │
           │  ┌──────────────────────────┐   │
           │  │ 2. Historical Fetcher    │   │  Tushare/BaoStock API
           │  └──────────────────────────┘   │
           │  ┌──────────────────────────┐   │
           │  │ 3. Percentile Engine     │   │  含负值清洗逻辑
           │  └──────────────────────────┘   │
           │  ┌──────────────────────────┐   │
           │  │ 4. Zone Mapper           │   │  范式校准 S 曲线
           │  └──────────────────────────┘   │
           └───────────────┬────────────────┘
                           │
           ┌───────────────▼────────────────┐
           │    FactorScore (valuation)      │
           │  score: 78.5 / 100              │
           │  details: {                     │
           │    archetype: "traditional_growth",
           │    primary_metric: "PE_TTM",    │
           │    primary_percentile: 32.4,    │
           │    zone: "accumulate"           │
           │  }                              │
           └─────────────────────────────────┘
```

---

## 4. 配置文件：`config/valuation_sector_routing.yaml`

```yaml
version: "1.0"
last_updated: "2026-05-15"
description: "MGFS Module B — 估值范式路由与击球区定义"

# ─────────────────────────────────────────
# 1. 估值范式定义（Archetypes）
# ─────────────────────────────────────────
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM",         weight: 0.50 }
      secondary: { name: "PEG",            weight: 0.30 }
      warning:   { name: "Dividend_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90

  heavy_asset_cyclical:
    label: "重资产与强周期"
    metrics:
      primary:   { name: "PB",                 weight: 0.50 }
      secondary: { name: "ROE",                weight: 0.30 }
      warning:   { name: "Operating_CF_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 15, score_range: [90, 100] }
      accumulate:  { percentile_max: 30, score_range: [75, 90]  }
      hold:        { percentile_max: 65, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 85   # 周期股提前拉警报

  saas_and_tech:
    label: "SaaS与前沿科技"
    metrics:
      primary:   { name: "PS_TTM",       weight: 0.50 }
      secondary: { name: "EV_Sales",     weight: 0.30 }
      warning:   { name: "Gross_Margin", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 25, score_range: [90, 100] }
      accumulate:  { percentile_max: 45, score_range: [75, 90]  }
      hold:        { percentile_max: 75, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 88

  crypto_and_utility:
    label: "Web3与数字商品"
    metrics:
      primary:   { name: "MarketCap_to_TVL", weight: 0.50 }
      secondary: { name: "FDV_to_Revenue",   weight: 0.30 }
      warning:   { name: "Token_Burn_Rate",  weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90

# ─────────────────────────────────────────
# 2. Sector → Archetype 映射
# ─────────────────────────────────────────
sector_to_archetype:
  "白酒": "traditional_growth"
  "医药生物": "traditional_growth"
  "食品饮料": "traditional_growth"
  "家用电器": "traditional_growth"
  "银行": "heavy_asset_cyclical"
  "保险": "heavy_asset_cyclical"
  "煤炭": "heavy_asset_cyclical"
  "有色金属": "heavy_asset_cyclical"
  "钢铁": "heavy_asset_cyclical"
  "化工": "heavy_asset_cyclical"
  "房地产": "heavy_asset_cyclical"
  "新能源汽车": "saas_and_tech"
  "人工智能": "saas_and_tech"
  "半导体": "saas_and_tech"
  "云计算": "saas_and_tech"
  "软件服务": "saas_and_tech"
  "Layer1": "crypto_and_utility"
  "DeFi": "crypto_and_utility"
  "NFT": "crypto_and_utility"

# ─────────────────────────────────────────
# 3. 投研总监强制覆盖（转型期公司专用）
# ─────────────────────────────────────────
# 优先级：override_archetype > sector_to_archetype > default
override_archetypes:
  "601899":   # 紫金矿业
    archetype: "heavy_asset_cyclical"
    note: "转型期，仍按周期股估值，待铜/锂收入结构改变后重新评估"
    reviewer: "投研总监"
    effective_until: "2026-12-31"

# ─────────────────────────────────────────
# 4. 全局默认
# ─────────────────────────────────────────
default_archetype: "traditional_growth"
```

---

## 5. 数据流

```
TargetInfo(symbol="601899", sector="有色金属")
           │
           ▼
┌─────────────────────┐
│  Archetype Router   │
│  1. 查 override     │ ← 命中 601899 → heavy_asset_cyclical
│  2. 查 sector_map   │
│  3. fallback default│
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Metric Selector    │
│  primary = PB       │
│  secondary = ROE    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Historical Fetcher │ ← Tushare/BaoStock API
│  拉取 5 年 PB 日频序列 │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Percentile Engine  │
│  含负值清洗逻辑      │
│  percentile = 78.3% │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Zone Mapper        │
│  78.3% > 65%        │ ← avoid 区
│  score = 35         │
└──────────┬──────────┘
           │
           ▼
   FactorScore(valuation, 35/100)
           │
           ▼
┌─────────────────────┐
│  Orchestrator       │
│  circuit_breaker:   │
│  78.3% > 85%? No    │
│  alert_level: avoid │
└─────────────────────┘
```

---

## 6. 插件接口

### 6.1 `ValuationFactorPlugin`

```python
class ValuationFactorPlugin(BaseFactorPlugin):
    factor_key = "valuation"
    factor_name = "估值水位"
    default_weight = 0.2

    def __init__(
        self,
        config_path: Path | None = None,
        fetcher: ValuationFetcher | None = None,
    ) -> None:
        self.config_path = config_path
        self.fetcher = fetcher
        self._config: dict | None = None

    def evaluate(self, target: TargetInfo) -> FactorScore:
        archetype = self._resolve_archetype(target)
        primary = archetype["metrics"]["primary"]
        history = self._fetch_history(target, primary["name"])
        percentile = self._compute_percentile(history, primary["name"])
        score, zone = self._map_to_score(percentile, archetype)

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=score,
            max_score=100.0,
            weight=self.default_weight,
            details={
                "archetype": archetype["label"],
                "primary_metric": primary["name"],
                "primary_percentile": round(percentile, 2),
                "zone": zone,
                "history_span_years": 5,
                "data_points": len(history),
            },
            confidence=0.85 if len(history) >= 500 else 0.6,
            warnings=self._build_warnings(percentile, archetype, history),
        )
```

### 6.2 `ValuationFetcher` 接口

```python
class ValuationFetcher(ABC):
    """Abstract base for historical valuation data fetchers."""

    @abstractmethod
    def fetch_history(
        self,
        symbol: str,
        market: Market,
        metric: str,
        years: int = 5,
    ) -> list[float]:
        """Fetch historical daily values for a valuation metric.

        Args:
            symbol: Stock/crypto symbol
            market: Market enum (A_SHARE, HK, US, CRYPTO)
            metric: Metric name (PE_TTM, PB, PS_TTM, etc.)
            years: Number of years of history to fetch

        Returns:
            List of daily metric values (most recent last).
            Negative or NaN values should be returned as-is;
            the Percentile Engine will handle cleaning.
        """
        raise NotImplementedError
```

**实现类：**
- `TushareValuationFetcher` — A 股财务数据
- `BaoStockValuationFetcher` — A 股备选源
- `MockValuationFetcher` — 回归测试用，返回随机正态分布序列

---

## 7. 百分位计算引擎

### 7.1 核心算法

```python
def _compute_percentile(
    self,
    history: list[float],
    metric_name: str,
) -> float:
    """Compute percentile of the current value in historical distribution.

    Args:
        history: List of daily values, most recent last.
                 May contain negative values (e.g., negative PE during losses).
        metric_name: Name of the metric, used for negative-value policy.

    Returns:
        Percentile (0.0 - 100.0). Returns 50.0 (neutral) if insufficient data.
    """
    if not history or len(history) < 60:
        return 50.0

    current = history[-1]

    # ── 负值清洗逻辑 ──
    if current < 0:
        # 亏损时的 PE 为负，不代表便宜，标记为异常
        return -1.0  # 哨兵值，下游识别为 invalid

    # 历史序列中也需清洗负值（它们不应参与分位计算）
    valid_history = [v for v in history[:-1] if v > 0 and not math.isnan(v)]
    if len(valid_history) < 30:
        return 50.0

    sorted_vals = sorted(valid_history)
    below = sum(1 for v in sorted_vals if v < current)
    return (below / len(sorted_vals)) * 100
```

### 7.2 负值处理策略

| 场景 | 行为 | 输出 |
|------|------|------|
| 当前 PE_TTM < 0 | percentile = -1.0 (哨兵值) | score=0, confidence=0.3, warning="标的处于亏损状态，PE 指标失效" |
| 历史序列中部分负值 | 剔除负值后再排序 | 正常计算，confidence 根据有效数据量调整 |
| 全部为负值（如早期 SaaS） | 无法计算 PE 百分位 | fallback 到 secondary 指标（PS） |

---

## 8. 范式校准评分映射

### 8.1 S 曲线映射

```python
def _map_to_score(
    self,
    percentile: float,
    archetype: dict,
) -> tuple[float, str]:
    """Map percentile to 0-100 score using archetype-calibrated zones.

    Returns:
        (score, zone_name)
    """
    # 负值哨兵处理
    if percentile < 0:
        return 0.0, "invalid"

    zones = archetype["zones"]
    prev_max = 0.0

    for zone_name, zone_cfg in zones.items():
        zone_max = zone_cfg["percentile_max"]
        if percentile <= zone_max:
            score_min, score_max = zone_cfg["score_range"]
            # 在 zone 内部线性插值
            if zone_max == prev_max:
                return float(score_max), zone_name
            pct_in_zone = (percentile - prev_max) / (zone_max - prev_max)
            score = score_max - pct_in_zone * (score_max - score_min)
            return round(score, 2), zone_name
        prev_max = zone_max

    return 0.0, "avoid"
```

### 8.2 各范式击球区对照表

| 范式 | strong_buy | accumulate | hold | avoid | hard_veto |
|------|-----------|-----------|------|-------|-----------|
| traditional_growth | < 20% | < 40% | < 70% | > 70% | > 90% |
| heavy_asset_cyclical | < 15% | < 30% | < 65% | > 65% | > 85% |
| saas_and_tech | < 25% | < 45% | < 75% | > 75% | > 88% |
| crypto_and_utility | < 20% | < 40% | < 70% | > 70% | > 90% |

---

## 9. 与 Orchestrator 集成

### 9.1 新增熔断规则

```yaml
# mgfs_config.yaml 中新增 Module B 熔断规则
circuit_breakers:
  # 1. 估值极端高估 → hard_veto
  valuation_extremely_overvalued:
    enabled: true
    rule: "valuation_primary_percentile > 90"
    alert_level: "hard_veto"
    message: "估值处于历史极端高位（>90%分位），一票否决"

  # 2. 估值偏高 + 护城河不足 → soft_veto
  # 核心纪律：护城河不够深，不配享有高估值
  valuation_overvalued_weak_moat:
    enabled: true
    rule: "valuation_primary_percentile > 70 and moat_score < 60"
    alert_level: "soft_veto"
    message: "估值偏高且护城河不足，建议回避"

  # 3. 周期股高 PB → hard_veto
  cyclical_high_pb:
    enabled: true
    rule: "valuation_archetype == 'heavy_asset_cyclical' and valuation_primary_percentile > 85"
    alert_level: "hard_veto"
    message: "周期股估值处于历史极端高位，禁止追顶"

  # 4. 亏损标的 PE 失效
  valuation_negative_pe:
    enabled: true
    rule: "valuation_zone == 'invalid'"
    alert_level: "yellow_warning"
    message: "标的处于亏损状态，PE 指标失效，建议切换至 PS/PB 评估"
```

### 9.2 动态安全边际解释

`valuation_overvalued_weak_moat` 规则的设计意图：

- **护城河 90 分 + 估值 75%分位** → 不触发熔断（允许作为底仓 Hold）
- **护城河 50 分 + 估值 75%分位** → 触发 `soft_veto`（不配享有高估值）

这是"二维联动风控"——估值不是绝对的，而是相对于护城河的。这就是系统的 Alpha 来源。

---

## 10. 输出契约

### 10.1 FactorScore.details 结构

```json
{
  "factor_key": "valuation",
  "factor_name": "估值水位",
  "score": 35.0,
  "max_score": 100.0,
  "weight": 0.2,
  "details": {
    "archetype": "heavy_asset_cyclical",
    "archetype_label": "重资产与强周期",
    "primary_metric": "PB",
    "primary_percentile": 78.3,
    "secondary_metric": "ROE",
    "secondary_percentile": 62.1,
    "zone": "avoid",
    "history_span_years": 5,
    "data_points": 1214,
    "current_value": 2.10,
    "history_min": 0.85,
    "history_max": 3.50,
    "history_median": 1.60
  },
  "confidence": 0.85,
  "warnings": [
    "当前 PB 处于历史 78% 分位，接近周期股危险区域"
  ]
}
```

### 10.2 CLI 输出格式

```text
--------------------------------------------------
估值水位: 35.0/100.0  [Avoid区]
  估值范式: 重资产与强周期
  主指标: PB (市净率) = 2.10
  历史 5 年百分位: 78.3%
  击球区: < 15% 分位
  数据质量: 1214 个交易日 (置信度: 0.85)
  ⚠️  当前 PB 处于历史 78% 分位，接近周期股危险区域
--------------------------------------------------
```

---

## 11. 错误处理

| 场景 | 行为 | 输出 |
|------|------|------|
| 标的不在 override/sector_map 中 | 使用 `default_archetype` | warning="未命中行业映射，使用默认范式 traditional_growth" |
| API 拉取历史数据失败 | score=0, confidence=0 | warning="历史估值数据获取失败" |
| 历史数据 < 60 个交易日 | 正常计算但 confidence=0.5 | warning="历史数据不足，百分位可靠性低" |
| 当前指标值为负（如亏损 PE） | percentile=-1 (哨兵), score=0 | warning="标的处于亏损状态，PE 指标失效" |
| 历史序列全部为负值 | fallback 到 secondary 指标 | warning="主指标全部无效，切换至辅助指标" |
| override_archetype 已过期 | 降级为 sector_to_archetype 匹配 | warning="override_archetype 已过期，请投研总监重新评估" |

---

## 12. 文件结构

```
sentinel/mgfs/
├── plugins/
│   ├── __init__.py
│   ├── moat.py                   # Module A (已完成)
│   ├── policy.py                 # Module A (已完成)
│   ├── timing.py                 # Module C mock (冻结)
│   └── valuation.py              # Module B ← 本 spec 核心实现
├── data/
│   ├── __init__.py
│   ├── metrics_aggregator.py     # Module A 数据层
│   └── valuation_fetcher.py      # Module B API 封装 ← 新增
├── factor_plugin.py              # 基类 (已完成)
├── orchestrator.py               # 编排器 (已完成)
├── config_loader.py              # 配置加载 (已完成)
└── registry.py                   # 插件注册表 (已完成)

config/
├── mgfs_config.yaml              # 主配置
├── moat_static_base.yaml         # Module A 静态护城河
├── policy_whitelist.yaml         # Module A 政策白名单
└── valuation_sector_routing.yaml # Module B 范式路由 ← 新增

tests/
├── test_mgfs_valuation_plugin.py       # 插件单元测试 ← 新增
├── test_mgfs_valuation_fetcher.py      # API 封装测试 ← 新增
├── test_mgfs_integration_module_b.py   # 全链路集成测试 ← 新增
└── ... (现有测试)
```

---

## 13. 开发阶段划分

| 阶段 | 任务 | 产出 | 优先级 |
|------|------|------|--------|
| Step B1 | `config/valuation_sector_routing.yaml` 定稿 + 样本数据 | 配置文件 | 高 |
| Step B2 | `ValuationFetcher` 接口 + `MockValuationFetcher` | 数据获取层 | **最高** |
| Step B3 | `TushareValuationFetcher` / `BaoStockValuationFetcher` | 真实 API 接入 | **最高** |
| Step B4 | `ValuationFactorPlugin` 核心逻辑 | 插件实现 | 高 |
| Step B5 | 负值清洗 + 异常处理 | 防御性编程 | 高 |
| Step B6 | Orchestrator 熔断规则集成 | 联动测试 | 高 |
| Step B7 | 全链路集成测试 | 端到端验证 | 中 |

---

## 14. 关联文档

- [MGFS Framework Design](2026-05-12-mgfs-design.md) — 框架总体设计
- [Module A — Moat & Policy](2026-05-14-module-a-moat-policy-design.md) — 护城河与国策因子库
- [Module C — Timing](module_c_timing.md) — 量化择时预研（冻结）

---

*文档版本: 1.0 | 生成日期: 2026-05-15 | 批准状态: Approved*
