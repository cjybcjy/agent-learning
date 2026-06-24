# MGFS 投研系统演示流程

## 系统架构总览

```
MGFS 价值投资评估系统
├── 1.0 雷达层 (Radar)
│   ├── 单票评估 — 护城河/估值/择时三维评分
│   └── 生态扫描 — 宏观主题 + 角色过滤
├── 1.5 执行层 (Execution)
│   ├── 仓位引擎 — Half-Kelly + 行业 exposure clip
│   ├── 影子跟投 — 虚拟持仓写入 + 自动止损追踪
│   └── 风控警报 — 三层熔断 + Web 红色战术卡片
└── 2.0 进化层 (Evolution)
    ├── 历史沙盘 — 时间旅行回测引擎
    └── 贝叶斯校准 — 静态评分偏见修正
```

---

## 演示步骤

### Step 1: 投研视图首页

打开 `/dashboard/research`

> **口述**: "这是 MGFS 投研系统的主控制台。顶部是实时风控警报舱，
> 目前显示绿色静默状态。下面是贝叶斯校准报告面板，
> 展示我们基于历史回测对静态评分的修正建议。"

**检查点**:
- [ ] 风控警报舱显示 "风控正常 — 无活跃警报" (绿色)
- [ ] 校准报告面板已加载 (紫色加载后显示表格)

---

### Step 2: 单票评估 (1.0 雷达层)

输入 `600519` (贵州茅台)，选择 A股 + 政策中性，点击评估

> **口述**: "首先演示单票评估。输入茅台，系统会从护城河、
> 估值、择时三个维度进行综合评分。"

**检查点**:
- [ ] 决策卡片加载成功，显示评级 (如 Strong Buy/Accumulate)
- [ ] 护城河五维雷达图渲染成功
- [ ] 估值带图表渲染成功
- [ ] 如果评级为 Strong Buy/Accumulate，决策卡片右上角显示 🛒 按钮

---

### Step 3: 影子跟投挂牌 (1.5 执行层)

在 Strong Buy 决策卡片上点击 **🛒 挂牌影子持仓**

> **口述**: "对于评级达到买入标准的标的，我们可以一键挂牌影子持仓。
> 这不是真实下单，而是将标的写入系统的追踪持仓表，
> 让 StopLossMonitor 开始自动追踪其回撤。"

**检查点**:
- [ ] 按钮被替换为绿色确认消息
- [ ] 消息包含标的名称、价格、权重

---

### Step 4: 大盘巡检触发 (1.0/1.5 联动)

切换到 **运维视图** (`/dashboard/ops`)

点击 **立即执行大盘巡检**

> **口述**: "运维视图用于管理全市场扫描。点击按钮触发后台巡检，
> 系统会对配置文件中定义的所有标的进行评估，并保存结果。"

**检查点**:
- [ ] 按钮点击后显示新批次记录
- [ ] 状态显示 "运行中" (黄色)
- [ ] 等待几秒后刷新，状态变为 "已完成" (绿色)

---

### Step 5: 批次详情展开

点击已完成的 **批次 ID**

> **口述**: "点击批次 ID 可以展开详情，看到该批次中所有标的的
> 评分、排名和建议。Strong Buy 和 Accumulate 评级的标的后
> 面也有 🛒 影子跟投按钮。"

**检查点**:
- [ ] 详情表格展开成功
- [ ] 按最终得分降序排列
- [ ] 评级徽章颜色正确 (Strong Buy=绿, Accumulate=蓝)
- [ ] Strong Buy/Accumulate 行显示 🛒 按钮

---

### Step 6: 风控警报演示 (1.5 执行层)

> **口述**: "现在我手动模拟一只持仓标的触发止损，来演示风控警报系统。"

在后台插入一条触发止损的持仓记录（提前准备好的测试数据）：

```python
# 在演示前执行:
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.storage.db import Database
from sentinel.config import AppSettings
repo = MGFSRepository(Database(AppSettings().database_path))
repo.save_active_holding(
    symbol="600690", name="海尔智家", sector="家电",
    entry_price=100.0, current_price=79.0, highest_price=100.0,
    weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
    portfolio_stop_loss=-0.10,
)
```

返回投研视图，等待 10 秒（HTMX 轮询）

> **口述**: "顶部的风控警报舱每 10 秒自动轮询。一旦持仓标的
> 触及止损线，红色警报卡片会自动弹出，显示具体的止损类型、
> 触发价和建议操作。"

**检查点**:
- [ ] 红色警报卡片弹出 (bg-red-600)
- [ ] 显示 [HARD_STOP] 600690 海尔智家
- [ ] 显示 "建议: MARKET_SELL"
- [ ] 两个操作按钮: "确认清仓" 和 "重置防线"

---

### Step 7: 风控 dismiss 演示

点击 **确认清仓**

> **口述**: "点击确认清仓会从持仓表中删除该记录，
> 警报卡片消失，恢复绿色静默状态。"

**检查点**:
- [ ] 警报卡片消失
- [ ] 恢复 "风控正常" 绿色状态

---

### Step 8: 贝叶斯校准报告 (2.0 进化层)

返回投研视图顶部，查看校准报告面板

> **口述**: "这是 MGFS 2.0 的核心能力 — 贝叶斯校准。
> 系统会读取历史 K 线数据，对静态 YAML 评分进行回溯验证。
> 如果某只标的在历史上的表现与静态评分严重不符，
> 校准器会计算出偏见惩罚。"

**口述要点**:
- 红色行: `bias_penalty < -5`，严重高估，需大幅下调
- 橙色行: `-5 <= penalty < -1`，轻度高估
- 绿色行: `penalty >= -1`，评分合理

**检查点**:
- [ ] 校准报告表格正确显示
- [ ] 颜色编码正确 (红/橙/绿)
- [ ] 包含静态分、建议分、偏见惩罚、置信度、原因

---

### Step 9: 历史回测 CLI (2.0 进化层)

在终端执行：

```bash
python -m sentinel.mgfs.evolution.backtest_cli \
    --start-date 2025-01-01 \
    --end-date 2025-06-30 \
    --symbols 300750,600519 \
    --min-samples 30
```

> **口述**: "除了 Web 面板，我们还提供了命令行工具，
> 可以灵活指定时间范围和股票池。工具会读取本地 Eastmoney
> K 线缓存（无需联网），运行回测并输出校准报告。"

**检查点**:
- [ ] CLI 运行成功，输出格式化报告
- [ ] 显示 300750 和 600519 的校准结果

---

### Step 10: 系统闭环总结

> **口述**: "MGFS 系统的完整闭环是这样的:
> 1. 投研评估 → 2. Strong Buy 触发影子跟投 → 3. 每日巡检自动止损扫描
> → 4. 触发风控警报 → 5. 人工决策清仓或重置防线 → 6. 历史回测修正 YAML 评分
> 
> 这个闭环实现了从评估、执行、风控到进化的全链路覆盖。"

---

## 演示前准备清单

### 环境检查
- [ ] Web 服务器已启动 (`python -m sentinel.web.main` 或对应启动命令)
- [ ] 数据库可正常连接 (SQLite/DuckDB)
- [ ] Eastmoney K 线缓存存在 (`~/.cache/sentinel/eastmoney/`)
- [ ] Moat YAML 配置文件存在

### 数据准备
- [ ] 可选: 预插入一条测试持仓用于风控演示
  ```python
  from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
  from sentinel.storage.db import Database
  from sentinel.config import AppSettings
  repo = MGFSRepository(Database(AppSettings().database_path))
  repo.bootstrap()
  repo.save_active_holding(
      symbol="600690", name="海尔智家", sector="家电",
      entry_price=100.0, current_price=79.0, highest_price=100.0,
      weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
      portfolio_stop_loss=-0.10,
  )
  ```

### 应急预案
- [ ] 如果风控警报不弹出: 检查 `mgfs_active_holdings` 表是否有记录
- [ ] 如果校准报告为空: 检查 Eastmoney 缓存是否包含指定 symbol
- [ ] 如果单票评估卡住: 检查 Orchestrator 依赖是否加载正常

---

## 技术规格速览

| 指标 | 数值 |
|------|------|
| 总测试数 | 285 |
| 核心模块数 | 8 |
| Web 端点数 | 11 |
| 前端模板数 | 12 |
| Eastmoney 缓存文件 | 337 |
| K 线数据跨度 | 2018-01 至 2026-05 |
| 回测 CLI 支持参数 | `--start-date`, `--end-date`, `--symbols`, `--min-samples` |
