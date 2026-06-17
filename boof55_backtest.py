"""
BOOF55 Backtest — A/B/C variants across multiple symbols
Fetches 60 days of 1-min bars, runs all 3 strategies, reports metrics.
"""
import alpaca_trade_api as t
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

ET  = pytz.timezone("America/New_York")
api = t.REST('PKKPME54QJA3KBPAJ3QZZOJXDF','J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y','https://paper-api.alpaca.markets')

SYMBOLS = [
    "TSLA","NVDA","AMD","HOOD","COIN","APP","MSFT","AMZN","META","PLTR",
    "UPST","SMCI","MSTR","CRWD","AVGO"
]

START = "2026-04-01"
END   = "2026-06-13"

# ── Trade simulator ────────────────────────────────────────────────────────────

def run_trade(df, entry_i, side, tp, sl, max_bars):
    if entry_i >= len(df): return None
    entry = df.iloc[entry_i]["open"]
    if entry <= 0: return None

    tp_price = entry * (1 + tp) if side == "long" else entry * (1 - tp)
    sl_price = entry * (1 - sl) if side == "long" else entry * (1 + sl)

    for j in range(entry_i, min(entry_i + max_bars, len(df))):
        bar = df.iloc[j]
        if side == "long":
            if bar["low"]  <= sl_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "SL",   "pnl": -sl,  "bars": j - entry_i}
            if bar["high"] >= tp_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "TP",   "pnl":  tp,  "bars": j - entry_i}
        else:
            if bar["high"] >= sl_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "SL",   "pnl": -sl,  "bars": j - entry_i}
            if bar["low"]  <= tp_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "TP",   "pnl":  tp,  "bars": j - entry_i}

    j = min(entry_i + max_bars, len(df) - 1)
    exit_price = df.iloc[j]["close"]
    pnl = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
    return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "TIME", "pnl": pnl, "bars": j - entry_i}

# ── Strategy A — VWAP Trend Pullback ──────────────────────────────────────────

def boof55a(df, tp=0.010, sl=0.005, max_bars=90):
    df = df.copy()
    df["vwap"]  = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["rvol"]  = df["volume"] / df["volume"].rolling(20).mean()
    trades = []
    in_trade_until = 0
    for i in range(30, len(df) - max_bars):
        if i < in_trade_until: continue
        row  = df.iloc[i]
        prev = df.iloc[i - 1]
        long_signal = (
            row["close"]  > row["vwap"]
            and row["close"]  > row["ema20"]
            and prev["low"]  <= prev["vwap"]
            and row["close"]  > prev["high"]
            and row["rvol"]  >= 1.5
        )
        short_signal = (
            row["close"]  < row["vwap"]
            and row["close"]  < row["ema20"]
            and prev["high"] >= prev["vwap"]
            and row["close"]  < prev["low"]
            and row["rvol"]  >= 1.5
        )
        if long_signal:
            t = run_trade(df, i + 1, "long",  tp, sl, max_bars)
            if t: trades.append(t); in_trade_until = t["exit_i"]
        elif short_signal:
            t = run_trade(df, i + 1, "short", tp, sl, max_bars)
            if t: trades.append(t); in_trade_until = t["exit_i"]
    return trades

# ── Strategy B — Multi-Timeframe Breakout ─────────────────────────────────────

def boof55b(df, tp=0.015, sl=0.005, max_bars=120):
    df = df.copy()
    df["vwap"]    = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["rvol"]    = df["volume"] / df["volume"].rolling(20).mean()
    df["high_30m"] = df["high"].rolling(30).max().shift(1)
    df["low_30m"]  = df["low"].rolling(30).min().shift(1)
    trades = []
    in_trade_until = 0
    for i in range(40, len(df) - max_bars):
        if i < in_trade_until: continue
        row  = df.iloc[i]
        prev = df.iloc[i - 1]
        long_signal = (
            prev["close"] <= prev["high_30m"]
            and row["close"]  > row["high_30m"]
            and row["close"]  > row["vwap"]
            and row["rvol"]  >= 1.5
        )
        short_signal = (
            prev["close"] >= prev["low_30m"]
            and row["close"]  < row["low_30m"]
            and row["close"]  < row["vwap"]
            and row["rvol"]  >= 1.5
        )
        if long_signal:
            t = run_trade(df, i + 1, "long",  tp, sl, max_bars)
            if t: trades.append(t); in_trade_until = t["exit_i"]
        elif short_signal:
            t = run_trade(df, i + 1, "short", tp, sl, max_bars)
            if t: trades.append(t); in_trade_until = t["exit_i"]
    return trades

# ── Strategy C — Structural Reversal ──────────────────────────────────────────

def boof55c(df, tp=0.015, sl=0.005, max_bars=120):
    df = df.copy()
    df["atr"]        = (df["high"] - df["low"]).rolling(14).mean()
    df["rvol"]       = df["volume"] / df["volume"].rolling(20).mean()
    df["swing_high"] = df["high"].rolling(10).max().shift(1)
    df["swing_low"]  = df["low"].rolling(10).min().shift(1)
    trades = []
    in_trade_until = 0
    for i in range(30, len(df) - max_bars):
        if i < in_trade_until: continue
        row  = df.iloc[i]
        prev = df.iloc[i - 1]
        long_signal = (
            prev["low"]   <= prev["swing_low"]
            and row["close"]  > prev["high"]
            and (row["close"] - prev["low"]) >= row["atr"] * 0.5
            and row["rvol"]  >= 1.2
        )
        short_signal = (
            prev["high"]  >= prev["swing_high"]
            and row["close"]  < prev["low"]
            and (prev["high"] - row["close"]) >= row["atr"] * 0.5
            and row["rvol"]  >= 1.2
        )
        if long_signal:
            t = run_trade(df, i + 1, "long",  tp, sl, max_bars)
            if t: trades.append(t); in_trade_until = t["exit_i"]
        elif short_signal:
            t = run_trade(df, i + 1, "short", tp, sl, max_bars)
            if t: trades.append(t); in_trade_until = t["exit_i"]
    return trades

# ── Metrics ────────────────────────────────────────────────────────────────────

def metrics(trades, days):
    if not trades: return None
    df   = pd.DataFrame(trades)
    wins = df[df["result"] == "TP"]
    loss = df[df["result"] == "SL"]
    time = df[df["result"] == "TIME"]
    n    = len(df)
    wr   = len(wins) / n
    avg_win  = wins["pnl"].mean() if len(wins) else 0
    avg_loss = loss["pnl"].mean() if len(loss) else 0  # negative
    pf   = (len(wins) * avg_win) / (len(loss) * abs(avg_loss)) if len(loss) > 0 and avg_loss != 0 else float("inf")
    ev   = df["pnl"].mean()
    avg_bars = df["bars"].mean()
    return {
        "Trades":      n,
        "Trades/day":  round(n / days, 2),
        "WR":          f"{wr*100:.1f}%",
        "PF":          f"{pf:.2f}",
        "EV":          f"{ev*100:+.3f}%",
        "Avg hold":    f"{avg_bars:.0f} bars",
        "TP hits":     len(wins),
        "SL hits":     len(loss),
        "Time exits":  len(time),
    }

# ── Fetch & run ────────────────────────────────────────────────────────────────

print(f"Fetching {len(SYMBOLS)} symbols {START} → {END}...")
all_trades = {"A": [], "B": [], "C": []}
total_days = 0

for sym in SYMBOLS:
    try:
        df = api.get_bars(sym, '1Min', start=START, end=END, feed='iex', limit=50000).df
        df = df.tz_convert(ET)
        # RTH only
        df = df.between_time("09:30", "16:00")
        if len(df) < 500:
            print(f"  {sym}: too few bars ({len(df)}) — skip")
            continue
        days = df.index.normalize().nunique()
        total_days = max(total_days, days)
        print(f"  {sym}: {len(df)} bars  {days} days")
        all_trades["A"] += boof55a(df)
        all_trades["B"] += boof55b(df)
        all_trades["C"] += boof55c(df)
    except Exception as e:
        print(f"  {sym}: FAILED — {e}")

trading_days = total_days if total_days else 50

# ── Report ─────────────────────────────────────────────────────────────────────

print(f"\n{'='*80}")
print(f"BOOF55 BACKTEST  |  {START} → {END}  |  {len(SYMBOLS)} symbols  |  ~{trading_days} trading days")
print(f"{'='*80}")

headers = ["Variant","Trades","Trades/day","WR","PF","EV","Avg hold","TP hits","SL hits","Time exits"]
print(f"{'Variant':<10} {'Trades':>7} {'T/day':>6} {'WR':>7} {'PF':>6} {'EV':>8} {'AvgHold':>8} {'TPs':>6} {'SLs':>6} {'TIME':>6}")
print("-" * 80)

configs = {
    "55A (VWAP)":    ("A", 0.010, 0.005,  90),
    "55B (Break)":   ("B", 0.015, 0.005, 120),
    "55C (Reversal)":("C", 0.015, 0.005, 120),
}

for name, (key, tp, sl, mb) in configs.items():
    m = metrics(all_trades[key], trading_days)
    if m:
        print(f"{name:<14} {m['Trades']:>7} {m['Trades/day']:>6} {m['WR']:>7} {m['PF']:>6} {m['EV']:>8} {m['Avg hold']:>8} {m['TP hits']:>6} {m['SL hits']:>6} {m['Time exits']:>6}")
    else:
        print(f"{name:<14} {'NO TRADES':>60}")

print(f"\nNote: TP={tp*100:.1f}%/SL={sl*100:.1f}% for each variant as specified.")
print(f"Backtest uses RTH bars only (09:30-16:00 ET), no overlapping trades per symbol.")
