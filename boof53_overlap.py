"""
BOOF53 Overlap Study — QQQ only
For every touch event, count how many distinct levels from different tiers
are within OVERLAP_PCT of each other at that price.

Overlap tiers:
  T1: PMH/PML (daily premarket)
  T2: PDH/PDL (previous day)
  T3: 1H S/R  (60-bar pivots)
  T4: 4H S/R  (240-bar pivots)

Overlap = abs(level1 - level2) / level1 < OVERLAP_PCT

Report:
  Overlap Count (1/2/3/4) x N x MFE15/30/60 x >=0.50% x >=0.75%
  Double combos: which pairs overlap most and perform best
  Triple combos
  Side x overlap count
  Gap regime x overlap count
"""
import pandas as pd
import numpy as np
import pytz

ET          = pytz.timezone("America/New_York")
SYM         = "QQQ"
NEAR_PCT    = 0.0015
OVERLAP_PCT = 0.0010          # 0.10% — levels within this = overlapping
BOUNCE      = 0.0015          # 0.15% minimum bounce to count touch
TARGETS     = [0.0050, 0.0075]
T_LABELS    = [">=0.50%",">=0.75%"]


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
    dates = sorted(rt_df["date"].unique()); prev={}
    for i in range(1,len(dates)):
        d=dates[i]; p=dates[i-1]; g=rt_df[rt_df["date"]==p]
        if not g.empty: prev[d]={"pdh":g["high"].max(),"pdl":g["low"].min()}
    return prev

def build_pivots(rt_df, lookback, wing):
    rt_df=rt_df.sort_values("time").reset_index(drop=True); sr={}
    dates=sorted(rt_df["date"].unique())
    for d in dates:
        hist=rt_df[rt_df["date"]<d].tail(lookback)
        if len(hist)<lookback//2: continue
        H=hist["high"].values; L=hist["low"].values; levels=[]
        for i in range(wing,len(hist)-wing):
            if H[i]==max(H[i-wing:i+wing+1]): levels.append((H[i],"res"))
            if L[i]==min(L[i-wing:i+wing+1]): levels.append((L[i],"sup"))
        if not levels: continue
        levels=sorted(levels,key=lambda x:x[0])
        cl=[list(levels[0])]
        for lv,lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP_PCT: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        sr[d]=[(c[0],c[1]) for c in cl]
    return sr

def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key]=float(max((H[sl]-ep)/ep*100)) if side=="long" \
            else float(max((ep-L[sl])/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end60+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res

def overlapping_levels(active_level, active_name, all_levels_today):
    """
    Return list of level names (from other tiers) that are within OVERLAP_PCT.
    all_levels_today: list of (price, name, tier)
    """
    matches = []
    for lv, nm, tier in all_levels_today:
        if nm == active_name: continue
        if abs(lv - active_level) / active_level <= OVERLAP_PCT:
            matches.append(nm)
    return sorted(matches)

def scan_touches(ddf, level, lname, tier, direction, all_day_levels):
    """
    Record every touch (with bounce >= BOUNCE).
    Tag each with how many other levels overlap.
    Return immediately after touch exits (no double-touch requirement).
    """
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; ext=None; touch_num=0; i=1

    while i < n-62:
        t=ddf.iloc[i]["time"].strftime("%H:%M")
        if t<"09:00" or t>="13:00": i+=1; continue
        cl=C[i]; hi=H[i]; lo=L[i]

        if direction=="sup":
            touching=lo<=level*(1+NEAR_PCT)
            if state=="IDLE":
                if touching: state="IN"; ext=cl; touch_num+=1
            elif state=="IN":
                if touching: ext=max(ext,cl)
                else:
                    if ext and (ext-level)/level>=BOUNCE:
                        # Valid bounce — record
                        ei=i; ep=ddf.iloc[ei]["open"] if ei<n else None
                        if ep:
                            ov=overlapping_levels(level,lname,all_day_levels)
                            results.append({
                                "touch_num": min(touch_num,3),
                                "ep": ep,
                                "overlap_names": ov,
                                "overlap_count": len(ov)+1,  # count self+overlapping
                                **exc(ddf,ei,ep,"long")
                            })
                    state="IDLE"; ext=None
        else:
            touching=hi>=level*(1-NEAR_PCT)
            if state=="IDLE":
                if touching: state="IN"; ext=cl; touch_num+=1
            elif state=="IN":
                if touching: ext=min(ext,cl)
                else:
                    if ext and (level-ext)/level>=BOUNCE:
                        ei=i; ep=ddf.iloc[ei]["open"] if ei<n else None
                        if ep:
                            ov=overlapping_levels(level,lname,all_day_levels)
                            results.append({
                                "touch_num": min(touch_num,3),
                                "ep": ep,
                                "overlap_names": ov,
                                "overlap_count": len(ov)+1,
                                **exc(ddf,ei,ep,"short")
                            })
                    state="IDLE"; ext=None
        i+=1
    return results


def scan(rt_df, pm_stats, prev_day, sr_1h, sr_4h):
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm=pm_stats.set_index("date"); records=[]

    for date,ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]; gap=day["gap_pct"]
        gap_regime="Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")
        ddf=ddf.reset_index(drop=True)
        pmh=day["pm_high"]; pml=day["pm_low"]
        pd_info=prev_day.get(date_ts,{}); pdh=pd_info.get("pdh",np.nan); pdl=pd_info.get("pdl",np.nan)
        dk=date.date() if hasattr(date,"date") else date
        lv1h=sr_1h.get(dk,[]); lv4h=sr_4h.get(dk,[])

        # Build full level catalog for this day with tier labels
        # (price, name, tier, direction)
        catalog = []
        catalog.append((pml, "PML", "T1", "sup"))
        catalog.append((pmh, "PMH", "T1", "res"))
        if not pd.isna(pdl): catalog.append((pdl, "PDL", "T2", "sup"))
        if not pd.isna(pdh): catalog.append((pdh, "PDH", "T2", "res"))
        for lv,lt in lv1h:
            catalog.append((lv, f"1H_{'Sup' if lt=='sup' else 'Res'}", "T3",
                             "sup" if lt=="sup" else "res"))
        for lv,lt in lv4h:
            catalog.append((lv, f"4H_{'Sup' if lt=='sup' else 'Res'}", "T4",
                             "sup" if lt=="sup" else "res"))

        # For overlap check: list of (price, name, tier) — all levels regardless of direction
        all_day_levels = [(lv, nm, tier) for lv, nm, tier, _ in catalog]

        for level, lname, tier, direction in catalog:
            if pd.isna(level): continue
            side = "long" if direction=="sup" else "short"
            for e in scan_touches(ddf, level, lname, tier, direction, all_day_levels):
                tl="1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({
                    "date": str(date.date()),
                    "side": side,
                    "level": lname,
                    "tier": tier,
                    "gap_regime": gap_regime,
                    "gap_pct": round(gap,3),
                    "touch_lbl": tl,
                    "overlap_count": e["overlap_count"],
                    "overlap_names": "|".join(e["overlap_names"]) if e["overlap_names"] else "none",
                    "ep": e["ep"],
                    **{k:v for k,v in e.items()
                       if k not in ("touch_num","ep","overlap_names","overlap_count")}
                })

    return pd.DataFrame(records) if records else pd.DataFrame()


def prow(label, s, w=28, min_n=3):
    if s.empty or len(s)<min_n:
        print(f"  {label:<{w}} {'<'+str(min_n):>4}"); return
    n=len(s); nd=s["date"].nunique()
    m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
    mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")


def report(df):
    W=96
    HDR=(f"  {'Label':<28} {'N':>5} {'Days':>5}  "
         f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP=f"  {'-'*92}"

    print(f"\n{'='*W}")
    print(f"  BOOF53 Overlap Study | {SYM} | overlap<{OVERLAP_PCT*100:.2f}%  bounce>={BOUNCE*100:.2f}%")
    print(f"{'='*W}")

    # ── 1. Overlap count summary ─────────────────────────────────────────────
    print(f"\n  OVERLAP COUNT SUMMARY — both sides combined")
    print(HDR); print(SEP)
    prow("ALL", df)
    print(SEP)
    for oc in sorted(df["overlap_count"].unique()):
        prow(f"Overlap={oc}  ({'single' if oc==1 else ('double' if oc==2 else ('triple' if oc==3 else '4+'))})",
             df[df["overlap_count"]==oc])

    # ── 2. Side × overlap count ──────────────────────────────────────────────
    print(f"\n  SIDE × OVERLAP COUNT")
    print(HDR); print(SEP)
    for side in ["long","short"]:
        base=df[df["side"]==side]
        print(f"  {'--- '+side.upper()+' ---'}")
        for oc in sorted(df["overlap_count"].unique()):
            prow(f"  {side} Overlap={oc}", base[base["overlap_count"]==oc])
        print(SEP)

    # ── 3. Double overlap pair breakdown ─────────────────────────────────────
    print(f"\n  DOUBLE OVERLAP PAIRS  (overlap_count==2)")
    print(HDR); print(SEP)
    double = df[df["overlap_count"]==2].copy()
    # Build canonical pair label: level + first overlap partner
    double["pair"] = double.apply(
        lambda r: "+".join(sorted([r["level"], r["overlap_names"].split("|")[0]])), axis=1)
    pair_counts = double["pair"].value_counts()
    for pair in pair_counts.index:
        s=double[double["pair"]==pair]
        prow(pair, s)

    # ── 4. Triple overlap ────────────────────────────────────────────────────
    print(f"\n  TRIPLE OVERLAP  (overlap_count==3)")
    print(HDR); print(SEP)
    triple = df[df["overlap_count"]==3].copy()
    if not triple.empty:
        triple["combo"] = triple.apply(
            lambda r: "+".join(sorted([r["level"]]+r["overlap_names"].split("|"))), axis=1)
        for combo in triple["combo"].value_counts().index:
            prow(combo, triple[triple["combo"]==combo])
    else:
        print(f"  (no triple overlaps found at {OVERLAP_PCT*100:.2f}% threshold)")

    # ── 5. Level × overlap count ─────────────────────────────────────────────
    print(f"\n  LEVEL × OVERLAP COUNT")
    print(f"  {'Level':<12} {'Overlap':>8}  {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*62}")
    for lname in ["PMH","PML","PDH","PDL","1H_Res","1H_Sup","4H_Res","4H_Sup"]:
        ls=df[df["level"]==lname]
        if ls.empty: continue
        for oc in sorted(ls["overlap_count"].unique()):
            s=ls[ls["overlap_count"]==oc]
            if len(s)<3: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
            print(f"  {lname:<12} {oc:>8}  {len(s):>5}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # ── 6. Gap regime × overlap count ────────────────────────────────────────
    print(f"\n  GAP REGIME × OVERLAP COUNT  (both sides)")
    print(f"  {'Regime':<12} {'Overlap':>8}  {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*62}")
    for regime in ["Gap Down","Flat","Gap Up"]:
        for oc in sorted(df["overlap_count"].unique()):
            s=df[(df["gap_regime"]==regime)&(df["overlap_count"]==oc)]
            if len(s)<3: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
            print(f"  {regime:<12} {oc:>8}  {len(s):>5}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # ── 7. Touch count × overlap count ───────────────────────────────────────
    print(f"\n  TOUCH COUNT × OVERLAP COUNT  (both sides)")
    print(f"  {'Touch':<8} {'Overlap':>8}  {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*55}")
    for tl in ["1st","2nd","3rd+"]:
        for oc in sorted(df["overlap_count"].unique()):
            s=df[(df["touch_lbl"]==tl)&(df["overlap_count"]==oc)]
            if len(s)<3: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
            print(f"  {tl:<8} {oc:>8}  {len(s):>5}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")


if __name__=="__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    prev_day = build_prev_day(rt_df)
    print("  Building pivots...", flush=True)
    sr_1h = build_pivots(rt_df, lookback=60,  wing=3)
    sr_4h = build_pivots(rt_df, lookback=240, wing=5)
    print(f"  {len(pm_stats)} days", flush=True)

    df = scan(rt_df, pm_stats, prev_day, sr_1h, sr_4h)
    print(f"  {len(df)} touch events", flush=True)
    print(f"  Overlap distribution:\n{df['overlap_count'].value_counts().sort_index().to_string()}", flush=True)

    report(df)
    df.to_csv(f"boof53_overlap_{SYM}.csv", index=False)
    print(f"\n  Saved boof53_overlap_{SYM}.csv")
