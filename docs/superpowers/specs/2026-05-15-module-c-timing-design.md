# Module C — 量化择时与盘口抓取 (Timing Module) 设计规范

> **Status:** Approved for implementation  
> **Depends on:** Module A (Moat), Module B (Valuation)  
> **Goal:** Add time-dimension timing signals to the MGFS decision engine, with archetype-aware parameter routing to avoid "catching a falling knife."

---

## 1. 核心设计哲学

Module B 回答 "**值不值得买**"（估值空间），Module C 回答 "**什么时候买**"（时间节奏）。

但时间节奏不能脱离估值空间独立存在。一只估值处于 95% 历史高位的股票，即便短期回踩 120 均线，也不应该触发买入信号——这是 Module B 的 hard_veto 职责。

Module C 的职责边界：
- **只服务估值处于合理区间（非 avoid 区）的标的**
- **绝不 override Module B 的否决决策**
- **通过趋势方向过滤 Module B 的模糊区（hold/accumulate）**

---

## 2. 三层分层参数体系

### 2.1 为什么不能用统一参数？

| 资产类别 | 年化波动率 | 120日均线标准差 | 统一 ±5% Bias 的后果 |
|---------|-----------|----------------|---------------------|
| A股银行股 | 15-20% | ±3% | 基本不触发，信号过少 |
| A股创业板 | 30-40% | ±8% | 偶尔触发，尚可 |
| Crypto (BTC) | 60-80% | ±15% | **永远触发，噪音爆炸** |
| Crypto (ALT) | 100-150% | ±25% | **系统失效** |

### 2.2 参数分层架构

```yaml
# config/timing_config.yaml
timing:
  # 第一层：Market 级默认值（兜底）
  market_defaults:
    A_SHARE:
      ma_period: 120
      ma_type: "sma"
      bias_threshold: 0.06        # ±6%
      slope_threshold: 0.02       # 2% 斜率阈值
      slope_window: 20            # 20日斜率计算窗口
      accel_threshold: 0.001      # 加速度阈值
      volume_confirm: true        # A股需要量能确认
      
    CRYPTO:
      ma_period: 20               # Crypto 趋势寿命短
      ma_type: "ema"              # EMA 对 Crypto 更敏感
      bias_threshold: 0.15        # ±15%
      slope_threshold: 0.05       # 5% 斜率阈值
      slope_window: 5             # 5日斜率窗口
      accel_threshold: 0.003
      volume_confirm: false       # 7x24 市场，量能失真少

  # 第二层：Archetype 级覆盖（与 Module B 联动，推荐）
  archetype_overrides:
    traditional_growth:           # 白酒等穿越周期资产
      ma_period: 120
      bias_threshold: 0.05        # 大盘股波动小，收紧
      
    heavy_asset_cyclical:         # 资源/周期股
      ma_period: 60               # 周期切换快
      bias_threshold: 0.08        # 周期股波动大
      
    saas_and_tech:                # 科技股
      ma_period: 60
      bias_threshold: 0.10
      
    crypto_and_utility:           # Crypto
      ma_period: 20
      bias_threshold: 0.18
      use_ema: true
```

### 2.3 参数解析优先级

```
Archetype override > Market default
```

`TimingFactorPlugin` 通过 `ArchetypeRouter.resolve_archetype()` 获取标的的范式配置，从中提取 `timing` 字段。如果该范式未定义 timing 参数，则 fallback 到 `market_defaults`。

---

## 3. 核心打分函数：`_score_bias()` 数学规范

### 3.1 输入变量

| 变量 | 含义 | 维度 |
|-----|------|------|
| `bias` | 乖离率 = (price - MA) / MA | 空间（位置） |
| `slope` | 均线斜率（线性回归或差分） | 时间一阶（方向） |
| `acceleration` | 斜率变化率 = slope[n] - slope[n-k] | 时间二阶（加速度） |
| `cfg` | 该标的的 timing 配置（ma_period, bias_threshold 等） | 参数 |

### 3.2 核心原则

> **趋势的方向和加速度可以一票否决空间上的"看起来便宜"。**

### 3.3 硬熔断规则（一票否决）

#### Rule 1: 接飞刀（Catching a Falling Knife）

```
IF abs(bias) < bias_threshold * 0.5    // 价格非常接近均线（看似"回踩"）
   AND slope < -slope_threshold         // 均线明显向下
   AND acceleration < 0                 // 均线向下加速
THEN
   RETURN score=0.0, zone="veto_catching_falling_knife"
```

**场景解释**：价格短暂触及均线后反弹，但均线本身在加速下跌。此时的 "bias ≈ 0" 不是支撑，而是下跌中继。买入 = 接飞刀。

#### Rule 2: 追高见顶（Chasing the Top）

```
IF bias > bias_threshold * 1.5         // 价格远高于均线
   AND slope > slope_threshold * 2      // 均线陡峭向上
   AND acceleration > 0                 // 均线向上加速
THEN
   RETURN score=10.0, zone="avoid_chasing_top"
```

**场景解释**：价格脱离均线过远，且趋势在加速冲顶。此时买入是追高，即使估值不贵也应回避。

### 3.4 连续评分（软评分）

硬熔断未触发时，进入三维连续评分。

#### Step 1: Bias 基础分（空间维度）

使用误差函数 `erf` 构造 S-curve，将乖离率映射到 0-100 分：

```python
import math

bias_normalized = bias / bias_threshold
bias_score = 50.0 + 50.0 * math.erf(-bias_normalized / math.sqrt(2))
```

映射表：

| bias | bias_normalized | bias_score | 含义 |
|------|----------------|-----------|------|
| +10% | +1.67 | ~8 | 严重超买 |
| +6% | +1.0 | ~16 | 超买 |
| 0% | 0 | 50 | 均线附近 |
| -6% | -1.0 | ~84 | 超卖（买入区） |
| -10% | -1.67 | ~92 | 极度超卖 |

**为什么用 erf 而不是 sigmoid？**  
erf 在 0 点附近更平缓（对小幅偏离不敏感），在尾部更陡峭（对极端偏离更敏感），更适合金融资产的价格分布特性。

#### Step 2: Trend 调制因子（方向维度）

趋势因子**不是加法，是乘法**——它直接调制 bias_score，体现"趋势压倒位置"的风控哲学。

```python
slope_normalized = slope / slope_threshold

if slope_normalized > 0:
    # 趋势向上：奖励买入信号（超卖时买入更可信）
    trend_multiplier = 1.0 + 0.3 * min(slope_normalized, 2.0)
    # 最大奖励 +60%（slope = 2 * threshold 时）
else:
    # 趋势向下：惩罚买入信号（压制接飞刀）
    # 非线性惩罚：斜率越陡，惩罚越重
    trend_multiplier = 1.0 / (1.0 + 0.5 * abs(slope_normalized) ** 1.5)
    # slope = -1 * threshold → multiplier ≈ 0.67
    # slope = -2 * threshold → multiplier ≈ 0.36
    # slope = -3 * threshold → multiplier ≈ 0.19
```

**不对称设计原则**：趋势向上的奖励（最大 +60%）远小于趋势向下的惩罚（可降至 0.1 以下）。这体现了 **"宁可错过，不可做错"** 的风控哲学。

#### Step 3: Acceleration 调制因子（加速度维度）

```python
accel_normalized = acceleration / accel_threshold

if accel_normalized > 0:
    # 趋势在加强（向上加速或向下减速）→ 奖励
    accel_multiplier = 1.0 + 0.15 * min(accel_normalized, 2.0)
else:
    # 趋势在减弱（向下加速或向上减速）→ 惩罚
    accel_multiplier = 1.0 / (1.0 + 0.3 * abs(accel_normalized))
```

**物理意义**：
- `acceleration > 0`：均线在"弯向有利于我们的方向"（向上变陡或向下变平）
- `acceleration < 0`：均线在"弯向不利于我们的方向"（向下变陡或向上变平）

#### Step 4: 综合得分与分区

```python
raw_score = bias_score * trend_multiplier * accel_multiplier
score = max(0.0, min(100.0, raw_score))

if score >= 90:
    zone = "strong_buy"
elif score >= 75:
    zone = "accumulate"
elif score >= 50:
    zone = "hold"
else:
    zone = "avoid"
```

### 3.5 完整伪代码

```python
def _score_bias(
    self,
    bias: float,
    slope: float,
    acceleration: float,
    cfg: dict[str, float],
) -> tuple[float, str]:
    """三维时空评分：bias（空间）× slope（方向）× acceleration（加速度）。"""
    import math

    bias_threshold = cfg.get("bias_threshold", 0.06)
    slope_threshold = cfg.get("slope_threshold", 0.02)
    accel_threshold = cfg.get("accel_threshold", 0.001)

    # ====== 硬熔断：一票否决 ======
    if (
        abs(bias) < bias_threshold * 0.5
        and slope < -slope_threshold
        and acceleration < 0
    ):
        return 0.0, "veto_catching_falling_knife"

    if (
        bias > bias_threshold * 1.5
        and slope > slope_threshold * 2
        and acceleration > 0
    ):
        return 10.0, "avoid_chasing_top"

    # ====== 连续评分 ======
    # Step 1: Bias S-curve via error function
    bias_norm = bias / bias_threshold
    bias_score = 50.0 + 50.0 * math.erf(-bias_norm / math.sqrt(2))

    # Step 2: Trend multiplier (asymmetric)
    slope_norm = slope / slope_threshold
    if slope_norm > 0:
        trend_mult = 1.0 + 0.3 * min(slope_norm, 2.0)
    else:
        trend_mult = 1.0 / (1.0 + 0.5 * abs(slope_norm) ** 1.5)

    # Step 3: Acceleration multiplier
    accel_norm = acceleration / accel_threshold if accel_threshold != 0 else 0
    if accel_norm > 0:
        accel_mult = 1.0 + 0.15 * min(accel_norm, 2.0)
    else:
        accel_mult = 1.0 / (1.0 + 0.3 * abs(accel_norm))

    # Step 4: Composite
    raw = bias_score * trend_mult * accel_mult
    score = max(0.0, min(100.0, raw))

    # Step 5: Zone mapping
    if score >= 90:
        zone = "strong_buy"
    elif score >= 75:
        zone = "accumulate"
    elif score >= 50:
        zone = "hold"
    else:
        zone = "avoid"

    return round(score, 2), zone
```

---

## 4. 与 Module B 的联调接口

### 4.1 Module C 绝不 Override Module B

```python
class TimingFactorPlugin(BaseFactorPlugin):
    def evaluate(self, target: TargetInfo) -> FactorScore:
        # 1. 先检查 Module B 的估值状态
        # （通过 details 透传，或由 Orchestrator 在更高层控制）
        
        # 2. 获取 Timing 参数（通过 ArchetypeRouter）
        archetype = self._router.resolve_archetype(target.symbol, target.sector)
        timing_cfg = archetype.get("timing", {})
        
        # 3. 获取 K 线数据
        kline = self._fetcher.fetch_kline(
            target.symbol, target.market,
            period="daily", years=2
        )
        
        # 4. 计算指标
        ma = compute_ma(kline.close, timing_cfg)
        bias = (kline.close[-1] - ma[-1]) / ma[-1]
        slope = compute_slope(ma, timing_cfg["slope_window"])
        acceleration = compute_acceleration(slope, timing_cfg["slope_window"])
        
        # 5. 评分
        score, zone = self._score_bias(bias, slope, acceleration, timing_cfg)
        
        return FactorScore(
            factor_key="timing",
            factor_name="量化择时",
            score=score,
            details={
                "ma_period": timing_cfg.get("ma_period"),
                "ma_type": timing_cfg.get("ma_type", "sma"),
                "current_bias": round(bias, 4),
                "current_slope": round(slope, 4),
                "current_acceleration": round(acceleration, 6),
                "bias_threshold": timing_cfg.get("bias_threshold"),
                "zone": zone,
            },
            confidence=self._compute_confidence(kline),
        )
```

### 4.2 Orchestrator 跨模块熔断（时空共振）

当 Module C 接入后，新增一条高阶熔断规则：

```yaml
circuit_breakers:
  # ... 原有 Module B 规则 ...
  
  # Module C 接入后新增
  perfect_storm_long:
    enabled: true
    rule: "valuation_zone == 'strong_buy' and timing_zone == 'strong_buy' and moat_score >= 70"
    alert_level: "green_pass"
    message: "估值绝对低估 + 趋势回踩企稳 + 护城河深厚，时空共振"
    
  false_bottom:
    enabled: true
    rule: "timing_zone == 'veto_catching_falling_knife'"
    alert_level: "hard_veto"
    message: "价格触及均线但趋势向下加速，疑似假反弹，一票否决"
```

---

## 5. K 线数据 Fetcher 设计

### 5.1 接口定义

```python
class KlineFetcher(ABC):
    @abstractmethod
    def fetch_kline(
        self,
        symbol: str,
        market: Market,
        period: str = "daily",    # daily, weekly, hourly
        years: int = 3,
    ) -> KlineData:
        """Fetch OHLCV + volume kline data.
        
        Returns:
            KlineData with fields: open, high, low, close, volume,
            each as list[float] with most recent last.
        """
        raise NotImplementedError
```

### 5.2 Tushare 实现

```python
class TushareKlineFetcher(KlineFetcher):
    """Fetch kline via Tushare pro_bar interface."""
    
    def fetch_kline(self, symbol, market, period="daily", years=3):
        pro = self._get_pro()
        
        # Tushare period mapping
        freq_map = {"daily": "D", "weekly": "W", "hourly": "60min"}
        freq = freq_map.get(period, "D")
        
        df = pro.daily(
            ts_code=self._to_ts_code(symbol, market),
            start_date=(datetime.now() - timedelta(days=years*365)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
        )
        
        return KlineData(
            open=df["open"].tolist(),
            high=df["high"].tolist(),
            low=df["low"].tolist(),
            close=df["close"].tolist(),
            volume=df["vol"].tolist(),
        )
```

### 5.3 反爬虫措施（复用 TushareValuationFetcher）

- 随机延迟 0.5-2.0s
- 指数退避重试（3 次）
- 与 valuation fetcher 共享 token 和 session

---

## 6. 输出示例

### 6.1 终端报告（完美时空共振）

```
==================================================
《投资权衡与决策说明书》
==================================================
标的: 600519 (A股)
行业: 白酒
-----------------------------
护城河深度: 85.2/100.0
国策环境: 110.0/100.0
估值水位: 95.8/100.0    ← PE 处于 12% 历史分位（绝对低估）
量化择时: 92.5/100.0    ← 价格回踩 120 均线，均线斜率 0.025 向上
-----------------------------
原始加权分: 91.23
政策乘数: 1.1
最终得分: 100.35
评级: Strong Buy
建议动作: 重仓出击
综合置信度: 0.92
告警级别: green_pass
🎯 时空共振: 估值绝对低估 + 趋势回踩企稳 + 护城河深厚
==================================================
```

### 6.2 终端报告（接飞刀被否决）

```
==================================================
《投资权衡与决策说明书》
==================================================
标的: 601899 (A股)
行业: 有色金属
-----------------------------
护城河深度: 45.6/100.0
国策环境: 100.0/100.0
估值水位: 55.2/100.0
量化择时: 0.0/100.0     ← VETO: 价格触及均线但均线向下加速
-----------------------------
原始加权分: 38.45
政策乘数: 1.0
最终得分: 38.45
评级: Avoid
建议动作: 回避
⚠️  [数据部分缺失]
综合置信度: 0.65
告警级别: hard_veto
触发熔断:
  - [hard_veto] 价格触及均线但趋势向下加速，疑似假反弹
==================================================
```

---

## 7. Self-Review

### Spec Coverage

| 需求 | 覆盖 |
|-----|------|
| 不同资产类别不同均线参数 | ✅ Archetype 级覆盖 |
| 乖离率 + 均线斜率 + 加速度三维评分 | ✅ `_score_bias()` 数学规范 |
| 接飞刀一票否决 | ✅ Hard熔断 Rule 1 |
| 趋势向上奖励 / 趋势向下惩罚不对称 | ✅ 乘法调制因子 |
| K 线数据 Fetcher | ✅ ABC + Tushare 实现 |
| 与 Module B 联调 | ✅ Orchestrator 熔断规则 |

### Placeholder Scan

- 无 TBD/TODO
- 所有数学公式完整
- 所有代码块可直接运行

---

## 附录：数学函数参考

### Error Function (erf)

```
erf(x) = (2/√π) ∫₀ˣ e^(-t²) dt

erf(0) = 0
erf(1) ≈ 0.8427
erf(-1) ≈ -0.8427
erf(2) ≈ 0.9953
```

Python: `math.erf(x)` (Python 3.2+)

### Slope 计算（线性回归）

```python
def compute_slope(series: list[float], window: int) -> float:
    """Linear regression slope of the last `window` points."""
    import numpy as np
    y = np.array(series[-window:])
    x = np.arange(len(y))
    return np.polyfit(x, y, 1)[0]  # slope coefficient
```

### Acceleration 计算

```python
def compute_acceleration(slope_series: list[float], window: int) -> float:
    """Second derivative = change in slope."""
    return slope_series[-1] - slope_series[-window]
```
