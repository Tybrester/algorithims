"""
BOOF53 Version E — Symbol-specialized engine
APP/SMCI/HIMS/ARM: PMH fresh 1st touch
MU: 30m fresh 1st touch + 1H/2H overlap fresh 1st touch
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25%
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
OVERLAP  = 0.0020
BOUNCE   = 0.0015
NEAR_PCT = 0.0015
STACK_PCT= 0.0015
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60
WEEKS    = 19.2
SYMS     = ["APP","SMCI","HIMS","ARM","MU"]


def load_sym(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm>="09:30")&(hm<="16:00")].copy()
    pm  = df[(hm>="04:00")&(hm< "09:30")].copy()
    rth["date"] = rth["time"].dt.date
    pm["date"]  = pm["time"].dt.date
    return rth, pm

def build_pm_levels(pm_df, rth_df):
    pm_df=pm_df.copy(); pm_df["date"]=pd.to_datetime(pm_df["date"])
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    pm_agg=pm_df.groupby("date").agg(pm_high=("high","max")).reset_index()
    pc=rth_df.groupby("date")["close"].last().reset_index()
    pc.columns=["date","prev_close"]; pc["next_date"]=pc["date"]+pd.Timedelta(days=1)
    ro=rth_df.groupby("date")["open"].first().reset_index(); ro.columns=["date","rth_open"]
    stats=pm_agg.merge(pc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
                       on="date",how="left").merge(ro,on="date",how="left")
    stats["gap_pct"]=(stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct","pm_high"]).set_index("date")

def build_pivots(rth_df, lookback, wing):
    rth_df=rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"]=pd.to_datetime(rth_df["date"]); sr={}
    for d in sorted(rth_df["date"].unique()):
        hist=rth_df[rth_df["date"]<d].tail(lookback)
        if len(hist)<max(wing+1,lookback//4): continue
        H=hist["high"].values; levels=[]
        for i in range(wing,len(hist)):
            if H[i]==H[i-wing:i+1].max(): levels.append(H[i])
        if not levels: continue
        levels=sorted(levels); cl=[levels[0]]
        for lv in levels[1:]:
            if abs(lv-cl[-1])/cl[-1]<OVERLAP: cl[-1]=(cl[-1]+lv)/2
            else: cl.append(lv)
        sr[d]=cl
    return sr

def race(ddf, ei, ep):
    n=len(ddf); tp_p=ep*(1-TP_PCT); sl_p=ep*(1+SL_PCT)
    for i in range(ei, min(ei+MAX_BARS, n-1)+1):
        if ddf.iloc[i]["high"]>=sl_p: return "SL", -SL_PCT*100
        if ddf.iloc[i]["low"] <=tp_p: return "TP",  TP_PCT*100
    return "TO", 0.0

def scan_fresh_1st(ddf, level):
    """Return first-touch-only event if level is untouched today. None otherwise."""
    n=len(ddf); H=ddf["high"].values; C=ddf["close"].values
    state="IDLE"; ext=None; touch_num=0; i=0
    while i<n-3:
        touching = H[i] >= level*(1-NEAR_PCT)
        if state=="IDLE":
            if touching: state="IN"; ext=C[i]; touch_num+=1
        elif state=="IN":
            if touching: ext=min(ext,C[i])
            else:
                bounced = ext is not None and (level-ext)/level >= BOUNCE
                if bounced and touch_num==1 and i+1<n:
                    ei=i+1; ep=ddf.iloc[ei]["open"]
                    return {"bar_i":ei,"ep":ep}
                state="IDLE"; ext=None
                if touch_num>=1: return None  # already touched, not fresh
        i+=1
    return None

def metrics(s):
    if len(s)<5: return None
    n=len(s); tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp=s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/WEEKS
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=n,tpw=tpw,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev,maxdd=maxdd)

HDR=(f"  {'Label':<34} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*86}"
W  =90

def prow(label, s, w=34):
    mx=metrics(s)
    if mx is None: print(f"  {label:<{w}} (n<5)"); return
    mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
        "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%{mk}")


if __name__=="__main__":
    print("Scanning Version E...", flush=True)
    records=[]

    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue

        piv_30m = build_pivots(rth_df, 30,  3)
        piv_1h  = build_pivots(rth_df, 60,  3)
        piv_2h  = build_pivots(rth_df, 120, 4)

        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        for date, ddf in rth_df.groupby("date"):
            date_ts = pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day = pm_stats.loc[date_ts]
            if day["gap_pct"] <= 0.5: continue
            ddf = ddf.reset_index(drop=True)
            dk  = date_ts.date()

            if sym in ["APP","SMCI","HIMS","ARM"]:
                # PMH fresh 1st only
                pmh = day["pm_high"]
                ev = scan_fresh_1st(ddf, pmh)
                if ev:
                    out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                    records.append({"sym":sym,"setup":"PMH_fresh1st",
                                    "outcome":out,"pnl":pnl,
                                    "date":pd.Timestamp(dk)})

            elif sym == "MU":
                res_1h = piv_1h.get(date_ts, piv_1h.get(dk, []))
                res_2h = piv_2h.get(date_ts, piv_2h.get(dk, []))
                res_30m= piv_30m.get(date_ts,piv_30m.get(dk,[]))

                # MU setup A: 30m fresh 1st
                for level in res_30m:
                    if pd.isna(level): continue
                    ev = scan_fresh_1st(ddf, level)
                    if ev:
                        out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                        records.append({"sym":sym,"setup":"30m_fresh1st",
                                        "outcome":out,"pnl":pnl,
                                        "date":pd.Timestamp(dk)})

                # MU setup B: 1H/2H overlap fresh 1st
                for level in res_1h:
                    if pd.isna(level): continue
                    # check overlap with 2H
                    overlaps = any(abs(lv2-level)/level <= STACK_PCT for lv2 in res_2h)
                    if not overlaps: continue
                    ev = scan_fresh_1st(ddf, level)
                    if ev:
                        out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                        records.append({"sym":sym,"setup":"1H2H_overlap_fresh1st",
                                        "outcome":out,"pnl":pnl,
                                        "date":pd.Timestamp(dk)})

    print()
    df = pd.DataFrame(records)
    df["month"] = df["date"].dt.to_period("M")

    # ── Version B baseline for comparison ────────────────────────────────────
    # Re-run Version B to get exact same-dataset comparison
    import importlib, sys
    print("Loading Version B baseline...", flush=True)

    # Inline Version B scan
    b_records=[]
    VB_LEVELS={"APP":{"1H_Res","PMH"},"SMCI":{"1H_Res","PMH"},
               "HIMS":{"1H_Res","PMH"},"ARM":{"PMH","4H_Res"},"MU":{"1H_Res"}}

    def build_pivots_both(rth_df, lookback, wing):
        rth_df=rth_df.sort_values("time").reset_index(drop=True)
        rth_df["date"]=pd.to_datetime(rth_df["date"]); sr={}
        for d in sorted(rth_df["date"].unique()):
            hist=rth_df[rth_df["date"]<d].tail(lookback)
            if len(hist)<max(wing+1,lookback//4): continue
            H=hist["high"].values; L=hist["low"].values; levels=[]
            for i in range(wing,len(hist)):
                if H[i]==H[i-wing:i+1].max(): levels.append((H[i],"res"))
                if L[i]==L[i-wing:i+1].min(): levels.append((L[i],"sup"))
            if not levels: continue
            levels=sorted(levels,key=lambda x:x[0]); cl=[list(levels[0])]
            for lv,lt in levels[1:]:
                if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
                else: cl.append([lv,lt])
            sr[d]=[(c[0],c[1]) for c in cl]
        return sr

    def build_pm_full(pm_df, rth_df):
        pm_df=pm_df.copy(); pm_df["date"]=pd.to_datetime(pm_df["date"])
        rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        pm_agg=pm_df.groupby("date").agg(pm_high=("high","max"),pm_low=("low","min")).reset_index()
        pc=rth_df.groupby("date")["close"].last().reset_index()
        pc.columns=["date","prev_close"]; pc["next_date"]=pc["date"]+pd.Timedelta(days=1)
        ro=rth_df.groupby("date")["open"].first().reset_index(); ro.columns=["date","rth_open"]
        stats=pm_agg.merge(pc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
                           on="date",how="left").merge(ro,on="date",how="left")
        stats["gap_pct"]=(stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
        return stats.dropna(subset=["gap_pct","pm_high"]).set_index("date")

    def race_b(ddf,ei,ep):
        n=len(ddf); tp_p=ep*(1-TP_PCT); sl_p=ep*(1+SL_PCT)
        for i in range(ei,min(ei+MAX_BARS,n-1)+1):
            if ddf.iloc[i]["high"]>=sl_p: return "SL",-SL_PCT*100
            if ddf.iloc[i]["low"] <=tp_p: return "TP", TP_PCT*100
        return "TO",0.0

    for sym,allowed in VB_LEVELS.items():
        rth_df,pm_df=load_sym(sym)
        pm_stats=build_pm_full(pm_df if not pm_df.empty else rth_df,rth_df)
        sr_1h=build_pivots_both(rth_df,60,3); sr_4h=build_pivots_both(rth_df,240,5)
        rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        for date,ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True)
            dk=date_ts.date()
            pmh=day["pm_high"]
            lv1h=sr_1h.get(date_ts,sr_1h.get(dk,[]))
            lv4h=sr_4h.get(date_ts,sr_4h.get(dk,[]))
            res_levels=[(pmh,"PMH")]
            for lv,lt in lv1h:
                if lt=="res": res_levels.append((lv,"1H_Res"))
            for lv,lt in lv4h:
                if lt=="res": res_levels.append((lv,"4H_Res"))
            H=ddf["high"].values; C=ddf["close"].values; n=len(ddf)
            for level,lname in res_levels:
                if pd.isna(level) or lname not in allowed: continue
                state="IDLE"; ext=None; touch_num=0; i=0
                while i<n-3:
                    touching=H[i]>=level*(1-NEAR_PCT)
                    if state=="IDLE":
                        if touching: state="IN"; ext=C[i]; touch_num+=1
                    elif state=="IN":
                        if touching: ext=min(ext,C[i])
                        else:
                            bounced=ext is not None and (level-ext)/level>=BOUNCE
                            if bounced and touch_num==1:
                                ei=i+1; ep=ddf.iloc[ei]["open"]
                                out,pnl=race_b(ddf,ei,ep)
                                b_records.append({"sym":sym,"setup":lname,
                                                  "outcome":out,"pnl":pnl,
                                                  "date":pd.Timestamp(dk)})
                            state="IDLE"; ext=None
                    i+=1
    b_df=pd.DataFrame(b_records); b_df["month"]=b_df["date"].dt.to_period("M")

    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  VERSION E  vs  VERSION B  |  Symbol-specialized engine")
    print(f"  SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25%")
    print(f"{'='*W}")
    print(f"\n  Version E rules:")
    print(f"    APP / SMCI / HIMS / ARM  ->  PMH fresh 1st touch only")
    print(f"    MU                       ->  30m fresh 1st  +  1H/2H overlap fresh 1st")
    print(f"\n  Version B rules:")
    print(f"    APP/SMCI/HIMS: 1H_Res + PMH | ARM: PMH + 4H_Res | MU: 1H_Res (all 1st touch)")
    print()
    print(HDR); print(SEP)
    prow("Version B (champion)",  b_df)
    prow("Version E (specialized)",df)
    print(SEP)

    # Per symbol
    print(f"\n  PER SYMBOL:")
    print(HDR); print(SEP)
    for sym in SYMS:
        sb=b_df[b_df["sym"]==sym]; se=df[df["sym"]==sym]
        prow(f"  B: {sym}", sb)
        prow(f"  E: {sym}", se)
        print(SEP)

    # Per setup inside E
    print(f"\n  VERSION E — by setup:")
    print(HDR); print(SEP)
    for setup in df["setup"].unique():
        prow(f"  {setup}", df[df["setup"]==setup])

    # Monthly for E
    print(f"\n{'='*W}")
    print(f"  VERSION E — MONTHLY")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'TP':>4}/{' SL':<4}  {'PF':>6}  {'EV':>7}  {'Mo PnL':>8}  {'Cumul':>8}")
    print(f"  {'-'*70}")
    cumul=0.0; mo_pnls=[]
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; n=len(s)
        tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
        wr=tp/n*100 if n>0 else 0
        pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        ev=s["pnl"].mean(); mo_pnl=s["pnl"].sum(); cumul+=mo_pnl
        mo_pnls.append(mo_pnl)
        flag=" v" if mo_pnl>=0 else " x"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {tp:>4}/{sl:<4}  "
              f"{pf:>6.3f}  {ev:>+6.4f}%  {mo_pnl:>+7.3f}%  {cumul:>+7.3f}%{flag}")
    print(f"  {'-'*70}")
    n=len(df); tp=df["outcome"].eq("TP").sum(); sl=df["outcome"].eq("SL").sum()
    pf_all=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    print(f"  {'TOTAL':<10} {n:>4}  {tp/n*100:>5.1f}%  {tp:>4}/{sl:<4}  "
          f"{pf_all:>6.3f}  {df['pnl'].mean():>+6.4f}%  {df['pnl'].sum():>+7.3f}%  {cumul:>+7.3f}%")
    wins=sum(1 for p in mo_pnls if p>0); total=len(mo_pnls)
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    print(f"  Best:  {max(mo_pnls):>+.3f}%   Worst: {min(mo_pnls):>+.3f}%   Avg: {np.mean(mo_pnls):>+.3f}%")

    # Head to head summary
    print(f"\n{'='*W}")
    print(f"  HEAD-TO-HEAD SUMMARY")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version B", b_df)
    prow("Version E", df)
    mx_b=metrics(b_df); mx_e=metrics(df)
    if mx_b and mx_e:
        print(f"\n  PF  delta:  {mx_e['pf']-mx_b['pf']:>+.3f}")
        print(f"  EV  delta:  {mx_e['ev']-mx_b['ev']:>+.4f}%")
        print(f"  N   delta:  {mx_e['n']-mx_b['n']:>+d} trades")
        print(f"  T/Wk delta: {mx_e['tpw']-mx_b['tpw']:>+.1f}")
        print(f"  MaxDD delta:{mx_e['maxdd']-mx_b['maxdd']:>+.2f}%")
