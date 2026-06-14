"""
BOOF53 Final Combined Study
Long:  1H/4H Sup + PDL + PML  | double touch | bounce>=0.20% | immediate entry
Short: 1H/4H Res + PDH + PMH  | double touch | reject>=0.20% | immediate entry
Report: Side, Level, Gap Regime, Touch#, N, MFE30, >=0.50%, >=0.75%
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
T_LABELS = [">=0.50%",">=0.75%"]


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

def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key]=float(max((H[sl]-ep)/ep*100)) if side=="long" \
            else float(max((ep-L[sl])/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end60+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res

def find_entries(ddf, level, direction):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; bounce_ext=None; touch_num=0; i=1
    while i < n-62:
        t=ddf.iloc[i]["time"].strftime("%H:%M")
        if t<"09:00" or t>="12:00": i+=1; continue
        cl=C[i]; hi=H[i]; lo=L[i]
        if direction=="sup":
            touching = lo <= level*(1+NEAR_PCT)
            if state=="IDLE":
                if touching: state="T1_TOUCHING"; bounce_ext=cl
            elif state=="T1_TOUCHING":
                if touching: bounce_ext=max(bounce_ext,cl)
                else:
                    if bounce_ext and (bounce_ext-level)/level>=BOUNCE:
                        state="T1_BOUNCED"; touch_num+=1
                    else: state="IDLE"
                    bounce_ext=None
            elif state=="T1_BOUNCED":
                if touching:
                    state="CONFIRM_WAIT" if cl>level else "IDLE"
            elif state=="CONFIRM_WAIT":
                if touching: i+=1; continue
                if cl >= level*(1+CONF_D):
                    ei=i+1
                    if ei<n:
                        ep=ddf.iloc[ei]["open"]
                        results.append({"bar_idx":i,"touch_num":min(touch_num,3),
                                        "ep":ep,**exc(ddf,ei,ep,"long")})
                    state="IDLE"
                elif cl < level: state="IDLE"
        else:
            touching = hi >= level*(1-NEAR_PCT)
            if state=="IDLE":
                if touching: state="T1_TOUCHING"; bounce_ext=cl
            elif state=="T1_TOUCHING":
                if touching: bounce_ext=min(bounce_ext,cl)
                else:
                    if bounce_ext and (level-bounce_ext)/level>=BOUNCE:
                        state="T1_BOUNCED"; touch_num+=1
                    else: state="IDLE"
                    bounce_ext=None
            elif state=="T1_BOUNCED":
                if touching:
                    state="CONFIRM_WAIT" if cl<level else "IDLE"
            elif state=="CONFIRM_WAIT":
                if touching: i+=1; continue
                if cl <= level*(1-CONF_D):
                    ei=i+1
                    if ei<n:
                        ep=ddf.iloc[ei]["open"]
                        results.append({"bar_idx":i,"touch_num":min(touch_num,3),
                                        "ep":ep,**exc(ddf,ei,ep,"short")})
                    state="IDLE"
                elif cl > level: state="IDLE"
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
        pd_info=prev_day.get(date_ts,{})
        pdh=pd_info.get("pdh",np.nan); pdl=pd_info.get("pdl",np.nan)
        dk=date.date() if hasattr(date,"date") else date
        lv1h=sr_1h.get(dk,[]); lv4h=sr_4h.get(dk,[])

        long_levels =[(pml,"PML"),(pdl,"PDL")] if not pd.isna(pdl) else [(pml,"PML")]
        short_levels=[(pmh,"PMH"),(pdh,"PDH")] if not pd.isna(pdh) else [(pmh,"PMH")]
        for lv,lt in lv1h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv,"1H_Sup" if lt=="sup" else "1H_Res"))
        for lv,lt in lv4h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv,"4H_Sup" if lt=="sup" else "4H_Res"))

        for level,lname in long_levels:
            if pd.isna(level): continue
            for e in find_entries(ddf,level,"sup"):
                tl="1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({"date":str(date.date()),"side":"long","level":lname,
                                "gap_regime":gap_regime,"gap_pct":round(gap,3),
                                "touch_lbl":tl,"ep":e["ep"],
                                **{k:v for k,v in e.items() if k not in ("bar_idx","touch_num","ep")}})

        for level,lname in short_levels:
            if pd.isna(level): continue
            for e in find_entries(ddf,level,"res"):
                tl="1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({"date":str(date.date()),"side":"short","level":lname,
                                "gap_regime":gap_regime,"gap_pct":round(gap,3),
                                "touch_lbl":tl,"ep":e["ep"],
                                **{k:v for k,v in e.items() if k not in ("bar_idx","touch_num","ep")}})

    return pd.DataFrame(records) if records else pd.DataFrame()


def prow(label, s, w=20, min_n=3):
    if s.empty or len(s)<min_n:
        print(f"  {label:<{w}} {'<'+str(min_n):>5}"); return
    n=len(s); nd=s["date"].nunique()
    m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
    mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")


def report(df):
    W=94
    HDR=(f"  {'Label':<20} {'N':>5} {'Days':>5}  "
         f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP=f"  {'-'*90}"

    print(f"\n{'='*W}")
    print(f"  BOOF53 FINAL | {SYM} | Double-Touch Bounce>=0.20% + Immediate Entry")
    print(f"  Long: PML/PDL/1H/4H Sup  |  Short: PMH/PDH/1H/4H Res")
    print(f"{'='*W}")

    for side in ["long","short"]:
        base=df[df["side"]==side]
        lnames=["PML","PDL","1H_Sup","4H_Sup"] if side=="long" \
           else ["PMH","PDH","1H_Res","4H_Res"]
        print(f"\n{'='*W}")
        print(f"  {'LONG — Support' if side=='long' else 'SHORT — Resistance'}   "
              f"N={len(base)}  Days={base['date'].nunique()}")
        print(f"{'='*W}")
        print(HDR); print(SEP)

        prow("ALL", base)
        print(SEP)

        # By level
        print(f"  BY LEVEL")
        for lname in lnames:
            prow(lname, base[base["level"]==lname])
        print(SEP)

        # By touch
        print(f"  BY TOUCH COUNT")
        for tl in ["1st","2nd","3rd+"]:
            prow(f"Touch {tl}", base[base["touch_lbl"]==tl])
        print(SEP)

        # By gap regime
        print(f"  BY GAP REGIME")
        for regime in ["Gap Down","Flat","Gap Up"]:
            prow(regime, base[base["gap_regime"]==regime])
        print(SEP)

        # Cross: level × gap regime (only rows with N>=5)
        print(f"\n  LEVEL × GAP REGIME")
        print(f"  {'Level':<12} {'Regime':<12} {'N':>5}  "
              f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*60}")
        for lname in lnames:
            for regime in ["Gap Down","Flat","Gap Up"]:
                s=base[(base["level"]==lname)&(base["gap_regime"]==regime)]
                if len(s)<3: continue
                h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
                mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
                print(f"  {lname:<12} {regime:<12} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

        # Cross: touch × gap regime
        print(f"\n  TOUCH × GAP REGIME")
        print(f"  {'Touch':<8} {'Regime':<12} {'N':>5}  "
              f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*55}")
        for tl in ["1st","2nd","3rd+"]:
            for regime in ["Gap Down","Flat","Gap Up"]:
                s=base[(base["touch_lbl"]==tl)&(base["gap_regime"]==regime)]
                if len(s)<3: continue
                h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
                mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
                print(f"  {tl:<8} {regime:<12} {len(s):>5}  "
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
    print(f"  {len(df)} total entries", flush=True)
    if not df.empty:
        print(f"  Long: {(df['side']=='long').sum()}  "
              f"Short: {(df['side']=='short').sum()}", flush=True)
        report(df)
        df.to_csv(f"boof53_final_{SYM}.csv", index=False)
        print(f"\n  Saved boof53_final_{SYM}.csv")
