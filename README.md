# Market Heatmap

多市场（A股/港股/美股/币圈）社媒热度采集 → 加权打分 → AI 信号引擎 → 可视化仪表盘。

## 安装

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 前端构建
cd frontend && npm install && npm run build && cd ..
```

## 配置

- `config/sources.yaml`：采集器开关（jqka/cls/aastocks/futu/reddit/stocktwits/coingecko/lunarcrush）。
- `config/aliases.csv`：标的与俚称映射，`is_ambiguous=true` 标记歧义词。
- `config/thresholds.yaml`：α/β 阈值、AI 配置、各源限速、来源权重、熔断器参数。
- `data/secrets.yaml`：API Key 存储（LUNARCRUSH_API_KEY 等），由 Web UI 的 Settings 面板管理。

## 架构

```
Collectors (12个) → Queue → BatchWriter → SQLite → RollupEngine → AI SignalEngine
                                                      ↓
                                              Web API (FastAPI) → React 前端
```

### 采集器矩阵

| 市场 | 采集器 | 权重 | 类型 |
|------|--------|------|------|
| A股 | 雪球 xueqiu | 0.9 | HTTP |
| A股 | 东方财富 eastmoney | 0.7 | HTTP |
| A股 | 同花顺 jqka | 1.0 | HTTP |
| A股 | 财联社 cls | 0.8 | RSS |
| 港股 | 阿斯达克 aastocks | 0.9 | HTML |
| 港股 | 富途牛牛 futu | 0.7 | Playwright |
| 美股 | Reddit WSB | 0.4 | JSON API |
| 美股 | StockTwits | 0.6 | HTTP |
| 币圈 | CoinGecko | 0.7 | HTTP |
| 币圈 | LunarCrush | 0.5 | HTTP |
| 币圈 | Telegram | — | MTProto |
| 币圈 | Discord | — | Gateway |

### 四层反爬

| 层级 | 模块 | 功能 |
|------|------|------|
| L1 | `ua_pool.py` | 17 个真实浏览器 UA 轮换 + Accept-Language + Sec-Ch-Ua |
| L2 | `jitter.py` | 请求间隔随机抖动 ±30% + Cookie 持久化 + 搜索引擎 Referrer 链 |
| L3 | `browser_fallback.py` | Playwright Chromium + stealth 插件 + 贝塞尔鼠标轨迹 + 慢速滚动 |
| L4 | `circuit_breaker.py` | 代理池可用率 < 20% 触发熔断，休眠后自动探测恢复 |

## 演示

### 1. 播种数据

```bash
python scripts/seed_demo.py
```

在数据库中插入 35 条跨 A股/港股/币圈三个市场的消息并运行 rollup 聚合。

### 2. 启动 Web 服务

```bash
bash scripts/demo.sh web
```

打开 **http://localhost:8000**，API 文档在 http://localhost:8000/docs。

### 3. 演示要点

**市场切换不再混乱：**
- 点击 A股 / 港股 / 全部 按钮切换市场，列表立即清空→loading→新数据
- 快速连续切换，无旧数据残留（useReducer 状态机 + AbortController 取消旧请求）

**数据状态三层标识：**
- 顶部概览条：标的数 / 消息数 / 来源列表 / 更新时间
- 行级：来源数量标签（2源绿色 / 1源橙色）+ 置信度评分（高/中/低）
- 市场按钮：✓有数据 / ⚠稀疏 / —无数据灰显
- 高热度+单源标的自带 "⚠ 单一源风险" 红色警告

**多信息源：**
- 点击不同市场查看各自的采集器覆盖（A股4源 / 港股2源 / 美股2源 / 币圈2源）
- 权重归一化：热榜官方数据权重高（同花顺 1.0），社区 UGC 权重低（Reddit 0.4）

### 4. 停止

```bash
bash scripts/demo.sh stop
```

## 运行

```bash
# 仅调度器（数据采集 + AI 信号）
python -m heatmap.scheduler

# 仅 Web 服务（API + 前端）
python -m heatmap.web

# 完整启动
bash scripts/demo.sh all
```

## 测试

```bash
python -m pytest tests/unit/ -v        # 单元测试
python -m pytest tests/integration/ -v  # 集成测试
```

## 文档

- 设计规格：[docs/superpowers/specs/2026-05-10-heatmap-v2-design.md](docs/superpowers/specs/2026-05-10-heatmap-v2-design.md)
- 实施计划：[docs/superpowers/plans/2026-05-10-heatmap-v2-plan.md](docs/superpowers/plans/2026-05-10-heatmap-v2-plan.md)
