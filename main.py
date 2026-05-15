from __future__ import annotations

import json

import typer

from sentinel.app import build_application
from sentinel.config import AppSettings
from sentinel.domain.models import Market

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    market: Market = typer.Option(..., "--market"),
    report: str | None = typer.Option(None, "--report"),
    time: str | None = typer.Option(None, "--time"),
    publish: bool = typer.Option(False, "--publish", help="Push results to Feishu Bitable + Doc"),
    collectors: str | None = typer.Option(None, "--collectors", help="Comma-separated collector keys (overrides markets.yaml)"),
) -> None:
    del report, time
    settings = AppSettings()
    application = build_application(settings)
    collector_keys = [c.strip() for c in collectors.split(",")] if collectors else None
    snapshots = application.run_market(market=market, collector_keys=collector_keys)
    typer.echo(f"collected {len(snapshots)} ranked snapshot for {market.value}")
    for s in snapshots:
        direction = "bullish" if s.directed_heat > 0 else ("bearish" if s.directed_heat < 0 else "neutral")
        delta = f"Δ{s.change_pct:+.1f}%" if s.change_pct is not None else "NEW"
        typer.echo(f"  {s.symbol}: heat={s.directed_heat:.2f} ({direction}) [{delta}]")

    if publish:
        from sentinel.publishers.lark_bitable import LarkBitablePublisher
        from sentinel.publishers.lark_doc import LarkDocPublisher

        config_dir = settings.resolved_config_dir
        bitable_pub = LarkBitablePublisher(config_dir)
        doc_pub = LarkDocPublisher(config_dir)
        bitable_pub.publish(market, snapshots)
        doc_pub.publish(market, snapshots)
        typer.echo(f"published to Feishu for {market.value}")


@app.command()
def evaluate(
    symbol: str = typer.Argument(..., help="标的代码"),
    market: Market = typer.Option(..., "--market"),
    asset_class: str = typer.Option("equity", "--asset-class"),
    policy: str = typer.Option("neutral", "--policy", help="政策评级"),
    sector: str | None = typer.Option(None, "--sector"),
    publish: bool = typer.Option(False, "--publish"),
) -> None:
    from sentinel.mgfs.config_loader import load_mgfs_config, build_orchestrator
    from sentinel.mgfs.factor_plugin import TargetInfo
    from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher

    settings = AppSettings()
    config_path = settings.resolved_config_dir / "mgfs_config.yaml"
    try:
        config = load_mgfs_config(config_path)
    except FileNotFoundError:
        typer.echo("错误: 未找到 mgfs_config.yaml，请检查配置目录", err=True)
        raise typer.Exit(1)

    fetchers = {"valuation": EastmoneyValuationFetcher()}
    orchestrator = build_orchestrator(
        config, config_dir=settings.resolved_config_dir, fetchers=fetchers
    )

    target = TargetInfo(
        symbol=symbol,
        market=market,
        asset_class=asset_class,
        sector=sector,
    )
    decision = orchestrator.evaluate(target, policy_rating=policy)

    typer.echo(f"\n{'='*50}")
    typer.echo("《投资权衡与决策说明书》")
    typer.echo(f"{'='*50}")
    typer.echo(f"标的: {decision.target.symbol} ({decision.target.market.value})")
    typer.echo(f"资产类别: {decision.target.asset_class}")
    typer.echo(f"评估时间: {decision.generated_at}")
    typer.echo("-" * 30)
    for key, score in decision.factor_scores.items():
        typer.echo(f"{score.factor_name}: {score.score:.1f}/{score.max_score}")
    typer.echo("-" * 30)
    typer.echo(f"原始加权分: {decision.raw_total}")
    typer.echo(f"政策乘数: {decision.policy_multiplier}")
    typer.echo(f"最终得分: {decision.final_score}")
    typer.echo(f"评级: {decision.rating}")
    typer.echo(f"建议动作: {decision.action}")
    if decision.report_sections.get("watermark"):
        typer.echo(f"⚠️  {decision.report_sections['watermark']}")
    oc = decision.report_sections.get('overall_confidence')
    typer.echo(f"综合置信度: {oc:.0%}" if oc is not None else "综合置信度: N/A")
    typer.echo(f"告警级别: {decision.alert_level.value}")
    if decision.circuit_breakers_triggered:
        typer.echo("触发熔断:")
        for cb in decision.circuit_breakers_triggered:
            action_label = cb.get("action") or cb.get("alert_level", "unknown")
            typer.echo(f"  - [{action_label}] {cb['message']}")
    typer.echo(f"{'='*50}\n")

    if publish:
        typer.echo("已推送至飞书文档")


@app.command()
def scan(
    theme: str = typer.Argument(..., help="宏观主题名称 (如 AI_Compute_Infrastructure)"),
    roles: str | None = typer.Option(None, "--roles", help="逗号分隔的生态角色过滤 (如 symbiotic_infra,upstream_resource)"),
    policy: str = typer.Option("neutral", "--policy", help="政策评级"),
    publish: bool = typer.Option(False, "--publish", help="推送至飞书"),
) -> None:
    """扫描指定产业链主题，筛选高护城河+低估值的价值标的。"""
    from sentinel.mgfs.config_loader import load_mgfs_config, build_orchestrator
    from sentinel.mgfs.scanner import EcosystemScanner
    from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher
    from sentinel.publishers.mgfs_report import build_ecosystem_scan_report

    settings = AppSettings()
    config_dir = settings.resolved_config_dir
    config_path = config_dir / "mgfs_config.yaml"

    try:
        config = load_mgfs_config(config_path)
    except FileNotFoundError:
        typer.echo("错误: 未找到 mgfs_config.yaml，请检查配置目录", err=True)
        raise typer.Exit(1)

    fetchers = {"valuation": EastmoneyValuationFetcher()}
    orchestrator = build_orchestrator(
        config, config_dir=config_dir, fetchers=fetchers
    )

    scanner = EcosystemScanner(
        orchestrator,
        moat_config_path=config_dir / "moat_static_base.yaml",
    )

    target_roles = [r.strip() for r in roles.split(",")] if roles else None
    result = scanner.scan_theme(theme, target_roles=target_roles, policy_rating=policy)

    # CLI output
    typer.echo("=" * 60)
    typer.echo("MGFS 产业链价值扫描报告")
    typer.echo("=" * 60)
    typer.echo(f"主题: {result.theme}")
    typer.echo(f"候选总数: {result.total_candidates}")
    typer.echo(f"通过筛选: {result.filtered_count}")
    typer.echo("-" * 40)

    for decision in result.reports:
        role = decision.target.ecosystem_role or "unknown"
        moat_score = decision.factor_scores.get("moat")
        moat_val = moat_score.score if moat_score else 0.0
        typer.echo(
            f"  {decision.target.symbol} ({decision.target.name or 'N/A'}) | 角色: {role}"
        )
        typer.echo(f"   护城河: {moat_val:.1f}")
        typer.echo(
            f"   最终得分: {decision.final_score:.2f} | 评级: {decision.rating}"
        )
        typer.echo(f"   建议: {decision.action}")
        typer.echo("")

    summary = result.summary
    skipped_veto = summary.get("skipped_by_veto", 0)
    skipped_zone = summary.get("skipped_by_zone", 0)
    skipped_moat = summary.get("skipped_by_moat", 0)
    skipped_roles = summary.get("skipped_by_role", 0)

    if skipped_veto:
        typer.echo(f"  {skipped_veto} 只标的触发熔断被剔除")
    if skipped_zone:
        typer.echo(f"  {skipped_zone} 只标的估值不在击球区")
    if skipped_moat:
        typer.echo(f"  {skipped_moat} 只标的护城河不足被剔除")
    if skipped_roles:
        typer.echo(f"  {skipped_roles} 只标的因角色过滤被跳过")
    typer.echo("=" * 60)

    if publish:
        report = build_ecosystem_scan_report(result)
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
