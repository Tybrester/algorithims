"""
BOOF53 Version E — Universe Expansion
Run all 3 setups on all available symbols, rank by PF, pick top 10-30.
Setups tested per symbol:
  A) PMH fresh 1st touch (short)
  B) 30m fresh 1st touch (short)
  C) 1H/2H overlap fresh 1st touch (short)
Then show per-symbol best-setup and composite rankings.
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | min N>=10
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

ALL_SYMS = ["AAPL","ADBE","AMD","AMZN","APP","ARM","AVGO","COIN","COST","CRM",
            "GOOGL","HIMS","HOOD","IWM","JPM","LLY","META","MSFT","MU","NFLX",
            "NVDA","ORCL","PLTR","QQQ","RKLB","SMCI","SPY","TEM","TSLA","UNH","WMT"]


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

def metrics(trades):
    s = pd.DataFrame(trades)
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

def run_sym(sym):
    rth_df, pm_df = load_sym(sym)
    if rth_df is None or rth_df.empty: return {}
    pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
    if pm_stats.empty: return {}
    piv_30m = build_pivots(rth_df, 30,  3)
    piv_1h  = build_pivots(rth_df, 60,  3)
    piv_2h  = build_pivots(rth_df, 120, 4)
    rth_df  = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

    pmh_trades=[]; m30_trades=[]; ov_trades=[]

    for date, ddf in rth_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm_stats.index: continue
        day = pm_stats.loc[date_ts]
        if day["gap_pct"] <= 0.5: continue
        ddf = ddf.reset_index(drop=True)
        dk  = date_ts.date()

        # Setup A: PMH fresh 1st
        pmh = day["pm_high"]
        ev = scan_fresh_1st(ddf, pmh)
        if ev:
            out, pnl = race(ddf, ev["bar_i"], ev["ep"])
            pmh_trades.append({"outcome":out,"pnl":pnl})

        # Setup B: 30m fresh 1st
        for level in piv_30m.get(date_ts, piv_30m.get(dk,[])):
            if pd.isna(level): continue
            ev = scan_fresh_1st(ddf, level)
            if ev:
                out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                m30_trades.append({"outcome":out,"pnl":pnl})

        # Setup C: 1H+2H overlap fresh 1st
        res_1h = piv_1h.get(date_ts, piv_1h.get(dk,[]))
        res_2h = piv_2h.get(date_ts, piv_2h.get(dk,[]))
        for level in res_1h:
            if pd.isna(level): continue
            if any(abs(lv2-level)/level<=STACK_PCT for lv2 in res_2h):
                ev = scan_fresh_1st(ddf, level)
                if ev:
                    out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                    ov_trades.append({"outcome":out,"pnl":pnl})

    return {
        "PMH":     metrics(pmh_trades),
        "30m":     metrics(m30_trades),
        "1H2H_ov": metrics(ov_trades),
        "ALL":     metrics(pmh_trades + m30_trades + ov_trades),
    }


HDR = (f"  {'Symbol':<7} {'Setup':<12} {'N':>5} {'T/Wk':>6}  "
       f"{'WR':>6}  {'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP = f"  {'-'*82}"
W   = 86

def prow(sym, setup, mx, w=7):
    if mx is None: return
    mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
        "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
    print(f"  {sym:<{w}} {setup:<12} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%{mk}")


if __name__ == "__main__":
    print("Scanning all symbols...", flush=True)
    results = {}
    for sym in ALL_SYMS:
        print(f"  {sym}", end=" ", flush=True)
        results[sym] = run_sym(sym)
    print()

    # ── Rank by PMH PF ────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  SETUP A: PMH Fresh 1st Touch  |  All 31 symbols ranked by PF  (N>=10)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    pmh_ranked = [(sym, results[sym].get("PMH")) for sym in ALL_SYMS
                  if results[sym].get("PMH") and results[sym]["PMH"]["n"]>=10]
    pmh_ranked.sort(key=lambda x: -x[1]["pf"])
    for sym, mx in pmh_ranked:
        prow(sym, "PMH", mx)

    # ── Rank by 30m PF ────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  SETUP B: 30m Fresh 1st Touch  |  All symbols ranked by PF  (N>=10)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    m30_ranked = [(sym, results[sym].get("30m")) for sym in ALL_SYMS
                  if results[sym].get("30m") and results[sym]["30m"]["n"]>=10]
    m30_ranked.sort(key=lambda x: -x[1]["pf"])
    for sym, mx in m30_ranked:
        prow(sym, "30m", mx)

    # ── Rank by 1H+2H overlap PF ──────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  SETUP C: 1H/2H Overlap Fresh 1st  |  All symbols ranked by PF  (N>=10)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    ov_ranked = [(sym, results[sym].get("1H2H_ov")) for sym in ALL_SYMS
                 if results[sym].get("1H2H_ov") and results[sym]["1H2H_ov"]["n"]>=10]
    ov_ranked.sort(key=lambda x: -x[1]["pf"])
    for sym, mx in ov_ranked:
        prow(sym, "1H2H_ov", mx)

    # ── Best setup per symbol ─────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BEST SETUP PER SYMBOL  (highest PF with N>=10)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    best_rows = []
    for sym in ALL_SYMS:
        r = results[sym]
        best_pf = -1; best_setup = None; best_mx = None
        for setup in ["PMH","30m","1H2H_ov"]:
            mx = r.get(setup)
            if mx and mx["n"]>=10 and mx["pf"]>best_pf:
                best_pf=mx["pf"]; best_setup=setup; best_mx=mx
        if best_mx:
            best_rows.append((sym, best_setup, best_mx))
    best_rows.sort(key=lambda x: -x[2]["pf"])
    for sym, setup, mx in best_rows:
        prow(sym, setup, mx)

    # ── ALL-setups composite per symbol (like Version E logic applied everywhere)
    print(f"\n{'='*W}")
    print(f"  COMPOSITE: All 3 setups combined per symbol  (N>=15)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    all_rows = []
    for sym in ALL_SYMS:
        mx = results[sym].get("ALL")
        if mx and mx["n"]>=15:
            all_rows.append((sym, mx))
    all_rows.sort(key=lambda x: -x[1]["pf"])
    for sym, mx in all_rows:
        prow(sym, "composite", mx)

    # ── TOP 10 recommendation ─────────────────────────────────────────────────
    # Score = PF * log(N) — balances quality and sample size
    print(f"\n{'='*W}")
    print(f"  TOP SYMBOL RANKINGS  (score = PF x log10(N), all 3 setups, N>=15)")
    print(f"{'='*W}")
    print(f"  {'Rank':<5} {'Symbol':<7} {'Best Setup':<12} {'N':>5} {'T/Wk':>6}  "
          f"{'WR':>6}  {'PF':>6}  {'EV':>9}  {'MaxDD':>7}  {'Score':>6}")
    print(f"  {'-'*82}")
    scored = []
    for sym in ALL_SYMS:
        r = results[sym]
        best_pf=-1; best_setup=None; best_mx=None
        for setup in ["PMH","30m","1H2H_ov"]:
            mx=r.get(setup)
            if mx and mx["n"]>=10 and mx["pf"]>best_pf:
                best_pf=mx["pf"]; best_setup=setup; best_mx=mx
        if best_mx and best_mx["n"]>=15:
            score = best_mx["pf"] * np.log10(best_mx["n"])
            scored.append((sym, best_setup, best_mx, score))
    scored.sort(key=lambda x:-x[3])
    for rank,(sym,setup,mx,score) in enumerate(scored,1):
        mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
            "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
        print(f"  {rank:<5} {sym:<7} {setup:<12} {mx['n']:>5} {mx['tpw']:>6.1f}  "
              f"{mx['wr']:>5.1f}%  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
              f"{mx['maxdd']:>+7.2f}%  {score:>6.3f}{mk}")

    # ── Recommended universe ──────────────────────────────────────────────────
    top_syms = [x[0] for x in scored[:15]]
    print(f"\n  Recommended top-15 universe: {top_syms}")
    print(f"  Recommended top-10 universe: {[x[0] for x in scored[:10]]}")

    # ── How does each top symbol assign to which setup? ───────────────────────
    print(f"\n{'='*W}")
    print(f"  SYMBOL ROUTING TABLE  (top 15 symbols, best setup per symbol)")
    print(f"{'='*W}")
    print(f"  {'Symbol':<7}  {'PMH PF':>8}  {'30m PF':>8}  {'1H2H PF':>9}  {'Best':>10}  {'N best':>6}")
    print(f"  {'-'*60}")
    for sym,setup,mx,score in scored[:15]:
        def pf_str(s):
            m=results[sym].get(s)
            return f"{m['pf']:.3f}" if m and m["n"]>=10 else "--"
        print(f"  {sym:<7}  {pf_str('PMH'):>8}  {pf_str('30m'):>8}  {pf_str('1H2H_ov'):>9}  "
              f"{setup:>10}  {mx['n']:>6}")
