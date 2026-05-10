# Market Heatmap v2 — 两期改进设计

**日期:** 2026-05-10
**分支:** `heat_factor_judgment`
**状态:** 已确认

---

## 概述

针对演示中发现的四个问题：市场切换列表混乱、数据状态不透明、信息源单一、反爬虫薄弱，分两期推进。

| 期次 | 目标 | 新增文件 | 修改文件 |
|------|------|----------|----------|
| 第一期 | UI状态重构 + 数据透明 | 0 | 6 |
| 第二期 | 多信息源 + 反反爬虫 | 11 | 4 |

---

## 第一期：UI 状态重构 + 数据透明

### 问题根因

`Dashboard.tsx` 用 6 个零散 `useState` 管理状态，`useCallback` 闭包捕获陈旧值，市场切换时 WebSocket 订阅与 HTTP 请求产生竞态：旧请求的响应可能覆盖新市场的数据。

### 方案：useReducer 状态机

**状态定义：**

```
state: idle | loading | data | empty | error | loading_more
```

**状态流转：**

- 市场/粒度切换 → `dispatch({ type: "RESET", epoch })` → 自动触发 `LOAD`
- `LOAD` → `loading`，请求成功且有数据 → `data`，请求成功无数据 → `empty`，请求失败 → `error`
- `LOAD_MORE`（翻页）→ `loading_more`，保留现有 items
- 每个 action 携带 `epoch`，reducer 忽略过期 epoch 的响应，根除竞态

**WebSocket 修正：**

- `useWebSocket` 订阅参数从 `[market]` 修正为 `{ markets: [market] }`，切换市场时先 unsubscribe 旧市场再 subscribe 新市场
- `onReconnect` 回调不再调用 `loadData`，改为 dispatch `RESET` 让状态机驱动

### 三层数据标识

**L1 — 顶部概览条：**

新增 `/api/market-stats` 端点，返回当前市场的标的数、总消息数、活跃来源列表、最新更新时间。Dashboard 渲染概览条。

**L2 — 行级来源标签：**

`/api/heatmap` 响应中 `HeatmapItem` 增加 `source_count` 和 `last_updated` 字段。HeatmapTable 新增"来源"列，显示 `N源` 标签（1源橙色警告，2+源绿色正常）。数据稀疏行（mention_count < 阈值）灰显。

**L3 — 市场选择器状态：**

`/api/market-stats` 返回每个市场的 `status: active | sparse | empty`。市场选择器渲染对应图标：✓ 有数据 / ⚠ 稀疏 / — 无数据（灰显但可选，选中显示 empty 状态页）。

### 改动文件

| 文件 | 改动 |
|------|------|
| `frontend/src/pages/Dashboard.tsx` | useReducer 替换 6 个 useState，epoch 竞态防护，概览条渲染 |
| `frontend/src/components/HeatmapTable/index.tsx` | 新增 source_count 列，数据稀疏行样式，空状态细分 |
| `frontend/src/services/api.ts` | 新增 fetchMarketStats() |
| `heatmap/web/models.py` | HeatmapItem 增加 source_count, last_updated |
| `heatmap/web/api.py` | /api/heatmap 返回新字段，新增 /api/market-stats |
| `heatmap/store/dao.py` | get_rollup_heatmap 返回 source_count，新增 get_market_stats() |

### 验收标准

1. 切换市场时列表立即清空并显示 loading，无旧数据残留
2. 快速切换 A→B→A 市场，最终显示 A 的正确数据
3. 无数据市场显示 empty 状态，概览条显示 0 标的/0 消息
4. A股行显示 "2源"，单源行显示橙色 "1源"
5. 概览条实时反映当前市场统计

---

## 第二期：多信息源 + 反反爬虫

### 新增采集器矩阵

| 市场 | 采集器 | 数据来源 | 类型 | 反爬难度 |
|------|--------|----------|------|----------|
| A股 | 同花顺 10jqka | 热榜API + 新闻 | HTTP API | 中 |
| A股 | 财联社 cls | 电报快讯 | RSS/HTML | 低 |
| 港股 | 阿斯达克 aastocks | 热门股票 + 新闻 | HTML解析 | 中 |
| 港股 | 富途牛牛 futu | 社区热议 | 无头浏览器 | 高 |
| 美股 | Reddit WSB | 热门帖 + 提及 | JSON API | 低 |
| 美股 | StockTwits | 趋势符号 | HTTP API | 中 |
| 币圈 | CoinGecko Trending | 趋势币种 | HTTP API | 低 |
| 币圈 | LunarCrush | 社交情绪 | HTTP API | 低 |

所有新采集器继承 `HttpCollector`，遵循 `_fetch_posts() → list[dict]` 接口。

### 四层反爬架构

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
- Playwright Chromium headful 模式
- 随机窗口尺寸，慢速滚动，随机停留
- 仅在 L1/L2 连续失败 3 次后触发
- 每个采集器可配置 `browser_fallback: bool` 开关
- 新文件: `heatmap/collectors/browser_fallback.py`

**L4: 代理池增强**
- 在现有 `ProxyPool` 基础上增加：
  - 按域名独立冷却时间
  - 自动健康检查（定期探测代理可用性）
  - 从 `config/proxies.yaml` 加载代理列表
- 修改文件: `heatmap/collectors/proxy_pool.py`

### HttpCollector 基类增强

`_request()` 方法集成：
1. `self.ua_pool.random()` 获取 UA
2. `self.cookie_jar.load(domain)` 加载会话
3. `self.cookie_jar.inject_referrer(domain)` 构建 Referrer
4. `self.jitter.wait(domain)` 抖动延迟
5. 请求失败 → 上报 proxy_pool → L3 降级尝试

现有子类（雪球/东方财富）无需改动，新能力通过基类自动继承。

### scheduler.py 注册

在 `serve()` 中按 `sources.yaml` 配置条件注册所有新采集器，每个采集器传入正确的 `market` 参数。

### 改动文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `heatmap/collectors/ua_pool.py` | 新增 | UA池 + 请求头匹配 |
| `heatmap/collectors/jitter.py` | 新增 | 延迟抖动 + Cookie管理 |
| `heatmap/collectors/browser_fallback.py` | 新增 | Playwright 无头浏览器降级 |
| `heatmap/collectors/http_base.py` | 修改 | 集成四层反爬能力 |
| `heatmap/collectors/proxy_pool.py` | 修改 | 按域名冷却 + 健康检查 |
| `heatmap/collectors/10jqka.py` | 新增 | 同花顺采集器 |
| `heatmap/collectors/cls.py` | 新增 | 财联社采集器 |
| `heatmap/collectors/aastocks.py` | 新增 | 阿斯达克采集器 |
| `heatmap/collectors/futu.py` | 新增 | 富途牛牛采集器 (Playwright) |
| `heatmap/collectors/reddit.py` | 新增 | Reddit WSB采集器 |
| `heatmap/collectors/stocktwits.py` | 新增 | StockTwits采集器 |
| `heatmap/collectors/coingecko.py` | 新增 | CoinGecko采集器 |
| `heatmap/collectors/lunarcrush.py` | 新增 | LunarCrush采集器 |
| `heatmap/scheduler.py` | 修改 | 注册所有新采集器 |
| `config/thresholds.yaml` | 修改 | 各源限速 + 代理配置 |
| `config/sources.yaml` | 修改 | 新源开关与配置 |

### 验收标准

1. 港股/美股/币圈市场有数据展示，概览条显示 ≥1 来源
2. 同花顺/阿斯达克/Reddit 等 API 类采集器稳定轮询
3. 富途牛牛通过 Playwright 成功获取数据
4. L1/L2 反爬对所有新采集器生效
5. 模拟被封 IP 场景：同一代理连续失败 3 次后进入冷却
6. 无头浏览器降级：HTTP 请求 3 连败后自动切换 Playwright 并成功

---

## 测试策略

### 第一期

- **单元测试**: Dashboard reducer 纯函数测试（各状态流转 + epoch 竞态）
- **组件测试**: HeatmapTable source_count 列渲染，empty/loading/data 状态快照
- **集成测试**: API /api/heatmap 返回 source_count，/api/market-stats 返回统计

### 第二期

- **单元测试**: UA池随机性、CookieJar 存取、Jitter 范围
- **集成测试**: 每个新采集器 `_fetch_posts()` 返回正确结构
- **冒烟测试**: 完整 pipeline 运行 1 个周期，验证数据入库
