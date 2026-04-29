from pathlib import Path

import pytest

from sentinel.config import AppSettings


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "markets.yaml").write_text(
        "A股:\n  collectors: [synthetic]\n",
        encoding="utf-8",
    )
    (config_dir / "weights.yaml").write_text(
        "base_heat:\n  posts: 0.35\n",
        encoding="utf-8",
    )
    return AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir)
