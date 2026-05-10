# Market Heatmap v2 — 两期改进设计

**日期:** 2026-05-10
**分支:** `heat_factor_judgment`
**状态:** 已确认（已吸收进阶建议）

---

## 概述

针对演示中发现的四个问题：市场切换列表混乱、数据状态不透明、信息源单一、反爬虫薄弱，分两期推进。已吸收业务获利与系统鲁棒性共4条进阶建议。

| 期次 | 目标 | 新增文件 | 修改文件 |
|------|------|----------|----------|
| 第一期 | UI状态重构 + 数据透明 + 置信度预警 | 0 | 7 |
| 第二期 | 多信息源 + 反反爬虫 + 权重归一化 + 熔断 | 13 | 5 |

---

## 第一期：UI 状态重构 + 数据透明 + 置信度预警

### 问题根因

`Dashboard.tsx` 用 6 个零散 `useState` 管理状态，`useCallback` 闭包捕获陈旧值，市场切换时 WebSocket 订阅与 HTTP 请求产生竞态：旧请求的响应可能覆盖新市场的数据。此外，旧请求未被取消，浪费浏览器并发连接。

### 方案：useReducer 状态机 + AbortController

**状态定义：**

```
state: idle | loading | data | empty | error | loading_more
```

**状态流转：**

- 市场/粒度切换 → `dispatch({ type: "RESET", epoch })` → 自动触发 `LOAD`
- `LOAD` → `loading`，请求成功且有数据 → `data`，请求成功无数据 → `empty`，请求失败 → `error`
- `LOAD_MORE`（翻页）→ `loading_more`，保留现有 items
- 每个 action 携带 `epoch`，reducer 忽略过期 epoch 的响应

**AbortController 深度优化：**

- `dispatch({ type: "RESET", epoch })` 时，调用上一个 `AbortController.abort()` 取消挂起的 HTTP 请求
- `fetchHeatmap()` 接受 `signal: AbortSignal`，传给 `fetch(url, { signal })`
- WebSocket unsubscribe 与 HTTP abort 同时触发，双向清理
- **收益：** 快速切换市场时，无效请求被浏览器层取消，不占用并发连接，最新请求立即发出

**WebSocket 修正：**

- `useWebSocket` 订阅参数从 `[market]` 修正为 `{ markets: [market] }`，切换市场时先 unsubscribe 旧市场再 subscribe 新市场
- `onReconnect` 回调不再调用 `loadData`，改为 dispatch `RESET` 让状态机驱动

### 三层数据标识

**L1 — 顶部概览条：**

新增 `/api/market-stats` 端点，返回当前市场的标的数、总消息数、活跃来源列表、最新更新时间。Dashboard 渲染概览条。

**L2 — 行级来源标签 + 置信度评分：**

`/api/heatmap` 响应中 `HeatmapItem` 增加：
- `source_count`: 来源数量
- `last_updated`: 最新更新时间
- `confidence_score`: **置信度评分 (0-100)**，综合 source_count 和 last_updated

置信度计算逻辑：
```
confidence = source_score × freshness_score
  source_score = min(source_count / 3, 1.0) × 100   // 3源=满分
  freshness_score = max(0, 1 - hours_since_update / 24)  // 24h内线性衰减
```

渲染规则：
- 置信度 ≥ 70：绿色 "高置信"
- 置信度 40-69：橙色 "中置信"
- 置信度 < 40：红色 "低置信" + 警告图标
- **关键规则：** 如果 mention_count > 热度阈值 (前10) 但 source_count = 1，自动标红并显示 "⚠ 单一源风险" 提示，防止庄家造势/乌龙消息误导

HeatmapTable 新增"来源"列和"置信度"列。

**L3 — 市场选择器状态：**

`/api/market-stats` 返回每个市场的 `status: active | sparse | empty`。市场选择器渲染对应图标：✓ 有数据 / ⚠ 稀疏 / — 无数据（灰显但可选，选中显示 empty 状态页）。

### 改动文件

| 文件 | 改动 |
|------|------|
| `frontend/src/pages/Dashboard.tsx` | useReducer + AbortController 替换 6 个 useState，epoch 竞态防护，概览条渲染，置信度报警 |
| `frontend/src/components/HeatmapTable/index.tsx` | 新增 source_count 列 + confidence_score 列，单一源风险红色警告样式，空状态细分 |
| `frontend/src/services/api.ts` | fetchHeatmap 支持 AbortSignal，新增 fetchMarketStats() |
| `frontend/src/hooks/useWebSocket.ts` | 订阅参数修正，切换市场 unsub/sub |
| `heatmap/web/models.py` | HeatmapItem 增加 source_count, last_updated, confidence_score |
| `heatmap/web/api.py` | /api/heatmap 返回新字段 + 计算置信度，新增 /api/market-stats |
| `heatmap/store/dao.py` | get_rollup_heatmap 返回 source_count，新增 get_market_stats() |

### 验收标准

1. 切换市场时列表立即清空并显示 loading，无旧数据残留
2. 快速切换 A→B→A 市场，最终显示 A 的正确数据，网络面板无堆积的 pending 请求
3. 无数据市场显示 empty 状态，概览条显示 0 标的/0 消息
4. A股行显示 "2源" + 绿色置信度，单源行显示橙色 "1源" + 中/低置信度
5. 高热度+单源标的自动标红 "⚠ 单一源风险"
6. 概览条实时反映当前市场统计

---

## 第二期：多信息源 + 反反爬虫 + 权重归一化 + 熔断

### 新增采集器矩阵（含权重因子与风险提示）

| 市场 | 采集器 | 数据来源 | 类型 | 权重 | 反爬难度 | 核心风险 |
|------|--------|----------|------|------|----------|----------|
| A股 | 同花顺 10jqka | 热榜API + 新闻 | HTTP API | 1.0 | 中 | JS签名加密(hex_export) |
| A股 | 财联社 cls | 电报快讯 | RSS/HTML | 0.8 | 低 | — |
| 港股 | 阿斯达克 aastocks | 热门股票 + 新闻 | HTML解析 | 0.9 | 中 | 动态 class 名 |
| 港股 | 富途牛牛 futu | 社区热议 | 无头浏览器 | 0.7 | 高 | 设备指纹·需 stealth |
| 美股 | Reddit WSB | 热门帖 + 提及 | JSON API | 0.4 | 低 | 噪音极高·需过滤 |
| 美股 | StockTwits | 趋势符号 | HTTP API | 0.6 | 中 | — |
| 币圈 | CoinGecko Trending | 趋势币种 | HTTP API | 0.7 | 低 | — |
| 币圈 | LunarCrush | 社交情绪 | HTTP API | 0.5 | 低 | API频率限制严苛 |

**权重说明：**
- 权重因子 `source_weight ∈ [0.1, 1.0]`，定义在采集器类属性 `SOURCE_WEIGHT`
- 加权热度 = Σ(mention_count × source_weight) 按来源聚合
- API 响应中的 `weighted_score` 使用加权公式替代原始计数
- 权重可配置：在 `config/thresholds.yaml` 中可覆盖默认值

### 各市场技术应对

**A股 — 同花顺 (10jqka)：**
- 检查响应数据是否需要逆向 JS 签名（如 `hex_export` 参数）
- 优先走其公开未加密的 JSONP 接口（如 `stockpage.10jqka.com.cn` 的热榜数据）
- Fallback: 解析 HTML 页面替代 API

**美股 — Reddit WSB：**
- 过滤噪音关键词：`Loss Porn`, `YOLO`, `wife's boyfriend` 等娱乐性帖子
- 聚焦 `DD` (Due Diligence), `Technical Analysis`, `Earnings` 标签帖
- 按 `score` 和 `upvote_ratio` 排序取 top N，丢弃低质量帖

**港股 — 富途牛牛 (Futu)：**
- Playwright 必须开启 `stealth` 插件绕过设备指纹检测
- 模拟真实鼠标轨迹（贝塞尔曲线移动 + 随机停留 + 慢速滚动）
- 注入 fake `navigator.webdriver = false` 和 `chrome.runtime = {}`
- 首次请求先访问首页 → 等待 3-8s → 再导航到目标页

**币圈 — LunarCrush：**
- 优先走其官方公开的微服务接口，避免高频请求主 API
- 严格遵循其 rate limit header (`X-RateLimit-Remaining`)
- 超出限制时自动退避 (exponential backoff)

所有新采集器继承 `HttpCollector`，遵循 `_fetch_posts() → list[dict]` 接口。

### 四层反爬 + 动态降级（含熔断）

**L1: 请求指纹随机化**
- `UserAgentPool`: 20+ 真实浏览器 UA，按平台分类 (Win/Mac/Linux × Chrome/Firefox/Safari)
- `Accept-Language` 与 UA 匹配的 Accept-Language 头
- `Sec-Ch-Ua` 客户端提示品牌版本
- Viewport/屏幕尺寸抖动
- 新文件: `heatmap/collectors/ua_pool.py`

**L2: 人类行为模拟**
- `JitteredDelay`: 请求间隔 = poll_interval × random(0.7, 1.3)，模拟人类阅读节奏
- `CookieJar`: 按域名持久化 Cookie (SQLite)，跨请求复用会话
- `ReferrerChain`: 自动构建来源链 (google.com → 站内导航 → 目标页)
- 新文件: `heatmap/collectors/jitter.py`

**L3: 无头浏览器降级**
- Playwright Chromium headful 模式 + stealth 插件
- 随机窗口尺寸，贝塞尔曲线鼠标移动，慢速滚动，随机停留
- 仅在 L1/L2 连续失败 3 次后触发，单次成功则重置失败计数
- 每个采集器可配置 `browser_fallback: bool` 开关
- 新文件: `heatmap/collectors/browser_fallback.py`

**L4: 代理池增强 + 熔断协议**
- 在现有 `ProxyPool` 基础上增加：
  - 按域名独立冷却时间
  - 自动健康检查（定期探测代理可用性）
  - **熔断器 (CircuitBreaker):** 当代理池可用率 < 20% 且持续时间 > 2min，触发熔断
    - 全局采集器休眠 15-30 分钟（可配置）
    - 休眠期间仅记录日志，不做任何出站请求
    - 休眠结束后先探测 1 个代理，成功则恢复，失败则继续休眠
    - **收益：** 避免代理段被整体拉黑时死循环重试，保护代理成本和服务器负载
- 修改文件: `heatmap/collectors/proxy_pool.py`
- 新文件: `heatmap/collectors/circuit_breaker.py`

### 数据归一化：加权热度评分

**Source Weight 系统：**
- 每个 `HttpCollector` 子类定义 `SOURCE_WEIGHT: float` 类属性
- `QueuedMessage` 新增 `source_weight` 字段
- `BatchWriter` 写入时携带权重
- Rollup 聚合公式变更：
  ```
  weighted_score = Σ(mention_count_i × source_weight_i) / Σ(source_weight_i)
  ```
  即来源加权平均，而非简单的 mention_count 之和
- `get_rollup_heatmap` 返回 `weighted_score`（已修改），`mention_count` 保留原始值供参考

**权重配置表（默认值，可在 thresholds.yaml 覆盖）：**

```yaml
source_weights:
  xueqiu: 0.9          # 雪球 — 投资者社区，质量高
  eastmoney: 0.7       # 东方财富 — 散户集中，噪声中等
  10jqka: 1.0          # 同花顺 — 热榜官方数据，权重最高
  cls: 0.8             # 财联社 — 专业财经媒体
  aastocks: 0.9        # 阿斯达克 — 港股权威
  futu: 0.7            # 富途 — 社区UGC
  reddit: 0.4          # Reddit — 噪音极高，娱乐性强
  stocktwits: 0.6      # StockTwits — 交易者社区
  coingecko: 0.7       # CoinGecko — 数据驱动
  lunarcrush: 0.5      # LunarCrush — 社交媒体聚合
```

### HttpCollector 基类增强

`_request()` 方法集成：
1. `self.ua_pool.random()` 获取 UA
2. `self.cookie_jar.load(domain)` 加载会话
3. `self.cookie_jar.inject_referrer(domain)` 构建 Referrer
4. `self.jitter.wait(domain)` 抖动延迟
5. 请求前检查 `circuit_breaker.allow_request()` 熔断状态
6. 请求失败 → 上报 proxy_pool → L3 降级尝试 / 熔断判断

`_poll_once()` 增强：
- 构建 `QueuedMessage` 时携带 `self.SOURCE_WEIGHT`

### scheduler.py 注册

在 `serve()` 中按 `sources.yaml` 配置条件注册所有新采集器，每个采集器传入正确的 `market` 参数。初始化全局 `CircuitBreaker` 并注入到每个采集器。

### 改动文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `heatmap/collectors/ua_pool.py` | 新增 | UA池 + 请求头匹配 |
| `heatmap/collectors/jitter.py` | 新增 | 延迟抖动 + Cookie管理 + Referrer链 |
| `heatmap/collectors/browser_fallback.py` | 新增 | Playwright stealth 无头浏览器降级 |
| `heatmap/collectors/circuit_breaker.py` | 新增 | 熔断器：代理池可用率监控 + 自动休眠/唤醒 |
| `heatmap/collectors/http_base.py` | 修改 | 集成四层反爬 + 熔断检查 + SOURCE_WEIGHT |
| `heatmap/collectors/proxy_pool.py` | 修改 | 按域名冷却 + 健康检查 + 可用率统计 |
| `heatmap/store/dao.py` | 修改 | QueuedMessage + source_weight，Rollup 加权公式 |
| `heatmap/store/writer.py` | 修改 | BatchWriter 携带 source_weight |
| `heatmap/collectors/10jqka.py` | 新增 | 同花顺采集器 (优先 JSONP, fallback HTML) |
| `heatmap/collectors/cls.py` | 新增 | 财联社采集器 |
| `heatmap/collectors/aastocks.py` | 新增 | 阿斯达克采集器 |
| `heatmap/collectors/futu.py` | 新增 | 富途牛牛采集器 (Playwright + stealth) |
| `heatmap/collectors/reddit.py` | 新增 | Reddit WSB采集器 (噪音过滤 + DD标签) |
| `heatmap/collectors/stocktwits.py` | 新增 | StockTwits采集器 |
| `heatmap/collectors/coingecko.py` | 新增 | CoinGecko采集器 |
| `heatmap/collectors/lunarcrush.py` | 新增 | LunarCrush采集器 (微服务接口 + backoff) |
| `heatmap/scheduler.py` | 修改 | 注册所有采集器 + 初始化 CircuitBreaker |
| `config/thresholds.yaml` | 修改 | source_weights 配置 + 熔断参数 + 各源限速 |
| `config/sources.yaml` | 修改 | 新源开关与配置 (API key, channel等) |

### 验收标准

1. 港股/美股/币圈市场有数据展示，概览条显示 ≥1 来源
2. 同花顺/阿斯达克/Reddit 等 API 类采集器稳定轮询
3. 富途牛牛通过 Playwright + stealth 成功获取数据
4. L1/L2 反爬对所有新采集器生效
5. 同一代理连续失败 3 次后进入冷却
6. 代理池可用率 < 20% 时触发熔断，采集器休眠 15-30 分钟
7. 熔断结束后自动探测恢复
8. Reddit 采集器过滤掉 Loss Porn/YOLO 等噪音帖
9. weighted_score 反映来源权重差异（同花顺 > Reddit）
10. 高热度+单源标的前端标红警告

---

## 测试策略

### 第一期

- **单元测试**: Dashboard reducer 纯函数测试（状态流转 + epoch 竞态 + AbortController 取消）
- **单元测试**: 置信度计算函数 (source_score × freshness_score)
- **组件测试**: HeatmapTable source_count/confidence 列渲染，单一源风险警告样式，empty/loading/data 状态快照
- **集成测试**: API /api/heatmap 返回 source_count + confidence_score，/api/market-stats 返回统计

### 第二期

- **单元测试**: UA池随机性、CookieJar 存取、Jitter 范围、CircuitBreaker 状态转换、权重计算
- **集成测试**: 每个新采集器 `_fetch_posts()` 返回正确结构
- **冒烟测试**: 完整 pipeline 运行 1 个周期，验证加权 rollup + 多源数据入库
- **压力测试**: 模拟代理大面积失效 → 验证熔断触发与恢复
