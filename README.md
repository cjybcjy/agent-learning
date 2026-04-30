# Crypto Heatmap MVP

币圈社媒（Telegram + Discord）热度采集 → 双闸门打分 → 飞书日报。

## 安装

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 配置

- `config/sources.yaml`：填入要监听的 Telegram 频道、Discord 服务器/频道。
- `config/aliases.csv`：维护标的与俚称的映射，`is_ambiguous=true` 标记歧义词。
- `config/thresholds.yaml`：α/β 阈值。
- 环境变量：`TELEGRAM_API_ID`、`TELEGRAM_API_HASH`、`DISCORD_BOT_TOKEN`。
- 飞书：先在另一个 shell 跑 `lark-cli config init` 与 `lark-cli auth login --scope ...` 完成授权（参考 lark-shared skill）。

## 运行

```bash
python -m heatmap.scheduler
```

## 测试

```bash
pytest -v
```

## 文档

- 设计稿：[docs/superpowers/specs/2026-04-30-crypto-heatmap-design.md](docs/superpowers/specs/2026-04-30-crypto-heatmap-design.md)
- 实现计划：[docs/superpowers/plans/2026-04-30-crypto-heatmap-plan.md](docs/superpowers/plans/2026-04-30-crypto-heatmap-plan.md)
