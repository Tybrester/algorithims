"""
BOOF53 1-Year Matrix — GOOGL, META, HIMS, RIOT
8 levels: PMH, PDH, 10m, 30m, 1H, 2H, 4H, Daily
Uses boof53_{sym}_1m_1yr.csv (1 year data)
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

SYMS = ["GOOGL", "META", "HIMS", "RIOT"]

PIVOT_TFS = [
    ("10m",   10,  2),
    ("30m",   30,  3),
    ("1H",    60,  3),
    ("2H",   120,  4),
    ("4H",   240,  5),
    ("Daily", 390, 5),
]
ALL_LEVELS = ["PMH", "PDH"] + [tf for tf,_,_ in PIVOT_TFS]


def load_sym(sym):
    path = f"boof53_{sym}_1m_1yr.csv"
    if not os.path.exists(path): return None, None
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm>="09:30")&(hm<="16:00")].copy()
    pm  = df[(hm>="04:00")&(hm< "09:30")].copy()
    rth["date"] = rth["time"].dt.date
    pm["date"]  = pm["time"].dt.date
    # compute weeks span
    dates = sorted(rth["date"].unique())
    weeks = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 7 if len(dates)>1 else 1
    return rth, pm, weeks

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
    dh=rth_df.groupby("date")["high"].max().reset_index().sort_values("date")
    result={}
    dates=list(dh["date"]); highs=list(dh["high"])
    for i in range(len(dates)-1):
        result[dates[i+1]] = highs[i]
    return result

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

def met(trades, weeks):
    if len(trades)<5: return None
    s=pd.DataFrame(trades); n=len(s)
    tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp=s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/weeks
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    score=pf*np.log10(n)
    return dict(n=n,tpw=tpw,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev,maxdd=maxdd,
                cumul=s["pnl"].sum(),score=score)

W = 108

if __name__=="__main__":
    print("Scanning 1-year matrix...", flush=True)
    all_results={}; all_weeks={}

    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        result = load_sym(sym)
        if result[0] is None: all_results[sym]={}; continue
        rth_df, pm_df, weeks = result
        all_weeks[sym] = weeks
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: all_results[sym]={}; continue

        pdh_map = build_pdh(rth_df)
        pivots  = {tf: build_pivots(rth_df, lb, wg) for tf,lb,wg in PIVOT_TFS}
        rth_df  = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        trades = {lv: [] for lv in ALL_LEVELS}

        for date, ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()

            ev=scan_fresh_1st(ddf, day["pm_high"])
            if ev:
                out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                trades["PMH"].append({"outcome":out,"pnl":pnl})

            pdh=pdh_map.get(date_ts)
            if pdh and not pd.isna(pdh):
                ev=scan_fresh_1st(ddf, pdh)
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    trades["PDH"].append({"outcome":out,"pnl":pnl})

            for tf,lb,wg in PIVOT_TFS:
                for level in pivots[tf].get(date_ts, pivots[tf].get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        trades[tf].append({"outcome":out,"pnl":pnl})

        all_results[sym]={lv: met(trades[lv], weeks) for lv in ALL_LEVELS}

    print()

    # ── PF Matrix ─────────────────────────────────────────────────────────────
    cw=10
    print(f"\n{'='*W}")
    print(f"  1-YEAR MATRIX  |  GOOGL, META, HIMS, RIOT  |  8 levels")
    print(f"  <<< >=2.0 | << >=1.5 | < >=1.2 | - <1.0 | -- N<5")
    print(f"{'='*W}")

    hdr=(f"\n  {'Sym':<7} {'Weeks':>5}" + "".join(f"  {lv:^{cw}}" for lv in ALL_LEVELS)
         + f"  {'Best':^8}  {'Score':>6}")
    print(hdr)
    print(f"  {'-'*100}")

    sym_bests={}
    for sym in SYMS:
        r=all_results.get(sym,{}); w=all_weeks.get(sym,52)
        cells=[]
        for lv in ALL_LEVELS:
            mx=r.get(lv)
            if mx is None or mx["n"]<5: cells.append("--")
            else:
                pf=mx["pf"]
                mk=("<<<" if pf>=2.0 else "<<" if pf>=1.5 else "<" if pf>=1.2 else "-" if pf<1.0 else "")
                cells.append(f"{pf:.2f}{mk}")
        best_lv=None; best_sc=-1; best_pf=-1
        for lv in ALL_LEVELS:
            mx=r.get(lv)
            if mx and mx["n"]>=8 and mx["score"]>best_sc:
                best_sc=mx["score"]; best_lv=lv; best_pf=mx["pf"]
        sym_bests[sym]=(best_lv,best_pf,best_sc)
        print(f"  {sym:<7} {w:>5.1f}" + "".join(f"  {c:^{cw}}" for c in cells)
              + f"  {str(best_lv):^8}  {best_sc:>6.2f}")

    # ── N table ───────────────────────────────────────────────────────────────
    print(f"\n  N by cell:")
    print(f"  {'-'*80}")
    hdr_n=(f"  {'Sym':<7} {'Weeks':>5}" + "".join(f"  {lv:^{cw}}" for lv in ALL_LEVELS))
    print(hdr_n)
    for sym in SYMS:
        r=all_results.get(sym,{}); w=all_weeks.get(sym,52)
        cells=[str(r[lv]["n"]) if r.get(lv) else "--" for lv in ALL_LEVELS]
        print(f"  {sym:<7} {w:>5.1f}" + "".join(f"  {c:^{cw}}" for c in cells))

    # ── EV table ──────────────────────────────────────────────────────────────
    print(f"\n  EV/trade by cell:")
    print(f"  {'-'*80}")
    print(hdr_n)
    for sym in SYMS:
        r=all_results.get(sym,{}); w=all_weeks.get(sym,52)
        cells=[f"{r[lv]['ev']:>+.3f}%" if r.get(lv) else "--" for lv in ALL_LEVELS]
        print(f"  {sym:<7} {w:>5.1f}" + "".join(f"  {c:^{cw}}" for c in cells))

    # ── Score table ───────────────────────────────────────────────────────────
    print(f"\n  Score (PF x log10(N)) by cell:")
    print(f"  {'-'*80}")
    print(hdr_n)
    for sym in SYMS:
        r=all_results.get(sym,{}); w=all_weeks.get(sym,52)
        cells=[f"{r[lv]['score']:.2f}" if r.get(lv) else "--" for lv in ALL_LEVELS]
        print(f"  {sym:<7} {w:>5.1f}" + "".join(f"  {c:^{cw}}" for c in cells))

    # ── Full ranked detail per symbol ─────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  RANKED LEVELS PER SYMBOL  (by Score, N>=5)")
    print(f"{'='*W}")
    HDR=(f"  {'Level':<8} {'N':>5} {'T/Wk':>5}  {'WR':>6}  {'TP/SL':>9}  "
         f"{'PF':>6}  {'EV':>9}  {'MaxDD':>7}  {'Cumul':>8}  {'Score':>6}")
    SEP=f"  {'-'*82}"

    for sym in SYMS:
        r=all_results.get(sym,{}); w=all_weeks.get(sym,52)
        best_lv,best_pf,best_sc=sym_bests.get(sym,(None,-1,-1))
        ranked=[(lv,r[lv]) for lv in ALL_LEVELS if r.get(lv) and r[lv]["n"]>=5]
        ranked.sort(key=lambda x:-x[1]["score"])
        print(f"\n  {sym}  ({w:.1f} weeks)  best: {best_lv}  PF {best_pf:.3f}  score {best_sc:.2f}")
        print(HDR); print(SEP)
        for lv,mx in ranked:
            mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
                "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
            star=" *" if lv==best_lv else ""
            print(f"  {lv:<8} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
                  f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}{mk}  "
                  f"{mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%  "
                  f"{mx['cumul']:>+7.3f}%  {mx['score']:>6.2f}{star}")

    # ── 6m vs 1yr comparison ──────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  6-MONTH vs 1-YEAR COMPARISON  (best level, top PF cells)")
    print(f"{'='*W}")
    # 6m results from phase2 (hardcoded from prior run)
    SIX_MO = {
        "GOOGL": {"PMH":1.17,"PDH":2.80,"10m":1.75,"30m":1.50,"1H":1.45,"2H":0.88,"4H":0.84,"Daily":1.47},
        "META":  {"PMH":0.73,"PDH":2.50,"10m":0.57,"30m":1.20,"1H":1.60,"2H":1.33,"4H":1.17,"Daily":1.33},
        "HIMS":  {"PMH":1.69,"PDH":0.47,"10m":0.89,"30m":0.94,"1H":0.92,"2H":1.24,"4H":0.93,"Daily":1.21},
        "RIOT":  {"PMH":1.28,"PDH":0.17,"10m":0.71,"30m":1.09,"1H":1.07,"2H":0.92,"4H":1.01,"Daily":0.91},
    }
    print(f"\n  {'Sym':<7} {'Level':<8}  {'6m PF':>8}  {'1yr PF':>8}  {'Delta':>8}  {'1yr N':>7}  {'Verdict'}")
    print(f"  {'-'*70}")
    for sym in SYMS:
        r=all_results.get(sym,{}); w=all_weeks.get(sym,52)
        s6=SIX_MO.get(sym,{})
        for lv in ALL_LEVELS:
            mx=r.get(lv); pf6=s6.get(lv)
            if mx is None or pf6 is None or mx["n"]<5: continue
            delta=mx["pf"]-pf6
            verdict=("CONFIRMED" if mx["pf"]>=1.5 and pf6>=1.5
                     else "IMPROVED" if delta>0.15
                     else "DEGRADED" if delta<-0.15
                     else "STABLE")
            if abs(delta)>0.10 or mx["pf"]>=1.5:
                mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
                    "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
                print(f"  {sym:<7} {lv:<8}  {pf6:>8.3f}  {mx['pf']:>8.3f}{mk}  "
                      f"{delta:>+8.3f}  {mx['n']:>7}  {verdict}")
