# 每日研究 Agent 讨论 RA_20260629_105309

- generated_at: 2026-06-29T10:53:09
- mode: read_only_advisory
- summary: 今日生成 7 条只读建议，其中 2 条高影响；建议先看证据和反向证据，再进入 YAML 编辑。

## 政策白名单需要复核

- target: 政策白名单
- config_file: policy_whitelist.yaml
- rationale: 政策白名单距离上次更新已有 45 天，超过 21 天复核窗口。
- proposed_change: 先查看近期政策、财报和产业链变化，再决定是否在配置控制台调整对应规则。
## 护城河评分需要复核

- target: 护城河评分
- config_file: moat_static_base.yaml
- rationale: 护城河评分距离上次更新已有 41 天，超过 21 天复核窗口。
- proposed_change: 先查看近期政策、财报和产业链变化，再决定是否在配置控制台调整对应规则。
## 主题覆盖过于集中

- target: Embodied_Robotics
- config_file: moat_static_base.yaml
- rationale: Embodied_Robotics 覆盖 10/25 个标的，占比 40%，可能放大单一叙事。
- proposed_change: 增加同产业链的反方样本、替代赛道或周期弱相关标的，再决定是否调整基础评分。
## 护城河评分缺少证据字段

- target: base_score
- config_file: moat_static_base.yaml
- rationale: 护城河静态评分证据字段覆盖率 40%，缺失 300 项，无效 0 项。
- proposed_change: 为高影响 base_score 维度补充 source/as_of/confidence/bear_case，再决定是否调整分数。
## 政策白名单有新外部信号待复核

- target: 银行、保险
- config_file: policy_whitelist.yaml
- rationale: 发现晚于政策白名单更新时间的外部政策信号：国务院办公厅关于加强监管防范风险促进私募投资基金高质量发展的指导意见。
- proposed_change: 核验原文与反向政策后，再决定是否调整 sector multiplier、policy_rating 或 note。
## 政策白名单有新外部信号待复核

- target: 农林牧渔、食品饮料
- config_file: policy_whitelist.yaml
- rationale: 发现晚于政策白名单更新时间的外部政策信号：国务院关于印发《加快农业农村现代化“十五五”规划》的通知。
- proposed_change: 核验原文与反向政策后，再决定是否调整 sector multiplier、policy_rating 或 note。
## 政策白名单有新外部信号待复核

- target: 有色金属、煤炭
- config_file: policy_whitelist.yaml
- rationale: 发现晚于政策白名单更新时间的外部政策信号：中华人民共和国矿产资源法实施条例。
- proposed_change: 核验原文与反向政策后，再决定是否调整 sector multiplier、policy_rating 或 note。
