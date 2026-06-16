# Gap Breakout Strategy — Locked Specification
**Validated:** Walk-forward test, Train 2022-2024 → Test 2025-2026

---

## Entry Conditions (ALL must be true)

| Filter | Value |
|--------|-------|
| Gap up | > 1% from prev close to open |
| RVOL | >= 1.5x (20-day avg daily volume) |
| Time window | 9:30 – 10:00 ET only |
| Signal | First 1-min close above PDH **or** PMH |
| Direction | Long only |

---

## Exit

| Parameter | Value |
|-----------|-------|
| Hold time | 2 hours fixed from entry bar |
| No TP/SL | Time-based exit only |

---

## Universe (30 symbols — frozen from 2022-2024 training)

Selected by highest EV in training period. MCap > $100B, AvgVol > 5M, ATR% < 5%.

```
AAPL  AMZN  APP   ARM   AVGO  AXP   BLK   CAT   CVX   ENPH
FANG  FCX   HD    IBM   LCID  LRCX  MDT   MRNA  MS    MU
ORCL  PANW  PLTR  RBLX  RIVN  SMCI  TTWO  ORCL  RBLX  TTWO
```

*(Full ranked list in walkforward_train.csv)*

---

## Validated Performance

### Training Period (2022–2024)
| Metric | Value |
|--------|-------|
| Trades | 382 |
| Win Rate | 69.9% |
| Avg EV | +1.046% |
| Profit Factor | 2.526 |
| Total Return | +399% |
| Trades/week | 7.3 |

### Test Period (2025–2026, OUT-OF-SAMPLE)
| Metric | Value |
|--------|-------|
| Trades | 84 |
| Win Rate | 71.4% |
| Avg EV | +1.254% |
| Profit Factor | 2.986 |
| Total Return | +105% |
| Trades/week | 7.0 |

### Gap Breakdown (Test)
| Bucket | N | WR | EV | PF |
|--------|---|----|----|-----|
| Gap 1-2% | 32 | 87.5% | +1.878% | 5.503 |
| Gap >2%  | 52 | 61.5% | +0.871% | 2.140 |

---

## Key Findings

- **Gap 1-2% is the stronger bucket** — higher WR and PF than gap >2%
- **RVOL >= 1.5 is the single most important filter** — removes ~85% of bad days
- **Early window (9:30-10:00) only** — almost all qualifying breakouts happen here
- **2hr hold > TP/SL** — time exit outperforms fixed TP/SL on this universe
- **PDH and PMH both valid** — whichever is broken first is the signal

---

## Best Individual Symbols (Test Period)
| Sym | N | WR | EV | PF |
|-----|---|----|----|-----|
| ARM | 9 | 66.7% | +2.298% | 6.43 |
| ORCL | 7 | 71.4% | +2.347% | 3.68 |
| MU | 6 | 66.7% | +1.230% | 2.17 |
| RBLX | 4 | 75.0% | +1.670% | 4.24 |
| LRCX | 3 | 100% | +2.311% | — |

---

## What NOT to Do
- Do NOT widen the time window past 10:00 AM — midday kills the edge
- Do NOT trade gap >2% on low-RVOL days — fake institutional interest
- Do NOT use TP/SL instead of the 2hr hold — cuts winners short
- Do NOT add symbols without walk-forward validation

---

## Files
| File | Description |
|------|-------------|
| `walkforward_train.csv` | All training trades 2022-2024 |
| `walkforward_test.csv` | All test trades 2025-2026 |
| `refined_results.csv` | In-sample results (reference only) |
| `data/train/*.parquet` | 3yr 1-min bars per symbol |
| `data/1m/*.parquet` | 6-month 1-min bars per symbol |
| `walkforward.py` | Full walk-forward backtest script |
