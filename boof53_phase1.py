"""
BOOF53 Phase 1 — Level assignment test
7 top symbols x 5 pivot timeframes (10m, 30m, 1H, 2H, 4H)
Find which timeframe each symbol is best suited to.
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

SYMS = ["UPST","APP","SMCI","MU","TSLA","PANW","NVDA"]

# Timeframe configs: (label, lookback_bars, wing_bars)
TIMEFRAMES = [
    ("10m",  10, 2),
    ("30m",  30, 3),
    ("1H",   60, 3),
    ("2H",  120, 4),
    ("4H",  240, 5),
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

W = 92

if __name__=="__main__":
    print("Scanning Phase 1...", flush=True)

    # results[sym][tf_label] = list of trade dicts
    all_results = {}

    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue

        # Build all pivot sets upfront
        pivots = {}
        for tf_label, lookback, wing in TIMEFRAMES:
            pivots[tf_label] = build_pivots(rth_df, lookback, wing)

        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        sym_results = {tf: [] for tf,_,_ in TIMEFRAMES}

        for date, ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()

            for tf_label, lookback, wing in TIMEFRAMES:
                levels = pivots[tf_label].get(date_ts, pivots[tf_label].get(dk,[]))
                for level in levels:
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf, level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        sym_results[tf_label].append({"outcome":out,"pnl":pnl})

        all_results[sym] = sym_results

    print()

    # ── Per-symbol level matrix ────────────────────────────────────────────────
    tf_labels = [tf for tf,_,_ in TIMEFRAMES]

    print(f"\n{'='*W}")
    print(f"  PHASE 1 — LEVEL ASSIGNMENT MATRIX")
    print(f"  PF by symbol x timeframe  (fresh 1st touch, short, gap up > 0.5%)")
    print(f"  '--' = N<5")
    print(f"{'='*W}")

    col=10
    header = f"  {'Sym':<6}" + "".join(f"  {tf:^{col}}" for tf in tf_labels)
    print(f"\n{header}")
    print(f"  {'-'*60}")

    assignments = {}  # sym -> best tf

    for sym in SYMS:
        r = all_results.get(sym, {})
        row = f"  {sym:<6}"
        best_pf=-1; best_tf=None
        for tf in tf_labels:
            mx=met(r.get(tf,[]))
            if mx and mx["n"]>=5:
                mk=("<<<" if mx["pf"]>=2.0 else "<<" if mx["pf"]>=1.5 else
                    "<" if mx["pf"]>=1.2 else "-" if mx["pf"]<1.0 else "")
                cell=f"{mx['pf']:.2f}{mk}"
                if mx["pf"]>best_pf and mx["n"]>=8:
                    best_pf=mx["pf"]; best_tf=tf
            else:
                cell="--"
            row += f"  {cell:^{col}}"
        assignments[sym] = (best_tf, best_pf)
        row += f"  => {best_tf}" if best_tf else "  => N/A"
        print(row)

    # N table
    print(f"\n  N by cell:")
    print(f"  {'-'*60}")
    header2 = f"  {'Sym':<6}" + "".join(f"  {tf:^{col}}" for tf in tf_labels)
    print(header2)
    for sym in SYMS:
        r = all_results.get(sym, {})
        row = f"  {sym:<6}"
        for tf in tf_labels:
            mx=met(r.get(tf,[]))
            n_str=f"{mx['n']}" if mx else "--"
            row += f"  {n_str:^{col}}"
        print(row)

    # EV table
    print(f"\n  EV/trade by cell:")
    print(f"  {'-'*60}")
    print(header2)
    for sym in SYMS:
        r = all_results.get(sym, {})
        row = f"  {sym:<6}"
        for tf in tf_labels:
            mx=met(r.get(tf,[]))
            ev_str=f"{mx['ev']:+.3f}%" if mx else "--"
            row += f"  {ev_str:^{col}}"
        print(row)

    # WR table
    print(f"\n  WR by cell:")
    print(f"  {'-'*60}")
    print(header2)
    for sym in SYMS:
        r = all_results.get(sym, {})
        row = f"  {sym:<6}"
        for tf in tf_labels:
            mx=met(r.get(tf,[]))
            wr_str=f"{mx['wr']:.1f}%" if mx else "--"
            row += f"  {wr_str:^{col}}"
        print(row)

    # ── Full detail per symbol ────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  FULL DETAIL PER SYMBOL")
    print(f"{'='*W}")
    HDR=(f"  {'Label':<18} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
         f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
    SEP=f"  {'-'*74}"

    for sym in SYMS:
        r = all_results.get(sym, {})
        best_tf, best_pf = assignments.get(sym, (None,-1))
        print(f"\n  {sym}  (best level: {best_tf}  PF {best_pf:.3f})")
        print(HDR); print(SEP)
        for tf in tf_labels:
            mx=met(r.get(tf,[]))
            if mx is None:
                print(f"  {tf:<18} (n<5)")
                continue
            mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
                "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
            star=" *" if tf==best_tf else ""
            print(f"  {tf:<18} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
                  f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
                  f"{mx['maxdd']:>+7.2f}%{mk}{star}")

    # ── Assignment summary ────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  LEVEL ASSIGNMENT SUMMARY")
    print(f"{'='*W}")
    print(f"\n  {'Symbol':<8}  {'Best TF':<8}  {'PF':>6}  {'Note'}")
    print(f"  {'-'*50}")
    for sym in SYMS:
        r = all_results.get(sym, {})
        best_tf, best_pf = assignments.get(sym, (None,-1))
        # find 2nd best
        ranked=[(tf, met(r.get(tf,[]))) for tf in tf_labels]
        ranked=[(tf,mx) for tf,mx in ranked if mx and mx["n"]>=8]
        ranked.sort(key=lambda x:-x[1]["pf"])
        note=""
        if len(ranked)>=2:
            second_tf,second_mx=ranked[1]
            note=f"2nd: {second_tf} PF {second_mx['pf']:.2f}"
        mk=(" <<<" if best_pf>=2.0 else " <<" if best_pf>=1.5 else
            "  <" if best_pf>=1.2 else "  -" if best_pf<1.0 else "   ")
        print(f"  {sym:<8}  {str(best_tf):<8}  {best_pf:>6.3f}{mk}  {note}")

    # ── PMH vs best pivot comparison ─────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PMH vs BEST PIVOT  (fresh 1st touch)")
    print(f"{'='*W}")
    print(f"  {'Symbol':<8}  {'PMH PF':>8}  {'Best pivot':>12}  {'Pivot PF':>9}  {'Winner'}")
    print(f"  {'-'*55}")

    pmh_results = {}
    for sym in SYMS:
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue
        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        trades=[]
        for date, ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True)
            ev=scan_fresh_1st(ddf, day["pm_high"])
            if ev:
                out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                trades.append({"outcome":out,"pnl":pnl})
        pmh_results[sym] = met(trades)

    for sym in SYMS:
        pmh_mx = pmh_results.get(sym)
        best_tf, best_pf = assignments.get(sym,(None,-1))
        pmh_pf = pmh_mx["pf"] if pmh_mx else 0
        pmh_str= f"{pmh_pf:.3f}" if pmh_mx else "--"
        piv_str= f"{best_pf:.3f}" if best_pf>0 else "--"
        if pmh_mx and best_pf>0:
            winner="PMH" if pmh_pf>=best_pf else f"{best_tf}"
            delta=abs(pmh_pf-best_pf)
            winner_str=f"{winner}  (delta {delta:.3f})"
        else:
            winner_str="--"
        print(f"  {sym:<8}  {pmh_str:>8}  {str(best_tf):>12}  {piv_str:>9}  {winner_str}")
