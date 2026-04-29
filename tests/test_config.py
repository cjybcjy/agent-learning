from pathlib import Path

from sentinel.config import AppSettings, load_market_config


def test_load_market_config_reads_collectors(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "markets.yaml").write_text(
        "A股:\n  collectors: [xueqiu, eastmoney]\n",
        encoding="utf-8",
    )

    data = load_market_config(config_dir / "markets.yaml")

    assert data["A股"]["collectors"] == ["xueqiu", "eastmoney"]


def test_app_settings_resolves_duckdb_path(tmp_path: Path) -> None:
    settings = AppSettings(
        base_dir=tmp_path,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        database_name="sentinel.duckdb",
    )

    assert settings.database_path == tmp_path / "data" / "sentinel.duckdb"


def test_app_settings_resolves_relative_dirs_from_base_dir(tmp_path: Path) -> None:
    settings = AppSettings(base_dir=tmp_path, config_dir=Path("config"), data_dir=Path("data"))

    assert settings.resolved_config_dir == tmp_path / "config"
    assert settings.database_path == tmp_path / "data" / "sentinel.duckdb"
