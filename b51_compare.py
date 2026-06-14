"""
BOOF51 Head-to-Head Comparison
QQQ Momentum:      Vol > 1.5x avg, VWAP slope > 0.10%, break prior 15m H/L
SPY Mean Reversion: dist from VWAP > 0.30%, RSI2 < 10 (long) / > 90 (short)
Window: 9:00-12:00 ET
Measure: MFE at 15/30/60m, % reaching +0.25/0.50/0.75/1.00% within 60 bars
"""
import pandas as pd
import numpy as np
import pytz

ET = pytz.timezone("America/New_York")
TARGETS  = [0.0025, 0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%", "+1.00%"]
WINDOWS  = [15, 30, 60]


def compute(df, sym):
    df = df.copy().reset_index(drop=True)
    df["date"]       = df["time"].dt.date
    df["typ"]        = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]         = df["typ"] * df["volume"]
    df["cpv"]        = df.groupby("date")["pv"].cumsum()
    df["cvol"]       = df.groupby("date")["volume"].cumsum()
    df["vwap"]       = df["cpv"] / df["cvol"]
    df["vol_ma20"]   = df["volume"].rolling(20).mean()
    df["vwap_slope"] = (df["vwap"].diff(5) / df["vwap"] * 100)   # % change over 5 bars
    df["prev_c"]     = df["close"].shift(1)
    df["dist_vwap"]  = (df["close"] - df["vwap"]).abs() / df["vwap"] * 100

    # RSI2
    d = df["close"].diff()
    g = d.clip(lower=0).ewm(com=1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=1, adjust=False).mean()
    df["rsi2"] = 100 - 100 / (1 + g / l.replace(0, 1e-9))

    return df


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


def run_qqq_momentum(df):
    """QQQ: Vol > 1.5x avg, VWAP slope > 0.10%, break prior 15m H/L"""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(20, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:00" <= t < "12:00"): continue
            if pd.isna(row["vwap_slope"]) or pd.isna(row["vol_ma20"]): continue
            if row["vol_ma20"] == 0: continue

            # Conditions
            vol_ok    = row["volume"] >= 1.5 * row["vol_ma20"]
            slope_up  = row["vwap_slope"] >  0.10
            slope_dn  = row["vwap_slope"] < -0.10

            # Prior 15m high/low
            w15 = ddf.iloc[max(0, i-15):i]
            p15h = w15["high"].max(); p15l = w15["low"].min()

            bull = vol_ok and slope_up and row["close"] > p15h
            bear = vol_ok and slope_dn and row["close"] < p15l

            if bull and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep,
                               **excursion(ddf, ei, ep, "long")}); lc += 1
            if bear and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep,
                               **excursion(ddf, ei, ep, "short")}); sc += 1
    return trades


def run_spy_mr(df):
    """SPY: dist from VWAP > 0.30%, RSI2 < 10 long / > 90 short"""
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0
        for i in range(20, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:00" <= t < "12:00"): continue
            if pd.isna(row["vwap"]) or pd.isna(row["rsi2"]): continue

            dist_ok = row["dist_vwap"] > 0.30

            bull = dist_ok and row["close"] < row["vwap"] and row["rsi2"] < 10
            bear = dist_ok and row["close"] > row["vwap"] and row["rsi2"] > 90

            if bull and lc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"long","ep":ep,
                               **excursion(ddf, ei, ep, "long")}); lc += 1
            if bear and sc < 3:
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"side":"short","ep":ep,
                               **excursion(ddf, ei, ep, "short")}); sc += 1
    return trades


def report_comparison(results):
    W = 85
    print(f"\n{'='*W}")
    print(f"  {'Symbol':<6} {'Setup':<22} {'N':>5}  "
          f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7} {'≥1.00%':>7}")
    print(f"  {'-'*80}")
    for sym, label, trades in results:
        if not trades:
            print(f"  {sym:<6} {label:<22} {'--':>5}"); continue
        df  = pd.DataFrame(trades)
        n   = len(df)
        m15 = df["mfe_15m"].mean()
        m30 = df["mfe_30m"].mean()
        m60 = df["mfe_60m"].mean()
        h25 = df[f"hit_{T_LABELS[0]}"].mean()*100
        h50 = df[f"hit_{T_LABELS[1]}"].mean()*100
        h75 = df[f"hit_{T_LABELS[2]}"].mean()*100
        h100= df[f"hit_{T_LABELS[3]}"].mean()*100
        print(f"  {sym:<6} {label:<22} {n:>5}  "
              f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
              f"{h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}% {h100:>6.1f}%")

        # Side breakdown
        for side in ["long", "short"]:
            s = df[df["side"] == side]
            if s.empty: continue
            sm15=s["mfe_15m"].mean(); sm60=s["mfe_60m"].mean()
            sh50=s[f"hit_{T_LABELS[1]}"].mean()*100
            sh75=s[f"hit_{T_LABELS[2]}"].mean()*100
            print(f"  {'':6}   {side:>22} {len(s):>5}  "
                  f"{'':>7} {sm15:>6.3f}% {sm60:>6.3f}%  "
                  f"{'':>7} {sh50:>6.1f}% {sh75:>6.1f}%")
    print(f"{'='*W}")


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    qqq = pd.read_csv("boof51_QQQ_1m.csv")
    qqq["time"] = pd.to_datetime(qqq["time"], utc=True).dt.tz_convert(ET)
    qqq = compute(qqq, "QQQ").dropna(subset=["vwap"])

    spy = pd.read_csv("boof51_SPY_1m.csv")
    spy["time"] = pd.to_datetime(spy["time"], utc=True).dt.tz_convert(ET)
    spy = compute(spy, "SPY").dropna(subset=["vwap"])

    print("  Running QQQ Momentum...", flush=True)
    qqq_trades = run_qqq_momentum(qqq)
    print("  Running SPY Mean Reversion...", flush=True)
    spy_trades = run_spy_mr(spy)

    results = [
        ("QQQ", "Momentum",       qqq_trades),
        ("SPY", "Mean Reversion", spy_trades),
    ]

    report_comparison(results)

    # Save CSVs
    pd.DataFrame(qqq_trades).to_csv("boof51_QQQ_momentum.csv", index=False)
    pd.DataFrame(spy_trades).to_csv("boof51_SPY_mr.csv", index=False)
    print("\nCSVs saved.", flush=True)
