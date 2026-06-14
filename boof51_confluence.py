"""
BOOF51 Confluence Level Scanner
For every minute bar: calculate distance to key levels, score confluence,
measure MFE/MAE at 15/30/60, classify reaction type.
No entries. No exits. No PF. Pure excursion from level touch.
"""
import pandas as pd
import numpy as np
import pytz

ET  = pytz.timezone("America/New_York")
SYM = "QQQ"

NEAR_PCT = 0.0015      # within 0.15% = "near" a level
TARGETS  = [0.0050, 0.0075]
T_LABELS = ["+0.50%", "+0.75%"]


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_rt():
    df = pd.read_csv(f"boof51_{SYM}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def load_pm():
    df = pd.read_csv(f"boof51_{SYM}_pm.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df

def build_pm_stats(pm_df, rt_df):
    pm_df = pm_df.copy(); pm_df["date"] = pm_df["time"].dt.date
    dc = rt_df.groupby("date")["close"].last().reset_index()
    dc.columns = ["date","prev_close"]; dc["date"] = pd.to_datetime(dc["date"])
    dc["next_date"] = dc["date"] + pd.Timedelta(days=1)
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"] = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct"])


# ── S/R from higher timeframes ────────────────────────────────────────────────

def build_sr_levels(rt_df, lookback_bars, label):
    """
    Rolling pivot highs/lows over lookback_bars on 1m data
    Returns dict: date -> list of (level, type) tuples
    """
    rt_df = rt_df.sort_values("time").reset_index(drop=True)
    sr = {}
    dates = sorted(rt_df["date"].unique())
    for d in dates:
        # Use all bars up to start of this day
        hist = rt_df[rt_df["date"] < d].tail(lookback_bars)
        if len(hist) < lookback_bars // 2: continue
        highs = hist["high"].values; lows = hist["low"].values
        # Simple pivot: bars that are local max/min over 5-bar window
        levels = []
        for i in range(5, len(hist)-5):
            if highs[i] == max(highs[i-5:i+6]):
                levels.append((highs[i], "res"))
            if lows[i] == min(lows[i-5:i+6]):
                levels.append((lows[i], "sup"))
        # Cluster: merge levels within 0.20% of each other
        if not levels: continue
        levels = sorted(levels, key=lambda x: x[0])
        clustered = [levels[0]]
        for lv, lt in levels[1:]:
            if abs(lv - clustered[-1][0]) / clustered[-1][0] < 0.002:
                clustered[-1] = ((clustered[-1][0]+lv)/2, lt)
            else:
                clustered.append((lv, lt))
        sr[d] = clustered
    return sr


# ── Distance calculator ───────────────────────────────────────────────────────

def nearest_level(price, levels):
    """Returns (distance_pct, level_price) for nearest level."""
    if not levels: return np.nan, np.nan
    dists = [(abs(price-lv)/price, lv) for lv,_ in levels]
    return min(dists, key=lambda x: x[0])


# ── Confluence score ──────────────────────────────────────────────────────────

def score_bar(close, pdh, pdl, pmh, pml, sr1h, sr4h, near=NEAR_PCT):
    score = 0; levels_hit = []
    def check(level, pts, name):
        nonlocal score
        if pd.isna(level): return
        if abs(close - level) / close <= near:
            score += pts; levels_hit.append(name)

    check(pdh, 5, "PDH"); check(pdl, 5, "PDL")
    check(pmh, 4, "PMH"); check(pml, 4, "PML")

    if sr4h:
        d4, l4 = nearest_level(close, sr4h)
        if not pd.isna(d4) and d4 <= near:
            score += 3; levels_hit.append(f"4H_SR@{l4:.2f}")

    if sr1h:
        d1, l1 = nearest_level(close, sr1h)
        if not pd.isna(d1) and d1 <= near:
            score += 2; levels_hit.append(f"1H_SR@{l1:.2f}")

    return score, levels_hit


# ── Reaction type classifier ──────────────────────────────────────────────────

def classify_reaction(ddf, i, ep, direction):
    """
    After touching a level, classify the next 5-bar reaction.
    direction: "above" (price approached from above) or "below"
    Returns: "rejection", "breakout", "retest_continue", "chop"
    """
    if i + 6 >= len(ddf): return "insufficient"
    future = ddf.iloc[i+1:i+6]
    f_high = future["high"].max(); f_low = future["low"].min()
    f_close5 = future.iloc[-1]["close"]
    move_up   = (f_high - ep) / ep * 100
    move_down = (ep - f_low)  / ep * 100

    if direction == "above":      # approached from above, level is support
        if move_down > 0.20 and f_close5 < ep:   return "rejection"       # bounced away down
        if move_up   > 0.20 and f_close5 > ep:   return "breakout"        # continued up through
        if abs(f_close5 - ep)/ep < 0.001:         return "retest_continue" # stuck at level
        return "chop"
    else:                          # approached from below, level is resistance
        if move_up   > 0.20 and f_close5 > ep:   return "rejection"       # broke above
        if move_down > 0.20 and f_close5 < ep:   return "breakout"        # continued down
        if abs(f_close5 - ep)/ep < 0.001:         return "retest_continue"
        return "chop"


# ── Excursion ─────────────────────────────────────────────────────────────────

def exc(ddf, ei, ep):
    """Both directions — return best (for level study we measure both)."""
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"15"),(30,"30"),(60,"60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[f"mfe{key}"] = float(max((H[sl]-ep)/ep*100))
        res[f"mae{key}"] = float(max((ep-L[sl])/ep*100))
        res[f"mfe{key}_s"] = float(max((ep-L[sl])/ep*100))   # short direction
        res[f"mae{key}_s"] = float(max((H[sl]-ep)/ep*100))
    end30=min(ei+30,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_up_{lbl}"]  = bool(any(H[ei:end30+1] >= ep*(1+tgt)))
        res[f"hit_dn_{lbl}"]  = bool(any(L[ei:end30+1] <= ep*(1-tgt)))
    return res


# ── Main scanner ──────────────────────────────────────────────────────────────

def scan(rt_df, pm_stats):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm    = pm_stats.set_index("date")
    dates = sorted(rt_df["date"].unique())

    # Build S/R levels: 1H ~ 60 bars, 4H ~ 240 bars
    print("  Building 1H S/R levels...", flush=True)
    sr_1h = build_sr_levels(rt_df, 60,  "1H")
    print("  Building 4H S/R levels...", flush=True)
    sr_4h = build_sr_levels(rt_df, 240, "4H")

    # Prev-day high/low lookup
    prev_day = {}
    for i in range(1, len(dates)):
        d = dates[i]; prev_d = dates[i-1]
        prev_bars = rt_df[rt_df["date"] == prev_d]
        if not prev_bars.empty:
            prev_day[d] = (prev_bars["high"].max(), prev_bars["low"].min())

    records = []
    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day["pm_high"]): continue

        pmh = day["pm_high"]; pml = day["pm_low"]
        pdh, pdl = prev_day.get(date, (np.nan, np.nan))

        s1h = sr_1h.get(date.date() if hasattr(date,"date") else date, [])
        s4h = sr_4h.get(date.date() if hasattr(date,"date") else date, [])

        ddf = ddf.reset_index(drop=True)

        # Only scan RTH 9:00-12:00
        for i in range(len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue

            close = row["close"]
            sc, hits = score_bar(close, pdh, pdl, pmh, pml, s1h, s4h)
            if sc == 0: continue    # not near any level

            # Distance to each level
            dist_pdh = abs(close-pdh)/close*100 if not pd.isna(pdh) else np.nan
            dist_pdl = abs(close-pdl)/close*100 if not pd.isna(pdl) else np.nan
            dist_pmh = abs(close-pmh)/close*100
            dist_pml = abs(close-pml)/close*100
            d1h, _ = nearest_level(close, s1h) if s1h else (np.nan, np.nan)
            d4h, _ = nearest_level(close, s4h) if s4h else (np.nan, np.nan)

            # Approach direction
            prev_close = ddf.iloc[i-1]["close"] if i > 0 else close
            approach = "above" if close <= prev_close else "below"

            # Reaction
            reaction = classify_reaction(ddf, i, close, approach)

            # Excursion from next bar
            ep = ddf.iloc[i+1]["open"]
            e  = exc(ddf, i+1, ep)

            records.append({
                "date":    str(date.date() if hasattr(date,"date") else date),
                "time":    t,
                "close":   round(close, 2),
                "score":   sc,
                "levels":  "|".join(hits),
                "approach":approach,
                "reaction":reaction,
                "dist_pdh":round(dist_pdh,4) if not pd.isna(dist_pdh) else np.nan,
                "dist_pdl":round(dist_pdl,4) if not pd.isna(dist_pdl) else np.nan,
                "dist_pmh":round(dist_pmh,4),
                "dist_pml":round(dist_pml,4),
                "dist_1h": round(d1h*100,4) if not pd.isna(d1h) else np.nan,
                "dist_4h": round(d4h*100,4) if not pd.isna(d4h) else np.nan,
                "gap_pct": round(float(day["gap_pct"]),3),
                "ep":      round(ep,2),
                **e
            })

    return pd.DataFrame(records)


# ── Report ────────────────────────────────────────────────────────────────────

def report(df):
    W = 108
    print(f"\n{'='*W}")
    print(f"  BOOF51 Confluence Scanner | {SYM} | Touch → Excursion")
    print(f"  Near threshold: {NEAR_PCT*100:.2f}% of price")
    print(f"{'='*W}")

    # ── By score bucket ───────────────────────────────────────────────────────
    print(f"\n  BY SCORE BUCKET (long direction = up, short = down)")
    print(f"  {'Score':<8} {'N':>5}  {'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'MAE15':>7} {'MAE30':>7} {'MAE60':>7}  {'>=0.50u':>8} {'>=0.75u':>8} {'>=0.50d':>8} {'>=0.75d':>8}")
    print(f"  {'-'*104}")

    buckets = [(2,3,"2-3"),(4,5,"4-5"),(6,7,"6-7"),(8,9,"8-9"),(10,99,"10+")]
    for lo,hi,lbl in buckets:
        s = df[(df["score"]>=lo)&(df["score"]<=hi)]
        if s.empty: continue
        n=len(s)
        m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
        a15=s["mae15"].mean(); a30=s["mae30"].mean(); a60=s["mae60"].mean()
        hu50=s["hit_up_+0.50%"].mean()*100; hu75=s["hit_up_+0.75%"].mean()*100
        hd50=s["hit_dn_+0.50%"].mean()*100; hd75=s["hit_dn_+0.75%"].mean()*100
        print(f"  {lbl:<8} {n:>5}  {m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
              f"{a15:>6.3f}% {a30:>6.3f}% {a60:>6.3f}%  "
              f"{hu50:>7.1f}% {hu75:>7.1f}% {hd50:>7.1f}% {hd75:>7.1f}%")

    # ── By reaction type ──────────────────────────────────────────────────────
    print(f"\n  BY REACTION TYPE (all score buckets combined)")
    print(f"  {'Reaction':<20} {'N':>5}  {'MFE30':>7} {'MAE30':>7}  {'>=0.50u':>8} {'>=0.75u':>8} {'>=0.50d':>8} {'>=0.75d':>8}")
    print(f"  {'-'*80}")
    for rxn in sorted(df["reaction"].unique()):
        s = df[df["reaction"]==rxn]
        if s.empty: continue
        print(f"  {rxn:<20} {len(s):>5}  {s['mfe30'].mean():>6.3f}% {s['mae30'].mean():>6.3f}%  "
              f"{s['hit_up_+0.50%'].mean()*100:>7.1f}% {s['hit_up_+0.75%'].mean()*100:>7.1f}% "
              f"{s['hit_dn_+0.50%'].mean()*100:>7.1f}% {s['hit_dn_+0.75%'].mean()*100:>7.1f}%")

    # ── Score x Reaction cross-tab ─────────────────────────────────────────────
    print(f"\n  SCORE x REACTION — MFE30 (up direction) | >=0.50% up")
    print(f"  {'Score':<8} {'Reaction':<20} {'N':>5}  {'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*65}")
    for lo,hi,lbl in buckets:
        sb = df[(df["score"]>=lo)&(df["score"]<=hi)]
        if sb.empty: continue
        for rxn, grp in sb.groupby("reaction"):
            if len(grp) < 3: continue
            print(f"  {lbl:<8} {rxn:<20} {len(grp):>5}  "
                  f"{grp['mfe30'].mean():>6.3f}%  "
                  f"{grp['hit_up_+0.50%'].mean()*100:>7.1f}%  "
                  f"{grp['hit_up_+0.75%'].mean()*100:>7.1f}%")

    # ── Level type breakdown ───────────────────────────────────────────────────
    print(f"\n  WHICH LEVELS FIRE MOST (score >= 4 only)")
    high_sc = df[df["score"]>=4]
    level_counts = {}
    for row in high_sc["levels"]:
        for lv in row.split("|"):
            lv_clean = lv.split("@")[0] if "@" in lv else lv
            level_counts[lv_clean] = level_counts.get(lv_clean, 0) + 1
    for lv, cnt in sorted(level_counts.items(), key=lambda x: -x[1]):
        subset = high_sc[high_sc["levels"].str.contains(lv.replace("+","\\+"), regex=True)]
        if subset.empty: continue
        print(f"  {lv:<12} N={cnt:>4}  MFE30={subset['mfe30'].mean():.3f}%  "
              f">=0.50%up={subset['hit_up_+0.50%'].mean()*100:.1f}%  "
              f">=0.50%dn={subset['hit_dn_+0.50%'].mean()*100:.1f}%")

    print(f"\n  Total bars scanned: {len(df):,}")
    print(f"  Score distribution: " +
          "  ".join([f"{lo}-{hi if hi<99 else '+'}: {len(df[(df['score']>=lo)&(df['score']<=hi)])}"
                     for lo,hi,_ in buckets]))


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    print(f"  {len(pm_stats)} days", flush=True)

    df = scan(rt_df, pm_stats)
    print(f"  {len(df):,} confluence touches found", flush=True)

    if not df.empty:
        report(df)
        df.to_csv(f"boof51_{SYM}_confluence.csv", index=False)
        print(f"\n  Saved boof51_{SYM}_confluence.csv")
