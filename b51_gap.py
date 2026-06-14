"""
BOOF51 Gap-Down + PM Level Break
TRADE_DAY: gap_pct <= -0.5%
LONG:  break above PM high (9:00-12:00 ET)
SHORT: break below PM low  (9:00-12:00 ET)
Measures excursion only — no exits
"""
import os, datetime
import pandas as pd
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]
KEY     = "PK7N52NHGPS2GBVZU64BCUEDNO"
SECRET  = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"

TARGETS  = [0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.50%", "+0.75%", "+1.00%"]


def load_pm(sym):
    cache = f"boof51_{sym}_pm.csv"
    df = pd.read_csv(cache)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df


def load_rt(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df


def build_pm_stats(pm_df, rt_df):
    pm_df["date"] = pm_df["time"].dt.date

    daily_close = rt_df.groupby("date")["close"].last().reset_index()
    daily_close.columns = ["date","prev_close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"])
    daily_close["next_date"] = daily_close["date"] + pd.Timedelta(days=1)

    records = []
    for date, g in pm_df.groupby("date"):
        records.append({
            "date":    pd.Timestamp(date),
            "pm_high": g["high"].max(),
            "pm_low":  g["low"].min(),
        })
    stats = pd.DataFrame(records)
    stats = stats.merge(
        daily_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    )

    # RTH open
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M") == "09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index()
    rth.columns = ["date","rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["gap_pct"])


def excursion(ddf, ei, ep, side):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values
    res = {}
    for bars, key in [(15,"15m"),(30,"30m"),(60,"60m")]:
        end = min(ei + bars, n - 1)
        sl  = slice(ei, end + 1)
        res[f"mfe_{key}"] = float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
        res[f"mae_{key}"] = float(max((ep-L[sl])/ep*100)) if side=="long" else float(max((H[sl]-ep)/ep*100))
    end60 = min(ei + 60, n - 1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        if side == "long":
            res[f"hit_{lbl}"] = bool(any(H[ei:end60+1] >= ep*(1+tgt)))
        else:
            res[f"hit_{lbl}"] = bool(any(L[ei:end60+1] <= ep*(1-tgt)))
    return res


def run(rt_df, pm_stats, gap_thresh=-0.5):
    rt_df = rt_df.copy()
    rt_df["date"] = pd.to_datetime(rt_df["date"])

    # Filter to gap-down days
    gap_days = pm_stats[pm_stats["gap_pct"] <= gap_thresh].set_index("date")

    trades = []
    for date, ddf in rt_df.groupby("date"):
        date = pd.Timestamp(date)
        if date not in gap_days.index: continue
        day = gap_days.loc[date]
        pm_high = day["pm_high"]; pm_low = day["pm_low"]

        ddf = ddf.reset_index(drop=True)
        long_fired = short_fired = False

        for i in range(len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue

            # Long: first bar that closes above PM high
            if not long_fired and row["close"] > pm_high:
                long_fired = True
                ei = i + 1
                if ei >= len(ddf): continue
                ep = ddf.iloc[ei]["open"]
                exc = excursion(ddf, ei, ep, "long")
                trades.append({"date": str(date.date()), "side": "long",
                               "pm_high": pm_high, "ep": ep,
                               "gap_pct": day["gap_pct"], **exc})

            # Short: first bar that closes below PM low
            if not short_fired and row["close"] < pm_low:
                short_fired = True
                ei = i + 1
                if ei >= len(ddf): continue
                ep = ddf.iloc[ei]["open"]
                exc = excursion(ddf, ei, ep, "short")
                trades.append({"date": str(date.date()), "side": "short",
                               "pm_low": pm_low, "ep": ep,
                               "gap_pct": day["gap_pct"], **exc})

    return trades


def report(trades, sym, gap_thresh):
    if not trades:
        print(f"\n{sym}: No trades (gap <= {gap_thresh}%)"); return
    df = pd.DataFrame(trades)
    n_days = df["date"].nunique()
    tpd    = len(df) / n_days

    S = "=" * 65
    print(f"\n{S}")
    print(f"  {sym} | Gap <= {gap_thresh}% | PM H/L Break | 9:00-12:00 ET")
    print(S)
    print(f"  Trade days : {n_days}  |  Total trades : {len(df)}  |  TPD : {tpd:.2f}")
    print(f"\n  {'Metric':<14} {'  15m':>8} {'30m':>8} {'60m':>8}")
    print(f"  {'-'*42}")

    for side in ["long", "short", "all"]:
        s = df if side == "all" else df[df["side"] == side]
        if s.empty: continue
        lbl = side.upper()
        m15 = s["mfe_15m"].mean(); m30 = s["mfe_30m"].mean(); m60 = s["mfe_60m"].mean()
        a15 = s["mae_15m"].mean(); a60 = s["mae_60m"].mean()
        print(f"\n  [{lbl}]  N={len(s)}")
        print(f"  {'Avg MFE':<14}  {m15:>7.4f}%  {m30:>7.4f}%  {m60:>7.4f}%")
        print(f"  {'Avg MAE':<14}  {a15:>7.4f}%  {'':>8}  {a60:>7.4f}%")
        print(f"\n  Target reach rates (within 60 bars):")
        for lbl2 in T_LABELS:
            col = f"hit_{lbl2}"
            pct = s[col].mean() * 100
            bar = "█" * int(pct / 5)
            print(f"    {lbl2:>7}  {pct:5.1f}%  {bar}")

    # Gap size buckets
    print(f"\n  BY GAP SIZE:")
    print(f"  {'Gap Bucket':<22} {'N':>4}  {'MFE60':>7}  {'≥0.50%':>7}  {'≥1.00%':>7}")
    for lo, hi, lbl in [(-0.5, -1.0, "-0.5 to -1.0%"), (-1.0, -99, "< -1.0%")]:
        s = df[(df["gap_pct"] <= lo) & (df["gap_pct"] > hi)] if hi != -99 else df[df["gap_pct"] <= lo]
        if s.empty: continue
        h50 = s[f"hit_{T_LABELS[0]}"].mean()*100
        h100= s[f"hit_{T_LABELS[2]}"].mean()*100
        print(f"  {lbl:<22} {len(s):>4}  {s['mfe_60m'].mean():>7.4f}%  {h50:>7.1f}%  {h100:>7.1f}%")


if __name__ == "__main__":
    for sym in SYMBOLS:
        print(f"Loading {sym}...", flush=True)
        pm_df   = load_pm(sym)
        rt_df   = load_rt(sym)
        pm_stats = build_pm_stats(pm_df, rt_df)

        trades = run(rt_df, pm_stats, gap_thresh=-0.5)
        report(trades, sym, -0.5)

        if trades:
            pd.DataFrame(trades).to_csv(f"boof51_{sym}_gap_trades.csv", index=False)
            print(f"  Saved boof51_{sym}_gap_trades.csv", flush=True)
