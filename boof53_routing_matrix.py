"""
BOOF53 Routing Matrix
All 22 F+ symbols x PMH + 5 pivot timeframes
Build full table: Symbol | PMH PF | 10m PF | 30m PF | 1H PF | 2H PF | 4H PF | Trades(best)
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
    "UPST","APP","SMCI","CRM","HIMS","ARM","HOOD","RIOT",
    "ADBE","PANW","MU","TSLA","AMD","CLSK","COIN","GOOGL",
    "NVDA","PLTR","META","AFRM","MRVL","AVGO",
]

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
    ev=s["pnl"].mean()
    return dict(n=n,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev)


if __name__=="__main__":
    print("Scanning routing matrix...", flush=True)

    rows = []

    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None:
            rows.append({"sym": sym}); continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty:
            rows.append({"sym": sym}); continue

        pivots = {tf: build_pivots(rth_df, lb, wing) for tf,lb,wing in TIMEFRAMES}
        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        pmh_t = []
        tf_trades = {tf: [] for tf,_,_ in TIMEFRAMES}

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
                pmh_t.append({"outcome":out,"pnl":pnl})

            # Pivots
            for tf,lb,wing in TIMEFRAMES:
                for level in pivots[tf].get(date_ts, pivots[tf].get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        tf_trades[tf].append({"outcome":out,"pnl":pnl})

        row = {"sym": sym}
        row["pmh_mx"]  = met(pmh_t)
        for tf,_,_ in TIMEFRAMES:
            row[f"{tf}_mx"] = met(tf_trades[tf])
        rows.append(row)

    print()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def pf_cell(mx, n_min=5):
        if mx is None or mx["n"]<n_min: return "--"
        pf=mx["pf"]
        mk=("<<<" if pf>=2.0 else "<<" if pf>=1.5 else "<" if pf>=1.2 else "-" if pf<1.0 else "")
        return f"{pf:.2f}{mk}"

    def best_col(row):
        candidates={"PMH":row.get("pmh_mx")}
        for tf,_,_ in TIMEFRAMES:
            candidates[tf]=row.get(f"{tf}_mx")
        best_pf=-1; best_k=None; best_n=0
        for k,mx in candidates.items():
            if mx and mx["n"]>=8 and mx["pf"]>best_pf:
                best_pf=mx["pf"]; best_k=k; best_n=mx["n"]
        return best_k, best_pf, best_n

    tf_labels = [tf for tf,_,_ in TIMEFRAMES]

    # ── Main table ────────────────────────────────────────────────────────────
    W=100
    print(f"\n{'='*W}")
    print(f"  BOOF53 ROUTING MATRIX  |  22 symbols x PMH + 5 pivot timeframes")
    print(f"  Fresh 1st touch | SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25%")
    print(f"  Format: PF  (<<< >=2.0 | << >=1.5 | < >=1.2 | - <1.0 | -- N<5)")
    print(f"{'='*W}")

    col=10
    hdr=(f"\n  {'Symbol':<7}  {'PMH':^{col}}  "
         + "  ".join(f"{tf:^{col}}" for tf in tf_labels)
         + f"  {'Best':^8}  {'N(best)':>7}  {'EV(best)':>9}")
    print(hdr)
    print(f"  {'-'*90}")

    for row in rows:
        sym=row["sym"]
        pmh_s  = pf_cell(row.get("pmh_mx"))
        tf_strs= [pf_cell(row.get(f"{tf}_mx")) for tf in tf_labels]
        best_k, best_pf, best_n = best_col(row)
        best_mx = row.get("pmh_mx") if best_k=="PMH" else row.get(f"{best_k}_mx") if best_k else None
        best_ev = f"{best_mx['ev']:>+.3f}%" if best_mx else "--"
        best_str= f"{best_k}" if best_k else "--"
        print(f"  {sym:<7}  {pmh_s:^{col}}  "
              + "  ".join(f"{s:^{col}}" for s in tf_strs)
              + f"  {best_str:^8}  {best_n:>7}  {best_ev:>9}")

    # ── N table ───────────────────────────────────────────────────────────────
    print(f"\n  N by cell (number of trades):")
    print(f"  {'-'*70}")
    hdr2=(f"  {'Symbol':<7}  {'PMH':^{col}}  "
          + "  ".join(f"{tf:^{col}}" for tf in tf_labels))
    print(hdr2)
    for row in rows:
        sym=row["sym"]
        pmh_n = str(row["pmh_mx"]["n"]) if row.get("pmh_mx") else "--"
        tf_ns = [str(row[f"{tf}_mx"]["n"]) if row.get(f"{tf}_mx") else "--" for tf in tf_labels]
        print(f"  {sym:<7}  {pmh_n:^{col}}  "
              + "  ".join(f"{n:^{col}}" for n in tf_ns))

    # ── EV table ─────────────────────────────────────────────────────────────
    print(f"\n  EV/trade by cell:")
    print(f"  {'-'*70}")
    print(hdr2)
    for row in rows:
        sym=row["sym"]
        def ev_str(mx): return f"{mx['ev']:>+.3f}%" if mx else "--"
        pmh_ev=ev_str(row.get("pmh_mx"))
        tf_evs=[ev_str(row.get(f"{tf}_mx")) for tf in tf_labels]
        print(f"  {sym:<7}  {pmh_ev:^{col}}  "
              + "  ".join(f"{e:^{col}}" for e in tf_evs))

    # ── Assignment summary ────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  OPTIMAL ROUTING  (best PF per symbol, N>=8)")
    print(f"{'='*W}")
    print(f"\n  {'Sym':<7}  {'Best':^6}  {'PF':>6}  {'N':>5}  {'WR':>6}  {'EV':>9}  "
          f"  {'PMH':^8}  {'10m':^8}  {'30m':^8}  {'1H':^8}  {'2H':^8}  {'4H':^8}")
    print(f"  {'-'*95}")

    for row in rows:
        sym=row["sym"]
        best_k,best_pf,best_n=best_col(row)
        best_mx=(row.get("pmh_mx") if best_k=="PMH"
                 else row.get(f"{best_k}_mx") if best_k else None)
        if best_mx is None: continue
        mk=(" <<<" if best_pf>=2.0 else "  <<" if best_pf>=1.5 else
            "   <" if best_pf>=1.2 else "   -" if best_pf<1.0 else "    ")
        star=lambda k: "*" if k==best_k else ""
        pmh_s =f"{row['pmh_mx']['pf']:.2f}{star('PMH')}" if row.get("pmh_mx") else "--"
        m10_s =f"{row['10m_mx']['pf']:.2f}{star('10m')}" if row.get("10m_mx") else "--"
        m30_s =f"{row['30m_mx']['pf']:.2f}{star('30m')}" if row.get("30m_mx") else "--"
        h1_s  =f"{row['1H_mx']['pf']:.2f}{star('1H')}" if row.get("1H_mx") else "--"
        h2_s  =f"{row['2H_mx']['pf']:.2f}{star('2H')}" if row.get("2H_mx") else "--"
        h4_s  =f"{row['4H_mx']['pf']:.2f}{star('4H')}" if row.get("4H_mx") else "--"
        print(f"  {sym:<7}  {best_k:^6}  {best_pf:>6.3f}{mk}  {best_n:>5}  "
              f"{best_mx['wr']:>5.1f}%  {best_mx['ev']:>+8.4f}%  "
              f"  {pmh_s:^8}  {m10_s:^8}  {m30_s:^8}  {h1_s:^8}  {h2_s:^8}  {h4_s:^8}")

    # ── PMH vs pivot split ────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PMH SYMBOLS vs PIVOT SYMBOLS  (clear split)")
    print(f"{'='*W}")
    pmh_wins=[]; pivot_wins=[]
    for row in rows:
        sym=row["sym"]; best_k,best_pf,_=best_col(row)
        if best_k=="PMH": pmh_wins.append(sym)
        elif best_k: pivot_wins.append(f"{sym}({best_k})")
    print(f"\n  PMH  wins ({len(pmh_wins)}): {', '.join(pmh_wins)}")
    print(f"  Pivot wins ({len(pivot_wins)}): {', '.join(pivot_wins)}")
