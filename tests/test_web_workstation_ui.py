from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_research_page_renders_trading_workstation_components():
    client = TestClient(create_app())

    response = client.get("/dashboard/research")

    assert response.status_code == 200
    assert "MGFS 交易工作站" in response.text
    assert "机会雷达" in response.text
    assert "半导体自主可控" in response.text
    assert "低空经济" in response.text
    assert "机器人与具身智能" in response.text
    assert "国企改革与高股息红利" in response.text
    assert "重仓基金数量排名" in response.text
    assert 'name="fund_rank_limit"' in response.text
    assert 'value="20"' in response.text
    assert "客观发现" in response.text
    assert 'hx-post="/api/candidates/discover"' in response.text
    assert 'id="scan-theme"' in response.text
    assert 'hx-include="#scan-theme"' in response.text
    assert "客观发现中" in response.text
    assert "决策票据" in response.text
    assert "组合风控" in response.text
    assert "贝叶斯校准" in response.text
    assert "总分构成配置" in response.text
    assert 'id="score-composition-config"' in response.text
    assert 'hx-post="/api/config/score-composition"' in response.text
    assert 'name="moat_weight"' in response.text
    assert 'name="valuation_weight"' in response.text
    assert 'name="policy_weight"' in response.text
    assert 'name="timing_weight"' in response.text
    assert 'name="strong_buy_min_score"' in response.text
    assert 'name="accumulate_min_score"' in response.text
    assert 'name="hold_watch_min_score"' in response.text
    assert 'hx-get="/api/config/load/mgfs_config.yaml"' not in response.text
    assert "<textarea" not in response.text
    assert "workflow-guide" in response.text
    assert "1 发现机会" in response.text
    assert "2 查看决策" in response.text
    assert "3 加入影子持仓" in response.text
    assert "4 处理风控" in response.text
    assert "5 复盘校准" in response.text
    assert 'href="#opportunity-radar"' in response.text
    assert 'href="#risk-console"' in response.text
    assert "workstation-layout-relaxed" in response.text
    assert "primary-workflow" in response.text
    assert "secondary-workflow" in response.text
    assert "risk-console-panel wide-panel" in response.text
    assert 'id="eval-result"' in response.text
    assert 'id="scan-result"' in response.text
    assert 'hx-get="/api/risk/alerts"' in response.text

    workflow_index = response.text.index("工作流导览")
    score_config_index = response.text.index("总分构成配置")
    radar_index = response.text.index("机会雷达")
    assert workflow_index < score_config_index < radar_index


def test_ops_page_renders_system_console_components():
    client = TestClient(create_app())

    response = client.get("/dashboard/ops")

    assert response.status_code == 200
    assert "系统控制台" in response.text
    assert "每日研究 Agent" in response.text
    assert "配置控制台" in response.text
    assert "半自动确认" in response.text
    assert "评分总配置" in response.text
    assert "外部信号源" in response.text
    assert 'hx-get="/api/config/load/research_signal_sources.yaml"' in response.text
    assert "保存前会先执行 YAML 与 MGFS Schema 校验" in response.text
    assert "流水线监控" in response.text
    assert "workflow-guide" in response.text
    assert "1 每日研究 Agent" in response.text
    assert "2 配置规则" in response.text
    assert "3 执行巡检" in response.text
    assert "4 复盘修正" in response.text
    assert 'href="#daily-research-agent"' in response.text
    assert 'href="#config-console"' in response.text
    assert 'href="#pipeline-monitor"' in response.text
    assert 'hx-get="/api/research-agent/panel"' in response.text
    assert 'hx-get="/api/config/load/mgfs_config.yaml"' in response.text
    assert 'hx-get="/api/config/proposals/panel"' in response.text
    assert 'id="research-agent-panel"' in response.text
    assert 'id="config-proposal-panel"' in response.text
    assert 'id="config-editor-container"' in response.text
    assert 'id="pipeline-section"' in response.text
