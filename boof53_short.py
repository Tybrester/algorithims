"""
BOOF53 Short Engine — 2-Touch Rejection
Touch resistance, reject >=0.20%, return, reject again, enter short immediately.
Levels: PMH, PDH, 1H Res, 4H Res
Report: Level x N x MFE15/30/60 x >=0.50% x >=0.75%
Also: gap regime x touch timing x combined level overlaps
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYM      = "QQQ"
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0020
CONF_D   = 0.0025
TARGETS  = [0.0050, 0.0075]
T_LABELS = [">=0.50%", ">=0.75%"]


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
    rt_df = rt_df.sort_values("time").reset_index(drop=True)
    sr = {}
    dates = sorted(rt_df["date"].unique())
    for d in dates:
        hist = rt_df[rt_df["date"] < d].tail(lookback)
        if len(hist) < lookback//2: continue
        H=hist["high"].values; L=hist["low"].values; levels=[]
        for i in range(wing, len(hist)-wing):
            if H[i]==max(H[i-wing:i+wing+1]): levels.append((H[i],"res"))
            if L[i]==min(L[i-wing:i+wing+1]): levels.append((L[i],"sup"))
        if not levels: continue
        levels=sorted(levels,key=lambda x:x[0])
        cl=[list(levels[0])]
        for lv,lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        sr[d]=[(c[0],c[1]) for c in cl]
    return sr

def exc(ddf, ei, ep):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key]=float(max((ep-L[sl])/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res

def find_rejections(ddf, level):
    """
    Two-touch rejection state machine.
    T1: touches resistance, rejects >=BOUNCE
    T2: returns, touches again, rejects (close < level)
    Entry: immediate (next bar open after T2 reject confirm D)
    Records EVERY T2 rejection (not just first per day).
    """
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; reject_ext=None; touch_count=0; i=1

    while i < n-62:
        t=ddf.iloc[i]["time"].strftime("%H:%M")
        if t<"09:00" or t>="12:00": i+=1; continue
        cl=C[i]; hi=H[i]

        touching = hi >= level*(1-NEAR_PCT)

        if state=="IDLE":
            if touching:
                state="T1_TOUCHING"; reject_ext=cl

        elif state=="T1_TOUCHING":
            if touching:
                reject_ext = min(reject_ext, cl)
            else:
                # Left zone — check if rejection was strong enough
                if reject_ext is not None and (level-reject_ext)/level >= BOUNCE:
                    state="T1_REJECTED"; touch_count=1
                else:
                    state="IDLE"
                reject_ext=None

        elif state=="T1_REJECTED":
            # Waiting for price to return to level
            if touching:
                # T2 touch — check if it rejects (close < level)
                if cl < level:
                    state="CONFIRM_WAIT"
                else:
                    # Broke above on T2 — reset
                    state="IDLE"; touch_count=0

        elif state=="CONFIRM_WAIT":
            if touching: i+=1; continue
            # Price left level zone — check conf D (0.25% below level)
            if cl <= level*(1-CONF_D):
                ei=i+1
                if ei < n:
                    ep=ddf.iloc[ei]["open"]
                    results.append({
                        "bar_idx": i,
                        "touch_count": touch_count,
                        "ep": ep,
                        **exc(ddf, ei, ep)
                    })
                state="IDLE"; touch_count=0
            elif cl > level:
                state="IDLE"; touch_count=0
            # else still between level and conf D, keep waiting

        i+=1
    return results


def scan(rt_df, pm_stats, prev_day, sr_1h, sr_4h):
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm=pm_stats.set_index("date"); records=[]

    for date, ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]; gap=day["gap_pct"]
        gap_regime="Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")
        ddf=ddf.reset_index(drop=True)

        pmh=day["pm_high"]
        pd_info=prev_day.get(date_ts,{})
        pdh=pd_info.get("pdh",np.nan)
        dk=date.date() if hasattr(date,"date") else date
        lv1h=sr_1h.get(dk,[]); lv4h=sr_4h.get(dk,[])

        # Build level list — each with name and price
        levels=[(pmh,"PMH")]
        if not pd.isna(pdh): levels.append((pdh,"PDH"))
        for lv,lt in lv1h:
            if lt=="res": levels.append((lv,"1H_Res"))
        for lv,lt in lv4h:
            if lt=="res": levels.append((lv,"4H_Res"))

        # Check which levels overlap (within OVERLAP %) for tagging
        level_prices=[lv for lv,_ in levels]

        for level, lname in levels:
            overlapping=[n2 for lv2,n2 in levels
                         if n2!=lname and abs(lv2-level)/level<=OVERLAP]
            overlap_tag="+".join(sorted(overlapping)) if overlapping else "none"

            for e in find_rejections(ddf, level):
                records.append({
                    "date":      str(date.date()),
                    "level":     lname,
                    "level_px":  round(level,2),
                    "overlap":   overlap_tag,
                    "gap_regime":gap_regime,
                    "gap_pct":   round(gap,3),
                    "ep":        e["ep"],
                    **{k:v for k,v in e.items() if k not in ("bar_idx","touch_count","ep")}
                })

    return pd.DataFrame(records) if records else pd.DataFrame()


def prow(label, s, w=20, min_n=3):
    if s.empty or len(s)<min_n:
        print(f"  {label:<{w}} {'<'+str(min_n):>5}"); return
    n=len(s); nd=s["date"].nunique()
    m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
    mark=" <<<" if h50>=45 else ("  <<" if h50>=30 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")


def report(df):
    W=94
    HDR=(f"  {'Label':<20} {'N':>5} {'Days':>5}  "
         f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP=f"  {'-'*90}"

    print(f"\n{'='*W}")
    print(f"  BOOF53 Short Engine | {SYM} | 2-Touch Rejection + Immediate Entry")
    print(f"  Bounce>=0.20%  ConfD=0.25% below level")
    print(f"{'='*W}")
    print(HDR); print(SEP)

    # Overall
    prow("ALL", df)
    print(SEP)

    # By level — the main table
    print(f"  BY LEVEL")
    for lname in ["PMH","PDH","1H_Res","4H_Res"]:
        prow(lname, df[df["level"]==lname])
    print(SEP)

    # By gap regime
    print(f"  BY GAP REGIME")
    for regime in ["Gap Down","Flat","Gap Up"]:
        prow(regime, df[df["gap_regime"]==regime])
    print(SEP)

    # Level × gap regime
    print(f"\n  LEVEL × GAP REGIME")
    print(f"  {'Level':<10} {'Regime':<12} {'N':>5}  "
          f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    print(f"  {'-'*78}")
    for lname in ["PMH","PDH","1H_Res","4H_Res"]:
        ls=df[df["level"]==lname]
        if ls.empty: continue
        for regime in ["Gap Down","Flat","Gap Up"]:
            s=ls[ls["gap_regime"]==regime]
            if len(s)<3: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark=" <<<" if h50>=45 else ("  <<" if h50>=30 else "")
            print(f"  {lname:<10} {regime:<12} {len(s):>5}  "
                  f"{s['mfe15'].mean():>6.3f}%  {s['mfe30'].mean():>6.3f}%  "
                  f"{s['mfe60'].mean():>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")

    # Overlap analysis
    print(f"\n  LEVEL OVERLAP EFFECT")
    print(f"  {'Level':<10} {'Overlap':<16} {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*66}")
    for lname in ["PMH","PDH","1H_Res","4H_Res"]:
        ls=df[df["level"]==lname]
        if ls.empty: continue
        alone=ls[ls["overlap"]=="none"]
        overlap=ls[ls["overlap"]!="none"]
        for lbl,s in [("alone",alone),("w/overlap",overlap)]:
            if len(s)<3: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark=" <<<" if h50>=45 else ("  <<" if h50>=30 else "")
            print(f"  {lname:<10} {lbl:<16} {len(s):>5}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # Time of day
    print(f"\n  BY TIME WINDOW (entry bar)")
    print(f"  {'Level':<10} {'Window':<14} {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*62}")
    # Re-scan needed for time — use gap_pct as proxy, show overall time buckets
    # (We'd need entry_time in records for this — skip for now, note it)
    print(f"  (entry time not stored in this run — add to records if needed)")

    # Summary ranked table
    print(f"\n{'='*W}")
    print(f"  RANKED BY >=0.50% HIT RATE (min N=5)")
    print(f"  {'Combo':<30} {'N':>5}  {'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*66}")
    rows=[]
    for lname in ["PMH","PDH","1H_Res","4H_Res"]:
        ls=df[df["level"]==lname]
        rows.append((lname,"ALL",ls))
        for regime in ["Gap Down","Flat","Gap Up"]:
            s=ls[ls["gap_regime"]==regime]
            rows.append((lname,regime,s))
    rows.sort(key=lambda x: -x[2]["hit_>=0.50%"].mean() if len(x[2])>=5 else 0)
    for lname,regime,s in rows:
        if len(s)<5: continue
        h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
        mark=" <<<" if h50>=45 else ("  <<" if h50>=30 else "")
        combo=f"{lname} {regime}"
        print(f"  {combo:<30} {len(s):>5}  "
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
    print(f"  {len(df)} short entries found", flush=True)

    if not df.empty:
        report(df)
        df.to_csv(f"boof53_short_{SYM}.csv", index=False)
        print(f"\n  Saved boof53_short_{SYM}.csv")
    else:
        print("  No entries found")
