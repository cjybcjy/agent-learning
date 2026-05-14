# Module A — 护城河与国策因子库 (Moat & Policy Engine)

> **状态：** 设计文档 | **前置依赖：** MGFS Step 0 框架骨架 | **版本：** 1.0

---

## 1. 设计目标

Module A 负责回答 MGFS 的第一个核心问题：**"这家公司值得买吗？"**

它由两个独立插件组成：
- **MoatFactorPlugin**：评估企业的内在护城河深度（三段式：静态存量 / 动态增量 / 安全余量）
- **PolicyFactorPlugin**：评估宏观政策环境对该标的的友好程度（作为全局乘数，非评分因子）

**核心公式：**
```
raw_total = (moat_normalized × 0.5 + token_normalized × 0.3 + financials_normalized × 0.2)
final_score = raw_total × policy_multiplier
```

---

## 2. 数据架构：混合模式 (Hybrid Data Model)

### 2.1 三层数据分类

| 分段 | 名称 | 数据来源 | 更新频率 | 维护方 |
|------|------|---------|---------|--------|
| **静态存量分** | Base Score | Git + YAML (`moat_static_base.yaml`) | 半年~一年 | 投研组（人工） |
| **动态增量分** | Trend Score | DuckDB (API 自动聚合) | 季度/月度/日 | 机器自动 |
| **安全余量分** | Safety Bias | DuckDB (API 自动聚合) | 日/实时 | 机器自动 |

### 2.2 为什么必须是混合模式？

- **纯手动** → 沦为静态 Excel，无法响应变化
- **纯自动** → 把"财务数字"等同于"护城河"，犯下量化基金的典型错误
- **混合** → 人类负责机器无法理解的商业洞察（品牌、特许经营权），机器负责无情校验（ROIC、毛利率趋势）

---

## 3. MoatFactorPlugin 设计

### 3.1 插件元信息

```python
class MoatFactorPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河深度"
    default_weight = 0.5
```

### 3.2 三段式评分逻辑

```python
def evaluate(self, target: TargetInfo) -> FactorScore:
    # 1. 读取静态存量分 (YAML)
    base_score = self._load_static_base(target)
    
    # 2. 查询动态增量分 (DuckDB)
    trend_score = self._query_trend_metrics(target)
    
    # 3. 查询安全余量分 (DuckDB)
    safety_score = self._query_safety_metrics(target)
    
    # 4. 加权聚合
    final_moat_score = (
        base_score.score * base_score.weight +
        trend_score.score * trend_score.weight +
        safety_score.score * safety_score.weight
    )
    
    return FactorScore(
        factor_key="moat",
        factor_name="护城河深度",
        score=round(final_moat_score, 2),
        max_score=100.0,
        weight=0.5,
        details={
            "base_score": base_score.score,
            "base_weight": base_score.weight,
            "trend_score": trend_score.score,
            "trend_weight": trend_score.weight,
            "safety_score": safety_score.score,
            "safety_weight": safety_score.weight,
        },
        confidence=min(
            base_score.confidence,
            trend_score.confidence,
            safety_score.confidence,
        ),
    )
```

### 3.3 静态存量分 (Base Score)

**数据源：** `moat_static_base.yaml`（Git 版本化）

**文件结构：**
```yaml
version: "1.0"
last_updated: "2026-05-14"
scoring_weights:
  base: { weight: 0.4 }      # 静态占 40%
  trend: { weight: 0.35 }    # 动态占 35%
  safety: { weight: 0.25 }   # 安全占 25%

companies:
  "600519":  # 贵州茅台
    name: "贵州茅台"
    sector: "白酒"
    base_score:
      brand_premium: { score: 95, note: "社交货币属性，议价能力极强" }
      franchise_barrier: { score: 90, note: "地理标志保护 + 产能壁垒" }
      policy_alignment: { score: 85, note: "消费品，非政策敏感行业" }
      cost_advantage: { score: 70, note: "毛利率高但原料成本有波动" }
    
  "000001":  # 平安银行
    name: "平安银行"
    sector: "银行"
    base_score:
      brand_premium: { score: 60, note: "品牌认知度中等" }
      franchise_barrier: { score: 75, note: "金融牌照壁垒" }
      policy_alignment: { score: 70, note: "受金融监管政策影响大" }
      cost_advantage: { score: 65, note: "资金成本优势一般" }
```

**指标定义：**

| 指标 | 含义 | 评分维度 |
|------|------|---------|
| `brand_premium` | 品牌溢价力 | 消费者心智占有率、定价权 |
| `franchise_barrier` | 特许经营权与行政壁垒 | 牌照、专利、资源开采权 |
| `policy_alignment` | 政策契合度 | 所属赛道是否受政策支持 |
| `cost_advantage` | 成本优势 | 规模效应、工艺壁垒、资源禀赋 |

**计算方式：** 四个子指标取算术平均，作为 Base Score（0-100）。

### 3.4 动态增量分 (Trend Score)

**数据源：** DuckDB 表 `trend_metrics`（API 自动抓取聚合）

**适用指标（传统资产）：**

| 指标 | 计算逻辑 | 阈值参考 |
|------|---------|---------|
| `roic_sustainability` | ROIC 连续 3 年 > 15% 得满分，每少一年扣 25 分 | ≥ 15% |
| `gmoat_stability` | 毛利率是否持续高于行业中位数 | 行业中位数 |
| `rd_efficiency` | 研发支出占比增速 vs 营收增速 | 研发投入转化率 |
| `market_share_trend` | 市占率变化率（年度） | 正增长加分 |

**适用指标（Crypto/Web3）：**

| 指标 | 计算逻辑 | 数据源 |
|------|---------|--------|
| `github_activity` | 代码提交热度（近 90 日） | GitHub API |
| `dau_growth` | 日活用户增速 | 项目方 API / Dune |
| `burn_rate` | 链上真实燃烧率 | Dune / Glassnode |
| `active_address_growth` | 活跃地址数增速 | Glassnode |

**计算方式：** 各子指标按预设权重加权平均，输出 Trend Score（0-100）。

### 3.5 安全余量分 (Safety Bias)

**数据源：** DuckDB 表 `safety_metrics`（API 自动抓取聚合）

**适用指标：**

| 指标 | 计算逻辑 | 预警阈值 |
|------|---------|---------|
| `pe_percentile` | PE 历史百分位（近 5 年） | > 90% 危险 |
| `pb_percentile` | PB 历史百分位（近 5 年） | > 90% 危险 |
| `debt_ratio_deterioration` | 资产负债率环比恶化 | 连续 2 季上升 |
| `goodwill_ratio` | 商誉占净资产比重 | > 30% 危险 |
| `operating_cashflow` | 经营现金流 / 净利润 | < 1.0 预警 |

**计算方式：** 偏离度越严重扣分越多，输出 Safety Score（0-100）。

---

## 4. PolicyFactorPlugin 设计

### 4.1 插件元信息

```python
class PolicyFactorPlugin(BaseFactorPlugin):
    factor_key = "policy"
    factor_name = "国策环境"
    default_weight = 0.0  # 不参与加权，作为乘数使用
```

### 4.2 为什么 Policy 是乘数而非评分因子？

1. **Alpha vs Beta 分离**：护城河是企业的内功（Alpha），国策是外部的天气（Beta）
2. **一票否决威力**：作为乘数，Policy=0.5 可直接将总分砍半；若嵌入 Moat 子维度，最多影响 10%
3. **生命周期解耦**：Moat 按 Ticker 评估，Policy 按 Sector 评估，运行成本极低

### 4.3 数据源

**数据源：** `policy_whitelist.yaml`（Git 版本化）

**文件结构：**
```yaml
version: "1.0"
last_updated: "2026-05-14"

# 全局默认乘数
default_multiplier: 1.0

# 行业政策评级
sectors:
  "白酒":
    policy_rating: "neutral"
    multiplier: 1.0
    note: "消费品，非政策敏感"
  
  "新能源汽车":
    policy_rating: "core_support"
    multiplier: 1.2
    note: "十五五核心赛道"
  
  "在线教育":
    policy_rating: "restricted"
    multiplier: 0.5
    note: "双减政策后行业整顿"
  
  "房地产":
    policy_rating: "restricted"
    multiplier: 0.6
    note: "房住不炒基调未变"
  
  "煤炭":
    policy_rating: "transition"
    multiplier: 0.8
    note: "能源安全保供 + 双碳转型压力"

# 特定标的例外（覆盖行业默认值）
overrides:
  "600519":  # 茅台
    multiplier: 1.1
    note: "消费品龙头，政策风险极低"
```

### 4.4 评估逻辑

```python
def evaluate(self, target: TargetInfo) -> FactorScore:
    policy_config = self._load_policy_config()
    
    # 1. 先查特定标的覆盖
    multiplier = policy_config["overrides"].get(target.symbol, {}).get("multiplier")
    note = policy_config["overrides"].get(target.symbol, {}).get("note")
    
    # 2. 无覆盖则按行业匹配
    if multiplier is None:
        sector_config = policy_config["sectors"].get(target.sector, {})
        multiplier = sector_config.get("multiplier", policy_config["default_multiplier"])
        note = sector_config.get("note", "")
    
    return FactorScore(
        factor_key="policy",
        factor_name="国策环境",
        score=multiplier * 100,  # 转为 0-100 尺度便于展示
        max_score=100.0,
        weight=0.0,  # 不参与加权求和
        details={
            "multiplier": multiplier,
            "policy_rating": self._rating_from_multiplier(multiplier),
            "note": note,
        },
        confidence=1.0,  # YAML 是确定性数据源
    )
```

### 4.5 乘数映射表

| 乘数 | 评级 | 语义 |
|------|------|------|
| 1.2 | `core_support` | 国家重点扶持赛道 |
| 1.1 | `favorable` | 政策友好 |
| 1.0 | `neutral` | 中性，无显著政策影响 |
| 0.8 | `transition` | 转型期，政策压力与机遇并存 |
| 0.6 | `restricted` | 受政策限制或整顿 |
| 0.5 | `hard_restricted` | 严厉打压，一票否决 |

---

## 5. Orchestrator 集成

### 5.1 权重动态归一化

```python
def _compute_raw_total(self, factor_scores: dict[str, FactorScore]) -> float:
    total = 0.0
    weight_sum = 0.0
    
    for key, score in factor_scores.items():
        w = self.scoring_weights.get(key, 0.0)
        total += score.normalized_score * 100 * w
        weight_sum += w
    
    return total / weight_sum if weight_sum > 0 else 0.0
```

**示例：**
- 场景：传统 A 股煤炭股，TokenFactorPlugin `is_applicable()` 返回 False
- 结果：factor_scores 中只有 moat + financials，weight_sum = 0.7
- Moat 实际权重 = 0.5 / 0.7 ≈ 71.4%，Financials = 0.2 / 0.7 ≈ 28.6%

### 5.2 插件适用性判定

```python
# BaseFactorPlugin 新增方法
class BaseFactorPlugin(ABC):
    def is_applicable(self, target: TargetInfo) -> bool:
        """子类可覆盖，声明该插件是否适用于特定标的"""
        return True
```

**TokenFactorPlugin 覆盖示例：**
```python
def is_applicable(self, target: TargetInfo) -> bool:
    return target.asset_class in ("crypto", "defi", "web3")
```

**Orchestrator 调用逻辑：**
```python
def _run_plugins(self, target: TargetInfo) -> dict[str, FactorScore]:
    scores: dict[str, FactorScore] = {}
    for key, plugin in self.plugins.items():
        if not plugin.is_applicable(target):
            continue  # 不适用 → 完全跳过
        try:
            scores[key] = plugin.evaluate(target)
        except Exception as e:
            logger.exception("Factor %s failed for %s", key, target.symbol)
            scores[key] = FactorScore(
                factor_key=key,
                factor_name=plugin.factor_name,
                score=0.0,
                confidence=0.0,  # 置信度归零
                warnings=[f"【系统故障】API 获取失败或解析错误: {str(e)}"],
            )
    return scores
```

### 5.3 置信度聚合与报告水印

```python
def _aggregate_confidence(self, factor_scores: dict[str, FactorScore]) -> float:
    """计算综合置信度，用于报告头部水印"""
    if not factor_scores:
        return 0.0
    
    total_weight = sum(self.scoring_weights.get(k, 0.0) for k in factor_scores)
    if total_weight == 0:
        return 0.0
    
    weighted_confidence = sum(
        score.confidence * self.scoring_weights.get(key, 0.0)
        for key, score in factor_scores.items()
    )
    return weighted_confidence / total_weight
```

**报告水印规则：**
- 综合置信度 ≥ 0.8 → 正常输出
- 0.5 ≤ 综合置信度 < 0.8 → 黄色警告：[数据部分缺失]
- 综合置信度 < 0.5 → 红色警告：[数据残缺 / 评估挂起]

---

## 6. 数据字典与来源映射表

### 6.1 静态指标（YAML）

| 指标名 | 字段路径 | 数据类型 | 评分范围 | 更新频率 |
|--------|---------|---------|---------|---------|
| `brand_premium` | `companies.{symbol}.base_score.brand_premium.score` | int | 0-100 | 半年 |
| `franchise_barrier` | `companies.{symbol}.base_score.franchise_barrier.score` | int | 0-100 | 半年 |
| `policy_alignment` | `companies.{symbol}.base_score.policy_alignment.score` | int | 0-100 | 季度 |
| `cost_advantage` | `companies.{symbol}.base_score.cost_advantage.score` | int | 0-100 | 半年 |
| `sector_policy_multiplier` | `policy_whitelist.yaml:sectors.{sector}.multiplier` | float | 0.5-1.2 | 季度 |

### 6.2 动态指标（DuckDB / API）

| 指标名 | 计算逻辑 | 数据源 | 更新频率 | 资产类别 |
|--------|---------|--------|---------|---------|
| `roic_sustainability` | ROIC 连续达标年数 | Wind / Choice | 季度 | 传统 |
| `gmoat_stability` | 毛利率 vs 行业中位数 | Wind / Choice | 季度 | 传统 |
| `rd_efficiency` | 研发转化率 | Wind / Choice | 季度 | 传统 |
| `market_share_trend` | 市占率变化率 | 行业报告 | 年度 | 传统 |
| `github_activity` | 90 日代码提交数 | GitHub API | 日 | Crypto |
| `dau_growth` | 日活增速 | Dune Analytics | 日 | Crypto |
| `burn_rate` | 链上燃烧率 | Dune / Glassnode | 日 | Crypto |
| `active_address_growth` | 活跃地址增速 | Glassnode | 日 | Crypto |
| `pe_percentile` | PE 历史百分位 | Wind / Choice | 日 | 全部 |
| `pb_percentile` | PB 历史百分位 | Wind / Choice | 日 | 全部 |
| `debt_ratio_deterioration` | 资产负债率环比 | Wind / Choice | 季度 | 传统 |
| `goodwill_ratio` | 商誉 / 净资产 | Wind / Choice | 季度 | 传统 |
| `operating_cashflow_ratio` | 经营现金流 / 净利润 | Wind / Choice | 季度 | 传统 |

---

## 7. 电路断路器 (Circuit Breakers)

Module A 与 Module C 联动，新增以下断路器：

```yaml
circuit_breakers:
  # 1. 择时信号强但护城河不足
  timing_without_moat:
    enabled: true
    rule: "timing_ma_120_score > 60 and moat_score < 60"
    alert_level: "hard_veto"
    message: "择时信号强烈但护城河评分不足，禁止买入垃圾股的反弹"
  
  # 2. 护城河评分过低
  min_moat:
    enabled: true
    rule: "moat_score < 40"
    alert_level: "soft_veto"
    message: "护城河评分过低，建议回避"
  
  # 3. 数据残缺
  low_confidence:
    enabled: true
    rule: "moat_confidence < 0.5"
    alert_level: "yellow_warning"
    message: "护城河数据残缺，评估可靠性低"
  
  # 4. 政策严厉打压
  policy_hard_restricted:
    enabled: true
    rule: "policy_multiplier < 0.6"
    alert_level: "hard_veto"
    message: "标的所属行业受政策严厉打压，一票否决"
```

---

## 8. 错误处理

| 场景 | 行为 | 输出 |
|------|------|------|
| 静态 YAML 文件缺失 | 抛出 `FileNotFoundError`，CLI 捕获后友好提示 | "错误: 未找到 moat_static_base.yaml" |
| 标的不在 YAML 中 | Base Score 返回 0，confidence=0.5，warning="未找到静态评分记录" | 部分可用 |
| DuckDB 查询无数据 | Trend/Safety Score 返回 0，confidence=0.0 | 严重警告 |
| API 调用超时/失败 | 异常捕获，fallback score=0，confidence=0.0 | 【系统故障】标记 |
| 全部插件崩溃 | `rating="Error"`，`action="系统异常，人工复核"` | 红色水印 |

---

## 9. 文件结构

```
sentinel/mgfs/
├── plugins/
│   ├── moat.py              # MoatFactorPlugin
│   ├── policy.py            # PolicyFactorPlugin
│   └── timing.py            # 现有 mock（Step 2 替换为 MovingAverageTimingPlugin）
├── data/
│   ├── __init__.py
│   ├── kline_fetcher.py     # K 线数据获取（Step 1.5 开发）
│   ├── financial_fetcher.py # 财务指标获取
│   └── metrics_aggregator.py # DuckDB 聚合查询
└── ...

config/
├── mgfs_config.yaml         # 模块开关、权重、断路器
├── moat_static_base.yaml    # 企业静态护城河评分
└── policy_whitelist.yaml    # 行业政策评级

tests/
├── test_mgfs_moat_plugin.py
├── test_mgfs_policy_plugin.py
├── test_mgfs_data_fetchers.py
└── test_mgfs_integration_step1.py  # 全链路集成测试
```

---

## 10. 开发阶段划分

| 阶段 | 任务 | 产出 |
|------|------|------|
| Step 1a | PolicyFactorPlugin + YAML | 国策乘数可独立运行 |
| Step 1b | MoatFactorPlugin 静态分 | 读取 YAML，输出 Base Score |
| Step 1c | DuckDB 数据层 + Fetchers | Trend/Safety 指标自动入库 |
| Step 1d | MoatFactorPlugin 完整版 | 三段式聚合 |
| Step 1e | Orchestrator 集成 + 置信度 | 动态权重 + 报告水印 |
| Step 1f | 全链路集成测试 | 端到端验证 |

---

*文档版本: 1.0 | 生成日期: 2026-05-14*
*关联文档: [MGFS Framework Design](2026-05-12-mgfs-design.md), [Module C Timing Pre-Research](module_c_timing.md)*
