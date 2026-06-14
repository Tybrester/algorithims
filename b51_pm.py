"""
BOOF51 Premarket Conditions → Intraday MFE Study
Fetches 4:00-9:30 ET premarket bars + regular session
Tests: Gap, PM Range, PM High/Low Break, PM Volume
For each condition bucket: Avg MFE at 15/30/60m on all 9:00-12:00 ET bars
"""
import os, datetime
import pandas as pd
import numpy as np
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

ET = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]
PM_CACHE = "boof51_{sym}_pm.csv"
RT_CACHE = "boof51_{sym}_1m.csv"

# ── Fetch premarket ────────────────────────────────────────────────────────────

def fetch_pm(sym):
    cache = PM_CACHE.format(sym=sym)
    if os.path.exists(cache):
        print(f"  {sym} PM: loading from cache", flush=True)
        df = pd.read_csv(cache)
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        return df

    print(f"  {sym} PM: fetching from Alpaca...", flush=True)
    key    = "PK7N52NHGPS2GBVZU64BCUEDNO"
    secret = "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E"
    client = StockHistoricalDataClient(key, secret)

    end   = datetime.datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
    start = end - datetime.timedelta(days=190)

    req = StockBarsRequest(
        symbol_or_symbols=sym,
        timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        start=start, end=end,
        feed="iex"
    )
    bars = client.get_stock_bars(req).df
    bars = bars.reset_index()
    bars = bars.rename(columns={"symbol":"sym", "timestamp":"time"})
    if bars["time"].dt.tz is None:
        bars["time"] = bars["time"].dt.tz_localize("UTC")
    bars["time"] = bars["time"].dt.tz_convert(ET)

    # Keep only 4:00-9:29 ET
    bars = bars[(bars["time"].dt.hour >= 4) & (bars["time"].dt.hour < 9) |
                ((bars["time"].dt.hour == 9) & (bars["time"].dt.minute < 30))]
    bars = bars.sort_values("time").reset_index(drop=True)
    bars.to_csv(cache, index=False)
    print(f"    Saved {len(bars):,} PM bars", flush=True)
    return bars


# ── Build daily premarket stats ───────────────────────────────────────────────

def build_pm_stats(pm_df, rt_df):
    """For each trading day, compute gap, PM range, PM volume."""
    pm_df["date"] = pm_df["time"].dt.date
    rt_df["date"] = rt_df["time"].dt.date

    # Yesterday close from RT data
    daily_close = rt_df.groupby("date")["close"].last().reset_index()
    daily_close.columns = ["date", "prev_close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"])
    daily_close["next_date"] = daily_close["date"] + pd.Timedelta(days=1)

    records = []
    for date, g in pm_df.groupby("date"):
        pm_high  = g["high"].max()
        pm_low   = g["low"].min()
        pm_range = (pm_high - pm_low) / pm_low * 100
        pm_vol   = g["volume"].sum()
        pm_open  = g.iloc[0]["open"]
        records.append({
            "date":     date,
            "pm_high":  pm_high,
            "pm_low":   pm_low,
            "pm_range": pm_range,
            "pm_vol":   pm_vol,
            "pm_open":  pm_open,
        })

    stats = pd.DataFrame(records)
    stats["date"] = pd.to_datetime(stats["date"])

    # Merge prev_close
    stats = stats.merge(
        daily_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    )

    # Get RTH open (first bar at 9:30)
    rth_open = rt_df[rt_df["time"].dt.strftime("%H:%M") == "09:30"].copy()
    rth_open["date"] = pd.to_datetime(rth_open["date"])
    rth_open = rth_open.groupby("date")["open"].first().reset_index()
    rth_open.columns = ["date","rth_open"]
    stats = stats.merge(rth_open, on="date", how="left")

    # Gap %
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100

    # PM vol z-score (rolling 20-day)
    stats = stats.sort_values("date").reset_index(drop=True)
    stats["pm_vol_ma20"] = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"]= stats["pm_vol"] / stats["pm_vol_ma20"]

    return stats


# ── Excursion on RTH bars ─────────────────────────────────────────────────────

def compute_mfe_for_day(ddf, side):
    """Return MFE at 15/30/60 bars from 9:30 open."""
    ddf = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:30"].reset_index(drop=True)
    if len(ddf) < 2: return None
    ep = ddf.iloc[0]["open"]
    H  = ddf["high"].values; L = ddf["low"].values
    res = {}
    for bars, key in [(15,"15m"),(30,"30m"),(60,"60m")]:
        end = min(bars, len(ddf)-1)
        if side == "long":
            res[f"mfe_{key}"] = max((H[:end+1] - ep) / ep * 100)
        else:
            res[f"mfe_{key}"] = max((ep - L[:end+1]) / ep * 100)
    return res


# ── Bucket analysis ───────────────────────────────────────────────────────────

def analyze(pm_stats, rt_df, sym):
    rt_df = rt_df.copy()
    rt_df["date"] = pd.to_datetime(rt_df["time"].dt.date)

    # For each day compute both-direction MFE (use absolute best)
    day_mfe = []
    for date, ddf in rt_df.groupby("date"):
        long_r  = compute_mfe_for_day(ddf, "long")
        short_r = compute_mfe_for_day(ddf, "short")
        if long_r is None: continue
        # Track best direction MFE and also PM high/low break intraday
        rth_bars = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:30"].reset_index(drop=True)

        # Check if PM high/low broken intraday (first 60 bars)
        end60 = min(60, len(rth_bars)-1)
        H60   = rth_bars["high"].values[:end60+1]
        L60   = rth_bars["low"].values[:end60+1]

        pm_row = pm_stats[pm_stats["date"] == pd.Timestamp(date)]
        if pm_row.empty: continue
        pm_row = pm_row.iloc[0]

        pm_high_broken = bool(any(H60 > pm_row["pm_high"]))
        pm_low_broken  = bool(any(L60 < pm_row["pm_low"]))

        day_mfe.append({
            "date":           date,
            "mfe_15m_long":   long_r["mfe_15m"],
            "mfe_30m_long":   long_r["mfe_30m"],
            "mfe_60m_long":   long_r["mfe_60m"],
            "mfe_15m_short":  short_r["mfe_15m"],
            "mfe_30m_short":  short_r["mfe_30m"],
            "mfe_60m_short":  short_r["mfe_60m"],
            "mfe_60m_best":   max(long_r["mfe_60m"], short_r["mfe_60m"]),
            "pm_high_broken": pm_high_broken,
            "pm_low_broken":  pm_low_broken,
        })

    mfe_df = pd.DataFrame(day_mfe)
    mfe_df["date"] = pd.to_datetime(mfe_df["date"])
    merged = mfe_df.merge(pm_stats, on="date", how="inner")

    W = 70
    print(f"\n{'='*W}")
    print(f"  {sym} | Premarket Condition → Intraday MFE (9:30 open, best direction)")
    print(f"{'='*W}")
    print(f"  {'Condition':<30} {'N':>5}  {'MFE15':>7} {'MFE30':>7} {'MFE60':>7}")
    print(f"  {'-'*65}")

    def row(label, mask):
        s = merged[mask]
        if len(s) == 0:
            print(f"  {label:<30} {'0':>5}"); return
        print(f"  {label:<30} {len(s):>5}  "
              f"{s['mfe_15m_long'].mean():>6.3f}% "
              f"{s['mfe_30m_long'].mean():>6.3f}% "
              f"{s['mfe_60m_best'].mean():>6.3f}%")

    # Gap buckets (long side for gaps up, short for gaps down — but showing best)
    row("Gap Up   > +1.0%",  merged["gap_pct"] >  1.0)
    row("Gap Up   +0.5-1.0%",  (merged["gap_pct"] >= 0.5) & (merged["gap_pct"] <  1.0))
    row("Flat     -0.5 to +0.5%", (merged["gap_pct"] >= -0.5) & (merged["gap_pct"] < 0.5))
    row("Gap Down -0.5 to -1.0%", (merged["gap_pct"] <= -0.5) & (merged["gap_pct"] > -1.0))
    row("Gap Down < -1.0%",  merged["gap_pct"] < -1.0)

    print(f"  {'-'*65}")
    row("PM Range < 0.5%",   merged["pm_range"] < 0.5)
    row("PM Range 0.5-1.0%", (merged["pm_range"] >= 0.5) & (merged["pm_range"] < 1.0))
    row("PM Range 1.0-1.5%", (merged["pm_range"] >= 1.0) & (merged["pm_range"] < 1.5))
    row("PM Range > 1.5%",   merged["pm_range"] >= 1.5)

    print(f"  {'-'*65}")
    row("PM High Broken",    merged["pm_high_broken"] == True)
    row("PM High NOT Broken",merged["pm_high_broken"] == False)
    row("PM Low Broken",     merged["pm_low_broken"]  == True)
    row("PM Low NOT Broken", merged["pm_low_broken"]  == False)

    print(f"  {'-'*65}")
    row("PM Vol > 2x avg",   merged["pm_vol_ratio"] > 2.0)
    row("PM Vol 1.5-2x avg", (merged["pm_vol_ratio"] >= 1.5) & (merged["pm_vol_ratio"] < 2.0))
    row("PM Vol 1.0-1.5x avg",(merged["pm_vol_ratio"] >= 1.0) & (merged["pm_vol_ratio"] < 1.5))
    row("PM Vol < 1x avg",   merged["pm_vol_ratio"] < 1.0)

    print(f"  {'-'*65}")
    row("ALL DAYS",          pd.Series([True]*len(merged), index=merged.index))

    return merged


if __name__ == "__main__":
    for sym in SYMBOLS:
        print(f"\n--- {sym} ---", flush=True)
        pm_df = fetch_pm(sym)
        rt_df = pd.read_csv(RT_CACHE.format(sym=sym))
        rt_df["time"] = pd.to_datetime(rt_df["time"], utc=True).dt.tz_convert(ET)

        pm_stats = build_pm_stats(pm_df, rt_df)
        print(f"  PM stats: {len(pm_stats)} days", flush=True)

        merged = analyze(pm_stats, rt_df, sym)
        merged.to_csv(f"boof51_{sym}_pm_study.csv", index=False)
        print(f"  Saved boof51_{sym}_pm_study.csv", flush=True)
