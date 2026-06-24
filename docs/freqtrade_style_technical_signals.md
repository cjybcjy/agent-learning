# Freqtrade-style Technical Signals for MGFS

This project does not embed Freqtrade or run a trading bot. It borrows the
strategy workflow shape:

1. `populate_indicators`: compute point-in-time indicators from OHLCV bars.
2. `populate_entry_trend`: label research-only entry watch candidates.
3. `populate_exit_trend`: label research-only exit risk candidates.
4. `analyze_as_of`: evaluate a historical cut without reading future bars.

The implementation lives in `sentinel.mgfs.technical_strategy.AShareTechnicalStrategy`
and consumes the existing `OHLCV` model. It currently computes MA20, MA60,
MA120, RSI(14), ATR(14), 20-day volume ratio, MA60 bias, and MA60 slope.

## Output Boundary

The output is a research signal, not a direct trading instruction.

- `entry_label = "entry_watch"` means the stock entered a technical observation
  zone such as a MA60 pullback recovery.
- `exit_label = "exit_risk"` means the stock triggered a risk condition such as
  volume breakdown or trend breakdown.
- `instruction_boundary = "research_only"` is carried into `FactorScore.details`
  so downstream UI and reports can preserve the boundary.

`TimingFactorPlugin` writes the latest signal under:

```json
{
  "technical_signal": {
    "entry_label": "entry_watch",
    "entry_tags": ["pullback_recovery"],
    "exit_label": "none",
    "entry_zone_low": 108.3,
    "entry_zone_high": 114.47,
    "stop_reference": 107.86,
    "instruction_boundary": "research_only"
  }
}
```

## A-share Adaptation Notes

- The strategy keeps A-share-specific guards in the existing timing layer:
  insufficient K-line sample downgrade, suspended trading / one-price-board
  neutralization, ATR band clamping, and confidence tiering.
- Entry and exit labels should remain downstream review inputs. They must not
  mutate stock pools, YAML config, or position state without a separate human
  confirmation flow.
