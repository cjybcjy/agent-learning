# Phase 3 Implementation Plan — Analysis Engine

> Status: COMPLETE  
> Date: 2026-04-30

## Scope

Phase 3 adds the analysis engine that transforms raw collector output into ranked heat snapshots:

1. **Anti-spam filter** — account age, follower threshold, URL dedup
2. **Heat calculator** — V_base (min-max normalized), M_kol (KOL amplifier), H_score (directed)
3. **Ranking** — bullish/bearish Top N, neutral fallback
4. **Pipeline integration** — full chain: collect → filter → compute_heat → rank → persist
5. **CLI output** — shows ranked symbols with directed heat

## Tasks Completed

| Task | Commit | Files |
|------|--------|-------|
| T1: Anti-spam filter | `e6f9130` | `sentinel/antispam/__init__.py`, `tests/test_antispam.py` |
| T2: Heat calculator | `10e0def` | `sentinel/analyzers/__init__.py`, `tests/test_heat_calculator.py` |
| T3: Ranking logic | `670afb9` | `sentinel/analyzers/ranking.py`, `tests/test_ranking.py` |
| T4: Pipeline integration | `5f3992e` | `sentinel/services/run_pipeline.py`, `sentinel/app.py`, `main.py`, tests updated |
| T5: Verification | — | 28/28 tests PASS, E2E output verified |

## Architecture After Phase 3

```
CLI → CollectorRegistry → [async collect] → filter_spam → compute_heat → rank_snapshots → persist → output
```

## Formulas Implemented

- $V_{base} = w_1 P_{norm} + w_2 C_{norm} + w_3 L_{norm} + w_4 S_{norm}$
- $M_{kol} = 1 + w_k \cdot (K_{mentions} / P_{total})$
- $H_{score} = V_{base} \cdot M_{kol} \times Sent_{fin}$ (neutral mode when Sent=0: H = V_base * M_kol)

## Next: Phase 4 Candidates

- FinBERT ONNX sentiment scoring (replace placeholder 0.0)
- Environment-variable changes (Δ%) computation from DuckDB history
- Feishu publisher (Bitable + Doc output via lark-cli)
