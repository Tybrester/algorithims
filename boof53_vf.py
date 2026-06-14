"""
BOOF53 Version F — 14-symbol specialized engine
PMH group:  APP, SMCI, ARM, HIMS, CRM, HOOD, PLTR
30m group:  MU, TSLA, AMD, COIN, GOOGL, ADBE, NVDA
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch
"""
import pandas as pd
import numpy as np
import pytz
import os

ET        = pytz.timezone("America/New_York")
OVERLAP   = 0.0020
BOUNCE    = 0.0015
NEAR_PCT  = 0.0015
TP_PCT    = 0.0050
SL_PCT    = 0.0025
MAX_BARS  = 60
WEEKS     = 19.2

PMH_SYMS  = ["APP","SMCI","ARM","HIMS","CRM","HOOD","PLTR"]
M30_SYMS  = ["MU","TSLA","AMD","COIN","GOOGL","ADBE","NVDA"]
ALL_SYMS  = PMH_SYMS + M30_SYMS


def load_sym(sym):
    path = f"boof51_{sym}_1m.csv"
    if not os.path.exists(path): return None, None
    df = pd.read_csv(path)
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
                    return {"bar_i":i+1,"ep":ddf.iloc[i+1]["open"]}
                state="IDLE"; ext=None
                if touch_num>=1: return None
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

HDR=(f"  {'Label':<32} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*84}"
W  =88

def prow(label, s, w=32):
    mx=metrics(s)
    if mx is None: print(f"  {label:<{w}} (n<5)"); return
    mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
        "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
          f"{mx['maxdd']:>+7.2f}%{mk}")


if __name__ == "__main__":
    print("Scanning Version F...", flush=True)
    records = []

    for sym in ALL_SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue
        piv_30m = build_pivots(rth_df, 30, 3) if sym in M30_SYMS else {}
        rth_df  = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        for date, ddf in rth_df.groupby("date"):
            date_ts = pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day = pm_stats.loc[date_ts]
            if day["gap_pct"] <= 0.5: continue
            ddf = ddf.reset_index(drop=True)
            dk  = date_ts.date()

            if sym in PMH_SYMS:
                ev = scan_fresh_1st(ddf, day["pm_high"])
                if ev:
                    out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                    records.append({"sym":sym,"setup":"PMH","outcome":out,
                                    "pnl":pnl,"date":pd.Timestamp(dk)})

            elif sym in M30_SYMS:
                for level in piv_30m.get(date_ts, piv_30m.get(dk,[])):
                    if pd.isna(level): continue
                    ev = scan_fresh_1st(ddf, level)
                    if ev:
                        out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                        records.append({"sym":sym,"setup":"30m","outcome":out,
                                        "pnl":pnl,"date":pd.Timestamp(dk)})

    print()
    df = pd.DataFrame(records)
    df["month"] = df["date"].dt.to_period("M")

    # ── Version E baseline (5 symbols) ───────────────────────────────────────
    print("Loading Version E baseline...", flush=True)
    e_records=[]
    VE_PMH=["APP","SMCI","ARM","HIMS"]
    for sym in VE_PMH:
        rth_df,pm_df=load_sym(sym)
        if rth_df is None: continue
        pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df,rth_df)
        if pm_stats.empty: continue
        rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        for date,ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()
            ev=scan_fresh_1st(ddf,day["pm_high"])
            if ev:
                out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                e_records.append({"sym":sym,"setup":"PMH","outcome":out,
                                  "pnl":pnl,"date":pd.Timestamp(dk)})
    for sym in ["MU"]:
        rth_df,pm_df=load_sym(sym)
        if rth_df is None: continue
        pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df,rth_df)
        piv_30m=build_pivots(rth_df,30,3)
        piv_1h=build_pivots(rth_df,60,3); piv_2h=build_pivots(rth_df,120,4)
        rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        for date,ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()
            for level in piv_30m.get(date_ts,piv_30m.get(dk,[])):
                if pd.isna(level): continue
                ev=scan_fresh_1st(ddf,level)
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    e_records.append({"sym":sym,"setup":"30m","outcome":out,
                                      "pnl":pnl,"date":pd.Timestamp(dk)})
            res_1h=piv_1h.get(date_ts,piv_1h.get(dk,[])); res_2h=piv_2h.get(date_ts,piv_2h.get(dk,[]))
            for level in res_1h:
                if pd.isna(level): continue
                if any(abs(lv2-level)/level<=0.0015 for lv2 in res_2h):
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        e_records.append({"sym":sym,"setup":"1H2H","outcome":out,
                                          "pnl":pnl,"date":pd.Timestamp(dk)})
    e_df=pd.DataFrame(e_records); e_df["month"]=e_df["date"].dt.to_period("M")

    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  BOOF53 VERSION F  |  14-symbol specialized engine")
    print(f"  SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch")
    print(f"{'='*W}")
    print(f"\n  PMH group : {', '.join(PMH_SYMS)}")
    print(f"  30m group : {', '.join(M30_SYMS)}")

    # ── Top-line metrics card ─────────────────────────────────────────────────
    mx = metrics(df)
    print(f"\n  {'Metric':<18} {'Value':>12}  {'Version E':>12}  {'Version B':>12}")
    print(f"  {'-'*56}")
    mx_e = metrics(e_df)

    # Version B hardcoded from prior run
    VB = dict(n=187,tpw=9.7,wr=48.7,pf=1.896,ev=0.1150,maxdd=-2.75)

    rows = [
        ("Trades total",  f"{mx['n']}",       f"{mx_e['n']}",    f"{VB['n']}"),
        ("Trades/week",   f"{mx['tpw']:.1f}",  f"{mx_e['tpw']:.1f}", f"{VB['tpw']:.1f}"),
        ("Win Rate",      f"{mx['wr']:.1f}%",  f"{mx_e['wr']:.1f}%", f"{VB['wr']:.1f}%"),
        ("PF",            f"{mx['pf']:.3f}",   f"{mx_e['pf']:.3f}",  f"{VB['pf']:.3f}"),
        ("EV/trade",      f"{mx['ev']:+.4f}%", f"{mx_e['ev']:+.4f}%",f"{VB['ev']:+.4f}%"),
        ("MaxDD",         f"{mx['maxdd']:+.2f}%",f"{mx_e['maxdd']:+.2f}%",f"{VB['maxdd']:+.2f}%"),
    ]
    for label, vf, ve, vb in rows:
        print(f"  {label:<18} {vf:>12}  {ve:>12}  {vb:>12}")

    # ── Per group ─────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BY GROUP")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version F  (all 14)",   df)
    prow("  PMH group (7 syms)", df[df["setup"]=="PMH"])
    prow("  30m group (7 syms)", df[df["setup"]=="30m"])
    print(SEP)
    prow("Version E  (5 syms)",   e_df)

    # ── Per symbol ────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PER SYMBOL")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    print(f"  --- PMH group ---")
    for sym in PMH_SYMS:
        prow(f"  {sym}", df[df["sym"]==sym])
    print(SEP)
    print(f"  --- 30m group ---")
    for sym in M30_SYMS:
        prow(f"  {sym}", df[df["sym"]==sym])

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MONTHLY  |  Version F")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'TP':>4}/{' SL':<4}  "
          f"{'PF':>6}  {'EV':>8}  {'Mo PnL':>8}  {'Cumul':>8}")
    print(f"  {'-'*72}")
    cumul=0.0; mo_pnls=[]
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; n=len(s)
        tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
        wr=tp/n*100 if n>0 else 0
        pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        ev=s["pnl"].mean(); mo_pnl=s["pnl"].sum(); cumul+=mo_pnl; mo_pnls.append(mo_pnl)
        flag=" v" if mo_pnl>=0 else " x"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {tp:>4}/{sl:<4}  "
              f"{pf:>6.3f}  {ev:>+7.4f}%  {mo_pnl:>+7.3f}%  {cumul:>+7.3f}%{flag}")
    print(f"  {'-'*72}")
    n=len(df); tp=df["outcome"].eq("TP").sum(); sl=df["outcome"].eq("SL").sum()
    print(f"  {'TOTAL':<10} {n:>4}  {tp/n*100:>5.1f}%  {tp:>4}/{sl:<4}  "
          f"{(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999:>6.3f}  "
          f"{df['pnl'].mean():>+7.4f}%  {df['pnl'].sum():>+7.3f}%  {cumul:>+7.3f}%")
    wins=sum(1 for p in mo_pnls if p>0); total=len(mo_pnls)
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    print(f"  Best:  {max(mo_pnls):>+.3f}%   Worst: {min(mo_pnls):>+.3f}%   Avg: {np.mean(mo_pnls):>+.3f}%")

    # ── Monthly PF table (side by side F vs E) ────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MONTHLY PF  |  Version F vs Version E")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'F  N':>5}  {'F PF':>6}  {'F MoPnL':>8}  |  "
          f"{'E  N':>5}  {'E PF':>6}  {'E MoPnL':>8}")
    print(f"  {'-'*70}")
    all_months = sorted(set(df["month"].tolist()) | set(e_df["month"].tolist()))
    for mo in all_months:
        sf=df[df["month"]==mo]; se=e_df[e_df["month"]==mo]
        def mo_stats(s):
            if len(s)<2: return "  --","  --","    --"
            tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
            pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
            return f"{len(s):>5}", f"{pf:>6.3f}", f"{s['pnl'].sum():>+7.3f}%"
        fn,fpf,fmo=mo_stats(sf); en,epf,emo=mo_stats(se)
        print(f"  {str(mo):<10} {fn}  {fpf}  {fmo}  |  {en}  {epf}  {emo}")

    # ── Equity curve summary ──────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  CUMULATIVE PnL COMPARISON")
    print(f"{'='*W}")
    print(f"  Version F total: {df['pnl'].sum():>+.3f}%  over {WEEKS:.0f} weeks")
    print(f"  Version E total: {e_df['pnl'].sum():>+.3f}%  over {WEEKS:.0f} weeks")
    print(f"  Version F MaxDD: {mx['maxdd']:>+.2f}%")
    print(f"  Version E MaxDD: {mx_e['maxdd']:>+.2f}%")
    print(f"  Version F T/Wk:  {mx['tpw']:.1f}   Version E T/Wk: {mx_e['tpw']:.1f}")
