"""
BOOF51 Gap-Down Reversal Entry Study — QQQ
gap_pct <= -0.5%
Long:  first green candle after open OR break of first 1m high
Short: first red candle  after open OR break of first 1m low
Measure: MFE/MAE at 15/30/60m, reach rates
"""
import pandas as pd
import pytz

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]

TARGETS  = [0.0025, 0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%", "+1.00%"]


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
    stats = pd.DataFrame([
        {"date": pd.Timestamp(d), "pm_high": g["high"].max(), "pm_low": g["low"].min()}
        for d, g in pm_df.groupby("date")
    ])
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

    entries = {"green_candle": [], "or1_break": []}

    for date, ddf in rt_df.groupby("date"):
        date = pd.Timestamp(date)
        if date not in gap_days.index: continue
        day = gap_days.loc[date]

        ddf = ddf.reset_index(drop=True)

        # Get first bar (9:30)
        rth = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:30"].reset_index(drop=True)
        if len(rth) < 3: continue

        bar0 = rth.iloc[0]   # 9:30 bar
        or1h = bar0["high"]  # first 1m high
        or1l = bar0["low"]   # first 1m low

        # ── Entry A: First green/red candle ───────────────────────────────
        # Green = close > open; Red = close < open
        # Look at bar0 first, then subsequent bars
        long_green  = False
        short_red   = False

        for j in range(len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break

            if not long_green and row["close"] > row["open"]:
                long_green = True
                ei = j + 1; ep = rth.iloc[ei]["open"]
                # map back to full ddf index
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi:
                    entries["green_candle"].append({
                        "date": str(date.date()), "side": "long",
                        "gap_pct": day["gap_pct"], "bar_num": j,
                        "ep": ep, **excursion(ddf, fi[0], ep, "long")
                    })

            if not short_red and row["close"] < row["open"]:
                short_red = True
                ei = j + 1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi:
                    entries["green_candle"].append({
                        "date": str(date.date()), "side": "short",
                        "gap_pct": day["gap_pct"], "bar_num": j,
                        "ep": ep, **excursion(ddf, fi[0], ep, "short")
                    })

            if long_green and short_red:
                break

        # ── Entry B: Break of first 1m high/low ──────────────────────────
        long_break  = False
        short_break = False

        for j in range(1, len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break

            if not long_break and row["close"] > or1h:
                long_break = True
                ei = j + 1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi:
                    entries["or1_break"].append({
                        "date": str(date.date()), "side": "long",
                        "gap_pct": day["gap_pct"], "bar_num": j,
                        "ep": ep, **excursion(ddf, fi[0], ep, "long")
                    })

            if not short_break and row["close"] < or1l:
                short_break = True
                ei = j + 1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi:
                    entries["or1_break"].append({
                        "date": str(date.date()), "side": "short",
                        "gap_pct": day["gap_pct"], "bar_num": j,
                        "ep": ep, **excursion(ddf, fi[0], ep, "short")
                    })

            if long_break and short_break:
                break

    return entries


def report(entries, sym, gap_thresh):
    W = 88
    print(f"\n{'='*W}")
    print(f"  {sym} | Gap-Down Reversal | gap <= {gap_thresh}%")
    print(f"{'='*W}")
    print(f"  {'Entry':<18} {'Side':<7} {'N':>5}  "
          f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'MAE60':>7}  "
          f"{'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7} {'≥1.00%':>7}")
    print(f"  {'-'*83}")

    labels = {
        "green_candle": "1st Green/Red",
        "or1_break":    "OR1 High/Low Brk",
    }

    for key, trades in entries.items():
        lbl = labels[key]
        if not trades:
            print(f"  {lbl:<18} {'--':<7} {'0':>5}"); continue
        df = pd.DataFrame(trades)

        for side in ["long", "short", "all"]:
            s = df if side == "all" else df[df["side"] == side]
            if s.empty: continue
            m15  = s["mfe_15m"].mean(); m30 = s["mfe_30m"].mean(); m60 = s["mfe_60m"].mean()
            ma60 = s["mae_60m"].mean()
            h25  = s[f"hit_{T_LABELS[0]}"].mean()*100
            h50  = s[f"hit_{T_LABELS[1]}"].mean()*100
            h75  = s[f"hit_{T_LABELS[2]}"].mean()*100
            h100 = s[f"hit_{T_LABELS[3]}"].mean()*100
            slbl = side.upper() if side != "all" else "BOTH"
            print(f"  {lbl:<18} {slbl:<7} {len(s):>5}  "
                  f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
                  f"{ma60:>6.3f}%  "
                  f"{h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}% {h100:>6.1f}%")

            # Bar timing — how many bars after open is the entry firing?
            avg_bar = s["bar_num"].mean()
            print(f"  {'':18} {'':7} {'':5}  avg entry bar: {avg_bar:.1f} (~{avg_bar:.0f}m after open)")

        print(f"  {'-'*83}")

        # Gap size breakdown
        df2 = pd.DataFrame(trades)
        print(f"  {'':18} BY GAP SIZE:")
        for lo, hi, glbl in [(-0.5, -1.0, "-0.5 to -1.0%"), (-1.0, -99, "< -1.0%")]:
            s = df2[(df2["gap_pct"] <= lo) & (df2["gap_pct"] > hi)] if hi != -99 else df2[df2["gap_pct"] <= lo]
            if s.empty: continue
            h50 = s[f"hit_{T_LABELS[1]}"].mean()*100; h75 = s[f"hit_{T_LABELS[2]}"].mean()*100
            print(f"  {'':18}   {glbl:<16} N={len(s)}  MFE60={s['mfe_60m'].mean():.3f}%  "
                  f"≥0.50%={h50:.1f}%  ≥0.75%={h75:.1f}%")
        print()


def run_regime(rt_df, pm_stats, mask, label):
    """Same run() logic but filtered to a specific gap regime mask."""
    rt_df = rt_df.copy()
    rt_df["date"] = pd.to_datetime(rt_df["date"])
    regime_days = pm_stats[mask].set_index("date")

    entries = {"green_candle": [], "or1_break": []}

    for date, ddf in rt_df.groupby("date"):
        date = pd.Timestamp(date)
        if date not in regime_days.index: continue
        day = regime_days.loc[date]

        ddf = ddf.reset_index(drop=True)
        rth = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:30"].reset_index(drop=True)
        if len(rth) < 3: continue

        bar0 = rth.iloc[0]
        or1h = bar0["high"]; or1l = bar0["low"]

        long_green = short_red = False
        for j in range(len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break
            if not long_green and row["close"] > row["open"]:
                long_green = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: entries["green_candle"].append({"date":str(date.date()),"side":"long","gap_pct":day["gap_pct"],"bar_num":j,"ep":ep,**excursion(ddf,fi[0],ep,"long")})
            if not short_red and row["close"] < row["open"]:
                short_red = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: entries["green_candle"].append({"date":str(date.date()),"side":"short","gap_pct":day["gap_pct"],"bar_num":j,"ep":ep,**excursion(ddf,fi[0],ep,"short")})
            if long_green and short_red: break

        long_break = short_break = False
        for j in range(1, len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break
            if not long_break and row["close"] > or1h:
                long_break = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: entries["or1_break"].append({"date":str(date.date()),"side":"long","gap_pct":day["gap_pct"],"bar_num":j,"ep":ep,**excursion(ddf,fi[0],ep,"long")})
            if not short_break and row["close"] < or1l:
                short_break = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: entries["or1_break"].append({"date":str(date.date()),"side":"short","gap_pct":day["gap_pct"],"bar_num":j,"ep":ep,**excursion(ddf,fi[0],ep,"short")})
            if long_break and short_break: break

    return entries


def regime_summary(all_results, sym):
    """Print side-by-side comparison across gap regimes."""
    W = 80
    print(f"\n{'='*W}")
    print(f"  {sym} | GAP REGIME COMPARISON | 1st Green/Red Candle Entry")
    print(f"{'='*W}")
    print(f"  {'Regime':<16} {'Side':<7} {'N':>5}  "
          f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'MAE60':>7}  {'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7}")
    print(f"  {'-'*75}")

    for regime_lbl, entries in all_results:
        trades = entries["green_candle"]
        if not trades:
            print(f"  {regime_lbl:<16} {'--'} N=0"); continue
        df = pd.DataFrame(trades)
        for side in ["long", "short", "all"]:
            s = df if side == "all" else df[df["side"] == side]
            if s.empty: continue
            slbl = side.upper() if side != "all" else "BOTH"
            m15  = s["mfe_15m"].mean(); m30 = s["mfe_30m"].mean(); m60 = s["mfe_60m"].mean()
            ma60 = s["mae_60m"].mean()
            h25  = s[f"hit_{T_LABELS[0]}"].mean()*100
            h50  = s[f"hit_{T_LABELS[1]}"].mean()*100
            h75  = s[f"hit_{T_LABELS[2]}"].mean()*100
            print(f"  {regime_lbl:<16} {slbl:<7} {len(s):>5}  "
                  f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
                  f"{ma60:>6.3f}%  {h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}%")
        print(f"  {'-'*75}")


if __name__ == "__main__":
    REGIMES = [
        ("Gap Down ≤-0.5%", lambda s: s["gap_pct"] <= -0.5),
        ("Flat -0.5–+0.5%", lambda s: (s["gap_pct"] > -0.5) & (s["gap_pct"] < 0.5)),
        ("Gap Up  ≥+0.5%",  lambda s: s["gap_pct"] >= 0.5),
    ]

    for sym in SYMBOLS:
        print(f"\nLoading {sym}...", flush=True)
        pm_df    = load_pm(sym)
        rt_df    = load_rt(sym)
        pm_stats = build_pm_stats(pm_df, rt_df)

        all_results = []
        for lbl, mask_fn in REGIMES:
            mask = mask_fn(pm_stats)
            n = mask.sum()
            print(f"  {lbl}: {n} days", flush=True)
            entries = run_regime(rt_df, pm_stats, mask, lbl)
            all_results.append((lbl, entries))

        regime_summary(all_results, sym)
