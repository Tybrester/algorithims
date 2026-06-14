"""
BOOF51 15-Minute Mover Scanner — SPY & QQQ
For each signal type, measure:
  - % trades reaching +0.25%, +0.50%, +0.75% within 15 bars
  - Avg MFE at 5m/10m/15m
  - Avg MAE at 15m
  - N trades (need volume to trust the stat)

Signal types tested:
  1. OR15 Break       — break of first 15m high/low
  2. OR30 Break       — break of first 30m high/low
  3. Vol Surge        — volume > 2x 20-bar avg, price moving same direction
  4. VWAP Reclaim     — cross back above/below VWAP with volume surge
  5. Prior 30m H/L    — break of rolling 30m high/low
  6. ADX Trend        — ADX > 25, break of last 5m high/low
  7. VWAP Slope       — VWAP slope steepening, price above/below
  8. Range Expansion  — bar range > 2x avg 20-bar range, breakout direction
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYMBOLS  = ["SPY", "QQQ"]
BARS_15  = 15
TARGETS  = [0.0025, 0.0050, 0.0075]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%"]


# ── Indicators ────────────────────────────────────────────────────────────────

def compute(df):
    df = df.copy().reset_index(drop=True)
    df["date"]    = df["time"].dt.date
    df["typ"]     = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]      = df["typ"] * df["volume"]
    df["cpv"]     = df.groupby("date")["pv"].cumsum()
    df["cvol"]    = df.groupby("date")["volume"].cumsum()
    df["vwap"]    = df["cpv"] / df["cvol"]
    df["bar_rng"] = df["high"] - df["low"]
    df["vol_ma20"]= df["volume"].rolling(20).mean()
    df["rng_ma20"]= df["bar_rng"].rolling(20).mean()
    df["prev_c"]  = df["close"].shift(1)
    df["prev_v"]  = df["volume"].shift(1)

    # VWAP slope (change over last 5 bars)
    df["vwap_slope"] = df["vwap"].diff(5)

    # ADX (14)
    tr  = pd.concat([df["high"] - df["low"],
                     (df["high"] - df["close"].shift()).abs(),
                     (df["low"]  - df["close"].shift()).abs()], axis=1).max(axis=1)
    dm_up   = (df["high"].diff()).clip(lower=0)
    dm_down = (-df["low"].diff()).clip(lower=0)
    dm_up   = dm_up.where(dm_up > dm_down, 0)
    dm_down = dm_down.where(dm_down > dm_up, 0)
    atr14   = tr.ewm(span=14, adjust=False).mean()
    pdi     = 100 * dm_up.ewm(span=14, adjust=False).mean()   / atr14
    mdi     = 100 * dm_down.ewm(span=14, adjust=False).mean() / atr14
    dx      = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9))
    df["adx"]  = dx.ewm(span=14, adjust=False).mean()
    df["pdi"]  = pdi
    df["mdi"]  = mdi
    return df


# ── Excursion helper ──────────────────────────────────────────────────────────

def excursion(ddf, ei, ep, side):
    n   = len(ddf)
    end = min(ei + BARS_15, n - 1)
    H   = ddf["high"].values
    L   = ddf["low"].values
    res = {}
    for bars, key in [(5,"5m"),(10,"10m"),(15,"15m")]:
        e2 = min(ei + bars, n - 1)
        if side == "long":
            res[f"mfe_{key}"] = max((H[ei:e2+1] - ep) / ep * 100)
            res[f"mae_{key}"] = max((ep - L[ei:e2+1]) / ep * 100)
        else:
            res[f"mfe_{key}"] = max((ep - L[ei:e2+1]) / ep * 100)
            res[f"mae_{key}"] = max((H[ei:e2+1] - ep) / ep * 100)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        if side == "long":
            res[f"hit_{lbl}"] = bool(any(H[ei:end+1] >= ep * (1 + tgt)))
        else:
            res[f"hit_{lbl}"] = bool(any(L[ei:end+1] <= ep * (1 - tgt)))
    return res


# ── Signal generators ─────────────────────────────────────────────────────────

def sig_or_break(df, or_end_str):
    """Break of opening range high/low (OR15 or OR30)."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        or_bars = ddf[ddf["time"].dt.strftime("%H:%M") < or_end_str]
        if len(or_bars) < 3: continue
        orh = or_bars["high"].max(); orl = or_bars["low"].min()
        fired_l = fired_s = False
        trade_bars = ddf[ddf["time"].dt.strftime("%H:%M") >= or_end_str].reset_index(drop=True)
        for i in range(len(trade_bars) - BARS_15 - 1):
            row = trade_bars.iloc[i]
            t   = row["time"].strftime("%H:%M")
            if t >= "15:40": break
            if not fired_l and row["close"] > orh and row["close"] > row["vwap"]:
                fired_l = True
                ei = i + 1; ep = trade_bars.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == trade_bars.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, fi[0], ep, "long")})
            if not fired_s and row["close"] < orl and row["close"] < row["vwap"]:
                fired_s = True
                ei = i + 1; ep = trade_bars.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == trade_bars.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, fi[0], ep, "short")})
    return trades


def sig_vol_surge(df):
    """Volume > 2x 20-bar avg, price moves in direction."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(20, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            if pd.isna(row["vol_ma20"]) or row["vol_ma20"] == 0: continue
            if row["volume"] < 2 * row["vol_ma20"]: continue
            bullish = row["close"] > row["prev_c"] and row["close"] > row["vwap"]
            bearish = row["close"] < row["prev_c"] and row["close"] < row["vwap"]
            if bullish and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, ei, ep, "long")})
                lc += 1
            if bearish and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, ei, ep, "short")})
                sc += 1
    return trades


def sig_vwap_reclaim(df):
    """VWAP reclaim/rejection: cross VWAP with volume > 1.5x avg."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(20, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; prev = ddf.iloc[i-1]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            if pd.isna(row["vwap"]) or pd.isna(row["vol_ma20"]): continue
            vol_ok = row["volume"] > 1.5 * row["vol_ma20"]
            # Reclaim: was below, now above
            reclaim = prev["close"] < prev["vwap"] and row["close"] > row["vwap"] and vol_ok
            # Reject: was above, now below
            reject  = prev["close"] > prev["vwap"] and row["close"] < row["vwap"] and vol_ok
            if reclaim and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, ei, ep, "long")})
                lc += 1
            if reject and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, ei, ep, "short")})
                sc += 1
    return trades


def sig_prior30_break(df):
    """Break of rolling prior 30-bar high/low (30 minutes)."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(30, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            window = ddf.iloc[i-30:i]
            ph = window["high"].max(); pl = window["low"].min()
            bull = row["close"] > ph and row["close"] > row["vwap"]
            bear = row["close"] < pl and row["close"] < row["vwap"]
            if bull and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, ei, ep, "long")})
                lc += 1
            if bear and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, ei, ep, "short")})
                sc += 1
    return trades


def sig_adx_break(df):
    """ADX > 25 trending, break of last 5-bar high/low."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(20, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            if pd.isna(row["adx"]) or row["adx"] < 25: continue
            w5h = ddf.iloc[i-5:i]["high"].max()
            w5l = ddf.iloc[i-5:i]["low"].min()
            bull = row["close"] > w5h and row["pdi"] > row["mdi"]
            bear = row["close"] < w5l and row["mdi"] > row["pdi"]
            if bull and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, ei, ep, "long")})
                lc += 1
            if bear and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, ei, ep, "short")})
                sc += 1
    return trades


def sig_range_expansion(df):
    """Bar range > 2x 20-bar avg range, break in direction."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(20, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            if pd.isna(row["rng_ma20"]) or row["rng_ma20"] == 0: continue
            if row["bar_rng"] < 2 * row["rng_ma20"]: continue
            bull = row["close"] > row["vwap"] and row["close"] > ddf.iloc[i-1]["close"]
            bear = row["close"] < row["vwap"] and row["close"] < ddf.iloc[i-1]["close"]
            if bull and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, ei, ep, "long")})
                lc += 1
            if bear and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, ei, ep, "short")})
                sc += 1
    return trades


def sig_vwap_slope(df):
    """VWAP slope steepening (abs slope > 2x prior), price on right side."""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(10, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            if pd.isna(row["vwap_slope"]): continue
            slope     = row["vwap_slope"]
            prev_slope= ddf.iloc[i-5]["vwap_slope"] if i >= 5 else 0
            accel     = abs(slope) > 2 * abs(prev_slope) if prev_slope != 0 else False
            if not accel: continue
            bull = slope > 0 and row["close"] > row["vwap"]
            bear = slope < 0 and row["close"] < row["vwap"]
            if bull and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep, **excursion(ddf, ei, ep, "long")})
                lc += 1
            if bear and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep, **excursion(ddf, ei, ep, "short")})
                sc += 1
    return trades


# ── Report ────────────────────────────────────────────────────────────────────

def report(results):
    W = 88
    print(f"\n{'='*W}")
    print(f"  {'Signal':<22} {'Sym':<5} {'N':>5}  {'MFE5m':>7} {'MFE10m':>7} {'MFE15m':>7} {'MAE15m':>7}  "
          f"{'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7}")
    print(f"  {'-'*84}")
    for name, sym, trades in results:
        if not trades:
            print(f"  {name:<22} {sym:<5} {'--':>5}"); continue
        df  = pd.DataFrame(trades)
        n   = len(df)
        mfe5  = df["mfe_5m"].mean()
        mfe10 = df["mfe_10m"].mean()
        mfe15 = df["mfe_15m"].mean()
        mae15 = df["mae_15m"].mean()
        h25   = df[f"hit_{T_LABELS[0]}"].mean() * 100
        h50   = df[f"hit_{T_LABELS[1]}"].mean() * 100
        h75   = df[f"hit_{T_LABELS[2]}"].mean() * 100
        print(f"  {name:<22} {sym:<5} {n:>5}  {mfe5:>6.3f}% {mfe10:>6.3f}% {mfe15:>6.3f}% {mae15:>6.3f}%  "
              f"{h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}%")
    print(f"{'='*W}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading & computing indicators...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        df = pd.read_csv(f"boof51_{sym}_1m.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute(df).dropna(subset=["vwap"])
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    signals = [
        ("OR15 Break",     lambda df: sig_or_break(df, "09:45")),
        ("OR30 Break",     lambda df: sig_or_break(df, "10:00")),
        ("Vol Surge 2x",   sig_vol_surge),
        ("VWAP Reclaim",   sig_vwap_reclaim),
        ("Prior30 H/L Brk",sig_prior30_break),
        ("ADX>25 Break",   sig_adx_break),
        ("Range Expansion",sig_range_expansion),
        ("VWAP Slope Accel",sig_vwap_slope),
    ]

    results = []
    for name, fn in signals:
        for sym in SYMBOLS:
            print(f"  Running {name} | {sym}...", flush=True)
            trades = fn(bars[sym])
            results.append((name, sym, trades))

    report(results)

    # Save best raw trades for further analysis
    for name, sym, trades in results:
        if trades:
            slug = name.lower().replace(" ","_").replace("/","").replace(">","gt")
            pd.DataFrame(trades).to_csv(f"boof51_{sym}_{slug}.csv", index=False)
    print("\nDone. CSVs saved.", flush=True)
