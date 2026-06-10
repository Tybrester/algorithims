"""
Backtest runner for Boof 22 and Boof 23
Uses cached 5-min pkl data — Boof No-ETF list, Dec 2025 – May 2026
"""

import pickle, os
import pandas as pd
import numpy as np
from collections import defaultdict

from boof22_algo import run_boof22, CONFIG22
from boof23_algo import run_boof23, CONFIG23

# ── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOLS   = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']
START     = pd.Timestamp("2025-06-01", tz="America/New_York")
END       = pd.Timestamp("2026-06-09", tz="America/New_York")
CACHE_DIR = "boof_cache"
ET        = "America/New_York"


# ── REPORT ────────────────────────────────────────────────────────────────────
def report(trades: pd.DataFrame, title="BACKTEST"):
    if trades.empty:
        print(f"{title}: No trades found.")
        return

    wins   = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]

    gross_win  = wins["pnl"].sum()
    gross_loss = abs(losses["pnl"].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    t = trades.copy()
    t["cum"]  = t["pnl"].cumsum()
    t["peak"] = t["cum"].cummax()
    t["dd"]   = t["cum"] - t["peak"]

    print("=" * 80)
    print(title)
    print("=" * 80)
    print(f"Trades:        {len(t)}")
    print(f"Win Rate:      {(t['pnl'] > 0).mean() * 100:.1f}%")
    print(f"Avg Trade:     {t['pnl'].mean() * 100:+.3f}%")
    print(f"Avg Winner:    {wins['pnl'].mean() * 100:+.3f}%" if not wins.empty else "Avg Winner:    --")
    print(f"Avg Loser:     {losses['pnl'].mean() * 100:+.3f}%" if not losses.empty else "Avg Loser:     --")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Total Return:  {t['pnl'].sum() * 100:+.2f}%")
    print(f"Max Drawdown:  {t['dd'].min() * 100:+.2f}%")

    if "direction" in t.columns:
        print("\nBY DIRECTION:")
        print(
            t.groupby("direction")["pnl"]
            .agg(
                trades="count",
                win_rate=lambda x: (x > 0).mean() * 100,
                avg_pnl=lambda x: x.mean() * 100,
                total_pnl=lambda x: x.sum() * 100,
            )
            .round(2)
        )

    if "setup" in t.columns and t["setup"].notna().any():
        print("\nBY SETUP:")
        print(
            t.groupby("setup")["pnl"]
            .agg(
                trades="count",
                win_rate=lambda x: (x > 0).mean() * 100,
                avg_pnl=lambda x: x.mean() * 100,
                total_pnl=lambda x: x.sum() * 100,
            )
            .round(2)
        )

    if "result" in t.columns:
        print("\nBY EXIT:")
        print(
            t.groupby("result")["pnl"]
            .agg(
                trades="count",
                win_rate=lambda x: (x > 0).mean() * 100,
                avg_pnl=lambda x: x.mean() * 100,
            )
            .round(3)
        )


# ── DATA LOADER ───────────────────────────────────────────────────────────────
def load_symbol(sym):
    names = [sym, 'GOOGL'] if sym == 'GOOG' else [sym]
    for name in names:
        for key in ["2025-01-01_2026-12-31", "2024-01-01_2026-12-31"]:
            path = os.path.join(CACHE_DIR, f"{name}_{key}.pkl")
            if os.path.exists(path):
                df = pickle.load(open(path, "rb"))
                if not isinstance(df, pd.DataFrame):
                    continue
                df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
                df.columns = [c.lower() for c in df.columns]
                df = df[~df.index.duplicated(keep='first')].sort_index()
                df = df[(df.index >= START) & (df.index <= END)]
                if len(df) < 300:
                    continue
                return df
    return None


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Period: {START.date()} → {END.date()}")
    print(f"Symbols: {SYMBOLS}\n")

    all22, all23 = [], []

    for sym in SYMBOLS:
        df = load_symbol(sym)
        if df is None:
            print(f"  {sym}: NO DATA — skip")
            continue

        print(f"  {sym}: {len(df)} bars", end="  ")

        t22 = run_boof22(df)
        t23 = run_boof23(df)

        print(f"B22:{len(t22)} trades  B23:{len(t23)} trades")

        if not t22.empty: all22.append(t22)
        if not t23.empty: all23.append(t23)

    print()

    combined22 = pd.concat(all22, ignore_index=True) if all22 else pd.DataFrame()
    combined23 = pd.concat(all23, ignore_index=True) if all23 else pd.DataFrame()

    report(combined22, f"BOOF 22 — Volume Zone Reversal  [{START.date()} → {END.date()}]")
    print()
    report(combined23, f"BOOF 23 — Swing Breakout (breakout mode)  [{START.date()} → {END.date()}]")

    # Also run Boof 23 in reversal mode
    print()
    from boof23_algo import Boof23Config
    cfg_rev = Boof23Config(mode="reversal")
    all23r = []
    for sym in SYMBOLS:
        df = load_symbol(sym)
        if df is None: continue
        t = run_boof23(df, cfg_rev)
        if not t.empty: all23r.append(t)
    combined23r = pd.concat(all23r, ignore_index=True) if all23r else pd.DataFrame()
    report(combined23r, f"BOOF 23 — Swing Reversal (reversal mode)  [{START.date()} → {END.date()}]")
