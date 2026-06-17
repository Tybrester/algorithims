#!/usr/bin/env python3
"""
BOOF33 Tests
  Test 1 : Month-by-month profitability (Jan-Jun 2025)
  Test 2 : Slippage stress (0.05%, 0.10%, 0.15%)
  Test 3 : Walk-forward  (train Jan-Apr → test May-Jun)

Uses boof32_data_*.csv cached 1-min bars (same as boof33_optimized.py).
Signal: support sweep + reclaim, close < VWAP, 9:30-10:30 ET
Exit  : 50% at +0.50%, runner to +1.50%, SL -0.30%, BE stop after TP1
"""

import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')

# ── Universe (from boof33_optimized.py) ───────────────────────────────────────
SYMBOLS = [
    "FCX", "NEM", "MU", "SCCO", "KLAC", "PANW",
    "TSLA", "CRWD", "QCOM", "HOOD", "TER", "CORZ",
    "APP", "DDOG", "COIN", "MDB", "NET", "ZS",
]

# ── Strategy params ────────────────────────────────────────────────────────────
LOOKBACK      = 80
SUPPORT_TOL   = 0.002
SWEEP_BUFFER  = 0.001
COOLDOWN_BARS = 30
MAX_HOLD_BARS = 60
BASE_SLIP     = 0.0002   # base slippage used in signal entry price
TP1           = 0.005    # +0.50%
TP2           = 0.015    # +1.50%
SL            = 0.003    # -0.30%
# Time window: 9:30-10:30 ET = 15:30-16:30 UTC
WINDOW_START = "15:30"
WINDOW_END   = "16:30"

# ── Indicator builder ──────────────────────────────────────────────────────────
def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]       = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["avg_vol_20"] = day["volume"].rolling(20).mean()
    day["rvol"]       = day["volume"] / day["avg_vol_20"]
    day["vwap_slope"] = day["vwap"].pct_change(5) * 100
    return day

# ── Support finder ─────────────────────────────────────────────────────────────
def find_support(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 30:
        return None, 0
    lows = window["low"].values
    best_level, best_touches = None, 0
    for low in lows:
        touches = np.sum(np.abs(lows - low) / low <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = low, touches
    if best_touches < 2:
        return None, 0
    return best_level, best_touches

# ── Signal detector ────────────────────────────────────────────────────────────
def detect_signal(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    bar = day.iloc[i]
    if (bar["low"]   < support * (1 - SWEEP_BUFFER) and
            bar["close"] > support and
            bar["close"] < bar["vwap"]):
        return True, {"support": support, "touches": touches, "entry_i": i + 1}
    return False, {}

# ── Exit simulator (scale-out with BE stop) ───────────────────────────────────
def simulate_exit(day, entry_i, entry_price, tp1=TP1, tp2=TP2, sl=SL, extra_slip=0.0):
    """
    50% off at tp1, runner to tp2 with BE stop.
    extra_slip is the additional one-way slippage to stress-test.
    """
    slip_cost = BASE_SLIP * 2 + extra_slip * 2   # entry + exit, both sides
    future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS]
    if future.empty:
        return 0.0, "no_future"
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        high_move = (bar["high"]  - entry_price) / entry_price
        low_move  = (bar["low"]   - entry_price) / entry_price
        if not half_out and low_move <= -sl:
            return -sl - slip_cost, "stop"
        if half_out and bar["close"] <= entry_price:
            return pnl - slip_cost, "scale_be"
        if not half_out and high_move >= tp1:
            pnl += 0.5 * tp1
            half_out = True
        if half_out and high_move >= tp2:
            pnl += 0.5 * tp2
            return pnl - slip_cost, "scale"
    final_move = (future.iloc[-1]["close"] - entry_price) / entry_price
    if half_out:
        pnl += 0.5 * final_move
        return pnl - slip_cost, "scale_time"
    return final_move - slip_cost, "time"

# ── Core setup scanner ─────────────────────────────────────────────────────────
def scan_all_setups(symbols=SYMBOLS):
    """
    Returns list of dicts, each containing raw trade info
    including the future bar DataFrame for flexible exit replay.
    """
    all_setups = []
    for symbol in symbols:
        cache_file = f"boof32_data_{symbol}.csv"
        if not os.path.exists(cache_file):
            print(f"  SKIP {symbol}: no cache file")
            continue
        df = pd.read_csv(cache_file, parse_dates=["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["date"]     = df["datetime"].dt.date
        df["time_utc"] = df["datetime"].dt.strftime("%H:%M")
        sym_count = 0
        for date, day in df.groupby("date"):
            day = day.copy().reset_index(drop=True)
            if len(day) < 150:
                continue
            day = add_indicators(day)
            last_trade_i = -999999
            for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - 2):
                t = day["time_utc"].iloc[i]
                if not (WINDOW_START <= t < WINDOW_END):
                    continue
                if i - last_trade_i < COOLDOWN_BARS:
                    continue
                found, signal = detect_signal(day, i)
                if not found:
                    continue
                entry_i = signal["entry_i"]
                if entry_i >= len(day):
                    continue
                entry_price = day["open"].iloc[entry_i] * (1 + BASE_SLIP)
                future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
                if future.empty:
                    continue
                all_setups.append(dict(
                    symbol=symbol,
                    date=date,
                    month=date.strftime("%Y-%m"),
                    entry_time=day["datetime"].iloc[entry_i],
                    entry_price=entry_price,
                    future=future,
                ))
                last_trade_i = i
                sym_count += 1
        print(f"  {symbol}: {sym_count} setups")
    print(f"\nTotal: {len(all_setups)} setups across {len(set(s['date'] for s in all_setups))} trading days")
    return all_setups

# ── Stats helper ───────────────────────────────────────────────────────────────
def pf(pnls):
    s = pd.Series(pnls)
    wins = s[s > 0].sum()
    loss = abs(s[s < 0].sum())
    return wins / loss if loss > 0 else float('inf')

def print_stats(label, pnls, indent="  "):
    if not pnls:
        print(f"{indent}{label:40s}  n:   0  —")
        return
    s = pd.Series(pnls)
    wr   = (s > 0).mean()
    pfv  = pf(pnls)
    ev   = s.mean()
    tot  = s.sum()
    tag  = "✓" if pfv >= 1.30 else ("~" if pfv >= 1.0 else "✗")
    print(f"{indent}{label:40s}  n:{len(s):4d}  WR:{wr:.1%}  PF:{pfv:.2f}  EV:{ev:.4%}  Sum:{tot:.3%}  {tag}")

# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Month-by-month breakdown
# ══════════════════════════════════════════════════════════════════════════════
def test1_monthly(all_setups):
    print("\n" + "="*70)
    print("  TEST 1: Month-by-Month Profitability")
    print("="*70)
    months = sorted(set(s['month'] for s in all_setups))
    monthly_results = {}
    for mo in months:
        sub = [s for s in all_setups if s['month'] == mo]
        pnls = [simulate_exit(s['future'], s['entry_price'])[0] for s in sub]
        monthly_results[mo] = pnls
        print_stats(mo, pnls, indent="  ")

    # Summary
    all_pnls = [p for v in monthly_results.values() for p in v]
    profitable_months = sum(1 for v in monthly_results.values() if sum(v) > 0)
    print(f"\n  Profitable months: {profitable_months}/{len(months)}")
    print_stats("FULL PERIOD", all_pnls, indent="  ")
    return monthly_results

# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Slippage stress
# ══════════════════════════════════════════════════════════════════════════════
def test2_slippage(all_setups):
    print("\n" + "="*70)
    print("  TEST 2: Slippage Stress (added to entries/exits)")
    print("="*70)
    print(f"  {'Config':<40}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'Sum':>8}  OK")
    for slip_bp, label in [
        (0.0000, "Base (0.02% base only)"),
        (0.0005, "+0.05% extra slippage"),
        (0.0010, "+0.10% extra slippage"),
        (0.0015, "+0.15% extra slippage"),
    ]:
        pnls = [simulate_exit(s['future'], s['entry_price'], extra_slip=slip_bp)[0] for s in all_setups]
        print_stats(label, pnls, indent="  ")

# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Walk-forward (train Jan-Apr, test May-Jun)
# ══════════════════════════════════════════════════════════════════════════════
def test3_walkforward(all_setups):
    print("\n" + "="*70)
    print("  TEST 3: Walk-Forward  (Train Jan-Apr → Test May-Jun)")
    print("="*70)

    months = sorted(set(s['month'] for s in all_setups))
    if len(months) < 2:
        print("  Not enough months in data for walk-forward.")
        return

    # Determine split: last 2 months = OOS, rest = IS
    oos_months = set(months[-2:])
    is_months  = set(months[:-2])

    is_setups  = [s for s in all_setups if s['month'] in is_months]
    oos_setups = [s for s in all_setups if s['month'] in oos_months]

    print(f"\n  In-sample  (train): {sorted(is_months)}")
    is_pnls = [simulate_exit(s['future'], s['entry_price'])[0] for s in is_setups]
    print_stats("In-sample result", is_pnls, indent="  ")

    # IS per-symbol ranking (best → use top N in OOS)
    by_sym_is = {}
    for s in is_setups:
        by_sym_is.setdefault(s['symbol'], []).append(
            simulate_exit(s['future'], s['entry_price'])[0]
        )
    sym_pf = {sym: pf(p) for sym, p in by_sym_is.items() if p}
    sym_rank = sorted(sym_pf, key=lambda s: -sym_pf[s])
    print(f"\n  IS symbol ranking (top PF):")
    for sym in sym_rank[:10]:
        p = by_sym_is[sym]
        print(f"    {sym:<6}  n:{len(p):3d}  PF:{sym_pf[sym]:.2f}  EV:{np.mean(p):.4%}")

    top5_is = set(sym_rank[:5])
    top10_is = set(sym_rank[:10])

    print(f"\n  Out-of-sample (test): {sorted(oos_months)}")
    oos_pnls = [simulate_exit(s['future'], s['entry_price'])[0] for s in oos_setups]
    print_stats("OOS — all symbols",   oos_pnls, indent="  ")

    oos_top5  = [s for s in oos_setups if s['symbol'] in top5_is]
    oos_top10 = [s for s in oos_setups if s['symbol'] in top10_is]
    pnls5  = [simulate_exit(s['future'], s['entry_price'])[0] for s in oos_top5]
    pnls10 = [simulate_exit(s['future'], s['entry_price'])[0] for s in oos_top10]
    print_stats(f"OOS — IS top-5 syms ({', '.join(sorted(top5_is))})",  pnls5,  indent="  ")
    print_stats(f"OOS — IS top-10 syms", pnls10, indent="  ")

    # OOS per-month
    print(f"\n  OOS month detail:")
    for mo in sorted(oos_months):
        sub = [s for s in oos_setups if s['month'] == mo]
        pnls = [simulate_exit(s['future'], s['entry_price'])[0] for s in sub]
        print_stats(mo, pnls, indent="    ")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("BOOF33 VALIDATION SUITE")
    print("Signal  : support sweep + reclaim, close < VWAP, 9:30-10:30 ET")
    print("Exit    : 50% @+0.50% / runner @+1.50% / SL -0.30% / BE stop")
    print(f"Universe: {len(SYMBOLS)} symbols")
    print("="*70)

    print("\nScanning setups (uses boof32_data_*.csv cache)...")
    all_setups = scan_all_setups()

    if not all_setups:
        print("ERROR: No setups found. Check that boof32_data_*.csv files exist.")
        exit(1)

    test1_monthly(all_setups)
    test2_slippage(all_setups)
    test3_walkforward(all_setups)

    print("\n" + "="*70)
    print("  DONE")
    print("="*70)
