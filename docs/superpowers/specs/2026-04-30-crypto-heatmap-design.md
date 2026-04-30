# Crypto Heatmap MVP — 设计稿

**日期：** 2026-04-30
**版本：** v1（币圈端到端 MVP）
**仓库：** agent-learning

---

## 1. 目标

每天产出一份"币圈市场异动 Top 10 标的"日报，自动写入飞书文档；为后续 A 股 / 港股 / 美股复用奠定可插拔架构。

**v1 范围（明确不做的事）：**

- 不接 A 股 / 港股 / 美股数据源（延后到 v1.1）。
- 不做实时滚动告警通道（Brainstorm Q4 中的 C 通道延后）。
- 不做 LLM 消歧的实际调用（仅预留接口）。
- 不做别名审批工作流（仅离线产出候选 CSV）。

---

## 2. 整体架构

5 个子模块，每个独立目录、独立单测，通过 dataclass / SQLite 表通信：

```
[Collectors]──►[Raw Store]──►[Entity Extractor]──►[Daily Aggregator]──►[Reporter]
   Telegram                   AC + alias dict      α/β dual gate         lark-doc
   Discord                    (+ ambiguity flag)   + composite score     block_replace
                              (+ LLM 消歧接口)                            + append
```

---

## 3. 数据流与存储

SQLite 单库 `data/heatmap.db`，三张表，时间戳统一存 UTC、精确到秒（为未来切换滚动窗口预留）：

| 表 | 字段 | 作用 |
|---|---|---|
| `raw_messages` | `id, platform, channel, author_id, content, posted_at, fetched_at` | 原始消息存档 |
| `mentions` | `message_id, symbol, matched_alias, is_ambiguous, confidence` | AC 抽取结果 |
| `daily_scores` | `symbol, date, mention_count, weighted_score, alpha, beta, composite` | 日切聚合 |

`platform` 枚举：`telegram | discord`（v1.1 起扩 `weibo | xueqiu | lihkg | ...`）。

---

## 4. 核心算法

### 4.1 Stage A — 候选筛子

当日 `mention_count` Top 50 进入候选池。

### 4.2 Stage B — 加权重排（已修正零乘陷阱）

```
weighted_score = mention × (1 + log₁₀(1 + interactions))
```

- `interactions` = 点赞 / 转发 / 评论之和；Telegram / Discord 无该字段时填 0。
- 当 `interactions = 0`，`weighted_score = mention × 1 = mention`，与 Stage A 口径平滑衔接，**不会清零**。
- **统一使用以 10 为底的对数**（`math.log10`），所有代码禁止使用 `math.log`，避免自然对数与常用对数的刻度混淆。

### 4.3 双闸门

- **α** = `today_score / yesterday_score − 1`，默认阈值 `≥ 0.5`（+50%）。
- **β** = `today_score / market_avg_today`，默认阈值 `≥ 1.5`。
- **入选条件**：α 与 β 同时达标。
- **排序**：`composite = α × log₁₀(1 + β)`，降序取 Top 10。

`yesterday_score = 0` 的冷启动情况：α 记为 `+inf`，仅按 β 与 composite 排序，并在报告里加 `🆕 NEW` 标记。

### 4.4 阈值配置

所有阈值存 `config/thresholds.yaml`，禁止硬编码到代码：

```yaml
stage_a_top_n: 50
stage_b_top_n: 10
alpha_min: 0.5
beta_min: 1.5
```

---

## 5. 实体抽取

### 5.1 算法

`pyahocorasick`，启动时把别名词典加载进 AC 自动机，O(N) 单次扫描得到一篇消息内所有 hit。**禁止在长文本上跑多重正则。**

### 5.2 词典 schema（`config/aliases.csv`）

```csv
symbol,alias,is_ambiguous,source
BTC,比特币,false,seed
BTC,btc,false,seed
DOGE,狗狗,false,seed
DOGE,doge,false,seed
PEPE,佩佩,true,seed         # 中文俚称容易撞名
APT,apt,true,seed             # 与 Linux 包管理工具同名
```

- **冷启动种子**：CoinGecko top 500 ticker + 手工维护的中英文俚称表。
- **`is_ambiguous` 字段**：v1 起即引入，明确无歧义的词直接采信；高歧义词（`is_ambiguous=true`）在双闸门触发后才走消歧路径。

### 5.3 消歧接口（v1 仅预留）

```python
class Disambiguator(Protocol):
    def resolve(self, message: RawMessage, candidates: list[Mention]) -> list[Mention]: ...

class NoopDisambiguator:
    """v1 默认实现，直接信任 AC 命中结果。"""
    def resolve(self, message, candidates): return candidates

class LLMDisambiguator:
    """v1.1 启用，仅当命中条目 is_ambiguous=true 且当日同比飙升 ≥ N 倍时调用。"""
    ...  # not implemented in v1
```

### 5.4 别名进化反馈环（v1 仅离线脚本）

`scripts/suggest_aliases.py`：

1. 拉取 `raw_messages` 近 30 天数据。
2. 对未命中任何 symbol 的高频词跑 TF-IDF 共现分析。
3. 候选 `(symbol, alias_candidate, cooccurrence_score)` 写入 `data/alias_suggestions.csv`。
4. v1 仅产出文件等待人工审核；v1.1 起接飞书审批流。

---

## 6. 数据采集（v1：Telegram + Discord）

### 6.1 接口

```python
class BaseCollector(Protocol):
    async def run(self) -> None: ...  # 常驻协程，写 raw_messages
```

### 6.2 实现

- **Telegram**：`telethon` user-bot 模式，监听 `config/sources.yaml` 中列出的频道。
- **Discord**：`discord.py`，监听已加入服务器的指定频道（机器人需被频道所有者邀请）。
- 两个 collector 互不耦合，新增平台 = 新增一个 `BaseCollector` 实现。

### 6.3 数据源清单（`config/sources.yaml`）

```yaml
telegram:
  channels:
    - "@example_alpha_channel_1"
    - "@example_alpha_channel_2"
discord:
  guilds:
    - guild_id: "..."
      channel_ids: ["...", "..."]
```

具体频道在实现阶段由用户填入；v1 默认占位、提供 schema。

---

## 7. 飞书报告（看板 + 折叠归档）

### 7.1 文档结构（首次创建）

```xml
<title>币圈市场热度日报</title>
<heading1>📊 今日榜单</heading1>
<p id="cover-anchor">（首次创建占位，每日被 block_replace 覆盖）</p>
<heading1>🗂 历史归档</heading1>
<p id="archive-anchor">（每日 append 折叠块到此 anchor 之后）</p>
```

### 7.2 每日更新流程

1. **覆盖今日榜单**：`lark-cli docs +update --api-version v2 --command block_replace --target cover-anchor`，内容为今日 Top 10 表格（含 symbol、mention、α、β、composite、🆕 标记）。
2. **追加历史归档**：`lark-cli docs +update --api-version v2 --command append`，把今日表格副本包在 `<collapsible>` 块内、标题为日期，追加到 `archive-anchor` 之后。
3. **文档 token 持久化**：`data/state.json` 存 `{ "feishu_doc_token": "..." }`，避免每天新建文档。

### 7.3 报告字段

| 排名 | 标的 | 当日提及 | α (%) | β | 复合分 | 标记 |
|---|---|---|---|---|---|---|
| 1 | DOGE | 1234 | +220% | 3.4 | 1.18 | 🆕 |

---

## 8. 调度

单进程 `python -m heatmap.scheduler`：

- Collectors 常驻（`asyncio.gather`）。
- 每日 UTC 00:05 触发 `aggregate + report` 任务（币圈 24 点切日，留 5 分钟缓冲等待延迟消息落库）。
- v1 用 `nohup` 或 `systemd` 跑，不引 Airflow / Celery。

---

## 9. 测试

- 每个子模块独立单测（`tests/unit/`）。
- 集成测试（`tests/integration/`）：用 `tests/fixtures/sample_messages.jsonl` 灌入 Raw Store，验证从原始消息 → AC 抽取 → 双闸门 → 飞书 XML 渲染的完整链路；飞书 API 用 mock。
- 关键算法（双闸门、复合分、零互动回退）必须有专门的边界用例。

---

## 10. 目录结构

```
heatmap/
  collectors/
    base.py
    telegram.py
    discord.py
  store/
    schema.sql
    dao.py
  extractor/
    ac.py
    dictionary.py
    disambiguator.py
  aggregator/
    scoring.py
    gates.py
  reporter/
    lark_doc.py
    templates.py
  scheduler.py
config/
  sources.yaml
  thresholds.yaml
  aliases.csv
scripts/
  suggest_aliases.py
tests/
  unit/
  integration/
  fixtures/
data/                       # gitignored
docs/superpowers/
  specs/
  plans/
```

---

## 11. 开放问题（v1.1 起处理）

- A 股 / 港股 / 美股数据源接入与代理池工程化。
- LLMDisambiguator 实际启用与缓存策略。
- 别名进化的飞书审批工作流。
- 滚动窗口（小时级）告警通道。
