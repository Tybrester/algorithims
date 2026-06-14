"""
BOOF53 Phase 2 — Full 8-level matrix
22 symbols x PMH, PDH, 10m, 30m, 1H, 2H, 4H, Daily
Rank each symbol's levels by PF, EV, N, PF*log(N)
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

SYMS = [
    "UPST","APP","SMCI","CRM","HIMS","ARM","RIOT",
    "HOOD","TSLA","CLSK","GOOGL",
    "ADBE","PANW","MU","AMD","COIN","NVDA",
    "META","AFRM","MRVL","AVGO","PLTR",
]

PIVOT_TFS = [
    ("10m",   10,  2),
    ("30m",   30,  3),
    ("1H",    60,  3),
    ("2H",   120,  4),
    ("4H",   240,  5),
    ("Daily",390,  5),  # ~6.5hr RTH session = 390 bars
]
ALL_LEVELS = ["PMH","PDH"] + [tf for tf,_,_ in PIVOT_TFS]


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
    """Previous day high — rolled forward to next trading day."""
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    dh=rth_df.groupby("date")["high"].max().reset_index()
    dh.columns=["date","pdh"]; dh=dh.sort_values("date")
    dh["next_date"]=dh["date"].shift(-1)
    result={}
    for _,row in dh.iterrows():
        if pd.notna(row["next_date"]):
            result[row["next_date"]]=row["pdh"]
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

def met(trades):
    if len(trades)<5: return None
    s=pd.DataFrame(trades); n=len(s)
    tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp=s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev=s["pnl"].mean()
    score=pf*np.log10(n) if n>0 else 0
    return dict(n=n,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev,score=score)

W=110

if __name__=="__main__":
    print("Scanning Phase 2 (8 levels x 22 symbols)...", flush=True)
    all_results={}

    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: all_results[sym]={}; continue
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

            # PMH
            ev=scan_fresh_1st(ddf, day["pm_high"])
            if ev:
                out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                trades["PMH"].append({"outcome":out,"pnl":pnl})

            # PDH
            pdh=pdh_map.get(date_ts)
            if pdh and not pd.isna(pdh):
                ev=scan_fresh_1st(ddf, pdh)
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    trades["PDH"].append({"outcome":out,"pnl":pnl})

            # Pivot TFs
            for tf,lb,wg in PIVOT_TFS:
                for level in pivots[tf].get(date_ts, pivots[tf].get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        trades[tf].append({"outcome":out,"pnl":pnl})

        all_results[sym]={lv: met(trades[lv]) for lv in ALL_LEVELS}

    print()

    # ── Helper ────────────────────────────────────────────────────────────────
    def pf_cell(mx, w=9):
        if mx is None or mx["n"]<5: return "--"
        pf=mx["pf"]
        mk=("<<<" if pf>=2.0 else "<<" if pf>=1.5 else "<" if pf>=1.2 else "-" if pf<1.0 else "")
        return f"{pf:.2f}{mk}"

    def score_cell(mx):
        if mx is None or mx["n"]<5: return "--"
        return f"{mx['score']:.2f}"

    # ── PF Matrix ─────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PHASE 2 — FULL 8-LEVEL MATRIX  |  22 symbols")
    print(f"  PF by symbol x level  (fresh 1st touch, short, gap up > 0.5%)")
    print(f"  <<< >=2.0 | << >=1.5 | < >=1.2 | - <1.0 | -- N<5")
    print(f"{'='*W}")

    cw=10
    hdr=(f"  {'Sym':<7}" + "".join(f"  {lv:^{cw}}" for lv in ALL_LEVELS)
         + f"  {'Best':^8}  {'Score':>6}")
    print(f"\n{hdr}")
    print(f"  {'-'*95}")

    sym_bests={}
    for sym in SYMS:
        r=all_results.get(sym,{})
        cells=[pf_cell(r.get(lv)) for lv in ALL_LEVELS]
        # find best by score
        best_lv=None; best_sc=-1; best_pf=-1
        for lv in ALL_LEVELS:
            mx=r.get(lv)
            if mx and mx["n"]>=8 and mx["score"]>best_sc:
                best_sc=mx["score"]; best_lv=lv; best_pf=mx["pf"]
        sym_bests[sym]=(best_lv,best_pf,best_sc)
        row=(f"  {sym:<7}" + "".join(f"  {c:^{cw}}" for c in cells)
             + f"  {str(best_lv):^8}  {best_sc:>6.2f}")
        print(row)

    # ── N Matrix ──────────────────────────────────────────────────────────────
    print(f"\n  N by cell:")
    print(f"  {'-'*80}")
    print(hdr[:hdr.index("  {'Best'")].rstrip() if "  {'Best'" in hdr else hdr)
    hdr_n=(f"  {'Sym':<7}" + "".join(f"  {lv:^{cw}}" for lv in ALL_LEVELS))
    print(hdr_n)
    for sym in SYMS:
        r=all_results.get(sym,{})
        cells=[str(r[lv]["n"]) if r.get(lv) else "--" for lv in ALL_LEVELS]
        print(f"  {sym:<7}" + "".join(f"  {c:^{cw}}" for c in cells))

    # ── EV Matrix ─────────────────────────────────────────────────────────────
    print(f"\n  EV/trade by cell:")
    print(f"  {'-'*80}")
    print(hdr_n)
    for sym in SYMS:
        r=all_results.get(sym,{})
        cells=[f"{r[lv]['ev']:>+.3f}%" if r.get(lv) else "--" for lv in ALL_LEVELS]
        print(f"  {sym:<7}" + "".join(f"  {c:^{cw}}" for c in cells))

    # ── Score Matrix (PF * log10(N)) ──────────────────────────────────────────
    print(f"\n  Score (PF x log10(N)) by cell:")
    print(f"  {'-'*80}")
    print(hdr_n)
    for sym in SYMS:
        r=all_results.get(sym,{})
        cells=[f"{r[lv]['score']:.2f}" if r.get(lv) else "--" for lv in ALL_LEVELS]
        print(f"  {sym:<7}" + "".join(f"  {c:^{cw}}" for c in cells))

    # ── Full detail per symbol — ranked levels ────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PER SYMBOL — LEVELS RANKED BY SCORE (PF x log10(N))")
    print(f"{'='*W}")
    SHDR=(f"  {'Level':<8} {'N':>5}  {'WR':>6}  {'TP/SL':>9}  "
          f"{'PF':>6}  {'EV':>9}  {'Score':>6}")
    SSEP=f"  {'-'*62}"

    for sym in SYMS:
        r=all_results.get(sym,{})
        best_lv,best_pf,best_sc=sym_bests.get(sym,(None,-1,-1))
        ranked=[(lv,r[lv]) for lv in ALL_LEVELS if r.get(lv) and r[lv]["n"]>=5]
        ranked.sort(key=lambda x:-x[1]["score"])
        print(f"\n  {sym}  (best: {best_lv}  PF {best_pf:.3f}  score {best_sc:.2f})")
        print(SHDR); print(SSEP)
        for lv,mx in ranked:
            mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
                "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
            star=" *" if lv==best_lv else ""
            print(f"  {lv:<8} {mx['n']:>5}  {mx['wr']:>5.1f}%  "
                  f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}{mk}  "
                  f"{mx['ev']:>+7.4f}%  {mx['score']:>6.2f}{star}")

    # ── Global level leaderboard (all symbols combined per level) ─────────────
    print(f"\n{'='*W}")
    print(f"  GLOBAL LEVEL LEADERBOARD  (all 22 symbols pooled per level)")
    print(f"{'='*W}")
    print(f"  {'Level':<8} {'N':>5}  {'WR':>6}  {'TP/SL':>9}  {'PF':>6}  {'EV':>9}  {'Score':>6}")
    print(f"  {'-'*62}")
    level_pool={lv:[] for lv in ALL_LEVELS}
    for sym in SYMS:
        r=all_results.get(sym,{})
        for lv in ALL_LEVELS:
            if r.get(lv):
                # re-expand from summary — approximate via tp/sl/to counts
                mx=r[lv]
                tp_cnt=mx["tp"]; sl_cnt=mx["sl"]; to_cnt=mx["n"]-tp_cnt-sl_cnt
                level_pool[lv]+=[{"outcome":"TP","pnl":TP_PCT*100}]*tp_cnt
                level_pool[lv]+=[{"outcome":"SL","pnl":-SL_PCT*100}]*sl_cnt
                level_pool[lv]+=[{"outcome":"TO","pnl":0.0}]*to_cnt
    lv_rows=[]
    for lv in ALL_LEVELS:
        mx=met(level_pool[lv])
        if mx: lv_rows.append((lv,mx))
    lv_rows.sort(key=lambda x:-x[1]["score"])
    for lv,mx in lv_rows:
        mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
            "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
        print(f"  {lv:<8} {mx['n']:>5}  {mx['wr']:>5.1f}%  "
              f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}{mk}  "
              f"{mx['ev']:>+7.4f}%  {mx['score']:>6.2f}")

    # ── Optimal routing table ─────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  OPTIMAL ROUTING TABLE  (best level per symbol by score, N>=8)")
    print(f"{'='*W}")
    print(f"  {'Sym':<7}  {'Best':^8}  {'PF':>6}  {'N':>5}  {'WR':>6}  "
          f"{'EV':>9}  {'Score':>6}  {'G routing':^10}  {'Change?'}")
    print(f"  {'-'*82}")

    # Version G routing for comparison
    VG={
        "UPST":"PMH","APP":"PMH","SMCI":"PMH","CRM":"PMH","HIMS":"PMH","ARM":"PMH","RIOT":"PMH",
        "HOOD":"10m","TSLA":"10m","CLSK":"10m","GOOGL":"10m",
        "ADBE":"30m","PANW":"30m","MU":"30m","AMD":"30m","COIN":"30m","NVDA":"30m",
        "META":"1H","AFRM":"2H","MRVL":"2H","AVGO":"2H","PLTR":"4H",
    }

    for sym in SYMS:
        r=all_results.get(sym,{})
        best_lv,best_pf,best_sc=sym_bests.get(sym,(None,-1,-1))
        if best_lv is None: continue
        mx=r[best_lv]
        mk=(" <<<" if best_pf>=2.0 else "  <<" if best_pf>=1.5 else
            "   <" if best_pf>=1.2 else "   -" if best_pf<1.0 else "    ")
        g_route=VG.get(sym,"?")
        changed=" ** NEW **" if best_lv!=g_route else ""
        print(f"  {sym:<7}  {best_lv:^8}  {best_pf:>6.3f}{mk}  {mx['n']:>5}  "
              f"{mx['wr']:>5.1f}%  {mx['ev']:>+8.4f}%  {best_sc:>6.2f}  "
              f"{g_route:^10}  {changed}")
