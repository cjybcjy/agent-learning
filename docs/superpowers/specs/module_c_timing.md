# Module C — 量化择时与盘面抓取 (Timing & Market Data)

> **状态：** 预研文档 | **负责人：** 量化择时组 | **版本：** 0.1

---

## 1. 核心命题

**如何通过多周期 120 均线矩阵建立"绝对安全"的择时边界？**

Module C 作为 MGFS 的"最后一道保险"，在基本面评分（Module A）达标后，负责寻找具体的买入区间。我们不追求"精准抄底"，而是追求"高概率的安全边际"——通过日/周/月三周期 120 均线的叠加判定，过滤掉"接飞刀"的伪买点，只保留"右侧上车"的真信号。

---

## 2. 设计原则

### 2.1 三段式结构（对标均线分析框架）

借鉴技术分析中"位置—斜率—乖离率"的三段式逻辑，Module C 的择时判定分为三个维度：

| 维度 | 均线语义 | 择时语义 | 判定标准 |
|------|---------|---------|---------|
| **位置** | 股价与均线的相对位置 | 是否触及支撑/压力区 | `|Bias| ≤ trigger_bias_percent` |
| **斜率** | 均线的方向与加速度 | 趋势是否向上（排除绞肉机） | `slope > 0`（走平或向上） |
| **乖离率** | 股价偏离均线的程度 | 入场时机的精确度 | `Bias = (Price - MA) / MA × 100%` |

### 2.2 时空共振：三周期叠加判定

单一周期信号不可靠，Module C 要求**至少两个周期同时触发**才给出高置信度信号：

- **日线 120（半年线）**：中期趋势，过滤短期杂波，识别"短期错杀破位"
- **周线 120（2.5 年线）**：机构资金的"建仓锚点"，识别"低位吸筹"区间
- **月线 120（10 年国运线）**：历史级底部，"砸锅卖铁级"战略买点

**信号强度递增原则**：
- 仅日线触发 → 观望，等待周线确认
- 日线 + 周线同时触发 → 分批建仓
- 三周期同时触发 → 重仓出击（需 Module A 护城河评分 ≥ 75）

### 2.3 斜率欺骗性过滤（核心纪律）

> **纪律红线：** 均线不仅看"破不破"，更要看"斜率（方向）"。

- 若半年线**加速朝下**，股价跌到均线附近 ≠ 支撑，而是"绞肉机"
- 只有当均线**走平或拐头向上**，股价缩量回调至均线附近，才是"右侧上车点"

实现上通过 `require_positive_slope: true` 强制过滤斜率为负的信号。

---

## 3. 数学模型

### 3.1 均线斜率（趋势强度）

```
Slope = (MA_today - MA_n_days_ago) / n
```

- `n`：回退周期数（通常取 20 个交易日 ≈ 1 个月）
- `Slope > 0`：均线走平或向上，趋势健康
- `Slope ≤ 0`：均线向下，放弃该周期信号

### 3.2 乖离率（入场时机）

```
Bias = (Price - MA) / MA × 100%
```

- `|Bias| ≤ trigger_bias_percent`：股价进入"击球区"
- `trigger_bias_percent` 默认 5.0%，即股价在均线上方 5% 以内或下方假跌破不超过 5%

### 3.3 信号得分加权

| 触发周期 | 基础加分 | 斜率过滤 |
|---------|---------|---------|
| 日线 120 | +20 | 要求 slope > 0 |
| 周线 120 | +35 | 要求 slope > 0 |
| 月线 120 | +50 | 要求 slope > 0 |
| 斜率向下 | -20 | 强制扣分 |

**最终得分钳制**：`score = clamp(0.0, 100.0, 50.0 + sum(adjustments))`

---

## 4. 插件架构设计

### 4.1 配置文件 (`mgfs_config.yaml`)

```yaml
modules:
  timing:
    enabled: true
    class_path: "sentinel.mgfs.plugins.timing.MovingAverageTimingPlugin"
    config:
      # 三大核心均线参数
      moving_averages:
        daily_120:
          period: 120
          timeframe: "1D"
          description: "半年强弱与错杀线"
        weekly_120:
          period: 120
          timeframe: "1W"
          description: "2.5年机构大底线"
        monthly_120:
          period: 120
          timeframe: "1M"
          description: "10年国运/历史底部线"

      # 乖离率触发阈值 (%)
      trigger_bias_percent: 5.0

      # 斜率过滤：仅当均线走平或向上时才判定为支撑
      require_positive_slope: true

      # 斜率计算回退周期
      slope_lookback_days: 20
```

### 4.2 插件接口 (`MovingAverageTimingPlugin`)

```python
class MovingAverageTimingPlugin(BaseFactorPlugin):
    factor_key = "timing_ma_120"
    factor_name = "三周期120均线择时"
    default_weight = 0.3  # MGFS 公式中 Timing 的权重

    def evaluate(self, target: TargetInfo) -> FactorScore:
        """
        核心流程：
        1. 拉取三个周期的历史 K 线
        2. 计算每条 MA120 的当前值与斜率
        3. 计算当前价格与均线的乖离率
        4. 按规则加权打分并生成信号列表
        """
        ...
```

### 4.3 数据依赖

| 数据项 | 来源 | 频率 | 备注 |
|--------|------|------|------|
| 日线 K 线 | 财经网站公开 API | 日更 | 至少 150 根用于计算 MA120 |
| 周线 K 线 | 日线聚合或独立 API | 周更 | 至少 150 根 |
| 月线 K 线 | 周线聚合或独立 API | 月更 | 至少 150 根 |
| 实时价格 | 同上 | 实时/收盘 | 用于计算乖离率 |

**数据获取封装**：`sentinel.mgfs.data.kline_fetcher`（Step 1 中独立开发，插件通过接口调用，不直接依赖具体 API）。

---

## 5. 输出物契约

插件运行后，`InvestmentDecision.factor_scores["timing_ma_120"]` 包含：

```json
{
  "factor_key": "timing_ma_120",
  "factor_name": "三周期120均线择时",
  "score": 85.0,
  "max_score": 100.0,
  "normalized_score": 0.85,
  "confidence": 0.9,
  "details": {
    "current_price": 42.50,
    "daily_120_value": 41.80,
    "daily_120_slope": 0.02,
    "daily_120_bias": 1.67,
    "weekly_120_value": 35.00,
    "weekly_120_slope": 0.05,
    "weekly_120_bias": 21.43,
    "monthly_120_value": 20.00,
    "monthly_120_slope": 0.12,
    "monthly_120_bias": 112.50,
    "suggested_buy_zone_low": 40.50,
    "suggested_buy_zone_high": 42.00
  },
  "warnings": [
    "【日线级别】回调至半年线支撑且均线向上，短期出现错杀买点"
  ]
}
```

CLI 输出中 `module_C_timing` 段落格式：

```
《投资权衡与决策说明书》
==================================================
...
--------------------------------------------------
三周期120均线择时: 85.0/100.0
  当前价格: 42.50
  日线120: 41.80 (斜率+0.02, 乖离率+1.67%)
  周线120: 35.00 (斜率+0.05, 乖离率+21.43%)
  月线120: 20.00 (斜率+0.12, 乖离率+112.50%)
  建议买入区间: 40.50 — 42.00
  信号: 【日线级别】回调至半年线支撑且均线向上，短期出现错杀买点
--------------------------------------------------
...
```

---

## 6. 与 Module A 的联动约束

**Module C 不能独立触发买入决策。** 以下约束硬编码在 Orchestrator 的电路断路器中：

```yaml
circuit_breakers:
  timing_without_moat:
    enabled: true
    rule: "timing_ma_120_score > 60 and moat_score < 60"
    alert_level: "hard_veto"
    message: "择时信号强烈但护城河评分不足，禁止买入垃圾股的反弹"
```

> 即：即使 Module C 给出 85 分的高择时评分，若 Module A 护城河评分 < 60，直接一票否决。

---

## 7. 开发优先级

| 阶段 | 任务 | 状态 |
|------|------|------|
| Step 0 | MGFS 框架骨架（已完成） | ✅ |
| Step 1 | Module A — 护城河与国策因子库 | 🔄 进行中 |
| Step 1.5 | K 线数据获取接口（封装层） | ⏳ 待启动 |
| **Step 2** | **Module C — MovingAverageTimingPlugin** | **📋 本文档** |
| Step 3 | Module B — 估值水位 | ⏳ 待定 |

---

## 8. 附录：将三段式逻辑融入 Module A（护城河插件）

Module A 的护城河评分可借鉴 Module C 的"位置—斜率—乖离率"三段式结构，设计为：

| 三段式维度 | 护城河语义 | 评分维度 |
|-----------|-----------|---------|
| **静态存量分** (位置) | 企业现有资源储备 | 专利数、特许经营权、资源储量 |
| **动态增量分** (斜率) | 护城河的增强/减弱趋势 | Token 消耗增速、产能爬坡斜率、市占率变化率 |
| **安全余量分** (乖离率) | 当前扩张是否透支护城河 | ROIC 与 WACC 的差值、负债率偏离历史均值程度 |

**实现方式**：在 `MoatFactorPlugin` 的 `details` 中输出三个子维度分数，由 Orchestrator 按权重聚合为最终 `moat_score`。三段式结构保持与 Module C 的概念对齐，便于投研团队统一理解。

---

*文档生成日期：2026-05-14*
*下次评审：Module A 完成后，联合评审 Module A + C 的联动逻辑*
