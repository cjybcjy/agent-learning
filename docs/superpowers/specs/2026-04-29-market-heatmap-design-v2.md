# 市场热度与情绪异动收集系统 (Project "Sentinel") — 设计文档

> 日期：2026-04-29  
> 状态：Review 修改版（专家评审后重构）

## 1. 概述

构建一个高频基本面与情绪异动收集系统，从主流金融社区及社交媒体采集指定市场（A 股/港股/美股/币圈）的标的讨论数据。通过金融专属 NLP 模型与反作弊加权机制，计算多维综合热度分及情绪方向。输出日环比及盘中异动 Top 10 标的，将结果推送至飞书，为量化策略提供低延迟的情绪 Alpha 和风险预警。

## 2. 运行方式

- **手动 CLI 触发**：`python main.py --market A股 [--datetime 2026-04-29T10:00:00]`
- **盘中高频监控**：`python main.py --market A股`（按交易时段小时级调度）
- **日终汇总报告**：`python main.py --market A股 --report daily`
- **盘前扫描**：`python main.py --market 美股 --time pre-market`
- **定时自动化**：通过 cron / Airflow 实现盘中高频与盘后日终汇总

## 3. 技术栈

- 语言：Python 3.11+
- 异步采集：asyncio + aiohttp + playwright（动态渲染）
- NLP 引擎：FinBERT（英文金融语境）/ FinBERT-zh（中文金融语境），通过 ONNX Runtime + INT8 动态量化部署，CPU 批量推理
- 数据处理：pandas + numpy
- 本地存储：DuckDB（嵌入式列存，零运维，向量化执行引擎，OLAP 分析型查询最优）
- 飞书输出：lark-cli（Bitable + Docx）
- 优先使用免费/开放数据源

## 4. 整体架构

```
┌─────────────────────────────────────────────────────┐
│                   CLI / 调度入口                     │
│  python main.py --market A股 [--datetime ...] [--report daily] │
└──────────────┬──────────────────────────────────────┘
               │
       ┌───────▼────────┐
       │  Market Router  │  路由到对应市场的并发采集器
       └───────┬────────┘
               │
    ┌──────────▼──────────┐
    │  Collector Layer     │  asyncio 并发采集 + 反爬处理
    └──────────┬──────────┘
               │  原始数据
    ┌──────────▼──────────┐
    │  Anti-Spam Layer     │  过滤水军/重复刷榜帖（去重、账户活跃度验证）
    └──────────┬──────────┘
               │  净数据
    ┌──────────▼──────────┐
    │  Analyzer Layer      │  FinBERT 情绪判别 + 热度计算 + 排名
    └──────────┬──────────┘
               │  Top 10 异动结果（看多 + 看空）
    ┌──────────▼──────────┐
    │  Storage Layer       │  DuckDB 持久化（时序存储）
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │  Publisher Layer     │  飞书 Bitable + Doc 自动化报告
    └─────────────────────┘
```

数据流：CLI/调度入口 → 路由到市场对应平台 → 并发采集原始数据 → 反作弊过滤 → FinBERT 情绪分析 + 热度计算 → 存入 DuckDB → 输出到飞书。

## 5. 采集器插件系统

### 5.1 统一接口

每个采集器实现 `BaseCollector` 抽象类：

```python
class BaseCollector(ABC):
    market: str          # "A股" / "港股" / "美股" / "币圈"
    platform: str        # "xueqiu" / "reddit" / ...

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        """采集指定时间窗口内该平台上的标的提及数据"""

@dataclass
class RawMention:
    symbol: str              # 标的代码/名称
    post_count: int          # 帖子/提及数
    comment_count: int       # 评论数
    like_count: int          # 点赞数
    share_count: int         # 转发数
    raw_text: str            # 原始帖子文本（供 FinBERT 分析）
    is_kol: bool             # 是否来自 KOL/大V（白名单匹配）
    account_age_days: int    # 发帖账号注册天数
    account_followers: int   # 发帖账号粉丝数
    source_url: str          # 来源链接
    post_time: datetime      # 发帖时间
```

### 5.2 市场-平台映射

```yaml
A股:
  collectors: [xueqiu, eastmoney, tonghuashun, weibo_finance, baidu_index]
  platform_weights: {xueqiu: 0.30, eastmoney: 0.25, tonghuashun: 0.20, weibo_finance: 0.15, baidu_index: 0.10}
  symbol_pattern: "中文名称 / 6位代码"
港股:
  collectors: [xueqiu_hk, futu, eastmoney_hk, weibo_finance]
  platform_weights: {xueqiu_hk: 0.30, futu: 0.30, eastmoney_hk: 0.25, weibo_finance: 0.15}
  symbol_pattern: "5位代码 / 中文名称"
美股:
  collectors: [reddit_wsb, reddit_stocks, twitter_cashtag, stocktwits, google_trends]
  platform_weights: {reddit_wsb: 0.25, reddit_stocks: 0.20, twitter_cashtag: 0.25, stocktwits: 0.20, google_trends: 0.10}
  symbol_pattern: "ticker symbol"
币圈:
  collectors: [twitter_crypto, reddit_crypto, coingecko, telegram_crypto, weibo_crypto]
  platform_weights: {twitter_crypto: 0.30, reddit_crypto: 0.20, coingecko: 0.20, telegram_crypto: 0.15, weibo_crypto: 0.15}
  symbol_pattern: "token symbol"
```

### 5.3 采集策略

- 用 aiohttp 做并发 HTTP 采集，playwright 处理需要 JS 渲染的页面
- 每个采集器内置频率限制（rate limiter），避免被封
- 失败重试 3 次，单个平台失败不影响其他平台
- 标的名称标准化：用 symbol_mapping 表统一别名为标准名称
- weibo_finance 采集器被 A 股和港股共用，内部根据 market 参数筛选不同话题标签
- 采集时间窗口：每次采集获取自上一次采集以来的新帖子（增量采集）

### 5.4 反作弊与降噪策略（Anti-Spam Layer）

- **账号过滤**：忽略注册时间 < 30 天、粉丝数 < 10 的账号发帖
- **去重**：同一账号在 1 小时内对同一标的的重复提及只计 1 次
- **KOL 白名单**：通过预设白名单（`config/kol_whitelist.yaml`）判定 KOL 身份，而非简单的粉丝阈值
- **异常检测**：单个标的在单小时内来自同一平台的提及数超过 3σ（标准差）时，标记为可疑并降权

## 6. 热度分析引擎（重构版）

**核心改进**：将原版的"情绪绝对值加法模型"重构为"基础热度 × 情绪方向"的乘积模型，解决 |Sent| 混淆多空的致命缺陷。

### 6.1 综合热度与情绪得分公式

**基础热度 (Volume Heat)**：

$$V_{base} = w_1 \cdot P_{norm} + w_2 \cdot C_{norm} + w_3 \cdot L_{norm} + w_4 \cdot S_{norm}$$

| 变量 | 含义 | 默认权重 |
|------|------|---------|
| $P_{norm}$ | 帖子/提及数（归一化） | 0.35 |
| $C_{norm}$ | 评论数（归一化） | 0.30 |
| $L_{norm}$ | 点赞数（归一化） | 0.20 |
| $S_{norm}$ | 转发数（归一化） | 0.15 |

**KOL 放大器 (KOL Multiplier)**：

$$M_{kol} = 1 + \left( w_k \cdot \frac{K_{mentions}}{P_{total}} \right)$$

- $K_{mentions}$：KOL 白名单内账号的提及次数
- $P_{total}$：总帖子数
- $w_k$：KOL 放大系数，默认 3.0

**最终有效情绪热度 (Directed Heat Score)**：

$$H_{score} = (V_{base} \cdot M_{kol}) \times Sent_{fin}$$

- $Sent_{fin}$：FinBERT 输出的情绪得分，范围 $[-1.0, 1.0]$
  - 负数 → 看空/恐慌
  - 正数 → 看多/乐观
  - 接近 0 → 中性/震荡

**关键特性**：$H_{score}$ 保留正负号，正值表示看多热度、负值表示看空热度，信号方向清晰。

- 所有原始指标按当日全市场 min-max 归一化到 [0, 1]
- 权重可在 `config/weights.yaml` 中调整
- 多平台数据合并方式：同一标的在不同平台的数据先按平台权重加权求和，再输入热度公式

### 6.2 环比变动计算

$$\Delta\% = \frac{|H_{current}| - |H_{prev}|}{|H_{prev}|} \times 100\%$$

使用绝对值做环比，衡量"关注度变化幅度"，方向信息由 $H_{score}$ 的正负号承载。

### 6.3 异动筛选逻辑

1. 计算时间窗口内所有标的的 $H_{score}$
2. **微盘股过滤**：剔除流动性极差的标的（通过外部接口过滤市值低于阈值的标的，A 股默认 50 亿以下，可配置），避免被杀猪盘误导
3. **双榜输出**：
   - **看多热度激增 Top 10**：$H_{score} > 0$ 且 $\Delta\%$ 最大
   - **看空热度激增 Top 10**：$H_{score} < 0$ 且 $|\Delta\%|$ 最大（用于黑天鹅预警）
4. 首次运行无历史数据时，按 $|H_{score}|$ 绝对值排序

### 6.4 情感分析引擎

- **英文**：FinBERT（`ProsusAI/finbert`），金融语境预训练，能正确识别 "bearish"、"short squeeze"、"sell-off" 等金融术语
- **中文**：FinBERT-zh（`yiyanghkust/finbert-tone` 或同等中文金融 BERT），能正确识别 "大跳水"、"杀估值"、"利空出尽" 等中文金融黑话
- **部署方式**：
  - 模型导出为 ONNX 格式
  - INT8 动态量化降低内存占用
  - ONNX Runtime CPU 推理，利用 SIMD 指令集加速
  - 批量推理：将文本打包为固定大小 Batch（默认 batch_size=64），单条推理延迟压缩至 ~10ms
  - 预计整体延迟：2000 条帖子 ≈ 10-15 秒（CPU），远低于小时级调度容忍窗口

## 7. 存储层（DuckDB）

单数据库文件 `data/sentinel.duckdb`，嵌入式列存，零运维。

### 7.1 表结构

```sql
-- 每次采集的原始净数据（反作弊过滤后）
CREATE TABLE raw_mentions (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,   -- 采集触发时间（支持盘中高频）
    market VARCHAR(20) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    platform VARCHAR(50) NOT NULL,
    post_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    sentiment_score REAL DEFAULT 0, -- FinBERT 情绪分
    kol_mention_count INTEGER DEFAULT 0,
    spam_filtered_count INTEGER DEFAULT 0, -- 被过滤的水军帖数
    UNIQUE(timestamp, market, symbol, platform)
);

-- 每次采集的综合热度得分
CREATE TABLE heat_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    market VARCHAR(20) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    base_heat REAL NOT NULL,          -- 基础热度 V_base
    kol_multiplier REAL NOT NULL,     -- KOL 放大器 M_kol
    sentiment_score REAL NOT NULL,    -- FinBERT 情绪分 Sent_fin
    directed_heat REAL NOT NULL,      -- 最终有效情绪热度 H_score
    prev_directed_heat REAL,          -- 上一周期 H_score
    change_pct REAL,                  -- 环比变动 %
    rank_bullish INTEGER,             -- 看多排名
    rank_bearish INTEGER,             -- 看空排名
    top_source VARCHAR(50),           -- 热度最高来源平台
    is_anomaly BOOLEAN DEFAULT FALSE, -- 异动标记
    UNIQUE(timestamp, market, symbol)
);

-- 标的名称映射表
CREATE TABLE symbol_mapping (
    id INTEGER PRIMARY KEY,
    market VARCHAR(20) NOT NULL,
    canonical_name VARCHAR(100) NOT NULL,
    alias VARCHAR(100) NOT NULL,
    UNIQUE(market, alias)
);

-- 标的基础信息（用于微盘股过滤）
CREATE TABLE symbol_info (
    id INTEGER PRIMARY KEY,
    market VARCHAR(20) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    market_cap REAL,                  -- 市值（亿）
    last_updated TIMESTAMP,
    UNIQUE(market, symbol)
);
```

### 7.2 DuckDB 优势

- **列式存储**：时序聚合、环比窗口计算原生高效
- **向量化执行**：批量分析查询性能远超 SQLite
- **零运维**：无需启动数据库服务，嵌入式使用
- **未来扩展**：如需迁移至 PostgreSQL（多用户并发场景），SQL 语法兼容度高

## 8. 飞书输出层

每个市场独立存放，互不干扰。

### 8.1 多维表格（Bitable）

每个市场单独一张多维表格（如 `A股市场情绪异动追踪`），字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 记录时间 | 日期时间 | 采集触发时间（支持盘中） |
| 标的 | 文本 | 标准化名称 |
| 净热度分 | 数字 | 基础热度总量（$V_{base} \cdot M_{kol}$） |
| 情绪极性 | 文本 | 强看多/偏多/震荡/偏空/恐慌（基于 $Sent_{fin}$ 映射） |
| 综合情绪得分 | 数字 | 包含方向的最终得分 $H_{score}$ |
| 环比变动 | 数字(%) | 较上一周期变化率 |
| 预警类型 | 单选 | 机会挖掘 / 黑天鹅预警 |
| 热度来源 | 文本 | 主要来源平台 |
| 排名 | 数字 | 当期排名 |

每次运行追加当期新记录。

情绪极性映射规则：
- $Sent_{fin} \geq 0.6$ → 强看多
- $0.2 \leq Sent_{fin} < 0.6$ → 偏多
- $-0.2 < Sent_{fin} < 0.2$ → 震荡
- $-0.6 < Sent_{fin} \leq -0.2$ → 偏空
- $Sent_{fin} \leq -0.6$ → 恐慌

### 8.2 文档（Docx）

每个市场单独一份文档（如 `A股市场情绪异动日报`）。

文档结构（最新记录在最上面）：

```
# A股市场情绪异动日报

## 2026-04-29 14:00 盘中异动

📊 本期市场概况
- 采集平台：雪球、东方财富、同花顺、微博、百度指数
- 有效帖子数：1,842（过滤水军 326 条）
- 市场整体情绪：偏多（均值 +0.23）

🟢 看多热度激增 Top 10

| 排名 | 标的 | 净热度 | 情绪极性 | 综合得分 | 环比变动 | 主要来源 |
|------|------|--------|----------|----------|----------|---------|
| 1 | XX科技 | 89.2 | 强看多 | +71.4 | +156% | 雪球 |
| ... | ... | ... | ... | ... | ... | ... |

🔴 看空热度激增 Top 10（黑天鹅预警）

| 排名 | 标的 | 净热度 | 情绪极性 | 综合得分 | 环比变动 | 主要来源 |
|------|------|--------|----------|----------|----------|---------|
| 1 | YY地产 | 76.5 | 恐慌 | -68.9 | +210% | 东方财富 |
| ... | ... | ... | ... | ... | ... | ... |

💡 关键洞察
- 基于数据特征自动生成的简要分析
```

### 8.3 飞书操作逻辑

- **首次运行**：用 lark-cli 创建 Bitable + Doc，记录文档 token 到 `config/lark_docs.yaml`
- **后续运行**：读取已存 token，在 Bitable 追加记录 + 在 Doc 头部插入新章节

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
market-sentinel/
├── main.py                        # CLI 入口（支持 --datetime / --report / --time）
├── config/
│   ├── markets.yaml               # 市场-平台映射 + 平台权重
│   ├── weights.yaml               # 热度权重配置
│   ├── kol_whitelist.yaml         # KOL 大V 白名单
│   ├── antispam.yaml              # 反作弊规则配置
│   ├── filter_thresholds.yaml     # 微盘股过滤阈值
│   └── lark_docs.yaml            # 飞书文档 token（运行时生成）
├── collectors/
│   ├── __init__.py
│   ├── base.py                    # BaseCollector 抽象类 + RawMention 数据类
│   ├── xueqiu.py                  # 雪球采集器
│   ├── eastmoney.py               # 东方财富股吧采集器
│   ├── tonghuashun.py             # 同花顺社区采集器
│   ├── weibo_finance.py           # 微博财经采集器（A股/港股共用）
│   ├── baidu_index.py             # 百度指数采集器
│   ├── xueqiu_hk.py              # 雪球港股采集器
│   ├── futu.py                    # 富途牛牛采集器
│   ├── eastmoney_hk.py           # 东方财富港股采集器
│   ├── reddit_wsb.py              # Reddit WSB 采集器
│   ├── reddit_stocks.py           # Reddit r/stocks 采集器
│   ├── twitter_cashtag.py         # Twitter $cashtag 采集器
│   ├── stocktwits.py              # StockTwits 采集器
│   ├── google_trends.py           # Google Trends 采集器
│   ├── twitter_crypto.py          # Twitter 加密货币采集器
│   ├── reddit_crypto.py           # Reddit 加密货币采集器
│   ├── coingecko.py               # CoinGecko 采集器
│   └── telegram_crypto.py         # Telegram 加密货币采集器
├── antispam/
│   ├── __init__.py
│   └── filter.py                  # 反作弊过滤引擎（账号过滤/去重/异常检测）
├── analyzers/
│   ├── __init__.py
│   ├── heat_calculator.py         # 热度计算引擎（乘积模型）
│   ├── sentiment.py               # FinBERT 情绪分析（ONNX Runtime 批量推理）
│   ├── symbol_normalizer.py       # 标的名称标准化
│   └── market_cap_filter.py       # 微盘股过滤
├── models/
│   ├── finbert_en.onnx            # FinBERT 英文 ONNX 模型（运行时下载）
│   └── finbert_zh.onnx            # FinBERT 中文 ONNX 模型（运行时下载）
├── storage/
│   ├── __init__.py
│   └── db.py                      # DuckDB 操作封装
├── publishers/
│   ├── __init__.py
│   ├── lark_bitable.py            # 飞书多维表格输出
│   └── lark_doc.py                # 飞书文档输出
├── data/
│   └── sentinel.duckdb            # DuckDB 数据库（运行时生成）
├── scripts/
│   └── export_onnx.py             # FinBERT → ONNX 导出 + INT8 量化脚本
├── requirements.txt
└── README.md
```

## 10. 错误处理

- 单个采集器失败：记录日志，跳过该平台，继续其他平台采集
- 全部采集器失败：终止运行，报错退出
- FinBERT 推理失败：回退到规则型情绪判断（关键词匹配），并在日志中标记降级
- 飞书 API 失败：重试 3 次，仍失败则将结果输出到本地 JSON 作为备份
- 首次运行无历史数据：环比标记为 "N/A"，按 $|H_{score}|$ 绝对值排序

## 11. 调度任务配置（高频 + 日终）

为捕捉 Alpha，调度贴近交易时间：

```bash
# A股/港股：盘中监控（9:30-15:00 每小时运行，捕捉日内异动）
0 10,11,13,14,15 * * 1-5 cd /path/to/market-sentinel && python main.py --market A股
0 10,11,13,14,15 * * 1-5 cd /path/to/market-sentinel && python main.py --market 港股

# A股/港股：日终汇总报告（17:30，沉淀后复盘）
30 17 * * 1-5 cd /path/to/market-sentinel && python main.py --market A股 --report daily
30 17 * * 1-5 cd /path/to/market-sentinel && python main.py --market 港股 --report daily

# 美股：盘前扫描（北京时间 20:30，夏令时）
30 20 * * 1-5 cd /path/to/market-sentinel && python main.py --market 美股 --time pre-market
# 美股：盘后汇总
0 5 * * 2-6 cd /path/to/market-sentinel && python main.py --market 美股 --report daily

# 币圈：高频波动，每 4 小时运行一次（24h 市场）
0 */4 * * * cd /path/to/market-sentinel && python main.py --market 币圈
```

## 12. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据库 | DuckDB（非 PostgreSQL） | 单机场景、列存时序聚合最优、零运维；未来扩容再迁移 PG |
| NLP 引擎 | FinBERT + ONNX（非 SnowNLP/TextBlob） | 金融语境预训练，能识别"大跳水"/"杀估值"等专业术语 |
| 热度模型 | 乘积模型（非加法模型） | $V_{base} \times Sent_{fin}$ 保留多空方向，避免 \|Sent\| 混淆信号 |
| 调度频率 | 盘中小时级 + 日终汇总（非仅 EOD） | EOD 数据是滞后指标，盘中才能捕捉 Alpha |
| 反作弊 | 账号过滤 + 去重 + 3σ 异常检测 | 防止水军/机器人操纵热度信号 |
| 推理优化 | ONNX INT8 量化 + 批量推理 | CPU 单条 ~10ms，2000 条 ~15s，满足小时级容忍窗口 |
