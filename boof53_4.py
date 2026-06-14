"""
BOOF53.4 — Level Tier Hierarchy
Tier 1: PDH, PDL, PMH, PML
Tier 2: 1H S/R (60-bar pivots)
Tier 3: 30m S/R (30-bar pivots), 10m S/R (10-bar pivots)

Same multi-touch pattern as 53.3:
  touch level → bounce/reject >=0.15% → return → confirm → entry

Test:
  Tier 1 only
  Tier 2 only
  Tier 3 only
  Tier 1 + Tier 2 overlap (within 0.20%)
  Tier 1 + Tier 3 overlap
  Tier 2 + Tier 3 overlap
  All tiers overlap
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYM      = "QQQ"
NEAR_PCT = 0.0015    # touching threshold
BOUNCE   = 0.0015    # min bounce before return
OVERLAP  = 0.0020    # two levels "overlap" if within 0.20%
TARGETS  = [0.0050, 0.0075]
T_LABELS = ["+0.50%", "+0.75%"]


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
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct"])

def build_prev_day(rt_df):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    dates = sorted(rt_df["date"].unique())
    prev = {}
    for i in range(1, len(dates)):
        d = dates[i]; p = dates[i-1]
        g = rt_df[rt_df["date"]==p]
        if not g.empty:
            prev[d] = {"pdh": g["high"].max(), "pdl": g["low"].min()}
    return prev

def build_pivots(rt_df, lookback, wing):
    """Rolling pivot H/L. lookback=bars of history, wing=bars each side for local max/min."""
    rt_df = rt_df.sort_values("time").reset_index(drop=True)
    sr = {}
    dates = sorted(rt_df["date"].unique())
    for d in dates:
        hist = rt_df[rt_df["date"] < d].tail(lookback)
        if len(hist) < lookback // 2: continue
        H = hist["high"].values; L = hist["low"].values
        levels = []
        for i in range(wing, len(hist)-wing):
            if H[i] == max(H[i-wing:i+wing+1]):
                levels.append((H[i], "res"))
            if L[i] == min(L[i-wing:i+wing+1]):
                levels.append((L[i], "sup"))
        if not levels: continue
        levels = sorted(levels, key=lambda x: x[0])
        clustered = [list(levels[0])]
        for lv, lt in levels[1:]:
            if abs(lv-clustered[-1][0])/clustered[-1][0] < OVERLAP:
                clustered[-1][0] = (clustered[-1][0]+lv)/2
            else:
                clustered.append([lv, lt])
        sr[d] = [(c[0], c[1]) for c in clustered]
    return sr


def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars, key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key] = float(max((H[sl]-ep)/ep*100)) if side=="long" \
              else float(max((ep-L[sl])/ep*100))
    end30=min(ei+30,n-1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end30+1]>=ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end30+1]<=ep*(1-tgt)))
    return res


def find_touches(ddf, level, direction):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    entries=[]; touch_num=0; state="IDLE"; bounce_ext=None; i=1
    while i < n-31:
        t=ddf.iloc[i]["time"].strftime("%H:%M")
        if t<"09:00" or t>="12:00": i+=1; continue
        cl=C[i]; hi=H[i]; lo=L[i]
        if direction=="sup":
            touching = lo <= level*(1+NEAR_PCT)
            if state=="IDLE":
                if touching: state="TOUCHING"; bounce_ext=cl
            elif state=="TOUCHING":
                if touching: bounce_ext=max(bounce_ext,cl) if bounce_ext else cl
                else:
                    if bounce_ext and (bounce_ext-level)/level>=BOUNCE:
                        state="BOUNCED"; touch_num+=1
                    else: state="IDLE"
                    bounce_ext=None
            elif state=="BOUNCED":
                if touching:
                    if cl>level:
                        state="IDLE"; ei=i+1
                        if ei<n:
                            ep=ddf.iloc[ei]["open"]
                            entries.append({"bar_idx":i,"touch_num":touch_num,"ep":ep,
                                            **exc(ddf,ei,ep,"long")})
                    else: state="IDLE"; touch_num=0
        else:
            touching = hi >= level*(1-NEAR_PCT)
            if state=="IDLE":
                if touching: state="TOUCHING"; bounce_ext=cl
            elif state=="TOUCHING":
                if touching: bounce_ext=min(bounce_ext,cl) if bounce_ext else cl
                else:
                    if bounce_ext and (level-bounce_ext)/level>=BOUNCE:
                        state="BOUNCED"; touch_num+=1
                    else: state="IDLE"
                    bounce_ext=None
            elif state=="BOUNCED":
                if touching:
                    if cl<level:
                        state="IDLE"; ei=i+1
                        if ei<n:
                            ep=ddf.iloc[ei]["open"]
                            entries.append({"bar_idx":i,"touch_num":touch_num,"ep":ep,
                                            **exc(ddf,ei,ep,"short")})
                    else: state="IDLE"; touch_num=0
        i+=1
    return entries


def tiers_at_level(level, direction, t1_levels, t2_levels, t3_levels):
    """Return which tiers are active within OVERLAP % of this level."""
    tiers = set()
    for lv, lt in t1_levels:
        if lt==("sup" if direction=="sup" else "res") and abs(lv-level)/level<=OVERLAP:
            tiers.add(1)
    for lv, lt in t2_levels:
        if lt==("sup" if direction=="sup" else "res") and abs(lv-level)/level<=OVERLAP:
            tiers.add(2)
    for lv, lt in t3_levels:
        if lt==("sup" if direction=="sup" else "res") and abs(lv-level)/level<=OVERLAP:
            tiers.add(3)
    return tiers


def scan(rt_df, pm_stats, prev_day, sr_1h, sr_30m, sr_10m):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm    = pm_stats.set_index("date")
    records = []

    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        gap = day["gap_pct"]
        gap_regime = "Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")

        ddf = ddf.reset_index(drop=True)
        pmh = day["pm_high"]; pml = day["pm_low"]
        pd_info = prev_day.get(date_ts, {})
        pdh = pd_info.get("pdh", np.nan); pdl = pd_info.get("pdl", np.nan)

        dk = date.date() if hasattr(date,"date") else date
        lv_1h  = sr_1h.get(dk,  [])
        lv_30m = sr_30m.get(dk, [])
        lv_10m = sr_10m.get(dk, [])

        # Build Tier 1 as list of (price, type)
        t1_sup = [(pml,"sup")]
        t1_res = [(pmh,"res")]
        if not pd.isna(pdl): t1_sup.append((pdl,"sup"))
        if not pd.isna(pdh): t1_res.append((pdh,"res"))

        t2_sup = [(lv,"sup") for lv,lt in lv_1h  if lt=="sup"]
        t2_res = [(lv,"res") for lv,lt in lv_1h  if lt=="res"]
        t3_sup = [(lv,"sup") for lv,lt in lv_30m+lv_10m if lt=="sup"]
        t3_res = [(lv,"res") for lv,lt in lv_30m+lv_10m if lt=="res"]

        all_sup_t1 = t1_sup + [(lv,"sup") for lv,_ in t2_sup] + [(lv,"sup") for lv,_ in t3_sup]
        all_res_t1 = t1_res + [(lv,"res") for lv,_ in t2_res] + [(lv,"res") for lv,_ in t3_res]

        # All levels to scan (dedupe by proximity)
        def dedup_levels(level_list):
            if not level_list: return []
            out = [level_list[0][0]]
            for lv,_ in level_list[1:]:
                if all(abs(lv-x)/x > OVERLAP for x in out):
                    out.append(lv)
            return out

        for direction, lvl_list, t1l, t2l, t3l in [
            ("sup", dedup_levels(sorted(t1_sup+t2_sup+t3_sup, key=lambda x:x[0])),
             t1_sup, t2_sup, t3_sup),
            ("res", dedup_levels(sorted(t1_res+t2_res+t3_res, key=lambda x:x[0], reverse=True)),
             t1_res, t2_res, t3_res),
        ]:
            side = "long" if direction=="sup" else "short"
            for level in lvl_list:
                touches = find_touches(ddf, level, direction)
                for t in touches:
                    # Determine which tiers cover this level
                    active_tiers = set()
                    for lv, lt in t1l:
                        if lt==direction and abs(lv-level)/level<=OVERLAP: active_tiers.add(1)
                    for lv, lt in t2l:
                        if lt==direction and abs(lv-level)/level<=OVERLAP: active_tiers.add(2)
                    for lv, lt in t3l:
                        if lt==direction and abs(lv-level)/level<=OVERLAP: active_tiers.add(3)

                    if not active_tiers: continue

                    # Tier label
                    if active_tiers == {1}:          tier_lbl = "T1 only"
                    elif active_tiers == {2}:         tier_lbl = "T2 only"
                    elif active_tiers == {3}:         tier_lbl = "T3 only"
                    elif active_tiers == {1,2}:       tier_lbl = "T1+T2"
                    elif active_tiers == {1,3}:       tier_lbl = "T1+T3"
                    elif active_tiers == {2,3}:       tier_lbl = "T2+T3"
                    elif active_tiers == {1,2,3}:     tier_lbl = "T1+T2+T3"
                    else:                             tier_lbl = "other"

                    tlbl = "1st" if t["touch_num"]==1 else ("2nd" if t["touch_num"]==2 else "3rd+")
                    records.append({
                        "date":       str(date.date()),
                        "side":       side,
                        "direction":  direction,
                        "tier_lbl":   tier_lbl,
                        "tiers":      str(sorted(active_tiers)),
                        "gap_regime": gap_regime,
                        "gap_pct":    round(gap,3),
                        "touch_num":  t["touch_num"],
                        "touch_lbl":  tlbl,
                        "level_px":   round(level,2),
                        "ep":         t["ep"],
                        **{k:v for k,v in t.items() if k not in ("bar_idx","touch_num","ep")}
                    })

    return pd.DataFrame(records) if records else pd.DataFrame()


def prow(label, s, w=18):
    if s.empty:
        print(f"  {label:<{w}} {'--':>5}"); return
    n=len(s); nd=s["date"].nunique()
    m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    h50=s[f"hit_{T_LABELS[0]}"].mean()*100
    h75=s[f"hit_{T_LABELS[1]}"].mean()*100
    mark=" <<<" if h50>=30 else ("  <<" if h50>=25 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")


def report(df):
    W=80
    HDR=(f"  {'Tier':<18} {'N':>5} {'Days':>5}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP=f"  {'-'*76}"

    TIER_ORDER = ["T1 only","T2 only","T3 only","T1+T2","T1+T3","T2+T3","T1+T2+T3"]

    print(f"\n{'='*W}")
    print(f"  BOOF53.4 | {SYM} | Level Tier Hierarchy")
    print(f"  Tiers — T1: PDH/PDL/PMH/PML | T2: 1H pivots | T3: 30m+10m pivots")
    print(f"  Overlap threshold: {OVERLAP*100:.2f}% | Bounce: {BOUNCE*100:.2f}%")
    print(f"{'='*W}")

    for side in ["long","short"]:
        base = df[df["side"]==side]
        print(f"\n  {'LONG (Support)' if side=='long' else 'SHORT (Resistance)'}   N={len(base)}")
        print(HDR); print(SEP)

        # All combined
        prow("ALL", base)
        print(SEP)

        # By tier label
        for tlbl in TIER_ORDER:
            prow(tlbl, base[base["tier_lbl"]==tlbl])
        print(SEP)

        # Touch count within each tier
        print(f"\n  TOUCH COUNT × TIER")
        print(f"  {'Tier':<12} {'Touch':<7} {'N':>5}  {'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*58}")
        for tlbl in TIER_ORDER:
            tb = base[base["tier_lbl"]==tlbl]
            if tb.empty: continue
            for tch in ["1st","2nd","3rd+"]:
                s = tb[tb["touch_lbl"]==tch]
                if s.empty: continue
                h50=s[f"hit_{T_LABELS[0]}"].mean()*100
                h75=s[f"hit_{T_LABELS[1]}"].mean()*100
                mark=" <<<" if h50>=35 else ("  <<" if h50>=25 else "")
                print(f"  {tlbl:<12} {tch:<7} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

        # Gap regime × tier
        print(f"\n  GAP REGIME × TIER (top combinations only)")
        print(f"  {'Tier':<12} {'Regime':<12} {'N':>5}  {'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*60}")
        for tlbl in TIER_ORDER:
            tb = base[base["tier_lbl"]==tlbl]
            if tb.empty: continue
            for regime in ["Gap Down","Flat","Gap Up"]:
                s = tb[tb["gap_regime"]==regime]
                if len(s)<3: continue
                h50=s[f"hit_{T_LABELS[0]}"].mean()*100
                h75=s[f"hit_{T_LABELS[1]}"].mean()*100
                mark=" <<<" if h50>=35 else ("  <<" if h50>=25 else "")
                print(f"  {tlbl:<12} {regime:<12} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")


if __name__=="__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    prev_day = build_prev_day(rt_df)

    print("  Building pivot levels...", flush=True)
    sr_1h  = build_pivots(rt_df, lookback=60,  wing=3)
    sr_30m = build_pivots(rt_df, lookback=30,  wing=2)
    sr_10m = build_pivots(rt_df, lookback=10,  wing=1)
    print(f"  {len(pm_stats)} days", flush=True)

    df = scan(rt_df, pm_stats, prev_day, sr_1h, sr_30m, sr_10m)
    print(f"  {len(df)} pattern entries", flush=True)

    if not df.empty:
        report(df)
        df.to_csv(f"boof53_4_{SYM}.csv", index=False)
        print(f"\n  Saved boof53_4_{SYM}.csv")
    else:
        print("  No patterns — try loosening thresholds")
