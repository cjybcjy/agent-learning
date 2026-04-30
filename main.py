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
) -> None:
    del report, time
    settings = AppSettings()
    application = build_application(settings)
    snapshots = application.run_market(market=market)
    typer.echo(f"collected {len(snapshots)} ranked snapshot for {market.value}")
    for s in snapshots:
        direction = "bullish" if s.directed_heat > 0 else ("bearish" if s.directed_heat < 0 else "neutral")
        delta = f"Δ{s.change_pct:+.1f}%" if s.change_pct is not None else "NEW"
        typer.echo(f"  {s.symbol}: heat={s.directed_heat:.2f} ({direction}) [{delta}]")


if __name__ == "__main__":
    app()
