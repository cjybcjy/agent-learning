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
    assert "发现候选" in response.text
    assert "启动扫描" not in response.text
    assert "客观发现中" not in response.text
    assert 'hx-post="/api/candidates/discover"' in response.text
    assert 'hx-post="/api/scan/start"' not in response.text
    assert 'id="scan-theme"' in response.text
    assert 'id="candidate-discovery-form"' in response.text
    assert 'hx-include="#candidate-discovery-form"' in response.text
    assert 'name="discovery_mode"' in response.text
    assert "决策票据" in response.text
    assert "独立风控" not in response.text
    assert 'id="risk-console"' not in response.text
    assert "risk-console-panel wide-panel" not in response.text
    assert 'hx-get="/api/risk/alerts"' not in response.text
    assert 'hx-trigger="load, every 10s"' not in response.text
    assert "贝叶斯校准" not in response.text
    assert "Bayes 校准" not in response.text
    assert 'id="calibration-lab"' not in response.text
    assert 'href="/dashboard/ops#historical-backtest-panel"' not in response.text
    assert "回测设置" not in response.text
    assert 'aria-label="跳转到历史回测设置"' not in response.text
    assert 'hx-target="#calibration-lab-content"' not in response.text
    assert 'id="calibration-lab-content"' not in response.text
    assert 'hx-get="/api/calibration/reports"' not in response.text
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
    assert "MGFS 分层链路" in response.text
    assert "1 发现机会" in response.text
    assert "2 查看决策" in response.text
    assert "3 加入影子持仓" in response.text
    assert "4 处理风控" in response.text
    assert "5 复盘校准" not in response.text
    assert "输入: symbol / theme / policy" in response.text
    assert "判断: 因子权重 + 置信度" in response.text
    assert "边界: Shadow Trading" in response.text
    assert "因子并行层" in response.text
    assert "决策保护层" in response.text
    assert "低置信度不会被权重重分配悄悄抬高" in response.text
    assert 'href="#opportunity-radar"' in response.text
    assert 'href="#risk-console"' not in response.text
    assert "workstation-layout-relaxed" in response.text
    assert "primary-workflow" in response.text
    assert "secondary-workflow" in response.text
    assert 'id="eval-result"' in response.text
    assert 'id="scan-result"' in response.text
    assert 'hx-get="/api/shadow-positions/panel"' in response.text
    assert 'id="shadow-position-dock-content"' in response.text

    workflow_index = response.text.index("MGFS 分层链路")
    score_config_index = response.text.index("总分构成配置")
    radar_index = response.text.index("机会雷达")
    assert workflow_index < score_config_index < radar_index


def test_ops_page_renders_system_console_components():
    client = TestClient(create_app())

    response = client.get("/dashboard/ops")

    assert response.status_code == 200
    assert "系统控制台" in response.text
    assert "待复核事项" in response.text
    assert "来源" in response.text
    assert "建议" in response.text
    assert "影响" in response.text
    assert "操作" in response.text
    assert "每日研究 Agent" not in response.text
    assert "配置控制台" in response.text
    assert "半自动确认" not in response.text
    assert "评分总配置" in response.text
    assert "外部信号源" in response.text
    assert 'hx-get="/api/config/load/research_signal_sources.yaml"' in response.text
    assert "保存前会先执行 YAML 与 MGFS Schema 校验" in response.text
    assert "流水线监控" in response.text
    assert "历史回测与研究可信度" in response.text
    assert "workflow-guide" in response.text
    assert "MGFS 治理链路" in response.text
    assert "1 待复核事项" in response.text
    assert "2 配置规则" in response.text
    assert "3 执行巡检" in response.text
    assert "4 历史回测" in response.text
    assert "5 回写假设" in response.text
    assert "输入: snapshot + suggestion + proposal" in response.text
    assert "边界: research_only" in response.text
    assert "信号快照层" in response.text
    assert "人工确认层" in response.text
    assert "所有配置变更都需要进入 approve / reject / edit 路径" in response.text
    assert 'href="#review-queue"' in response.text
    assert 'href="#config-console"' in response.text
    assert 'href="#pipeline-monitor"' in response.text
    assert 'href="#historical-backtest-panel"' in response.text
    assert 'hx-get="/api/review-queue/panel"' in response.text
    assert 'hx-get="/api/config/load/mgfs_config.yaml"' in response.text
    assert 'hx-get="/api/config/proposals/panel"' not in response.text
    assert 'id="review-queue-panel"' in response.text
    assert 'id="research-agent-panel"' not in response.text
    assert 'id="config-proposal-panel"' not in response.text
    assert 'id="config-editor-container"' in response.text
    assert 'id="pipeline-section"' in response.text
    assert 'id="historical-backtest-panel"' in response.text
    assert 'hx-get="/api/calibration/reports"' in response.text
    assert 'id="backtest-window-form"' in response.text
    assert 'name="start_date"' in response.text
    assert 'type="date"' in response.text
    assert 'value="2025-01-01"' in response.text
    assert 'name="end_date"' in response.text
    assert 'value="2025-06-30"' in response.text
    assert 'hx-target="#historical-backtest-content"' in response.text
    assert 'hx-include="#backtest-window-form"' in response.text
    assert "运行回测" in response.text
    assert "Bayes 校准" not in response.text
