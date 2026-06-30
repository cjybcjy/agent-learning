# TradingAgents 本地接入

本项目通过隔离 Python 环境调用 TauricResearch/TradingAgents，避免把
TradingAgents 的 LangChain/LLM 依赖混入 MGFS 主运行环境。

## 已安装位置

- 隔离环境：`.venv-tradingagents/`
- 安装来源：`https://github.com/TauricResearch/TradingAgents.git@v0.3.0`
- 本项目桥接脚本：`scripts/run_tradingagents_fundamental.py`

## 启动方式

```bash
TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese \
TRADINGAGENTS_TIMEOUT_SECONDS=120 \
PYTHONPATH=. \
uvicorn sentinel.web.main:app --host 127.0.0.1 --port 8000
```

默认情况下，页面上的“基本面建议”会自动发现并使用
`.venv-tradingagents/bin/python`。如果需要改用其他隔离环境，可以显式设置
`TRADINGAGENTS_PYTHON`；只有在没有可用隔离环境时，本项目才会尝试在主 Python
环境中直接 import `tradingagents`。

## Provider 配置

TradingAgents 默认 provider 是 `openai`。模型 provider 的密钥应通过本机
环境或部署侧 secret 注入，不要写入仓库。

常用环境变量：

- `TRADINGAGENTS_LLM_PROVIDER`
- `TRADINGAGENTS_DEEP_THINK_LLM`
- `TRADINGAGENTS_QUICK_THINK_LLM`
- `TRADINGAGENTS_OUTPUT_LANGUAGE`
- `TRADINGAGENTS_MAX_DEBATE_ROUNDS`
- `TRADINGAGENTS_MAX_RISK_ROUNDS`
- `TRADINGAGENTS_TIMEOUT_SECONDS`

没有 provider API key 时，页面会显示“TradingAgents 不可用/缺少 key”，并且
不会生成臆测评分，也不会修改 `config/moat_static_base.yaml`。

## 安全边界

TradingAgents 输出只作为“可追溯基本面评分建议”的证据来源：

- 只生成建议，不自动写入 YAML。
- 只在输出包含 `dimension_scores` 时生成具体分数建议。
- 原始输出会保留为证据，反向证据会标明“未结构化/需人工复核”。
