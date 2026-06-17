"""
BOOF51 Trend Filter Tests - A/B/C
Test A: 1m entry + 5m trend filter
Test B: 1m entry + 10m trend filter
Test C: 1m entry + 5m AND 10m agree
Runs against best windows from first backtest.
Requires: boof51_SPY_1m.csv, boof51_QQQ_1m.csv
"""

import datetime, sys
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
SYMBOLS = ["SPY", "QQQ"]

CONFIG = {
    "SPY": {"long": {"tp": 0.0035, "sl": 0.0025}, "short": {"tp": 0.0030, "sl": 0.0025}},
    "QQQ": {"long": {"tp": 0.0045, "sl": 0.0030}, "short": {"tp": 0.0040, "sl": 0.0030}},
}

MAX_TRADES_PER_SIDE = 5
COOLDOWN_MINUTES    = 10
TIME_STOP_MINUTES   = 90

# Best windows from first run
BEST_WINDOWS = {
    "SPY": [("11:00","12:00"), ("13:30","15:00")],
    "QQQ": [("09:30","10:00"), ("13:30","15:30")],
}


def resample_vwap_ema(df_1m, minutes):
    """Resample 1m bars to Nm, compute VWAP and EMA9, forward-fill back to 1m index."""
    rule = f"{minutes}min"
    df_1m = df_1m.set_index("time")
    rs = df_1m.resample(rule, closed="left", label="left").agg(
        open=("open","first"), high=("high","max"),
        low=("low","min"), close=("close","last"), volume=("volume","sum")
    ).dropna()
    rs["date"] = rs.index.date
    rs["typ"]  = (rs["high"] + rs["low"] + rs["close"]) / 3
    rs["pv"]   = rs["typ"] * rs["volume"]
    rs["cum_pv"]  = rs.groupby("date")["pv"].cumsum()
    rs["cum_vol"] = rs.groupby("date")["volume"].cumsum()
    rs[f"vwap{minutes}"]  = rs["cum_pv"] / rs["cum_vol"]
    rs[f"ema9_{minutes}"] = rs["close"].ewm(span=9, adjust=False).mean()
    rs[f"trend{minutes}"] = (rs["close"] > rs[f"vwap{minutes}"]).astype(int) * 2 - 1  # +1 up, -1 down
    keep = [f"vwap{minutes}", f"ema9_{minutes}", f"trend{minutes}"]
    df_1m = df_1m.reset_index()
    merged = pd.merge_asof(df_1m.sort_values("time"), rs[keep].reset_index().rename(columns={"time":"rs_time"}),
                           left_on="time", right_on="rs_time", direction="backward")
    return merged


def compute_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["date"] = df["time"].dt.date
    df["typ"]  = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]   = df["typ"] * df["volume"]
    df["cum_pv"]  = df.groupby("date")["pv"].cumsum()
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"]    = df["cum_pv"] / df["cum_vol"]
    df["ema9"]      = df["close"].ewm(span=9, adjust=False).mean()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    df["prev_close"] = df["close"].shift(1)
    df["prev_vwap"]  = df["vwap"].shift(1)
    return df


def long_signal(row):
    return (row["close"] > row["vwap"] and row["prev_close"] <= row["prev_vwap"] and
            row["volume"] > row["vol_sma20"] * 1.2 and row["close"] > row["ema9"])

def short_signal(row):
    return (row["close"] < row["vwap"] and row["prev_close"] >= row["prev_vwap"] and
            row["volume"] > row["vol_sma20"] * 1.2 and row["close"] < row["ema9"])


def _sim_exit(day_df, entry_idx, ep, tp, sl, side):
    max_i  = min(entry_idx + TIME_STOP_MINUTES, len(day_df) - 1)
    highs  = day_df["high"].values
    lows   = day_df["low"].values
    closes = day_df["close"].values
    for j in range(entry_idx, max_i + 1):
        if side == "long":
            if highs[j] >= tp: return {"exit_type": "tp", "pnl_pct": (tp-ep)/ep*100}
            if lows[j]  <= sl: return {"exit_type": "sl", "pnl_pct": (sl-ep)/ep*100}
        else:
            if lows[j]  <= tp: return {"exit_type": "tp", "pnl_pct": (ep-tp)/ep*100}
            if highs[j] >= sl: return {"exit_type": "sl", "pnl_pct": (ep-sl)/ep*100}
    exit_px = closes[max_i]
    pnl = (exit_px-ep)/ep*100 if side=="long" else (ep-exit_px)/ep*100
    return {"exit_type": "time", "pnl_pct": pnl}


def run_test(df, sym, windows, trend_filter):
    """trend_filter: None | 'A' (5m) | 'B' (10m) | 'C' (5m+10m)"""
    cfg    = CONFIG[sym]
    trades = []
    for date, day_df in df.groupby("date"):
        day_df = day_df.reset_index(drop=True)
        long_count = short_count = 0
        long_cd = short_cd = None
        for i in range(1, len(day_df) - 1):
            row = day_df.iloc[i]
            t   = row["time"].strftime("%H:%M")
            if not any(ws <= t < we for ws, we in windows): continue
            if pd.isna(row.get("vwap")) or pd.isna(row.get("vol_sma20")): continue

            # Trend gate
            if trend_filter == "A":
                t5 = row.get("trend5", 0)
                long_ok  = (t5 == 1)
                short_ok = (t5 == -1)
            elif trend_filter == "B":
                t10 = row.get("trend10", 0)
                long_ok  = (t10 == 1)
                short_ok = (t10 == -1)
            elif trend_filter == "C":
                t5  = row.get("trend5",  0)
                t10 = row.get("trend10", 0)
                long_ok  = (t5 == 1  and t10 == 1)
                short_ok = (t5 == -1 and t10 == -1)
            else:
                long_ok = short_ok = True

            now_dt = row["time"]

            if long_count < MAX_TRADES_PER_SIDE and long_ok:
                if long_cd is None or now_dt >= long_cd:
                    if long_signal(row):
                        ep  = day_df.iloc[i+1]["open"]
                        tp  = ep * (1 + cfg["long"]["tp"])
                        sl  = ep * (1 - cfg["long"]["sl"])
                        res = _sim_exit(day_df, i+1, ep, tp, sl, "long")
                        res.update({"sym": sym, "date": str(date), "side": "long"})
                        trades.append(res)
                        long_count += 1
                        long_cd = now_dt + datetime.timedelta(minutes=COOLDOWN_MINUTES)

            if short_count < MAX_TRADES_PER_SIDE and short_ok:
                if short_cd is None or now_dt >= short_cd:
                    if short_signal(row):
                        ep  = day_df.iloc[i+1]["open"]
                        tp  = ep * (1 - cfg["short"]["tp"])
                        sl  = ep * (1 + cfg["short"]["sl"])
                        res = _sim_exit(day_df, i+1, ep, tp, sl, "short")
                        res.update({"sym": sym, "date": str(date), "side": "short"})
                        trades.append(res)
                        short_count += 1
                        short_cd = now_dt + datetime.timedelta(minutes=COOLDOWN_MINUTES)
    return trades


def summarize(trades, label):
    if not trades:
        return {"label": label, "n": 0, "wr": 0, "avg_pnl": 0, "total_pnl": 0, "pf": 0, "tpd": 0}
    df   = pd.DataFrame(trades)
    wins = df[df["exit_type"] == "tp"]
    loss = df[df["exit_type"].isin(["sl", "time"])]
    wr   = len(wins) / len(df) * 100
    avg  = df["pnl_pct"].mean()
    tot  = df["pnl_pct"].sum()
    gw   = wins["pnl_pct"].sum() if len(wins) else 0
    gl   = abs(loss["pnl_pct"].sum()) if len(loss) else 1e-9
    pf   = gw / gl
    tpd  = len(df) / df["date"].nunique()
    return {"label": label, "n": len(df), "wr": wr, "avg_pnl": avg, "total_pnl": tot, "pf": pf, "tpd": tpd}


if __name__ == "__main__":
    print("Loading cached bars...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        f = f"boof51_{sym}_1m.csv"
        if not __import__("os").path.exists(f):
            print(f"Missing {f} - run boof51_fetch.py first"); sys.exit(1)
        df = pd.read_csv(f)
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_indicators(df)
        # Add 5m and 10m trend columns
        df = resample_vwap_ema(df, 5)
        df = resample_vwap_ema(df, 10)
        df = df.dropna(subset=["vwap", "ema9", "vol_sma20"])
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    results = []
    tests = [
        ("Baseline (no filter)", None),
        ("Test A - 5m trend",    "A"),
        ("Test B - 10m trend",   "B"),
        ("Test C - 5m+10m agree","C"),
    ]

    for sym in SYMBOLS:
        df      = bars[sym]
        windows = [BEST_WINDOWS[sym]]  # use best combo from prior run as single window set
        # flatten to list of tuples
        win_list = BEST_WINDOWS[sym]
        for label, filt in tests:
            trades = run_test(df, sym, win_list, filt)
            stats  = summarize(trades, f"{sym} | {label}")
            results.append(stats)
            print(f"  {sym} {label}: N={stats['n']}  PF={stats['pf']:.2f}  WR={stats['wr']:.1f}%  TPD={stats['tpd']:.1f}", flush=True)

    print(f"\n{'='*90}")
    print(f"  BOOF51 TREND FILTER COMPARISON")
    print(f"{'='*90}")
    print(f"{'Label':<45} {'N':>5} {'WR%':>6} {'AvgPnL':>8} {'TotPnL':>9} {'PF':>6} {'TPD':>5}")
    print("-"*90)
    for r in results:
        print(f"{r['label']:<45} {r['n']:>5} {r['wr']:>6.1f} {r['avg_pnl']:>8.4f} {r['total_pnl']:>9.3f} {r['pf']:>6.2f} {r['tpd']:>5.1f}")

    pd.DataFrame(results).to_csv("boof51_trend_results.csv", index=False)
    print("\nSaved to boof51_trend_results.csv")
