# Utopia 借鉴落地：MGFS 研究信号闭环

## 本次借鉴范围

本次只借鉴 Utopia 的研究闭环结构，不借鉴它的加密货币、Freqtrade 或实盘执行形态。

借鉴的核心是三件事：

1. point-in-time 决策输入：历史回测时只允许使用当时已经可见的数据。
2. 统一研究信号 JSONL：多 agent 讨论之后不直接改配置、不直接下交易指令，而是写入可复盘信号。
3. 运行工件校验：一轮研究/回测结果必须带齐摘要、输入、信号和讨论记录，才能被认为可信。

## 借鉴点一：point-in-time 决策输入

### Utopia 怎么做

Utopia 的 `historical_trials.py` 会为每个历史 `decision_time` 构造输入，只保留 `available_at <= decision_time` 的 K 线和事件。

这解决的是未来函数污染问题：agent 不能用后来的行情或新闻去解释过去的决策。

### agent-learning 改前

`sentinel/mgfs/evolution/historical_backtest.py` 已经有单资产历史沙盘：

- 输入是日期、价格和每日分数。
- 回测能记录止损、收益和回撤。
- 但它还没有一个明确的“当日可见研究输入”对象。
- 外部信号、配置版本、价格快照和证据 hash 还没有被统一绑定到某个 `as_of_date`。

### agent-learning 改后

新增 `sentinel/mgfs/evolution/research_signal.py`：

- `MGFSEvidenceEvent`：表示一个带 `available_at` 和 `content_hash` 的证据事件。
- `MGFSDecisionInput`：表示某个标的在某个 `as_of_date` 的研究输入。
- `PointInTimeViolation`：当证据的 `available_at` 晚于 `as_of_date` 时直接拒绝。

对应测试：

- `tests/test_mgfs_research_signal.py::test_decision_input_rejects_evidence_not_available_at_as_of_date`

现在 MGFS 后续做历史回测时，可以先生成 `decision_inputs.jsonl`，每行都带：

```json
{
  "symbol": "300750",
  "name": "宁德时代",
  "as_of_date": "2026-06-20",
  "config_hash": "config-hash",
  "price_snapshot_hash": "price-hash",
  "evidence_hashes": ["event-hash"]
}
```

## 借鉴点二：统一研究信号 JSONL

### Utopia 怎么做

Utopia 使用 `alpha_signal_v1.jsonl` 作为研究层和执行层之间的桥。

它的策略只读取信号文件，不在策略里再调用 LLM。信号中保留：

- `decision_time`
- `expires_at`
- `source_scores`
- `risk_flags`
- `evidence_hashes`

### agent-learning 改前

`ResearchAgentService` 已经能生成只读建议，并且区分 evidence / counter_evidence。

但改前缺少一个面向回测和复盘的统一信号文件：

- 多 agent 或规则建议没有统一的 JSONL schema。
- 建议与配置 hash、价格快照 hash 没有强绑定。
- 读取历史信号时，没有“忽略未来信号、拒绝过期信号”的公共函数。
- “只做研究支持，不给直接交易指令”主要靠文本约束，没有进入 schema。

### agent-learning 改后

新增 `MGFSResearchSignalV1`：

```json
{
  "schema_version": "mgfs_research_signal_v1",
  "symbol": "300750",
  "as_of_date": "2026-06-20",
  "action_hint": "increase_attention",
  "score": 0.36,
  "confidence": 0.7,
  "instruction_boundary": "research_only",
  "source_scores": {
    "moat_agent": 0.6,
    "risk_agent": -0.2
  },
  "evidence_hashes": ["moat-hash", "risk-hash"],
  "risk_flags": ["conflict"],
  "config_hash": "config-hash",
  "price_snapshot_hash": "price-hash",
  "expires_at": "2026-06-23"
}
```

新增函数：

- `merge_mgfs_agent_signals()`：把多个 agent 的分数、证据和风险旗标合并成一条研究信号。
- `load_latest_research_signal()`：只读取 `as_of_date` 之前的最新未过期信号。

和 Utopia 不同的是，MGFS 的信号不叫 `LONG/SHORT/FLAT`，而是：

- `increase_attention`
- `reduce_attention`
- `hold_review`

并且强制保留：

- `instruction_boundary = "research_only"`

这表示输出只能用于研究复核、配置候选和回测校准，不能被解释成买入、卖出、加仓、减仓指令。

对应测试：

- `tests/test_mgfs_research_signal.py::test_merge_mgfs_agent_signals_preserves_evidence_scores_and_boundary`
- `tests/test_mgfs_research_signal.py::test_load_latest_research_signal_ignores_future_signals`
- `tests/test_mgfs_research_signal.py::test_load_latest_research_signal_treats_expiry_as_exclusive`

## 借鉴点三：运行工件校验

### Utopia 怎么做

Utopia 的 `run_validation.py` 不只看脚本是否退出成功，还会检查：

- run summary 是否存在且 `ok=true`
- 信号 JSONL 行数是否匹配
- 每条信号是否有 evidence hash
- source score 是否完整
- LLM 调用记录是否存在
- 回测、lookahead、dry-run 证据是否齐全

### agent-learning 改前

MGFS 已经有回测 CLI 和研究 agent 面板，但一轮研究结果还缺少类似的“工件可信度检查”：

- 缺少统一校验 `run_summary.json`、`decision_inputs.jsonl`、信号 JSONL 和 agent 讨论记录的工具。
- 缺少对 `research_only` 边界的机器检查。
- 缺少对 evidence hash/source score 的硬约束。

### agent-learning 改后

新增 `sentinel/mgfs/evolution/research_run_validation.py`：

- `validate_mgfs_research_run()`：校验一轮 MGFS 研究运行目录。
- `MGFSResearchRunValidationReport`：输出 `passed/failures/warnings`。

当前校验的最小工件集合：

```text
run_summary.json
decision_inputs.jsonl
mgfs_research_signal_v1.jsonl
agent_discussion.md
```

当前硬约束：

- `run_summary.ok` 必须为 true。
- `adapter_status.point_in_time_inputs` 必须启用。
- `adapter_status.research_signal_schema` 必须是 `mgfs_research_signal_v1`。
- `adapter_status.instruction_boundary` 必须是 `research_only`。
- `decision_count` 必须同时匹配决策输入行数和信号行数。
- 每条决策输入必须有 `config_hash`、`price_snapshot_hash`、`evidence_hashes`。
- 每条信号必须有 `evidence_hashes`、`source_scores`。
- 每条信号的 `config_hash` 和 `price_snapshot_hash` 必须匹配对应决策输入。
- `agent_discussion.md` 必须存在且非空。

对应测试：

- `tests/test_mgfs_research_run_validation.py::test_validate_mgfs_research_run_accepts_complete_artifact`
- `tests/test_mgfs_research_run_validation.py::test_validate_mgfs_research_run_rejects_missing_signal_evidence`
- `tests/test_mgfs_research_run_validation.py::test_validate_mgfs_research_run_rejects_direct_trading_boundary`

## 改前 vs 改后总览

| 维度 | 改前 | 改后 |
| --- | --- | --- |
| 历史输入 | 有价格/分数沙盘，但缺少统一 point-in-time 研究输入 | 有 `MGFSDecisionInput`，拒绝晚于 `as_of_date` 的证据 |
| 外部信号 | 能进入 daily research agent 建议 | 可进一步固化为带 hash 的历史决策输入 |
| 多 agent 输出 | 主要是建议文本和 evidence/counter_evidence | 可合并成 `mgfs_research_signal_v1.jsonl` |
| 未来信号 | 没有公共读取约束 | `load_latest_research_signal()` 忽略未来信号并拒绝过期信号 |
| 交易边界 | 依赖文案说明“研究支持” | schema 强制 `instruction_boundary=research_only` |
| 运行可信度 | 回测结果和 agent 运行记录较分散 | `validate_mgfs_research_run()` 做机器校验 |

## 后续接入建议

下一步可以把现有 `ResearchAgentService` 和历史回测连接起来：

1. 在每日研究运行时写出 `agent_discussion.md` 和 `mgfs_research_signal_v1.jsonl`。
2. 在历史回测前生成 `decision_inputs.jsonl`，把价格快照、配置 hash、外部信号 hash 绑定到每个 `as_of_date`。
3. 在回测报告生成前调用 `validate_mgfs_research_run()`。
4. 将校验结果展示到 Ops 工作台，让“研究可信度”成为回测结果旁边的第一等信息。
