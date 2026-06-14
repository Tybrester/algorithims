"""
BOOF53 Version F — Full 30-symbol universe scan
Tests all 3 setups (PMH, 30m, 1H2H_overlap) fresh 1st touch on every symbol.
Ranks and recommends final routing table.
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25%
"""
import pandas as pd
import numpy as np
import pytz
import os

ET        = pytz.timezone("America/New_York")
OVERLAP   = 0.0020
BOUNCE    = 0.0015
NEAR_PCT  = 0.0015
STACK_PCT = 0.0015
TP_PCT    = 0.0050
SL_PCT    = 0.0025
MAX_BARS  = 60
WEEKS     = 19.2

UNIVERSE = [
    "APP","SMCI","HIMS","ARM","MU",
    "TSLA","AMD","COIN","NVDA","CRM",
    "PLTR","HOOD","GOOGL","ADBE","TEM",
    "RKLB","ASTS","LUNR","AFRM","UPST",
    "AVGO","MRVL","ANET","CRWD","PANW",
    "META","AMZN","MSTR","CLSK","RIOT",
]


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

def met(trades):
    if len(trades)<5: return None
    s=pd.DataFrame(trades); n=len(s)
    tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp=s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/WEEKS
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=n,tpw=tpw,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev,maxdd=maxdd)

def run_sym(sym):
    rth_df, pm_df = load_sym(sym)
    if rth_df is None or rth_df.empty: return {}
    pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
    if pm_stats.empty: return {}
    piv_30m = build_pivots(rth_df, 30,  3)
    piv_1h  = build_pivots(rth_df, 60,  3)
    piv_2h  = build_pivots(rth_df, 120, 4)
    rth_df  = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    pmh_t=[]; m30_t=[]; ov_t=[]

    for date, ddf in rth_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm_stats.index: continue
        day=pm_stats.loc[date_ts]
        if day["gap_pct"]<=0.5: continue
        ddf=ddf.reset_index(drop=True); dk=date_ts.date()

        ev=scan_fresh_1st(ddf, day["pm_high"])
        if ev:
            out,pnl=race(ddf,ev["bar_i"],ev["ep"])
            pmh_t.append({"outcome":out,"pnl":pnl})

        for level in piv_30m.get(date_ts,piv_30m.get(dk,[])):
            if pd.isna(level): continue
            ev=scan_fresh_1st(ddf,level)
            if ev:
                out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                m30_t.append({"outcome":out,"pnl":pnl})

        res_1h=piv_1h.get(date_ts,piv_1h.get(dk,[]))
        res_2h=piv_2h.get(date_ts,piv_2h.get(dk,[]))
        for level in res_1h:
            if pd.isna(level): continue
            if any(abs(lv2-level)/level<=STACK_PCT for lv2 in res_2h):
                ev=scan_fresh_1st(ddf,level)
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    ov_t.append({"outcome":out,"pnl":pnl})

    return {"PMH":met(pmh_t),"30m":met(m30_t),"1H2H":met(ov_t),
            "ALL":met(pmh_t+m30_t+ov_t)}

HDR=(f"  {'Sym':<6} {'Setup':<8} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*78}"
W  =82

def prow(sym, setup, mx):
    if mx is None: return
    mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
        "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
    print(f"  {sym:<6} {setup:<8} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
          f"{mx['maxdd']:>+7.2f}%{mk}")


if __name__=="__main__":
    print("Scanning 30 symbols...", flush=True)
    results={}
    for sym in UNIVERSE:
        print(f"  {sym}", end=" ", flush=True)
        results[sym]=run_sym(sym)
    print()

    # ── Per-setup rankings ────────────────────────────────────────────────────
    for setup_key, setup_label in [("PMH","PMH Fresh 1st"),
                                    ("30m","30m Fresh 1st"),
                                    ("1H2H","1H+2H Overlap Fresh 1st")]:
        print(f"\n{'='*W}")
        print(f"  {setup_label}  |  Ranked by PF  (N>=10)")
        print(f"{'='*W}")
        print(HDR); print(SEP)
        rows=[(sym,results[sym].get(setup_key)) for sym in UNIVERSE
              if results[sym].get(setup_key) and results[sym][setup_key]["n"]>=10]
        rows.sort(key=lambda x:-x[1]["pf"])
        for sym,mx in rows:
            prow(sym,setup_key,mx)

    # ── Best setup per symbol ─────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BEST SETUP PER SYMBOL  (N>=10, ranked by PF)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    scored=[]
    for sym in UNIVERSE:
        r=results[sym]; best_pf=-1; best_s=None; best_mx=None
        for s in ["PMH","30m","1H2H"]:
            mx=r.get(s)
            if mx and mx["n"]>=10 and mx["pf"]>best_pf:
                best_pf=mx["pf"]; best_s=s; best_mx=mx
        if best_mx:
            score=best_mx["pf"]*np.log10(best_mx["n"])
            scored.append((sym,best_s,best_mx,score))
    scored.sort(key=lambda x:-x[3])
    for sym,setup,mx,score in scored:
        prow(sym,setup,mx)

    # ── Full routing table ────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  FULL ROUTING TABLE  (PMH PF | 30m PF | 1H2H PF | Best)")
    print(f"{'='*W}")
    col=9
    print(f"  {'Sym':<6}  {'PMH':>{col}}  {'30m':>{col}}  {'1H2H':>{col}}  {'Best':<8}  {'N':>5}  {'PF':>6}  {'EV':>9}")
    print(f"  {'-'*72}")
    def pf_str(sym,s):
        mx=results[sym].get(s)
        if mx and mx["n"]>=10: return f"{mx['pf']:.3f}{' <<<' if mx['pf']>=2.0 else ' <<' if mx['pf']>=1.5 else '  <' if mx['pf']>=1.2 else '  -' if mx['pf']<1.0 else '   '}"
        return "--"
    for sym,setup,mx,score in scored:
        print(f"  {sym:<6}  {pf_str(sym,'PMH'):>{col+4}}  {pf_str(sym,'30m'):>{col+4}}  "
              f"{pf_str(sym,'1H2H'):>{col+4}}  {setup:<8}  {mx['n']:>5}  "
              f"{mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%")

    # ── Tier classification ───────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  TIER CLASSIFICATION  (best-setup PF, N>=10)")
    print(f"{'='*W}")
    tiers={"S (PF>=2.0)":[],"A (1.5-2.0)":[],"B (1.2-1.5)":[],"C (1.0-1.2)":[],"D (<1.0)":[]}
    no_data=[]
    for sym in UNIVERSE:
        r=results[sym]; best_pf=-1; best_s=None; best_mx=None
        for s in ["PMH","30m","1H2H"]:
            mx=r.get(s)
            if mx and mx["n"]>=10 and mx["pf"]>best_pf:
                best_pf=mx["pf"]; best_s=s; best_mx=mx
        if best_mx is None: no_data.append(sym); continue
        if   best_pf>=2.0: tiers["S (PF>=2.0)"].append((sym,best_s,best_pf))
        elif best_pf>=1.5: tiers["A (1.5-2.0)"].append((sym,best_s,best_pf))
        elif best_pf>=1.2: tiers["B (1.2-1.5)"].append((sym,best_s,best_pf))
        elif best_pf>=1.0: tiers["C (1.0-1.2)"].append((sym,best_s,best_pf))
        else:               tiers["D (<1.0)"].append((sym,best_s,best_pf))
    for tier,syms in tiers.items():
        if not syms: continue
        syms.sort(key=lambda x:-x[2])
        entries=", ".join(f"{s}({setup},{pf:.2f})" for s,setup,pf in syms)
        print(f"  {tier}: {entries}")
    if no_data: print(f"  No data / N<10: {', '.join(no_data)}")

    # ── Recommended Version F+ routing ────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  RECOMMENDED VERSION F+ ROUTING  (S + A tier, plus selective B)")
    print(f"{'='*W}")
    s_syms = [x[0] for x in tiers["S (PF>=2.0)"]]
    a_syms = [x[0] for x in tiers["A (1.5-2.0)"]]
    b_syms = [x[0] for x in tiers["B (1.2-1.5)"]]
    pmh_rec = [sym for sym,setup,*_ in (tiers["S (PF>=2.0)"]+tiers["A (1.5-2.0)"]+tiers["B (1.2-1.5)"]) if setup=="PMH"]
    m30_rec = [sym for sym,setup,*_ in (tiers["S (PF>=2.0)"]+tiers["A (1.5-2.0)"]+tiers["B (1.2-1.5)"]) if setup=="30m"]
    ov_rec  = [sym for sym,setup,*_ in (tiers["S (PF>=2.0)"]+tiers["A (1.5-2.0)"]+tiers["B (1.2-1.5)"]) if setup=="1H2H"]
    print(f"  PMH  group ({len(pmh_rec)}): {', '.join(pmh_rec)}")
    print(f"  30m  group ({len(m30_rec)}): {', '.join(m30_rec)}")
    print(f"  1H2H group ({len(ov_rec)}):  {', '.join(ov_rec)}")
    all_rec=pmh_rec+m30_rec+ov_rec
    print(f"\n  Total recommended: {len(all_rec)} symbols")
    print(f"  Cut (C/D tier): {[sym for sym,setup,*_ in tiers['C (1.0-1.2)']+tiers['D (<1.0)']]}")
