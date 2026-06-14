"""
BOOF53 — PDH and Daily level evidence run
6 symbols: AFRM/GOOGL/META -> PDH | AMD/CRM/HIMS -> Daily
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch
"""
import pandas as pd
import numpy as np
import pytz
import os

ET       = pytz.timezone("America/New_York")
OVERLAP  = 0.0020
BOUNCE   = 0.0015
NEAR_PCT = 0.0015
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60
WEEKS    = 19.2

TARGETS = {
    "AFRM":  "PDH",
    "GOOGL": "PDH",
    "META":  "PDH",
    "AMD":   "Daily",
    "CRM":   "Daily",
    "HIMS":  "Daily",
}


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

def build_pdh(rth_df):
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    dh=rth_df.groupby("date")["high"].max().reset_index()
    dh=dh.sort_values("date"); result={}
    dates=list(dh["date"]); highs=list(dh["high"])
    for i in range(len(dates)-1):
        result[dates[i+1]] = highs[i]
    return result

def build_daily_pivots(rth_df):
    """Daily pivot highs — prior RTH session high as resistance level."""
    return build_pdh(rth_df)  # same as PDH — prior day high

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

def met(trades):
    if len(trades)<3: return None
    s=pd.DataFrame(trades); n=len(s)
    tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp=s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/WEEKS
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=n,tpw=tpw,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev,maxdd=maxdd,
                cumul=s["pnl"].sum())

W=90

if __name__=="__main__":
    print("Running PDH + Daily evidence...\n", flush=True)

    all_trades = {}
    monthly_trades = {}

    for sym, level_type in TARGETS.items():
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue

        if level_type == "PDH":
            level_map = build_pdh(rth_df)
            # single level per day
        else:  # Daily — 390-bar swing pivots
            level_map = None
            piv_daily = build_pivots(rth_df, 390, 5)

        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        trades = []; mo_trades = {}

        for date, ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()
            mo=date_ts.to_period("M")

            if level_type == "PDH":
                level = level_map.get(date_ts)
                if level is None or pd.isna(level): continue
                ev=scan_fresh_1st(ddf, level)
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    t={"outcome":out,"pnl":pnl,"date":date_ts}
                    trades.append(t)
                    mo_trades.setdefault(mo,[]).append(t)
            else:
                levels = piv_daily.get(date_ts, piv_daily.get(dk,[]))
                for level in levels:
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        t={"outcome":out,"pnl":pnl,"date":date_ts}
                        trades.append(t)
                        mo_trades.setdefault(mo,[]).append(t)

        all_trades[sym] = trades
        monthly_trades[sym] = mo_trades

    # ── Top-line results ──────────────────────────────────────────────────────
    print(f"{'='*W}")
    print(f"  PDH GROUP: AFRM, GOOGL, META")
    print(f"  Daily GROUP: AMD, CRM, HIMS")
    print(f"  SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch")
    print(f"{'='*W}")

    HDR=(f"\n  {'Symbol':<8} {'Level':<8} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
         f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}  {'Cumul':>8}")
    SEP=f"  {'-'*80}"
    print(HDR); print(SEP)

    pdh_all=[]; daily_all=[]
    for sym, level_type in TARGETS.items():
        t=all_trades.get(sym,[])
        mx=met(t)
        if mx is None:
            print(f"  {sym:<8} {level_type:<8} (n<3)")
            continue
        mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
            "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
        print(f"  {sym:<8} {level_type:<8} {mx['n']:>5} {mx['tpw']:>5.1f}  "
              f"{mx['wr']:>5.1f}%  {mx['tp']:>4}/{mx['sl']:<4}  "
              f"{mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
              f"{mx['maxdd']:>+7.2f}%{mk}  {mx['cumul']:>+7.3f}%")
        if level_type=="PDH": pdh_all+=t
        else: daily_all+=t

    print(SEP)
    for label, pool in [("PDH group total", pdh_all), ("Daily group total", daily_all),
                        ("Combined total", pdh_all+daily_all)]:
        mx=met(pool)
        if mx:
            mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
                "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
            print(f"  {label:<16}       {mx['n']:>5} {mx['tpw']:>5.1f}  "
                  f"{mx['wr']:>5.1f}%  {mx['tp']:>4}/{mx['sl']:<4}  "
                  f"{mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
                  f"{mx['maxdd']:>+7.2f}%{mk}  {mx['cumul']:>+7.3f}%")

    # ── Monthly breakdown per symbol ──────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MONTHLY BREAKDOWN PER SYMBOL")
    print(f"{'='*W}")

    all_months = sorted(set(
        mo for sym in TARGETS for mo in monthly_trades.get(sym,{}).keys()
    ))

    for sym, level_type in TARGETS.items():
        mo_t = monthly_trades.get(sym,{})
        print(f"\n  {sym} ({level_type})")
        print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'PF':>6}  {'Mo PnL':>8}  {'Cumul':>8}")
        print(f"  {'-'*52}")
        cumul=0.0
        for mo in all_months:
            t=mo_t.get(mo,[])
            if not t: print(f"  {str(mo):<10}    --"); continue
            mx=met(t)
            if mx is None: print(f"  {str(mo):<10} {len(t):>4}  (n<3)"); continue
            pf_=(mx['tp']*TP_PCT*100)/(mx['sl']*SL_PCT*100) if mx['sl']>0 else 999
            mo_pnl=sum(x["pnl"] for x in t); cumul+=mo_pnl
            flag=" v" if mo_pnl>=0 else " x"
            print(f"  {str(mo):<10} {len(t):>4}  {mx['wr']:>5.1f}%  "
                  f"{pf_:>6.3f}  {mo_pnl:>+7.3f}%  {cumul:>+7.3f}%{flag}")

    # ── Consistency check ─────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  CONSISTENCY CHECK  (months profitable / total)")
    print(f"{'='*W}")
    print(f"\n  {'Symbol':<8} {'Level':<8} {'Prof Mo':>8}  {'Total':>6}  {'%':>6}  {'Best Mo':>9}  {'Worst Mo':>9}")
    print(f"  {'-'*62}")
    for sym, level_type in TARGETS.items():
        mo_t=monthly_trades.get(sym,{})
        mo_pnls=[]
        for mo in all_months:
            t=mo_t.get(mo,[])
            if t: mo_pnls.append(sum(x["pnl"] for x in t))
        if not mo_pnls: continue
        wins=sum(1 for p in mo_pnls if p>0)
        total=len(mo_pnls)
        print(f"  {sym:<8} {level_type:<8} {wins:>8}  {total:>6}  "
              f"{wins/total*100:>5.0f}%  {max(mo_pnls):>+8.3f}%  {min(mo_pnls):>+8.3f}%")
