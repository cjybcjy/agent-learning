from pathlib import Path
from heatmap.config import load_thresholds, load_sources

def test_load_thresholds(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text("stage_a_top_n: 50\nstage_b_top_n: 10\nalpha_min: 0.5\nbeta_min: 1.5\n")
    cfg = load_thresholds(p)
    assert cfg.stage_a_top_n == 50
    assert cfg.alpha_min == 0.5

def test_load_sources(tmp_path: Path):
    p = tmp_path / "s.yaml"
    p.write_text("telegram:\n  channels: ['@a', '@b']\ndiscord:\n  guilds: []\n")
    cfg = load_sources(p)
    assert cfg.telegram.channels == ["@a", "@b"]
    assert cfg.discord.guilds == []
