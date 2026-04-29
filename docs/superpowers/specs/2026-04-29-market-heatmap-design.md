# 市场热度信息收集系统 — 设计文档

> 日期：2026-04-29  
> 状态：已批准

## 1. 概述

构建一个基本面信息收集系统，每日从主流社交媒体和论坛采集指定市场（A 股/港股/美股/币圈）的标的讨论热度，通过多维加权模型计算综合热度分，与前一日做环比对比，筛选出热度激增的 Top 10 标的，并将结果输出到飞书（多维表格 + 文档）。

## 2. 运行方式

- **手动 CLI 触发**：`python main.py --market A股 [--date 2026-04-29]`
- **定时自动化**：通过 cron 每日固定时间运行

## 3. 技术栈

- 语言：Python 3.11+
- 异步采集：asyncio + aiohttp + playwright（JS 渲染页面）
- 中文情感分析：SnowNLP
- 英文情感分析：TextBlob / VADER
- 数据处理：pandas
- 本地存储：SQLite
- 飞书输出：lark-cli（Bitable + Docx）
- 优先使用免费/开放数据源

## 4. 整体架构

```
┌─────────────────────────────────────────────────┐
│                   CLI 入口                       │
│  python main.py --market A股 [--date 2026-04-29]│
└──────────────┬──────────────────────────────────┘
               │
       ┌───────▼────────┐
       │  Market Router  │  根据市场选择对应的采集器组合
       └───────┬────────┘
               │
    ┌──────────▼──────────┐
    │  Collector Layer     │  asyncio 并发采集（插件式）
    └──────────┬──────────┘
               │  原始数据（帖子数/互动量/情绪/KOL标记）
    ┌──────────▼──────────┐
    │  Analyzer Layer      │  热度计算 + 日环比 + 排名
    └──────────┬──────────┘
               │  Top 10 结果
    ┌──────────▼──────────┐
    │  Storage Layer       │  SQLite 持久化历史数据
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │  Publisher Layer     │  飞书 Bitable + Doc 输出
    │  (lark-cli)          │
    └─────────────────────┘
```

数据流：CLI 入口 → 路由到市场对应平台 → 并发采集原始数据 → 分析计算热度分 → 存入 SQLite → 输出到飞书。

## 5. 采集器插件系统

### 5.1 统一接口

每个采集器实现 `BaseCollector` 抽象类：

```python
class BaseCollector(ABC):
    market: str          # "A股" / "港股" / "美股" / "币圈"
    platform: str        # "xueqiu" / "reddit" / ...

    async def collect(self, date: date) -> list[RawMention]:
        """采集某日该平台上的标的提及数据"""

class RawMention:
    symbol: str          # 标的代码/名称
    post_count: int      # 帖子/提及数
    comment_count: int   # 评论数
    like_count: int      # 点赞数
    share_count: int     # 转发数
    sentiment_score: float  # 情绪分 (-1 ~ 1)
    is_kol: bool         # 是否来自 KOL/大V
    source_url: str      # 来源链接
```

### 5.2 市场-平台映射

```yaml
A股:
  collectors: [xueqiu, eastmoney, tonghuashun, weibo_finance, baidu_index]
  symbol_pattern: "中文名称 / 6位代码"
港股:
  collectors: [xueqiu_hk, futu, eastmoney_hk, weibo_finance]
  symbol_pattern: "5位代码 / 中文名称"
美股:
  collectors: [reddit_wsb, reddit_stocks, twitter_cashtag, stocktwits, google_trends]
  symbol_pattern: "ticker symbol"
币圈:
  collectors: [twitter_crypto, reddit_crypto, coingecko, telegram_crypto, weibo_crypto]
  symbol_pattern: "token symbol"
```

### 5.3 采集策略

- 用 aiohttp 做并发 HTTP 采集，playwright 处理需要 JS 渲染的页面
- 每个采集器内置频率限制（rate limiter），避免被封
- 失败重试 3 次，单个平台失败不影响其他平台
- 标的名称标准化：用 symbol_mapping 表统一别名为标准名称

## 6. 热度分析引擎

### 6.1 热度计算公式

```
H_score = w1·P + w2·C + w3·L + w4·S + w5·|Sent| + w6·K
```

| 变量 | 含义 | 默认权重 |
|------|------|---------|
| P | 帖子/提及数（归一化） | 0.25 |
| C | 评论数（归一化） | 0.20 |
| L | 点赞数（归一化） | 0.15 |
| S | 转发数（归一化） | 0.15 |
| \|Sent\| | 情绪强度（取绝对值） | 0.10 |
| K | KOL 加权因子（KOL 帖子 ×3） | 0.15 |

- 所有原始指标按当日全市场 min-max 归一化到 [0, 1]
- 权重可在 `config/weights.yaml` 中调整
- 多平台数据按平台权重加权合并

### 6.2 日环比计算

```
Δ% = (H_today - H_yesterday) / H_yesterday × 100%
```

### 6.3 筛选逻辑

1. 计算当日所有标的的热度分
2. 计算全市场平均热度 H_avg
3. 筛选条件：H_score > H_avg 且 Δ% > 0
4. 按 Δ% 降序排列，取 Top 10

### 6.4 情感分析

- A 股/港股：SnowNLP（中文，轻量免费）
- 美股/币圈：TextBlob / VADER（英文）
- 不引入大模型，保持轻量

## 7. 存储层（SQLite）

单数据库 `data/heatmap.db`，用 `market` 字段区分不同市场。

### 7.1 表结构

```sql
-- 每日标的热度原始数据
CREATE TABLE daily_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    platform TEXT NOT NULL,
    post_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    sentiment_score REAL DEFAULT 0,
    kol_mention_count INTEGER DEFAULT 0,
    UNIQUE(date, market, symbol, platform)
);

-- 每日标的综合热度得分
CREATE TABLE daily_heatmap (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    heat_score REAL NOT NULL,
    prev_heat_score REAL,
    change_pct REAL,
    market_avg_score REAL,
    rank INTEGER,
    top_source TEXT,
    sentiment_avg REAL,
    UNIQUE(date, market, symbol)
);

-- 标的名称映射表
CREATE TABLE symbol_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    alias TEXT NOT NULL,
    UNIQUE(market, alias)
);
```

## 8. 飞书输出层

每个市场独立存放，互不干扰。

### 8.1 多维表格（Bitable）

每个市场单独一张多维表格（如 `A股市场热度追踪`），字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 日期 | 日期 | 采集日期 |
| 标的 | 文本 | 标准化名称 |
| 热度分 | 数字 | 综合热度得分 |
| 日环比 | 数字(%) | 较前日变化百分比 |
| 市场均值 | 数字 | 当日市场平均热度 |
| 超均幅度 | 数字(%) | (热度分-均值)/均值 |
| 情绪倾向 | 单选 | 正面/中性/负面 |
| 热度来源 | 文本 | 主要来源平台 |
| 排名 | 数字 | 当日排名 |

每次运行追加当日新记录。

### 8.2 文档（Docx）

每个市场单独一份文档（如 `A股市场热度日报`）。

文档结构（最新日期在最上面）：

```
# A股市场热度日报

## 2026-04-29 热度报告

📊 今日市场概况
- 采集平台：雪球、东方财富、同花顺、微博、百度指数
- 市场平均热度：42.3
- 热度激增标的数：23 个

🔥 Top 10 热度激增标的

| 排名 | 标的 | 热度分 | 日环比 | 超均幅度 | 情绪 | 主要来源 |
|------|------|--------|--------|----------|------|---------|
| 1 | XX科技 | 89.2 | +156% | +110% | 正面 | 雪球 |
| ... | ... | ... | ... | ... | ... | ... |

💡 关键洞察
- 基于数据特征自动生成的简要分析
```

### 8.3 飞书操作逻辑

- **首次运行**：用 lark-cli 创建 Bitable + Doc，记录文档 token 到 `config/lark_docs.yaml`
- **后续运行**：读取已存 token，在 Bitable 追加记录 + 在 Doc 头部插入新日期章节

本地配置 `config/lark_docs.yaml`：

```yaml
A股:
  bitable_token: "xxx"
  bitable_table_id: "xxx"
  doc_token: "xxx"
港股:
  bitable_token: "xxx"
  bitable_table_id: "xxx"
  doc_token: "xxx"
美股:
  bitable_token: "xxx"
  bitable_table_id: "xxx"
  doc_token: "xxx"
币圈:
  bitable_token: "xxx"
  bitable_table_id: "xxx"
  doc_token: "xxx"
```

## 9. 项目结构

```
market-heatmap/
├── main.py                    # CLI 入口
├── config/
│   ├── markets.yaml           # 市场-平台映射
│   ├── weights.yaml           # 热度权重配置
│   └── lark_docs.yaml         # 飞书文档 token（运行时生成）
├── collectors/
│   ├── __init__.py
│   ├── base.py                # BaseCollector 抽象类 + RawMention 数据类
│   ├── xueqiu.py              # 雪球采集器
│   ├── eastmoney.py           # 东方财富股吧采集器
│   ├── tonghuashun.py         # 同花顺社区采集器
│   ├── weibo_finance.py       # 微博财经采集器
│   ├── baidu_index.py         # 百度指数采集器
│   ├── xueqiu_hk.py           # 雪球港股采集器
│   ├── futu.py                # 富途牛牛采集器
│   ├── eastmoney_hk.py        # 东方财富港股采集器
│   ├── reddit_wsb.py          # Reddit WSB 采集器
│   ├── reddit_stocks.py       # Reddit r/stocks 采集器
│   ├── twitter_cashtag.py     # Twitter $cashtag 采集器
│   ├── stocktwits.py          # StockTwits 采集器
│   ├── google_trends.py       # Google Trends 采集器
│   ├── twitter_crypto.py      # Twitter 加密货币采集器
│   ├── reddit_crypto.py       # Reddit 加密货币采集器
│   ├── coingecko.py           # CoinGecko 采集器
│   └── telegram_crypto.py     # Telegram 加密货币采集器
├── analyzers/
│   ├── __init__.py
│   ├── heat_calculator.py     # 热度计算引擎
│   ├── sentiment.py           # 情感分析（中/英文）
│   └── symbol_normalizer.py   # 标的名称标准化
├── storage/
│   ├── __init__.py
│   └── db.py                  # SQLite 操作封装
├── publishers/
│   ├── __init__.py
│   ├── lark_bitable.py        # 飞书多维表格输出
│   └── lark_doc.py            # 飞书文档输出
├── data/
│   └── heatmap.db             # SQLite 数据库（运行时生成）
├── requirements.txt
└── README.md
```

## 10. 错误处理

- 单个采集器失败：记录日志，跳过该平台，继续其他平台采集
- 全部采集器失败：终止运行，报错退出
- 飞书 API 失败：重试 3 次，仍失败则将结果输出到本地 JSON 作为备份
- 首日运行无前日数据：日环比标记为 "N/A"，不参与 Δ% 排序，仅按绝对热度排序

## 11. 定时任务配置

推荐 crontab 配置示例：

```bash
# A股：每个交易日 20:00 运行（收盘后留充分时间让讨论沉淀）
0 20 * * 1-5 cd /path/to/market-heatmap && python main.py --market A股

# 美股：每个交易日北京时间 10:00 运行（美股收盘后）
0 10 * * 2-6 cd /path/to/market-heatmap && python main.py --market 美股

# 币圈：每天 09:00 运行（24h 市场）
0 9 * * * cd /path/to/market-heatmap && python main.py --market 币圈
```
