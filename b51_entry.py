"""
BOOF51 Entry Timing Study — QQQ Gap-Down Days
Same universe: gap_pct <= -0.5%, 9:00-12:00 ET
4 entry types tested for LONG and SHORT:
  A: Open       — enter at 9:30 open bar
  B: OR5 Break  — first break of 9:30-9:35 high/low
  C: PM H/L     — first break of premarket high/low
  D: VWAP Reclaim — first VWAP cross with momentum
Compare MFE at 15/30/60m and reach rates
"""
import pandas as pd
import pytz

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]

TARGETS  = [0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.50%", "+0.75%", "+1.00%"]


def load_pm(sym):
    df = pd.read_csv(f"boof51_{sym}_pm.csv")
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
    daily_close.columns = ["date", "prev_close"]
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
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M") == "09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index()
    rth.columns = ["date", "rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["gap_pct"])


def add_vwap(ddf):
    ddf = ddf.copy().reset_index(drop=True)
    ddf["typ"]  = (ddf["high"] + ddf["low"] + ddf["close"]) / 3
    ddf["pv"]   = ddf["typ"] * ddf["volume"]
    ddf["cpv"]  = ddf["pv"].cumsum()
    ddf["cvol"] = ddf["volume"].cumsum()
    ddf["vwap"] = ddf["cpv"] / ddf["cvol"]
    return ddf


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
    gap_days = pm_stats[pm_stats["gap_pct"] <= gap_thresh].set_index("date")

    entries = {
        "Open":  [],
        "OR5":   [],
        "PM_HL": [],
        "VWAP":  [],
    }

    for date, ddf in rt_df.groupby("date"):
        date = pd.Timestamp(date)
        if date not in gap_days.index: continue
        day     = gap_days.loc[date]
        pm_high = day["pm_high"]
        pm_low  = day["pm_low"]

        ddf = add_vwap(ddf).reset_index(drop=True)
        H   = ddf["high"].values; L = ddf["low"].values

        # ── Entry A: Open (9:30 bar) ──────────────────────────────────────
        open_bar = ddf[ddf["time"].dt.strftime("%H:%M") == "09:30"]
        if not open_bar.empty:
            ei = open_bar.index[0]
            ep = ddf.iloc[ei]["open"]
            # Both directions from open
            entries["Open"].append({"date":str(date.date()),"side":"long","ep":ep,
                                    **excursion(ddf, ei, ep, "long")})
            entries["Open"].append({"date":str(date.date()),"side":"short","ep":ep,
                                    **excursion(ddf, ei, ep, "short")})

        # ── Entry B: OR5 Break (first break of 9:30-9:34 range) ──────────
        or5 = ddf[ddf["time"].dt.strftime("%H:%M") < "09:35"]
        if len(or5) >= 2:
            or5h = or5["high"].max(); or5l = or5["low"].min()
            fl = fs = False
            post5 = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:35"].reset_index(drop=True)
            for i in range(len(post5) - 61):
                row = post5.iloc[i]; t = row["time"].strftime("%H:%M")
                if t >= "12:00": break
                if not fl and row["close"] > or5h:
                    fl = True
                    ei = i + 1; ep = post5.iloc[ei]["open"]
                    fi = ddf.index[ddf["time"] == post5.iloc[ei]["time"]].tolist()
                    if fi: entries["OR5"].append({"date":str(date.date()),"side":"long","ep":ep,
                                                  **excursion(ddf, fi[0], ep, "long")})
                if not fs and row["close"] < or5l:
                    fs = True
                    ei = i + 1; ep = post5.iloc[ei]["open"]
                    fi = ddf.index[ddf["time"] == post5.iloc[ei]["time"]].tolist()
                    if fi: entries["OR5"].append({"date":str(date.date()),"side":"short","ep":ep,
                                                  **excursion(ddf, fi[0], ep, "short")})

        # ── Entry C: PM High/Low Break ────────────────────────────────────
        fl = fs = False
        for i in range(len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            if not fl and row["close"] > pm_high:
                fl = True; ei = i+1; ep = ddf.iloc[ei]["open"]
                entries["PM_HL"].append({"date":str(date.date()),"side":"long","ep":ep,
                                         **excursion(ddf, ei, ep, "long")})
            if not fs and row["close"] < pm_low:
                fs = True; ei = i+1; ep = ddf.iloc[ei]["open"]
                entries["PM_HL"].append({"date":str(date.date()),"side":"short","ep":ep,
                                         **excursion(ddf, ei, ep, "short")})

        # ── Entry D: VWAP Reclaim/Rejection ──────────────────────────────
        fl = fs = False
        for i in range(1, len(ddf) - 61):
            row = ddf.iloc[i]; prev = ddf.iloc[i-1]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            if pd.isna(row["vwap"]): continue
            # Reclaim: was below, now above
            if not fl and prev["close"] < prev["vwap"] and row["close"] > row["vwap"]:
                fl = True; ei = i+1; ep = ddf.iloc[ei]["open"]
                entries["VWAP"].append({"date":str(date.date()),"side":"long","ep":ep,
                                        **excursion(ddf, ei, ep, "long")})
            # Rejection: was above, now below
            if not fs and prev["close"] > prev["vwap"] and row["close"] < row["vwap"]:
                fs = True; ei = i+1; ep = ddf.iloc[ei]["open"]
                entries["VWAP"].append({"date":str(date.date()),"side":"short","ep":ep,
                                        **excursion(ddf, ei, ep, "short")})

    return entries


def report(entries, sym, gap_thresh):
    W = 85
    print(f"\n{'='*W}")
    print(f"  {sym} | Entry Timing Study | Gap <= {gap_thresh}% | 9:00-12:00 ET")
    print(f"{'='*W}")
    print(f"  {'Entry':<12} {'Side':<7} {'N':>5}  "
          f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'MAE60':>7}  {'≥0.50%':>7} {'≥0.75%':>7} {'≥1.00%':>7}")
    print(f"  {'-'*80}")

    for name, trades in entries.items():
        if not trades:
            print(f"  {name:<12} {'--':<7} {'0':>5}"); continue
        df = pd.DataFrame(trades)
        for side in ["long", "short", "all"]:
            s = df if side == "all" else df[df["side"] == side]
            if s.empty: continue
            m15  = s["mfe_15m"].mean(); m30 = s["mfe_30m"].mean(); m60 = s["mfe_60m"].mean()
            ma60 = s["mae_60m"].mean()
            h50  = s[f"hit_{T_LABELS[0]}"].mean()*100
            h75  = s[f"hit_{T_LABELS[1]}"].mean()*100
            h100 = s[f"hit_{T_LABELS[2]}"].mean()*100
            side_lbl = side.upper() if side != "all" else "BOTH"
            print(f"  {name:<12} {side_lbl:<7} {len(s):>5}  "
                  f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
                  f"{ma60:>6.3f}%  {h50:>6.1f}% {h75:>6.1f}% {h100:>6.1f}%")
        print(f"  {'-'*80}")


if __name__ == "__main__":
    for sym in SYMBOLS:
        print(f"Loading {sym}...", flush=True)
        pm_df    = load_pm(sym)
        rt_df    = load_rt(sym)
        pm_stats = build_pm_stats(pm_df, rt_df)

        entries = run(rt_df, pm_stats, gap_thresh=-0.5)
        report(entries, sym, -0.5)
