"""
BOOF52 v2 — Clean Restart
Day filter: pm_range >= 0.50% OR abs(gap) >= 0.50% OR pm_vol_ratio >= 1.5
Entry:
  Long:  break above PM high OR OR5 high
         + vol > 2x avg + candle_body > 0.20% + close near high
  Short: break below PM low  OR OR5 low
         + vol > 2x avg + candle_body > 0.20% + close near low
Window: 9:00-12:00 ET
Measure: MFE30, MAE30, % >= +0.50%, % >= +0.75% within 30m
"""
import pandas as pd
import numpy as np
import pytz

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]

TARGETS  = [0.0050, 0.0075]
T_LABELS = ["+0.50%", "+0.75%"]


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_rt(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df


def load_pm(sym):
    df = pd.read_csv(f"boof51_{sym}_pm.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df


def build_pm_stats(pm_df, rt_df):
    pm_df = pm_df.copy(); pm_df["date"] = pm_df["time"].dt.date
    dc = rt_df.groupby("date")["close"].last().reset_index()
    dc.columns = ["date","prev_close"]; dc["date"] = pd.to_datetime(dc["date"])
    dc["next_date"] = dc["date"] + pd.Timedelta(days=1)

    records = []
    for d, g in pm_df.groupby("date"):
        records.append({
            "date":         pd.Timestamp(d),
            "pm_high":      g["high"].max(),
            "pm_low":       g["low"].min(),
            "pm_range_pct": (g["high"].max() - g["low"].min()) / g["low"].min() * 100,
            "pm_vol":       g["volume"].sum(),
        })
    stats = pd.DataFrame(records)
    stats = stats.merge(
        dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    )
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M") == "09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index()
    rth.columns = ["date","rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"]      = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    stats["pm_vol_ma20"]  = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"] = stats["pm_vol"] / stats["pm_vol_ma20"]
    # Day has energy
    stats["has_energy"]   = (
        (stats["pm_range_pct"] >= 0.50) |
        (stats["gap_pct"].abs() >= 0.50) |
        (stats["pm_vol_ratio"] >= 1.50)
    )
    return stats.dropna(subset=["gap_pct"])


def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]      = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]       = df["typ"] * df["volume"]
    df["cpv"]      = df.groupby("date")["pv"].cumsum()
    df["cvol"]     = df.groupby("date")["volume"].cumsum()
    df["vwap"]     = df["cpv"] / df["cvol"]
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["body_pct"] = (df["close"] - df["open"]).abs() / df["open"] * 100
    df["near_high"]= (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-9)
    df["near_low"] = (df["high"] - df["close"]) / (df["high"] - df["low"] + 1e-9)
    return df


# ── Excursion ─────────────────────────────────────────────────────────────────

def excursion(ddf, ei, ep, side):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values
    end = min(ei + 30, n - 1); sl = slice(ei, end + 1)
    mfe = float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
    mae = float(max((ep-L[sl])/ep*100)) if side=="long" else float(max((H[sl]-ep)/ep*100))
    res = {"mfe_30m": mfe, "mae_30m": mae}
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end+1] >= ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end+1] <= ep*(1-tgt)))
    return res


# ── Entry filter ──────────────────────────────────────────────────────────────

def entry_ok(row, side, vol_ma):
    """Volume > 1.5x, body > 0.10%, close near high (long) or low (short)."""
    if vol_ma <= 0 or pd.isna(vol_ma): return False
    vol_ok  = row["volume"] > 1.5 * vol_ma
    body_ok = row["body_pct"] > 0.10
    if side == "long":
        dir_ok  = row["close"] > row["open"]          # green candle
        near_ok = row["near_high"] > 0.50             # close in top 50% of range
    else:
        dir_ok  = row["close"] < row["open"]          # red candle
        near_ok = row["near_low"] > 0.50              # close in bottom 50% of range
    return vol_ok and body_ok and dir_ok and near_ok


# ── Main run ──────────────────────────────────────────────────────────────────

def run(rt_df, pm_stats):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm    = pm_stats[pm_stats["has_energy"]].set_index("date")

    trades = []

    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        pm_high = day["pm_high"]; pm_low = day["pm_low"]

        ddf = ddf.reset_index(drop=True)

        # OR5: first 5 bars of RTH (9:30-9:34)
        or5 = ddf[ddf["time"].dt.strftime("%H:%M") < "09:35"]
        or5h = or5["high"].max() if len(or5) else pm_high
        or5l = or5["low"].min()  if len(or5) else pm_low

        long_pm = long_or5 = short_pm = short_or5 = False

        for i in range(20, len(ddf) - 31):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            vol_ma = row["vol_ma20"]
            if pd.isna(vol_ma) or vol_ma <= 0: continue

            ei = i + 1
            if ei >= len(ddf): continue
            ep = ddf.iloc[ei]["open"]

            # ── LONG entries ─────────────────────────────────────────────────
            # A: PM high break
            if not long_pm and row["close"] > pm_high and entry_ok(row, "long", vol_ma):
                long_pm = True
                exc = excursion(ddf, ei, ep, "long")
                trades.append({"date":str(date),"sym":"","signal":"PM_High_Brk","side":"long",
                               "gap_pct":round(day["gap_pct"],3),"pm_range":round(day["pm_range_pct"],3),
                               "vol_ratio":round(day["pm_vol_ratio"],2),"ep":ep,**exc})

            # B: OR5 high break (only if different from PM high)
            if (not long_or5 and or5h != pm_high and
                    row["close"] > or5h and entry_ok(row, "long", vol_ma)):
                long_or5 = True
                exc = excursion(ddf, ei, ep, "long")
                trades.append({"date":str(date),"sym":"","signal":"OR5_High_Brk","side":"long",
                               "gap_pct":round(day["gap_pct"],3),"pm_range":round(day["pm_range_pct"],3),
                               "vol_ratio":round(day["pm_vol_ratio"],2),"ep":ep,**exc})

            # ── SHORT entries ─────────────────────────────────────────────────
            # A: PM low break
            if not short_pm and row["close"] < pm_low and entry_ok(row, "short", vol_ma):
                short_pm = True
                exc = excursion(ddf, ei, ep, "short")
                trades.append({"date":str(date),"sym":"","signal":"PM_Low_Brk","side":"short",
                               "gap_pct":round(day["gap_pct"],3),"pm_range":round(day["pm_range_pct"],3),
                               "vol_ratio":round(day["pm_vol_ratio"],2),"ep":ep,**exc})

            # B: OR5 low break
            if (not short_or5 and or5l != pm_low and
                    row["close"] < or5l and entry_ok(row, "short", vol_ma)):
                short_or5 = True
                exc = excursion(ddf, ei, ep, "short")
                trades.append({"date":str(date),"sym":"","signal":"OR5_Low_Brk","side":"short",
                               "gap_pct":round(day["gap_pct"],3),"pm_range":round(day["pm_range_pct"],3),
                               "vol_ratio":round(day["pm_vol_ratio"],2),"ep":ep,**exc})

    return pd.DataFrame(trades) if trades else pd.DataFrame()


# ── Report ────────────────────────────────────────────────────────────────────

def report(df, sym, pm_stats):
    n_days   = len(pm_stats)
    n_energy = pm_stats["has_energy"].sum()
    W = 88

    print(f"\n{'='*W}")
    print(f"  BOOF52 v2 | {sym} | Energy days: {n_energy}/{n_days} | Signals: {len(df)}")
    print(f"{'='*W}")

    if df.empty:
        print("  No trades."); return

    print(f"  {'Signal':<16} {'Side':<7} {'N':>5} {'Days':>5} {'TPD':>5}  "
          f"{'MFE30':>7} {'MAE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
    print(f"  {'-'*82}")

    # All signals combined
    for grp_key, grp_df in [("ALL", df)] + [(s, df[df["signal"]==s]) for s in df["signal"].unique()]:
        if grp_df.empty: continue
        for side in ["long","short","all"]:
            s = grp_df if side=="all" else grp_df[grp_df["side"]==side]
            if s.empty: continue
            nd   = s["date"].nunique(); tpd = len(s)/nd
            m30  = s["mfe_30m"].mean(); ma30 = s["mae_30m"].mean()
            h50  = s[f"hit_{T_LABELS[0]}"].mean()*100
            h75  = s[f"hit_{T_LABELS[1]}"].mean()*100
            slbl = side.upper() if side!="all" else "BOTH"
            lbl  = grp_key if side!="all" else ""
            print(f"  {lbl:<16} {slbl:<7} {len(s):>5} {nd:>5} {tpd:>5.1f}  "
                  f"{m30:>6.3f}% {ma30:>6.3f}%  {h50:>7.1f}% {h75:>7.1f}%")
        if grp_key != "ALL":
            print(f"  {'-'*82}")

    # Day filter breakdown
    print(f"\n  DAY FILTER CONTRIBUTION (energy days, N={n_energy})")
    print(f"  {'Filter triggered by':<28} {'N days':>7}")
    print(f"  {'-'*38}")
    pm2 = pm_stats.copy()
    r1 = (pm2["pm_range_pct"] >= 0.50).sum()
    r2 = (pm2["gap_pct"].abs() >= 0.50).sum()
    r3 = (pm2["pm_vol_ratio"] >= 1.50).sum()
    print(f"  {'PM Range >= 0.50%':<28} {r1:>7}")
    print(f"  {'abs(Gap) >= 0.50%':<28} {r2:>7}")
    print(f"  {'PM Vol Ratio >= 1.5x':<28} {r3:>7}")
    print(f"  {'Any (total energy days)':<28} {n_energy:>7}")

    # Gap regime breakdown
    print(f"\n  BY GAP REGIME")
    print(f"  {'Regime':<20} {'N':>5}  {'MFE30':>7} {'MAE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
    print(f"  {'-'*65}")
    regimes = [
        ("Gap Down <-0.5%",  df["gap_pct"] < -0.5),
        ("Flat -0.5 to 0.5%",(df["gap_pct"] >= -0.5) & (df["gap_pct"] <= 0.5)),
        ("Gap Up >+0.5%",    df["gap_pct"] > 0.5),
    ]
    for lbl, mask in regimes:
        s = df[mask]
        if s.empty: continue
        print(f"  {lbl:<20} {len(s):>5}  {s['mfe_30m'].mean():>6.3f}% {s['mae_30m'].mean():>6.3f}%  "
              f"{s[f'hit_{T_LABELS[0]}'].mean()*100:>7.1f}% {s[f'hit_{T_LABELS[1]}'].mean()*100:>7.1f}%")


if __name__ == "__main__":
    for sym in SYMBOLS:
        print(f"Loading {sym}...", flush=True)
        pm_df    = load_pm(sym)
        rt_df    = load_rt(sym)
        rt_df    = add_indicators(rt_df)
        pm_stats = build_pm_stats(pm_df, rt_df)

        n_energy = pm_stats["has_energy"].sum()
        print(f"  {n_energy}/{len(pm_stats)} energy days", flush=True)

        trades = run(rt_df, pm_stats)
        print(f"  {len(trades)} signals", flush=True)

        report(trades, sym, pm_stats)

        if not trades.empty:
            trades.to_csv(f"boof52v2_{sym}_trades.csv", index=False)
            print(f"  Saved boof52v2_{sym}_trades.csv", flush=True)
