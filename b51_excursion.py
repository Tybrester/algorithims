"""
BOOF51 Excursion Profiler — SPY & QQQ
Same signal logic as mean reversion (RSI2<5/>95, dist>0.40%, VWAP filter)
No exits — just track MFE/MAE at 5m, 10m, 15m after entry
Report % of trades reaching TP targets within 15 minutes
"""
import datetime
import pandas as pd
import numpy as np
import pytz

ET = pytz.timezone("America/New_York")
SYMBOLS  = ["SPY", "QQQ"]
MIN_DIST = 0.0040
BARS_5   = 5
BARS_10  = 10
BARS_15  = 15

TARGETS  = [0.0025, 0.0050, 0.0060, 0.0075, 0.0100]
TARGET_LABELS = ["+0.25%", "+0.50%", "+0.60%", "+0.75%", "+1.00%"]


def calc_rsi2(s):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))


def compute_1m(df):
    df = df.copy().reset_index(drop=True)
    df["date"]  = df["time"].dt.date
    df["typ"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]    = df["typ"] * df["volume"]
    df["cpv"]   = df.groupby("date")["pv"].cumsum()
    df["cvol"]  = df.groupby("date")["volume"].cumsum()
    df["vwap"]  = df["cpv"] / df["cvol"]
    df["rsi2"]  = calc_rsi2(df["close"])
    df["dist"]  = (df["vwap"] - df["close"]) / df["vwap"]
    return df


def scan_excursion(ddf, ei, ep, side):
    """Scan forward 15 bars, record MFE/MAE at 5/10/15 bars."""
    H = ddf["high"].values
    L = ddf["low"].values
    n = len(ddf)

    result = {}
    for bars, key in [(BARS_5, "5m"), (BARS_10, "10m"), (BARS_15, "15m")]:
        end = min(ei + bars, n - 1)
        if side == "long":
            mfe = max((H[ei:end+1] - ep) / ep * 100)
            mae = max((ep - L[ei:end+1]) / ep * 100)
        else:
            mfe = max((ep - L[ei:end+1]) / ep * 100)
            mae = max((H[ei:end+1] - ep) / ep * 100)
        result[f"mfe_{key}"] = round(mfe, 4)
        result[f"mae_{key}"] = round(mae, 4)

    # Did price reach each target within 15 bars?
    end15 = min(ei + BARS_15, n - 1)
    for tgt, lbl in zip(TARGETS, TARGET_LABELS):
        if side == "long":
            hit = any(H[ei:end15+1] >= ep * (1 + tgt))
        else:
            hit = any(L[ei:end15+1] <= ep * (1 - tgt))
        result[f"hit_{lbl}"] = hit

    return result


def run(df):
    trades = []
    MAX_TRADES = 5; COOLDOWN = 10

    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0; lcd = scd = None

        for i in range(1, len(ddf) - BARS_15 - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:40"): continue
            if pd.isna(row["vwap"]) or pd.isna(row["rsi2"]): continue

            nd   = row["time"]
            dist = abs(row["dist"])

            if (lc < MAX_TRADES and (lcd is None or nd >= lcd) and
                    row["close"] < row["vwap"] and
                    row["rsi2"]  < 5 and
                    dist > MIN_DIST):
                ei = i + 1
                ep = ddf.iloc[ei]["open"]
                exc = scan_excursion(ddf, ei, ep, "long")
                trades.append({"date": str(date), "side": "long",
                               "entry_dist": dist * 100, **exc})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            if (sc < MAX_TRADES and (scd is None or nd >= scd) and
                    row["close"] > row["vwap"] and
                    row["rsi2"]  > 95 and
                    dist > MIN_DIST):
                ei = i + 1
                ep = ddf.iloc[ei]["open"]
                exc = scan_excursion(ddf, ei, ep, "short")
                trades.append({"date": str(date), "side": "short",
                               "entry_dist": dist * 100, **exc})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)

    return trades


def report(trades, sym):
    if not trades:
        print(f"\n{sym}: No trades"); return
    df = pd.DataFrame(trades)

    S = "=" * 65
    for side in ["long", "short", "all"]:
        s = df if side == "all" else df[df["side"] == side]
        if s.empty: continue
        lbl = f"{sym} | {side.upper()}"
        print(f"\n{S}\n  {lbl}  (N={len(s)})\n{S}")

        print(f"  {'Metric':<12} {'  5m':>8} {'10m':>8} {'15m':>8}")
        print(f"  {'-'*38}")
        for stat in ["mfe", "mae"]:
            vals = [s[f"{stat}_5m"].mean(), s[f"{stat}_10m"].mean(), s[f"{stat}_15m"].mean()]
            label = "Avg MFE" if stat == "mfe" else "Avg MAE"
            print(f"  {label:<12}  {vals[0]:>7.4f}%  {vals[1]:>7.4f}%  {vals[2]:>7.4f}%")
        for stat in ["mfe", "mae"]:
            vals = [s[f"{stat}_5m"].median(), s[f"{stat}_10m"].median(), s[f"{stat}_15m"].median()]
            label = "Med MFE" if stat == "mfe" else "Med MAE"
            print(f"  {label:<12}  {vals[0]:>7.4f}%  {vals[1]:>7.4f}%  {vals[2]:>7.4f}%")

        print(f"\n  TARGET REACH RATE (within 15 bars / ~15 minutes)")
        print(f"  {'-'*38}")
        for tgt, lbl2 in zip(TARGETS, TARGET_LABELS):
            col = f"hit_{lbl2}"
            pct = s[col].mean() * 100
            bar = "█" * int(pct / 5)
            print(f"  {lbl2:>7}  {pct:5.1f}%  {bar}")


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    all_trades = {}
    for sym in SYMBOLS:
        df = pd.read_csv(f"boof51_{sym}_1m.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_1m(df).dropna(subset=["vwap", "rsi2"])
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)
        trades = run(df)
        all_trades[sym] = trades
        pd.DataFrame(trades).to_csv(f"boof51_{sym}_excursion.csv", index=False)

    for sym in SYMBOLS:
        report(all_trades[sym], sym)
