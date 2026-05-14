from __future__ import annotations

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

    settings = AppSettings()
    config_path = settings.resolved_config_dir / "mgfs_config.yaml"
    try:
        config = load_mgfs_config(config_path)
    except FileNotFoundError:
        typer.echo("错误: 未找到 mgfs_config.yaml，请检查配置目录", err=True)
        raise typer.Exit(1)
    orchestrator = build_orchestrator(config, config_dir=settings.resolved_config_dir)

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
    typer.echo(f"综合置信度: {decision.report_sections.get('overall_confidence', 'N/A')}")
    typer.echo(f"告警级别: {decision.alert_level.value}")
    if decision.circuit_breakers_triggered:
        typer.echo("触发熔断:")
        for cb in decision.circuit_breakers_triggered:
            action_label = cb.get("action") or cb.get("alert_level", "unknown")
            typer.echo(f"  - [{action_label}] {cb['message']}")
    typer.echo(f"{'='*50}\n")

    if publish:
        typer.echo("已推送至飞书文档")


if __name__ == "__main__":
    app()
