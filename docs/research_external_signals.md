# Research External Signals

每日研究 Agent 会读取 `data/research_external_signals.json` 作为外部信号快照。
外部信号由 `config/research_signal_sources.yaml` 配置的采集器生成；也可以由人工或其他脚本写入同一快照格式。
Agent 只生成建议，不直接改 YAML。

## Snapshot Shape

```json
{
  "generated_at": "2026-06-23T08:00:00",
  "items": [
    {
      "category": "policy",
      "source": "国务院政策例行吹风会",
      "title": "人工智能+行动持续推进",
      "published_at": "2026-06-22",
      "sectors": ["人工智能"],
      "themes": ["AI_Compute_Infrastructure"],
      "url": "https://example.com/policy-ai",
      "polarity": "supporting",
      "impact": "高"
    },
    {
      "category": "moat",
      "source": "交易所公告",
      "title": "宁德时代海外订单结构变化",
      "published_at": "2026-06-21",
      "symbols": ["300750"],
      "url": "https://example.com/300750",
      "polarity": "counter",
      "impact": "中"
    }
  ]
}
```

## Rules

- `category=policy` drives policy whitelist review suggestions.
- `category=moat` drives moat score review suggestions.
- `published_at` newer than config `last_updated` is treated as a review trigger.
- `polarity=counter` is shown as counter-evidence, not as an automatic downgrade.
- YAML edits still require manual confirmation in the Ops config console.

## Collector

Ops 页面加载每日研究 Agent 时会检查当天是否已有快照；如果没有，会按
`config/research_signal_sources.yaml` 采集一次。也可以在 Agent 面板点击
“更新外部信号”强制刷新。

采集源支持：

- `kind: json`：读取 JSON 列表或对象中的列表字段。
- `kind: rss`：读取 RSS/Atom 条目。
- `require_keyword_match: true`：只有命中 `keyword_rules.contains` 的条目才写入快照。

默认启用的政策源是中国政府网政策推送：
`https://www.gov.cn/pushinfo/v150203/pushinfo.json`。

巨潮公告源已作为模板写在配置中，但默认禁用；它需要进一步补充 POST 查询参数适配后再启用。
