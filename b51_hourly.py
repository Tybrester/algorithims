"""
BOOF51 Hourly Mover Profile — QQQ
For each signal, break down by MST hour:
  Avg MFE at 15m / 30m / 60m
  % reaching +0.25%, +0.50%, +0.75%, +1.00% within those windows
MST = ET - 2 hours
"""
import pandas as pd
import numpy as np
import pytz

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ"]   # QQQ only — SPY showed weak across the board

TARGETS  = [0.0025, 0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%", "+1.00%"]
WINDOWS  = [15, 30, 60]


# ── Indicators ────────────────────────────────────────────────────────────────

def compute(df):
    df = df.copy().reset_index(drop=True)
    df["date"]       = df["time"].dt.date
    df["hour_et"]    = df["time"].dt.hour
    df["hour_mst"]   = df["hour_et"] - 2
    df["typ"]        = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]         = df["typ"] * df["volume"]
    df["cpv"]        = df.groupby("date")["pv"].cumsum()
    df["cvol"]       = df.groupby("date")["volume"].cumsum()
    df["vwap"]       = df["cpv"] / df["cvol"]
    df["bar_rng"]    = df["high"] - df["low"]
    df["vol_ma20"]   = df["volume"].rolling(20).mean()
    df["rng_ma20"]   = df["bar_rng"].rolling(20).mean()
    df["vwap_slope"] = df["vwap"].diff(5)
    df["prev_c"]     = df["close"].shift(1)

    tr      = pd.concat([df["high"] - df["low"],
                         (df["high"] - df["close"].shift()).abs(),
                         (df["low"]  - df["close"].shift()).abs()], axis=1).max(axis=1)
    dm_up   = df["high"].diff().clip(lower=0)
    dm_down = (-df["low"].diff()).clip(lower=0)
    dm_up   = dm_up.where(dm_up > dm_down, 0)
    dm_down = dm_down.where(dm_down > dm_up, 0)
    atr14   = tr.ewm(span=14, adjust=False).mean()
    pdi     = 100 * dm_up.ewm(span=14, adjust=False).mean()   / atr14
    mdi     = 100 * dm_down.ewm(span=14, adjust=False).mean() / atr14
    dx      = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    df["adx"] = dx.ewm(span=14, adjust=False).mean()
    df["pdi"] = pdi; df["mdi"] = mdi
    return df


# ── Excursion ─────────────────────────────────────────────────────────────────

def excursion(ddf, ei, ep, side):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values
    res = {}
    for bars in WINDOWS:
        end = min(ei + bars, n - 1)
        sl  = slice(ei, end + 1)
        if side == "long":
            res[f"mfe_{bars}m"] = float(max((H[sl] - ep) / ep * 100))
            res[f"mae_{bars}m"] = float(max((ep - L[sl]) / ep * 100))
        else:
            res[f"mfe_{bars}m"] = float(max((ep - L[sl]) / ep * 100))
            res[f"mae_{bars}m"] = float(max((H[sl] - ep) / ep * 100))
    end60 = min(ei + 60, n - 1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        if side == "long":
            res[f"hit_{lbl}"] = bool(any(H[ei:end60+1] >= ep * (1 + tgt)))
        else:
            res[f"hit_{lbl}"] = bool(any(L[ei:end60+1] <= ep * (1 - tgt)))
    return res


# ── Signals ───────────────────────────────────────────────────────────────────

def sig_or15(df):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        or_b = ddf[ddf["time"].dt.strftime("%H:%M") < "09:45"]
        if len(or_b) < 3: continue
        orh = or_b["high"].max(); orl = or_b["low"].min()
        fl = fs = False
        post = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:45"].reset_index(drop=True)
        for i in range(len(post) - 61):
            row = post.iloc[i]; t = row["time"].strftime("%H:%M")
            if t >= "15:00": break
            if not fl and row["close"] > orh and row["close"] > row["vwap"]:
                fl = True; ei = i+1; ep = post.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == post.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"side":"long","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,fi[0],ep,"long")})
            if not fs and row["close"] < orl and row["close"] < row["vwap"]:
                fs = True; ei = i+1; ep = post.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == post.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"side":"short","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,fi[0],ep,"short")})
    return trades


def sig_vwap_slope(df):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True); lc = sc = 0
        for i in range(10, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:00"): continue
            if pd.isna(row["vwap_slope"]): continue
            slope = row["vwap_slope"]
            ps    = ddf.iloc[i-5]["vwap_slope"] if i >= 5 else 0
            if ps == 0 or abs(slope) <= 2 * abs(ps): continue
            bull = slope > 0 and row["close"] > row["vwap"]
            bear = slope < 0 and row["close"] < row["vwap"]
            if bull and lc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"long")}); lc+=1
            if bear and sc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"short")}); sc+=1
    return trades


def sig_vol_surge(df):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True); lc = sc = 0
        for i in range(20, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:00"): continue
            if pd.isna(row["vol_ma20"]) or row["vol_ma20"] == 0: continue
            if row["volume"] < 2 * row["vol_ma20"]: continue
            bull = row["close"] > row["prev_c"] and row["close"] > row["vwap"]
            bear = row["close"] < row["prev_c"] and row["close"] < row["vwap"]
            if bull and lc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"long")}); lc+=1
            if bear and sc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"short")}); sc+=1
    return trades


def sig_prior30(df):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True); lc = sc = 0
        for i in range(30, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:00"): continue
            ph = ddf.iloc[i-30:i]["high"].max(); pl = ddf.iloc[i-30:i]["low"].min()
            bull = row["close"] > ph and row["close"] > row["vwap"]
            bear = row["close"] < pl and row["close"] < row["vwap"]
            if bull and lc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"long")}); lc+=1
            if bear and sc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"short")}); sc+=1
    return trades


def sig_adx(df):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True); lc = sc = 0
        for i in range(20, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:00"): continue
            if pd.isna(row["adx"]) or row["adx"] < 25: continue
            w5h = ddf.iloc[i-5:i]["high"].max(); w5l = ddf.iloc[i-5:i]["low"].min()
            bull = row["close"] > w5h and row["pdi"] > row["mdi"]
            bear = row["close"] < w5l and row["mdi"] > row["pdi"]
            if bull and lc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"long")}); lc+=1
            if bear and sc < 3:
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","hour_mst":row["hour_mst"],"ep":ep, **excursion(ddf,ei,ep,"short")}); sc+=1
    return trades


# ── Report ────────────────────────────────────────────────────────────────────

def hourly_report(trades, signal_name, sym):
    if not trades: print(f"\n{signal_name} | {sym}: no trades"); return
    df = pd.DataFrame(trades)
    hours = sorted(df["hour_mst"].unique())

    W = 95
    print(f"\n{'='*W}")
    print(f"  {signal_name} | {sym} | Total N={len(df)}")
    print(f"  {'Hour (MST)':<12} {'N':>5}  "
          f"{'MFE15m':>7} {'MFE30m':>7} {'MFE60m':>7}  "
          f"{'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7} {'≥1.00%':>7}")
    print(f"  {'-'*90}")

    for hr in hours:
        h = df[df["hour_mst"] == hr]
        label = f"{hr}:00-{hr+1}:00"
        m15  = h["mfe_15m"].mean()
        m30  = h["mfe_30m"].mean()
        m60  = h["mfe_60m"].mean()
        h25  = h[f"hit_{T_LABELS[0]}"].mean() * 100
        h50  = h[f"hit_{T_LABELS[1]}"].mean() * 100
        h75  = h[f"hit_{T_LABELS[2]}"].mean() * 100
        h100 = h[f"hit_{T_LABELS[3]}"].mean() * 100
        print(f"  {label:<12} {len(h):>5}  "
              f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
              f"{h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}% {h100:>6.1f}%")

    print(f"  {'-'*90}")
    m15  = df["mfe_15m"].mean(); m30 = df["mfe_30m"].mean(); m60 = df["mfe_60m"].mean()
    h25  = df[f"hit_{T_LABELS[0]}"].mean()*100; h50 = df[f"hit_{T_LABELS[1]}"].mean()*100
    h75  = df[f"hit_{T_LABELS[2]}"].mean()*100; h100= df[f"hit_{T_LABELS[3]}"].mean()*100
    print(f"  {'ALL':<12} {len(df):>5}  "
          f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
          f"{h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}% {h100:>6.1f}%")


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
        ("OR15 Break",      sig_or15),
        ("VWAP Slope Accel",sig_vwap_slope),
        ("Vol Surge 2x",    sig_vol_surge),
        ("Prior30 H/L Brk", sig_prior30),
        ("ADX>25 Break",    sig_adx),
    ]

    for name, fn in signals:
        for sym in SYMBOLS:
            print(f"  Running {name} | {sym}...", flush=True)
            trades = fn(bars[sym])
            hourly_report(trades, name, sym)
