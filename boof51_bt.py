"""
BOOF 51 Backtest — SPY / QQQ VWAP cross strategy
Tests all time window combinations including ALL DAY
Run: python boof51_bt.py
"""

import datetime, itertools
import pandas as pd
import numpy as np
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

PAPER_KEY    = "PK7N52NHGPS2GBVZU64BCUEDNO"
PAPER_SECRET = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
ET           = pytz.timezone("America/New_York")
SYMBOLS      = ["SPY", "QQQ"]

CONFIG = {
    "SPY": {
        "long":  {"tp": 0.0035, "sl": 0.0025},
        "short": {"tp": 0.0030, "sl": 0.0025},
    },
    "QQQ": {
        "long":  {"tp": 0.0045, "sl": 0.0030},
        "short": {"tp": 0.0040, "sl": 0.0030},
    },
}

MAX_TRADES_PER_SIDE = 5
COOLDOWN_MINUTES    = 10
TIME_STOP_MINUTES   = 90

# Morning windows to test individually and in pairs
MORNING_SLOTS = [
    ("09:30", "10:00"),
    ("09:30", "10:30"),
    ("09:30", "11:00"),
    ("09:30", "11:30"),
    ("09:30", "12:00"),
    ("09:45", "11:00"),
    ("10:00", "11:00"),
    ("10:00", "11:30"),
    ("10:00", "12:00"),
    ("11:00", "12:00"),
]
# Afternoon windows
AFTERNOON_SLOTS = [
    ("13:30", "15:00"),
    ("13:30", "15:30"),
    ("14:00", "15:30"),
]
ALL_DAY = [("09:30", "15:55")]


# ── Indicators ──────────────────────────────────────────────────────────────────

def compute_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["date"] = df["time"].dt.date
    df["typ"]  = (df["high"] + df["low"] + df["close"]) / 3
    # Fast VWAP using cumsum per date group via transform
    df["pv"]      = df["typ"] * df["volume"]
    df["cum_pv"]  = df.groupby("date")["pv"].cumsum()
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"]    = df["cum_pv"] / df["cum_vol"]
    df["ema9"]      = df["close"].ewm(span=9, adjust=False).mean()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    df["prev_close"] = df["close"].shift(1)
    df["prev_vwap"]  = df["vwap"].shift(1)
    return df


# ── Signal logic ────────────────────────────────────────────────────────────────

def long_signal(row):
    return (
        row["close"]       > row["vwap"] and
        row["prev_close"]  <= row["prev_vwap"] and
        row["volume"]      > row["vol_sma20"] * 1.2 and
        row["close"]       > row["ema9"]
    )

def short_signal(row):
    return (
        row["close"]       < row["vwap"] and
        row["prev_close"]  >= row["prev_vwap"] and
        row["volume"]      > row["vol_sma20"] * 1.2 and
        row["close"]       < row["ema9"]
    )


# ── Single backtest run ─────────────────────────────────────────────────────────

def run_backtest(df, sym, windows):
    cfg    = CONFIG[sym]
    trades = []

    # Group by date
    for date, day_df in df.groupby("date"):
        day_df = day_df.reset_index(drop=True)
        long_count = short_count = 0
        long_cooldown = short_cooldown = None

        for i in range(1, len(day_df) - 1):
            row  = day_df.iloc[i]
            t    = row["time"].strftime("%H:%M")

            # Check if within any allowed window
            in_window = any(ws <= t < we for ws, we in windows)
            if not in_window:
                continue

            if pd.isna(row["vwap"]) or pd.isna(row["vol_sma20"]):
                continue

            now_dt = row["time"]

            # LONG
            if long_count < MAX_TRADES_PER_SIDE:
                if long_cooldown is None or now_dt >= long_cooldown:
                    if long_signal(row):
                        entry_bar = day_df.iloc[i + 1]
                        ep  = entry_bar["open"]
                        tp  = round(ep * (1 + cfg["long"]["tp"]), 4)
                        sl  = round(ep * (1 - cfg["long"]["sl"]), 4)
                        result = _sim_exit(day_df, i + 1, ep, tp, sl, "long")
                        result.update({"sym": sym, "date": str(date), "side": "long",
                                       "entry": ep, "tp": tp, "sl": sl})
                        trades.append(result)
                        long_count   += 1
                        long_cooldown = now_dt + datetime.timedelta(minutes=COOLDOWN_MINUTES)

            # SHORT
            if short_count < MAX_TRADES_PER_SIDE:
                if short_cooldown is None or now_dt >= short_cooldown:
                    if short_signal(row):
                        entry_bar = day_df.iloc[i + 1]
                        ep  = entry_bar["open"]
                        tp  = round(ep * (1 - cfg["short"]["tp"]), 4)
                        sl  = round(ep * (1 + cfg["short"]["sl"]), 4)
                        result = _sim_exit(day_df, i + 1, ep, tp, sl, "short")
                        result.update({"sym": sym, "date": str(date), "side": "short",
                                       "entry": ep, "tp": tp, "sl": sl})
                        trades.append(result)
                        short_count   += 1
                        short_cooldown = now_dt + datetime.timedelta(minutes=COOLDOWN_MINUTES)

    return trades


def _sim_exit(day_df, entry_idx, ep, tp, sl, side):
    max_i = min(entry_idx + TIME_STOP_MINUTES, len(day_df) - 1)
    highs = day_df["high"].values
    lows  = day_df["low"].values
    closes = day_df["close"].values
    for j in range(entry_idx, max_i + 1):
        if side == "long":
            if highs[j] >= tp: return {"exit": tp, "exit_type": "tp", "pnl_pct": (tp - ep) / ep * 100}
            if lows[j]  <= sl: return {"exit": sl, "exit_type": "sl", "pnl_pct": (sl - ep) / ep * 100}
        else:
            if lows[j]  <= tp: return {"exit": tp, "exit_type": "tp", "pnl_pct": (ep - tp) / ep * 100}
            if highs[j] >= sl: return {"exit": sl, "exit_type": "sl", "pnl_pct": (ep - sl) / ep * 100}
    exit_px = closes[max_i]
    pnl = (exit_px - ep) / ep * 100 if side == "long" else (ep - exit_px) / ep * 100
    return {"exit": exit_px, "exit_type": "time", "pnl_pct": pnl}


# ── Stats summary ───────────────────────────────────────────────────────────────

def summarize(trades, label):
    if not trades:
        return {"label": label, "n": 0, "wr": 0, "avg_pnl": 0, "total_pnl": 0, "pf": 0}
    df  = pd.DataFrame(trades)
    wins = df[df["exit_type"] == "tp"]
    loss = df[df["exit_type"].isin(["sl", "time"])]
    wr   = len(wins) / len(df) * 100
    avg  = df["pnl_pct"].mean()
    tot  = df["pnl_pct"].sum()
    gross_w = wins["pnl_pct"].sum() if len(wins) else 0
    gross_l = abs(loss["pnl_pct"].sum()) if len(loss) else 1e-9
    pf   = gross_w / gross_l
    tpd  = len(df) / df["date"].nunique() if df["date"].nunique() else 0
    return {"label": label, "n": len(df), "wr": wr, "avg_pnl": avg,
            "total_pnl": tot, "pf": pf, "tpd": tpd}


# ── Main ─────────────────────────────────────────────────────────────────────────

def fetch_bars_cached(sym, data_client):
    cache = f"boof51_cache_{sym}.csv"
    if os.path.exists(cache):
        print(f"  {sym}: loading from cache...")
        df = pd.read_csv(cache, parse_dates=["time"])
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        return df

    print(f"  {sym}: fetching from Alpaca (chunked)...")
    now   = datetime.datetime.now(ET)
    start = now - datetime.timedelta(days=182)
    chunks = []
    chunk_start = start
    while chunk_start < now:
        chunk_end = min(chunk_start + datetime.timedelta(days=30), now)
        try:
            req = StockBarsRequest(symbol_or_symbols=sym,
                                   timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                                   start=chunk_start, end=chunk_end)
            resp = data_client.get_stock_bars(req).df.reset_index()
            if not resp.empty:
                chunks.append(resp)
            print(f"    chunk {chunk_start.strftime('%Y-%m-%d')} → {chunk_end.strftime('%Y-%m-%d')}: {len(resp)} bars")
        except Exception as e:
            print(f"    chunk error: {e}")
        chunk_start = chunk_end

    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    df = df.rename(columns={"timestamp": "time"})
    df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(ET)
    df = df[df["time"].dt.time >= datetime.time(9, 30)]
    df = df[df["time"].dt.time <= datetime.time(16, 0)]
    df.to_csv(cache, index=False)
    print(f"  {sym}: cached {len(df):,} bars to {cache}")
    return df


if __name__ == "__main__":
    import os, sys

    print("Loading cached 1-min bars...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        f = f"boof51_{sym}_1m.csv"
        if not os.path.exists(f):
            print(f"  ERROR: {f} not found. Run boof51_fetch.py first.")
            sys.exit(1)
        df = pd.read_csv(f)
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_indicators(df).dropna(subset=["vwap", "ema9", "vol_sma20"])
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars across {df['date'].nunique()} days", flush=True)

    # Build all window configs: morning singles, afternoon singles, morning+afternoon pairs, all day
    morning_singles   = [[s] for s in MORNING_SLOTS]
    afternoon_singles = [[s] for s in AFTERNOON_SLOTS]
    ma_pairs          = [[m, a] for m in MORNING_SLOTS for a in AFTERNOON_SLOTS]
    all_configs       = morning_singles + afternoon_singles + ma_pairs + [ALL_DAY]

    results = []
    total = len(SYMBOLS) * len(all_configs)
    done  = 0
    for sym in SYMBOLS:
        df = bars[sym]
        for windows in all_configs:
            label = f"{sym} | " + " + ".join(f"{w[0]}-{w[1]}" for w in windows)
            trades = run_backtest(df, sym, windows)
            stats  = summarize(trades, label)
            results.append(stats)
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{total} configs done...", flush=True)

    results_df = pd.DataFrame(results).sort_values("pf", ascending=False)

    print(f"\n{'='*100}")
    print(f"  BOOF51 BACKTEST RESULTS — All Window Combos (sorted by Profit Factor)")
    print(f"{'='*100}")
    print(f"{'Label':<55} {'N':>5} {'WR%':>6} {'AvgPnL':>8} {'TotPnL':>9} {'PF':>6} {'TPD':>5}")
    print("-" * 100)
    for _, r in results_df.iterrows():
        print(f"{r['label']:<55} {r['n']:>5} {r['wr']:>6.1f} {r['avg_pnl']:>8.4f} {r['total_pnl']:>9.3f} {r['pf']:>6.2f} {r['tpd']:>5.1f}")

    results_df.to_csv("boof51_results.csv", index=False)
    print(f"\nSaved to boof51_results.csv")

    # Top 10
    print(f"\n{'='*100}")
    print("  TOP 10 by Profit Factor")
    print(f"{'='*100}")
    for _, r in results_df.head(10).iterrows():
        print(f"  {r['label']:<55}  PF={r['pf']:.2f}  WR={r['wr']:.1f}%  N={r['n']}  TPD={r['tpd']:.1f}")
