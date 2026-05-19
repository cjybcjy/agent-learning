from __future__ import annotations

from sentinel.mgfs.orchestrator import MGFSOrchestrator
from sentinel.mgfs.scanner import EcosystemScanner

_orchestrator: MGFSOrchestrator | None = None
_scanner: EcosystemScanner | None = None


def get_orchestrator() -> MGFSOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        from sentinel.config import AppSettings
        from sentinel.mgfs.config_loader import build_orchestrator, load_mgfs_config
        from sentinel.mgfs.data import get_price_fetcher
        from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher

        settings = AppSettings()
        config_path = settings.resolved_config_dir / "mgfs_config.yaml"
        config = load_mgfs_config(config_path)
        fetchers = {
            "valuation": EastmoneyValuationFetcher(),
            "timing": get_price_fetcher(),
        }
        _orchestrator = build_orchestrator(
            config, config_dir=settings.resolved_config_dir, fetchers=fetchers
        )
    return _orchestrator


def get_scanner() -> EcosystemScanner:
    global _scanner
    if _scanner is None:
        from sentinel.config import AppSettings

        settings = AppSettings()
        moat_path = settings.resolved_config_dir / "moat_static_base.yaml"
        _scanner = EcosystemScanner(
            orchestrator=get_orchestrator(),
            moat_config_path=moat_path,
        )
    return _scanner
