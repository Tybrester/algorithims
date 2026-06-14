"""
BOOF53.6 — Double-Touch + Conf D + Entry Timing Comparison
Fixed: bounce>=0.20%, conf D (+0.25% away from level)
Levels: PML, PDL, PMH, PDH, 1H, 4H

Entry A: enter immediately when price moves 0.25% off level (conf D bar+1)
Entry B: wait for break of previous 5m swing high/low (highest high / lowest low of last 5 bars)
Entry C: wait for break of previous 15m swing high/low (last 15 bars)

Measure: MFE15, MFE30, MFE60, >=0.40%, >=0.50%, >=0.60%, >=0.75%
Also track: slippage (entry vs conf bar close), bars waited for B/C
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYM      = "QQQ"
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0020    # fixed 0.20%
CONF_D   = 0.0025    # fixed conf D
TARGETS  = [0.0040, 0.0050, 0.0060, 0.0075]
T_LABELS = [">=0.40%",">=0.50%",">=0.60%",">=0.75%"]
MAX_WAIT = 30        # max bars to wait for swing break after conf D fires


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
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
                        on="date", how="left")
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
        H=hist["high"].values; L=hist["low"].values
        levels=[]
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
    """
    Double-touch state machine → fires when conf D triggers.
    Then generates three entries:
      A: immediate (next bar open after conf D)
      B: wait up to MAX_WAIT bars for 5m swing break
      C: wait up to MAX_WAIT bars for 15m swing break
    """
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; bounce_ext=None; i=1

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
                        state="T1_BOUNCED"
                    else: state="IDLE"
                    bounce_ext=None
            elif state=="T1_BOUNCED":
                if touching:
                    state="CONFIRM_WAIT" if cl>level else "IDLE"
            elif state=="CONFIRM_WAIT":
                if touching: i+=1; continue
                # Conf D: price moved 0.25% above level
                if cl >= level*(1+CONF_D):
                    conf_bar=i; state="IDLE"
                    ep_A_idx=conf_bar+1
                    if ep_A_idx>=n: break
                    ep_A=ddf.iloc[ep_A_idx]["open"]

                    # Entry A — immediate
                    results.append({"entry":"A","bar_idx":conf_bar,
                                    "ep":ep_A,"bars_waited":0,
                                    "conf_close":round(cl,2),
                                    **exc(ddf,ep_A_idx,ep_A,"long")})

                    # Entry B — wait for 5m swing high break
                    sw5_base=max(H[max(0,conf_bar-5):conf_bar+1])
                    fired_B=False
                    for j in range(conf_bar+1, min(conf_bar+MAX_WAIT+1, n-1)):
                        tj=ddf.iloc[j]["time"].strftime("%H:%M")
                        if tj>="12:00": break
                        if C[j]>sw5_base:
                            ep_B=ddf.iloc[j+1]["open"] if j+1<n else C[j]
                            results.append({"entry":"B","bar_idx":j,
                                            "ep":ep_B,"bars_waited":j-conf_bar,
                                            "conf_close":round(cl,2),
                                            **exc(ddf,j+1,ep_B,"long")})
                            fired_B=True; break
                    if not fired_B:
                        results.append({"entry":"B","bar_idx":None,
                                        "ep":None,"bars_waited":None,
                                        "conf_close":round(cl,2),
                                        **{k:0 for k in ["mfe15","mfe30","mfe60"]+
                                           [f"hit_{l}" for l in T_LABELS]}})

                    # Entry C — wait for 15m swing high break
                    sw15_base=max(H[max(0,conf_bar-15):conf_bar+1])
                    fired_C=False
                    for j in range(conf_bar+1, min(conf_bar+MAX_WAIT+1, n-1)):
                        tj=ddf.iloc[j]["time"].strftime("%H:%M")
                        if tj>="12:00": break
                        if C[j]>sw15_base:
                            ep_C=ddf.iloc[j+1]["open"] if j+1<n else C[j]
                            results.append({"entry":"C","bar_idx":j,
                                            "ep":ep_C,"bars_waited":j-conf_bar,
                                            "conf_close":round(cl,2),
                                            **exc(ddf,j+1,ep_C,"long")})
                            fired_C=True; break
                    if not fired_C:
                        results.append({"entry":"C","bar_idx":None,
                                        "ep":None,"bars_waited":None,
                                        "conf_close":round(cl,2),
                                        **{k:0 for k in ["mfe15","mfe30","mfe60"]+
                                           [f"hit_{l}" for l in T_LABELS]}})
                elif cl < level:
                    state="IDLE"  # broke below, reset

        else:  # res / short
            touching = hi >= level*(1-NEAR_PCT)
            if state=="IDLE":
                if touching: state="T1_TOUCHING"; bounce_ext=cl
            elif state=="T1_TOUCHING":
                if touching: bounce_ext=min(bounce_ext,cl)
                else:
                    if bounce_ext and (level-bounce_ext)/level>=BOUNCE:
                        state="T1_BOUNCED"
                    else: state="IDLE"
                    bounce_ext=None
            elif state=="T1_BOUNCED":
                if touching:
                    state="CONFIRM_WAIT" if cl<level else "IDLE"
            elif state=="CONFIRM_WAIT":
                if touching: i+=1; continue
                if cl <= level*(1-CONF_D):
                    conf_bar=i; state="IDLE"
                    ep_A_idx=conf_bar+1
                    if ep_A_idx>=n: break
                    ep_A=ddf.iloc[ep_A_idx]["open"]

                    results.append({"entry":"A","bar_idx":conf_bar,
                                    "ep":ep_A,"bars_waited":0,
                                    "conf_close":round(cl,2),
                                    **exc(ddf,ep_A_idx,ep_A,"short")})

                    sw5_base=min(L[max(0,conf_bar-5):conf_bar+1])
                    fired_B=False
                    for j in range(conf_bar+1, min(conf_bar+MAX_WAIT+1, n-1)):
                        tj=ddf.iloc[j]["time"].strftime("%H:%M")
                        if tj>="12:00": break
                        if C[j]<sw5_base:
                            ep_B=ddf.iloc[j+1]["open"] if j+1<n else C[j]
                            results.append({"entry":"B","bar_idx":j,
                                            "ep":ep_B,"bars_waited":j-conf_bar,
                                            "conf_close":round(cl,2),
                                            **exc(ddf,j+1,ep_B,"short")})
                            fired_B=True; break
                    if not fired_B:
                        results.append({"entry":"B","bar_idx":None,
                                        "ep":None,"bars_waited":None,
                                        "conf_close":round(cl,2),
                                        **{k:0 for k in ["mfe15","mfe30","mfe60"]+
                                           [f"hit_{l}" for l in T_LABELS]}})

                    sw15_base=min(L[max(0,conf_bar-15):conf_bar+1])
                    fired_C=False
                    for j in range(conf_bar+1, min(conf_bar+MAX_WAIT+1, n-1)):
                        tj=ddf.iloc[j]["time"].strftime("%H:%M")
                        if tj>="12:00": break
                        if C[j]<sw15_base:
                            ep_C=ddf.iloc[j+1]["open"] if j+1<n else C[j]
                            results.append({"entry":"C","bar_idx":j,
                                            "ep":ep_C,"bars_waited":j-conf_bar,
                                            "conf_close":round(cl,2),
                                            **exc(ddf,j+1,ep_C,"long")})
                            fired_C=True; break
                    if not fired_C:
                        results.append({"entry":"C","bar_idx":None,
                                        "ep":None,"bars_waited":None,
                                        "conf_close":round(cl,2),
                                        **{k:0 for k in ["mfe15","mfe30","mfe60"]+
                                           [f"hit_{l}" for l in T_LABELS]}})
                elif cl > level:
                    state="IDLE"
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
        pmh=day["pm_high"]; pml=day["pm_low"]
        pd_info=prev_day.get(date_ts,{})
        pdh=pd_info.get("pdh",np.nan); pdl=pd_info.get("pdl",np.nan)
        dk=date.date() if hasattr(date,"date") else date
        lv1h=sr_1h.get(dk,[]); lv4h=sr_4h.get(dk,[])

        long_levels =[(pml,"PML")]
        short_levels=[(pmh,"PMH")]
        if not pd.isna(pdl): long_levels.append((pdl,"PDL"))
        if not pd.isna(pdh): short_levels.append((pdh,"PDH"))
        for lv,lt in lv1h+lv4h:
            if lt=="sup": long_levels.append((lv,"1H/4H_Sup"))
            else:         short_levels.append((lv,"1H/4H_Res"))

        for level,lname in long_levels:
            for e in find_entries(ddf,level,"sup"):
                if e["ep"] is None: continue
                records.append({"date":str(date.date()),"side":"long","level":lname,
                                "gap_regime":gap_regime,"gap_pct":round(gap,3),**e})
        for level,lname in short_levels:
            for e in find_entries(ddf,level,"res"):
                if e["ep"] is None: continue
                records.append({"date":str(date.date()),"side":"short","level":lname,
                                "gap_regime":gap_regime,"gap_pct":round(gap,3),**e})

    return pd.DataFrame(records) if records else pd.DataFrame()


def prow(label, s, w=24):
    if s.empty or len(s)<3:
        print(f"  {label:<{w}} {'<3':>4}"); return
    n=len(s); nd=s["date"].nunique()
    m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    bw=s["bars_waited"].mean() if "bars_waited" in s and s["bars_waited"].notna().any() else 0
    hits=[s[f"hit_{l}"].mean()*100 for l in T_LABELS]
    mark=" <<<" if hits[1]>=40 else ("  <<" if hits[1]>=30 else "")
    print(f"  {label:<{w}} {n:>4} {nd:>3}d  "
          f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
          f"{hits[0]:>6.1f}% {hits[1]:>6.1f}% {hits[2]:>6.1f}% {hits[3]:>6.1f}%"
          f"  wait={bw:.1f}m{mark}")


def report(df):
    W=116
    HDR=(f"  {'Label':<24} {'N':>4} {'Days':>4}  "
         f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
         f"{'>=0.40%':>8} {'>=0.50%':>8} {'>=0.60%':>8} {'>=0.75%':>8}  {'Wait':>6}")
    SEP=f"  {'-'*112}"

    print(f"\n{'='*W}")
    print(f"  BOOF53.6 | {SYM} | Double-Touch Bounce>=0.20% ConfD +0.25%")
    print(f"  Entry A=immediate  B=5m swing break  C=15m swing break")
    print(f"{'='*W}")

    for side in ["long","short"]:
        base=df[df["side"]==side]
        print(f"\n  {'LONG' if side=='long' else 'SHORT'}  N={len(base)}")
        print(HDR); print(SEP)

        # Entry comparison — top level
        for entry in ["A","B","C"]:
            s=base[base["entry"]==entry]
            prow(f"Entry {entry} ALL",s)

        print(SEP)

        # Per entry × level
        for entry in ["A","B","C"]:
            s=base[base["entry"]==entry]
            if s.empty: continue
            for level in ["PML","PDL","1H/4H_Sup"] if side=="long" \
                     else ["PMH","PDH","1H/4H_Res"]:
                ls=s[s["level"]==level]
                prow(f"  {entry} {level}",ls)
            print(SEP)

        # Per entry × gap regime
        print(f"\n  GAP REGIME")
        print(HDR); print(SEP)
        for entry in ["A","B","C"]:
            for regime in ["Gap Down","Flat","Gap Up"]:
                s=base[(base["entry"]==entry)&(base["gap_regime"]==regime)]
                prow(f"  {entry} {regime}",s)
            print(SEP)


if __name__=="__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    prev_day = build_prev_day(rt_df)
    print("  Building pivots...", flush=True)
    sr_1h=build_pivots(rt_df,lookback=60, wing=3)
    sr_4h=build_pivots(rt_df,lookback=240,wing=5)
    print(f"  {len(pm_stats)} days", flush=True)

    df=scan(rt_df,pm_stats,prev_day,sr_1h,sr_4h)
    print(f"  {len(df)} entries", flush=True)

    if not df.empty:
        report(df)
        df.to_csv(f"boof53_6_{SYM}.csv",index=False)
        print(f"\n  Saved boof53_6_{SYM}.csv")
    else:
        print("  No entries found")
