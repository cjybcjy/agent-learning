# Market Heatmap Web Dashboard — 设计稿

**日期：** 2026-05-02
**版本：** v2（A股/港股/美股/币圈 + Web 可视化 + AI 分析）
**仓库：** agent-learning
**前置设计：** 2026-04-30 币圈 MVP（已归档，见 git 历史）

---

## 1. 目标

将 v1 的"币圈社媒热度 → 双闸门打分 → 飞书日报"扩展为：

**多市场覆盖**：A股 / 港股 / 美股 / 币圈
**高频采集**：每 30 分钟采集一次
**多粒度展示**：30 分钟 / 4 小时 / 日 / 周（用户自选）
**AI 分析**：实时异动检测 + 结构化信号输出（支持下游 ML 因子消费）
**可视化网页**：FastAPI + React，内网部署，免登录
**AI 互动**：常驻聊天面板 + 快捷提问按钮

**废弃**：飞书日报（`reporter/lark_doc.py` 不再维护，输出完全转向 Web API）

---

## 2. 整体架构

```
[Collectors] ──► [Rate Limiter + Proxy Pool] ──► [asyncio.Queue] ──► [BatchWriter] ──► [SQLite WAL]
   雪球/东财/...        domain:proxy 隔离            内存缓冲         单协程批量写入      data/heatmap.db
   Telegram                        冷却期机制
   Discord

[SQLite] ──► [Aggregator + Rollup] ──► [AI Signal Engine] ──► [WebSocket Push]
   rollup_30min        即时 α 计算            真实语料注入              实时推送前端
   rollup_4h           4h/日级预计算          结构化 JSON 输出
   rollup_daily                              成本护栏（日预算限制）
   ai_signals

[Web API] ──► [React Frontend]
   FastAPI REST        热度榜单 / 趋势图 / AI 聊天面板
   WebSocket
```

**两阶段交付**：
- **阶段一**：扩展采集系统（多源 + 30min 粒度 + Rollup 预计算）
- **阶段二**：叠加 Web 可视化 + AI 分析引擎

---

## 3. 存储层设计

### 3.1 SQLite WAL 模式

初始化时强制执行：

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
```

- WAL 模式允许读写并发，Collector 批量写入不阻塞 Web API 查询
- `synchronous=NORMAL` 在性能和持久性之间取得平衡

### 3.2 数据库 Schema

```sql
-- 原始消息（不变）
CREATE TABLE IF NOT EXISTS raw_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  channel TEXT NOT NULL,
  author_id TEXT,
  content TEXT NOT NULL,
  posted_at TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_posted_at ON raw_messages(posted_at);
CREATE INDEX IF NOT EXISTS idx_raw_platform ON raw_messages(platform);

-- 实体命中（不变）
CREATE TABLE IF NOT EXISTS mentions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  matched_alias TEXT NOT NULL,
  is_ambiguous INTEGER NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  FOREIGN KEY (message_id) REFERENCES raw_messages(id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_symbol ON mentions(symbol);
CREATE INDEX IF NOT EXISTS idx_mentions_message ON mentions(message_id);

-- ========== Rollup 预计算表 ==========
CREATE TABLE IF NOT EXISTS rollup_30min (
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  market TEXT NOT NULL,  -- 枚举: a_share | hk | us | crypto
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  PRIMARY KEY (symbol, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rollup30_market ON rollup_30min(market, window_start);
CREATE INDEX IF NOT EXISTS idx_rollup30_symbol ON rollup_30min(symbol);

CREATE TABLE IF NOT EXISTS rollup_4h (
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  PRIMARY KEY (symbol, window_start)
);

CREATE TABLE IF NOT EXISTS rollup_daily (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  alpha REAL,
  beta REAL,
  composite REAL,
  PRIMARY KEY (symbol, date)
);

-- ========== AI 结构化信号表 ==========
CREATE TABLE IF NOT EXISTS ai_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  model_version TEXT NOT NULL,
  created_at TEXT NOT NULL,

  anomaly_score REAL,
  sentiment_shift TEXT,
  sentiment_confidence REAL,
  key_driver TEXT,
  key_driver_confidence REAL,
  driver_keywords TEXT,  -- JSON 数组字符串，如 '["美联储", "降息", "50BP"]'，通过 json.loads 解析

  raw_analysis TEXT,     -- 大模型推理原文

  -- 预留：基本面数据 Join 字段（未来扩展）
  -- 下游 ML 模型可结合热度因子与基本面因子做联合判断
  pe_ratio REAL,         -- 市盈率
  pb_ratio REAL,         -- 市净率
  roe_ttm REAL,          -- ROE (TTM)
  dividend_yield REAL,   -- 股息率

  FOREIGN KEY (symbol, window_start) REFERENCES rollup_30min(symbol, window_start)
);
CREATE INDEX IF NOT EXISTS idx_ai_signals_symbol ON ai_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_ai_signals_window ON ai_signals(window_start);

-- AI 调用日志（成本护栏用）
CREATE TABLE IF NOT EXISTS ai_call_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  model_version TEXT NOT NULL,
  called_at TEXT NOT NULL,
  cost_estimate REAL  -- 可选：记录预估成本
);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_date ON ai_call_log(called_at);

-- 兼容 v1 daily_scores（数据迁移用）
CREATE TABLE IF NOT EXISTS daily_scores (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  alpha REAL,
  beta REAL,
  composite REAL,
  PRIMARY KEY (symbol, date)
);
```

### 3.3 Rollup 预计算触发逻辑

```
每 30 分钟触发：
  1. 采集器经 Queue → BatchWriter 批量写入 raw_messages
  2. 对刚过去的 30 分钟窗口做聚合 → 写入 rollup_30min
  3. 如果是 4h 边界（00:00, 04:00, 08:00...），
     汇总最近 8 个 30min 记录 → 写入 rollup_4h
  4. 如果是日边界（00:00 UTC），
     直接基于 rollup_4h 累加（6 条 4h 记录）→ 写入 rollup_daily（同时计算 α/β/composite）
     【优化：不回溯 raw_messages 全表，计算复杂度 O(1)】
  5. 对 rollup_30min 中即时 α 突破阈值的标的触发 AI 分析 → 写入 ai_signals
     并通过 WebSocket 推送给前端
```

**关键**：AI 触发挂在 `rollup_30min` 上，日切只做沉淀，不做首发预警。

### 3.4 缓冲队列与批量写入

```python
# Collector → asyncio.Queue → BatchWriter → aiosqlite

class BatchWriter:
    async def run(self, queue: asyncio.Queue, store: Store, batch_size: int = 100):
        batch = []
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                batch.append(msg)
                if len(batch) >= batch_size:
                    await self._flush(store, batch)
                    batch = []
            except asyncio.TimeoutError:
                if batch:
                    await self._flush(store, batch)
                    batch = []
```

- **唯一**的 SQLite 写入入口，避免多协程竞争
- aiosqlite 已经是异步驱动，无需 `asyncio.to_thread()`
- Queue 满时（maxsize=10000）新数据写入 **File-based Dead Letter Queue**（本地 `.jsonl` 文件），系统空闲时通过恢复协程重播入库，避免极端行情下丢失关键异动信号

---

## 4. 采集层设计

### 4.1 按代理+域名隔离的 Rate Limiter

```python
class RateLimiter:
    def __init__(self, limits: dict[str, float]):
        # limits: {"xueqiu.com": 1.0, ...}
    
    async def acquire(self, domain: str, proxy_ip: str | None) -> None:
        key = f"{domain}:{proxy_ip}" if proxy_ip else domain
        # Token Bucket per key
```

- 50 个代理 × 1 req/s = 50 req/s 真实并发
- 无代理时回退到全局域名级限速

### 4.2 代理池冷却机制

```python
class ProxyPool:
    def __init__(self, proxies: list[str]):
        self._available: set[str] = set(proxies)
        self._cooldown: dict[str, datetime] = {}  # proxy -> cooldown_until
    
    async def get(self) -> str | None:
        # 优先返回可用代理，冷却期内的跳过
    
    async def report_failure(self, proxy: str):
        # 连续失败 3 次 → cooldown_until = now + 10 minutes
    
    async def _reaper(self):
        # 后台协程：定期检查并恢复冷却完毕的代理
```

- 临时封禁的代理冷却 10 分钟后自动恢复
- 极大降低商业代理池的财务成本

### 4.3 采集器基类

```python
class BaseCollector(Protocol):
    async def run(
        self,
        queue: asyncio.Queue,
        limiter: RateLimiter,
        proxy_pool: ProxyPool,
    ) -> None:
        """常驻协程：采集 → 放入 Queue，不直接写库"""
```

每个 Collector 内部逻辑：
1. 定时/事件触发采集
2. 请求前 `await limiter.acquire(domain, proxy)`
3. 原始数据封装为 `RawMessage` → `await queue.put(msg)`

---

## 5. AI 信号引擎

### 5.1 触发条件

每完成一个 `rollup_30min` 窗口后：

```python
# 即时 α 计算（EMA 平滑，避免时间带偏差误触发）
current_30min = rollup_30min[symbol][window]
# 过去 14 天同一时段的 EMA，消除各市场天然活跃时间带差异
historical_ema = ema(rollup_30min[symbol][same_time_last_14_days], span=7)
instant_alpha = current_30min / historical_ema - 1

if instant_alpha >= threshold_alpha and current_30min >= threshold_min_mentions:
    # 检查日预算
    if daily_ai_calls < MAX_AI_CALLS_PER_DAY:
        trigger_ai_analysis(symbol, window)
    else:
        # 超预算：仅 UI 标红，提示手动点击获取分析
        mark_as_anomaly_without_ai(symbol, window)
```

- 阈值从 `config/thresholds.yaml` 读取，支持按市场独立配置
- `MAX_AI_CALLS_PER_DAY` 默认 50，保护 API 账单
- 日调用计数持久化到 SQLite（`ai_call_log` 表），避免进程重启后计数丢失

### 5.2 真实语料注入

触发 AI 分析前，从 `raw_messages` 捞取该窗口内最具代表性的 Top 10 帖子：

```python
async def get_top_posts(symbol: str, window_start: str, limit: int = 10) -> list[dict]:
    # 按互动量 + 内容长度排序
    # 返回 [{content, platform, channel, posted_at, interactions}, ...]
```

### 5.3 Few-shot Prompting

```
你是一名量化市场异动分析专家。请根据以下标的在最近30分钟内的统计异动和【真实讨论抽样】，
分析其异动背后的核心驱动力。

[统计异动]
标的: {symbol} | 即时α涨幅: {instant_alpha:.2%} | 来源: {sources}

[真实讨论抽样 (Top 10 高赞/高频提及帖子)]
1. {post_1_content} (赞: {post_1_likes})
2. {post_2_content} (赞: {post_2_likes})
...
10. {post_10_content} (赞: {post_10_likes})

请基于上述真实讨论，返回严格符合以下 JSON Schema 的结果：
{
  "anomaly_score": float,      // 0.0~1.0，异常置信度
  "sentiment_shift": string,   // "positive" | "negative" | "neutral"
  "sentiment_confidence": float,
  "key_driver": string,        // "fundamental" | "policy" | "sentiment" | "manipulation" | "other"
  "key_driver_confidence": float,
  "driver_keywords": [string], // 具体实体词，如 ["美联储", "降息", "50BP"]
  "reasoning": string          // 推理过程简短总结
}
```

### 5.4 API 级 JSON 强制约束

为确保 100% 解析成功率，不依赖 Prompt 中的格式说明：

- **OpenAI**: 请求参数设置 `response_format={"type": "json_object"}`
- **Claude**: 请求参数设置 `tool_choice={"type": "tool", "name": "analyze_market_anomaly"}`，将 Schema 定义为 Tool 的 input_schema
- 解析失败时记录原始响应并重试一次，两次均失败则标记为 `parse_error` 并存入 `raw_analysis`

### 5.5 结构化输出与 ML 因子消费

| 字段 | 类型 | ML 用途 |
|---|---|---|
| `anomaly_score` | float (连续) | XGBoost/LightGBM 直接输入 |
| `sentiment_confidence` | float (连续) | 信噪比判断 |
| `sentiment_shift` | categorical | One-Hot / Label Encoding |
| `key_driver` | categorical | One-Hot / Label Encoding |
| `driver_keywords` | JSON 数组 | 预训练词向量 Mean Pooling 或 Hashing Trick → Alpha 因子 |

**特征工程注意事项**：

- **NLP 特征状态一致性**：`driver_keywords` 向量化必须使用离线训练好的冻结模型（`.pkl` 序列化的 TfidfVectorizer 或预训练 Word2Vec），禁止在线实时计算 TF-IDF（会导致特征空间漂移和维度不对齐）
- **Hashing Trick 备选**：对于工程维护优先的场景，可用 sklearn.feature_extraction.FeatureHasher 替代 TF-IDF，无需维护词表
- **未来函数防范**：离线训练时特征与 label 必须严格时间截面对齐。30min 窗口的 anomaly_score 只能 Join 到该截面前的累积特征，label（未来 N 期收益率）的基准价必须取自该窗口的收盘价/VWAP
- **价值交叉筛选**：A股/港股场景下，高置信度 sentiment_shift=positive 且 key_driver=fundamental/policy 时，可叠加 PB 分位数、ROE、股息率等静态截面筛选，过滤游资炒作假阳性
- **特征存储优化**：高维 numpy.ndarray 实时查询时建议前置 Redis/Memcached 缓存层，SQLite 仅作为持久化备份

### 5.6 WebSocket 实时推送

AI 分析完成后，立即推送：

```json
{
  "type": "ai_signal",
  "symbol": "BTC",
  "window_start": "2026-05-02T14:00:00Z",
  "anomaly_score": 0.92,
  "sentiment_shift": "positive",
  "key_driver": "policy",
  "driver_keywords": ["美联储", "降息", "50BP"],
  "instant_alpha": "+920%",
  "timestamp": "2026-05-02T14:05:23Z"
}
```

---

## 6. Web API 设计（FastAPI）

### 6.1 REST Endpoints

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/heatmap` | 热度榜单（支持 `?granularity=30min\|4h\|day\|week&market=all\|a_share\|hk\|us\|crypto&limit=50&cursor=`）|
| GET | `/api/heatmap/{symbol}/trend` | 单个标的趋势图数据 |
| GET | `/api/heatmap/{symbol}/ai_signals` | 单个标的的 AI 分析历史 |
| GET | `/api/markets` | 市场列表 |
| GET | `/api/symbols?market=` | 某市场下的所有标的 |

**强制分页**：
- `/api/heatmap` 默认 `limit=50`，最大 `limit=200`
- 支持基于游标的分页（`cursor` 参数），避免 deep offset 性能问题
- 不带 `limit` 时返回 Top 50，防止一次性拉取上万条打爆内存

### 6.2 WebSocket 实时推送

```
/ws/heatmap

# 客户端连接后订阅
{"action": "subscribe", "markets": ["crypto", "a_share"]}

# 服务端推送 rollup_update
{
  "type": "rollup_update",
  "symbol": "BTC",
  "market": "crypto",
  "window_start": "2026-05-02T14:00:00Z",
  "granularity": "30min",
  "mention_count": 523,
  "weighted_score": 523.0,
  "source_count": 12,
  "instant_alpha": "+920%"
}

# 服务端推送 ai_signal
{
  "type": "ai_signal",
  "symbol": "BTC",
  "window_start": "2026-05-02T14:00:00Z",
  "anomaly_score": 0.92,
  "sentiment_shift": "positive",
  "key_driver": "policy",
  "driver_keywords": ["美联储", "降息", "50BP"],
  "instant_alpha": "+920%",
  "timestamp": "2026-05-02T14:05:23Z"
}
```

### 6.3 AI 聊天 API

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/chat` | 自由问答（流式 SSE 返回）|

```json
// Request
{
  "question": "过去一周 BTC 的热度趋势如何？",
  "context": {
    "markets": ["crypto"],
    "time_range": "7d",
    "focused_symbol": null  // 用户点击标的时自动填入
  }
}
```

AI 聊天支持工具调用（Tool Use），当问题涉及实时数据时自动调用内部 API 获取后再回答。

---

## 7. 前端设计（React）

### 7.1 组件结构

```
frontend/
  src/
    components/
      HeatmapTable/
        index.tsx
        SymbolRow.tsx         # 单行标的（含快捷提问按钮）
        AIBadge.tsx           # AI 信号徽章
      TrendChart/             # 趋势图（Recharts/ECharts）
      AIChatPanel/
        ChatMessage.tsx
        QuickQuestions.tsx    # 快捷问题按钮
      TimeGranularityTabs/    # 30min/4h/day/week
      MarketSelector/         # 市场筛选
      AlertBanner/            # 异常告警横幅
    pages/
      Dashboard.tsx
    hooks/
      useWebSocket.ts
      useHeatmapData.ts
      useAIChat.ts
    services/
      api.ts
      ws.ts
```

### 7.2 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  Logo    A股 | 港股 | 美股 | 币圈    [30min  4h  日  周] │
├────────────────────┬────────────────────────────────────┤
│  📊 热度榜单        │      💬 AI 助手                   │
│  ┌──────────────┐  │      ┌────────────────────────┐   │
│  │ 1. BTC  🔥   │  │      │ 过去一周 BTC 的趋势...  │   │
│  │    +920% 📈  │  │      │                        │   │
│  │ [为什么?][分析]│  │      └────────────────────────┘   │
│  ├──────────────┤  │      [输入问题...]               │
│  │ 2. 茅台       │  │                                    │
│  │    +85%      │  │                                    │
│  ├──────────────┤  │                                    │
│  │ 3. 特斯拉 ⚠️  │  │                                    │
│  │    -30% 📉   │  │                                    │
│  │ [查看原因]    │  │                                    │
│  └──────────────┘  │                                    │
├────────────────────┴────────────────────────────────────┤
│  📈 趋势图区域（点击榜单标的后展开）                      │
└─────────────────────────────────────────────────────────┘
```

### 7.3 AI 聊天上下文隐式携带

用户点击标的的 `[为什么?]` 按钮时，前端自动打包上下文：

```json
{
  "question": "为什么热度飙升？",
  "context": {
    "focused_symbol": "BTC",
    "instant_alpha": "+920%",
    "window_start": "2026-05-02T14:00:00Z",
    "current_sentiment": "positive",
    "current_mention_count": 523
  }
}
```

### 7.4 WebSocket 断线重连与状态同步

`useWebSocket.ts` 实现：

1. **指数退避重连**：断线后等待 1s → 2s → 4s → 8s → 最大 30s 重试
2. **重连后补齐**：重新连接成功后，自动调用 REST API `/api/heatmap?since=<last_seen_timestamp>` 拉取断线期间错过的 `ai_signal` 和 `rollup_update`
3. **心跳保活**：每 30 秒发送一次 `{"type": "ping"}`，服务端响应 `{"type": "pong"}`，无响应则判定为断线
4. **重连状态 UI**：断线期间显示 "连接中..." 提示，重连成功后静默恢复

大模型因此能"看见"用户正在指着屏幕上的哪一行发问。

---

## 8. 调度设计

```python
# heatmap/scheduler.py

async def main():
    # 初始化
    store = Store(DATA / "heatmap.db")
    await store.init()  # 执行 WAL PRAGMA
    
    queue = asyncio.Queue(maxsize=10000)
    limiter = RateLimiter(config.rate_limits)
    proxy_pool = ProxyPool(config.proxies)
    
    # 启动协程
    tasks = [
        asyncio.create_task(batch_writer.run(queue, store)),
        asyncio.create_task(rollup_scheduler.run(store)),  # 每30分钟触发 Rollup
        asyncio.create_task(ai_scheduler.run(store)),       # 检查即时 α 触发 AI
        asyncio.create_task(websocket_broadcaster.run()),   # WebSocket 推送
    ]
    
    # 启动各市场采集器
    for collector in build_collectors(config):
        tasks.append(asyncio.create_task(
            collector.run(queue, limiter, proxy_pool)
        ))
    
    await asyncio.gather(*tasks)
```

---

## 9. 目录结构

```
heatmap/
  collectors/
    base.py
    rate_limiter.py
    proxy_pool.py
    telegram.py
    discord.py
    xueqiu.py          # 新增
    eastmoney.py       # 新增
    ...
  store/
    schema.sql
    dao.py
    writer.py          # 新增：BatchWriter
  extractor/
    dictionary.py
    ac.py
    disambiguator.py
  aggregator/
    scoring.py
    gates.py
    pipeline.py
    rollup.py          # 新增：Rollup 预计算
  ai/                  # 新增
    signal_engine.py   # AI 分析引擎
    prompts.py         # Prompt 模板
    cost_guard.py      # 成本护栏
  web/                 # 新增
    api.py             # FastAPI 路由
    websocket.py       # WebSocket 管理
    models.py          # Pydantic 请求/响应模型
  scheduler.py
frontend/              # 新增
  src/
    components/
    pages/
    hooks/
    services/
  package.json
  vite.config.ts
config/
  sources.yaml
  thresholds.yaml      # 新增 ai 相关阈值
  aliases.csv
  proxies.yaml         # 新增：代理列表
scripts/
  suggest_aliases.py
tests/
  unit/
  integration/
  fixtures/
data/                  # gitignored
docs/superpowers/
  specs/
  plans/
```

---

## 10. 配置示例

```yaml
# config/thresholds.yaml

stage_a_top_n: 50
stage_b_top_n: 10
alpha_min: 0.5
beta_min: 1.5

# AI 触发阈值
ai:
  instant_alpha_threshold: 2.0      # 即时 α 突破 200% 触发 AI
  min_mentions_for_ai: 20           # 最少提及数，过滤噪音
  max_calls_per_day: 50             # 日预算护栏
  model: "claude-sonnet-4-6"        # 模型配置

# 限速配置
rate_limits:
  "xueqiu.com": 1.0
  "eastmoney.com": 0.5
  "api.twitter.com": 2.0

# 代理池
proxies:
  - "http://proxy1.example.com:8080"
  - "http://proxy2.example.com:8080"
  - "socks5://proxy3.example.com:1080"
```

---

## 11. 测试策略

| 层级 | 内容 |
|---|---|
| 单元测试 | RateLimiter Token Bucket 逻辑、ProxyPool 冷却机制、BatchWriter 攒批逻辑、AI JSON 解析鲁棒性 |
| 集成测试 | 端到端：模拟采集 → Queue → BatchWriter → Rollup → AI 触发 → WebSocket 推送 |
| 性能测试 | 100 并发采集写入 Queue，验证 WAL + BatchWriter 不阻塞 |

---

## 12. 开放问题（v2.1 起处理）

- 更多数据源：微博、知乎、雪球组合讨论区
- 用户权限管理：当前内网免登录，未来如需权限控制引入 JWT
- AI 模型本地化：当前依赖外部 API，未来可切换为本地部署模型
- 多机部署：当前单机 SQLite，未来如需横向扩展引入 PostgreSQL/TimescaleDB
