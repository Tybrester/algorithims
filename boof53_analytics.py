"""
BOOF53 Version H — Full Analytics Suite
1. Monthly breakdown (2022 + 2025-26 combined)
2. Walk-forward test (train on 2022, validate on 2025-26)
3. Monte Carlo simulation (10,000 runs)
4. Rolling 50/100-trade PF
5. Options simulation (buy puts on entry signal)

Uses: boof53_{sym}_1m_2022.csv + boof51_{sym}_1m.csv (recent 6m)
"""
import pandas as pd
import numpy as np
import pytz
import os
import random

ET        = pytz.timezone("America/New_York")
OVERLAP   = 0.0020
BOUNCE    = 0.0015
NEAR_PCT  = 0.0015
TP_PCT    = 0.0050
SL_PCT    = 0.0025
MAX_BARS  = 60

ROUTING = {
    "UPST":  ("PMH", None, None),
    "APP":   ("PMH", None, None),
    "SMCI":  ("PMH", None, None),
    "HIMS":  ("PMH", None, None),
    "GOOGL": ("PMH", None, None),
    "META":  ("PDH", None, None),
    "AFRM":  ("PDH", None, None),
    "TSLA":  ("PIV", 10,   2),
    "CLSK":  ("PIV", 10,   2),
    "HOOD":  ("PIV", 10,   2),
    "ADBE":  ("PIV", 30,   3),
    "PANW":  ("PIV", 30,   3),
    "MU":    ("PIV", 30,   3),
    "AMD":   ("PIV", 30,   3),
    "COIN":  ("PIV", 30,   3),
    "NVDA":  ("PIV", 30,   3),
    "MRVL":  ("PIV", 120,  4),
    "AVGO":  ("PIV", 120,  4),
    "PLTR":  ("PIV", 240,  5),
    "CRM":   ("PIV", 390,  5),
}

# ── Core scan functions ───────────────────────────────────────────────────────

def load_sym(sym, suffix):
    path = f"boof53_{sym}_1m_{suffix}.csv" if suffix != "6m" else f"boof51_{sym}_1m.csv"
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
        if ddf.iloc[i]["high"]>=sl_p: return "SL", -SL_PCT*100, ep
        if ddf.iloc[i]["low"] <=tp_p: return "TP",  TP_PCT*100, ep
    return "TO", 0.0, ep

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

def scan_dataset(suffix):
    records=[]
    for sym,(rtype,lb,wing) in ROUTING.items():
        rth_df,pm_df=load_sym(sym,suffix)
        if rth_df is None: continue
        pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue
        pdh_map=build_pdh(rth_df) if rtype=="PDH" else {}
        pivots=build_pivots(rth_df,lb,wing) if rtype=="PIV" else {}
        rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        tf_label=("PMH" if rtype=="PMH" else "PDH" if rtype=="PDH"
                  else f"{lb}m" if lb and lb<60 else f"{lb//60}H" if lb and lb<390 else "Daily")
        for date,ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()
            if rtype=="PMH":
                ev=scan_fresh_1st(ddf,day["pm_high"])
                if ev:
                    out,pnl,ep=race(ddf,ev["bar_i"],ev["ep"])
                    records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                    "pnl":pnl,"ep":ep,"date":date_ts,"period":suffix})
            elif rtype=="PDH":
                level=pdh_map.get(date_ts)
                if level and not pd.isna(level):
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl,ep=race(ddf,ev["bar_i"],ev["ep"])
                        records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                        "pnl":pnl,"ep":ep,"date":date_ts,"period":suffix})
            else:
                for level in pivots.get(date_ts,pivots.get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl,ep=race(ddf,ev["bar_i"],ev["ep"])
                        records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                        "pnl":pnl,"ep":ep,"date":date_ts,"period":suffix})
    return records

W=92

if __name__=="__main__":
    print("Loading 2022 data...", flush=True)
    r2022=scan_dataset("2022")
    print("Loading 2025-26 data...", flush=True)
    r6m=scan_dataset("6m")

    df22=pd.DataFrame(r2022); df22["month"]=df22["date"].dt.to_period("M")
    df6m=pd.DataFrame(r6m);   df6m["month"]=df6m["date"].dt.to_period("M")
    df_all=pd.concat([df22,df6m],ignore_index=True).sort_values("date").reset_index(drop=True)
    df_all["month"]=df_all["date"].dt.to_period("M")

    wk22=(df22["date"].max()-df22["date"].min()).days/7
    wk6m=(df6m["date"].max()-df6m["date"].min()).days/7
    wk_all=(df_all["date"].max()-df_all["date"].min()).days/7

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. MONTHLY BREAKDOWN — COMBINED
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  1. MONTHLY BREAKDOWN — 2022 + 2025-26 COMBINED")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'PF':>6}  {'Mo PnL':>8}  {'Cumul':>9}  {'Period'}")
    print(f"  {'-'*65}")
    cumul=0.0; mo_pnls=[]; mo_list=[]
    for mo in sorted(df_all["month"].unique()):
        s=df_all[df_all["month"]==mo]; n=len(s)
        tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
        wr=tp/n*100 if n>0 else 0
        pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        mo_pnl=s["pnl"].sum(); cumul+=mo_pnl; mo_pnls.append(mo_pnl)
        flag="v" if mo_pnl>=0 else "x"
        period="2022" if str(mo).startswith("2022") else "2025-26"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {pf:>6.3f}  "
              f"{mo_pnl:>+7.3f}%  {cumul:>+8.3f}%  {flag}  {period}")
        mo_list.append((str(mo),mo_pnl,period))
    print(f"  {'-'*65}")
    wins=sum(1 for p in mo_pnls if p>0); total=len(mo_pnls)
    print(f"  {'TOTAL':<10} {len(df_all):>4}  {df_all['outcome'].eq('TP').sum()/len(df_all)*100:>5.1f}%"
          f"         {df_all['pnl'].sum():>+7.3f}%  {cumul:>+8.3f}%")
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    wins22=sum(1 for mo,p,per in mo_list if per=="2022" and p>0)
    tot22=sum(1 for mo,p,per in mo_list if per=="2022")
    wins6m=sum(1 for mo,p,per in mo_list if per=="2025-26" and p>0)
    tot6m=sum(1 for mo,p,per in mo_list if per=="2025-26")
    print(f"  2022:    {wins22}/{tot22}  ({wins22/tot22*100:.0f}%)")
    print(f"  2025-26: {wins6m}/{tot6m}  ({wins6m/tot6m*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. WALK-FORWARD TEST
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  2. WALK-FORWARD TEST")
    print(f"  Train: 2022 (in-sample)  |  Validate: 2025-26 (out-of-sample)")
    print(f"{'='*W}")

    def mets(df, weeks):
        if len(df)<5: return None
        n=len(df); tp=df["outcome"].eq("TP").sum(); sl=df["outcome"].eq("SL").sum()
        wr=tp/n*100
        g_tp=df[df["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
        g_sl=abs(df[df["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
        pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
        ev=df["pnl"].mean(); tpw=n/weeks
        cum=np.cumsum(df["pnl"].values); peak=np.maximum.accumulate(cum)
        maxdd=(cum-peak).min()
        return dict(n=n,tpw=tpw,wr=wr,pf=pf,ev=ev,maxdd=maxdd,cumul=df["pnl"].sum())

    def prow_wf(label, mx, w=30):
        if mx is None: print(f"  {label:<{w}} (n<5)"); return
        mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
            "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
        print(f"  {label:<{w}} N={mx['n']:>4}  T/Wk={mx['tpw']:>5.1f}  "
              f"WR={mx['wr']:>5.1f}%  PF={mx['pf']:>6.3f}{mk}  "
              f"EV={mx['ev']:>+6.4f}%  MaxDD={mx['maxdd']:>+6.2f}%  "
              f"Cumul={mx['cumul']:>+7.3f}%")

    m22=mets(df22,wk22); m6m=mets(df6m,wk6m)
    print(f"\n  {'Period':<30} {'N':>5}  {'T/Wk':>5}  {'WR':>6}  {'PF':>8}  "
          f"{'EV':>8}  {'MaxDD':>7}  {'Cumul':>8}")
    print(f"  {'-'*80}")
    prow_wf("TRAIN    2022 (in-sample)", m22)
    prow_wf("VALIDATE 2025-26 (OOS)",   m6m)
    print(f"\n  Walk-forward verdict:")
    if m22 and m6m:
        pf_drift=m6m["pf"]-m22["pf"]
        ev_drift=m6m["ev"]-m22["ev"]
        verdict=("STRONG PASS" if m6m["pf"]>=1.5 and m22["pf"]>=1.0
                 else "PASS" if m6m["pf"]>=1.2
                 else "MARGINAL" if m6m["pf"]>=1.0
                 else "FAIL")
        print(f"  PF drift:  {m22['pf']:.3f} -> {m6m['pf']:.3f}  ({pf_drift:>+.3f})")
        print(f"  EV drift:  {m22['ev']:>+.4f}% -> {m6m['ev']:>+.4f}%  ({ev_drift:>+.4f}%)")
        print(f"  WR drift:  {m22['wr']:.1f}% -> {m6m['wr']:.1f}%  ({m6m['wr']-m22['wr']:>+.1f}%)")
        print(f"  Verdict:   {verdict}")

    # per-symbol walk-forward
    print(f"\n  Per-symbol walk-forward (PF: train -> OOS):")
    print(f"  {'Sym':<8} {'Level':<6}  {'Train PF':>10}  {'OOS PF':>10}  {'Drift':>8}  {'OOS Verdict'}")
    print(f"  {'-'*62}")
    for sym,(rtype,lb,wing) in ROUTING.items():
        s22=df22[df22["sym"]==sym]; s6=df6m[df6m["sym"]==sym]
        m_tr=mets(s22,wk22); m_oos=mets(s6,wk6m)
        if m_tr is None or m_oos is None: continue
        drift=m_oos["pf"]-m_tr["pf"]
        verdict=("PASS" if m_oos["pf"]>=1.2 else "MARGINAL" if m_oos["pf"]>=1.0 else "FAIL")
        tf=(rtype if rtype in ("PMH","PDH")
            else f"{lb}m" if lb and lb<60 else f"{lb//60}H" if lb and lb<390 else "Daily")
        mk=(" <<<" if m_oos["pf"]>=2.0 else "  <<" if m_oos["pf"]>=1.5 else
            "   <" if m_oos["pf"]>=1.2 else "   -" if m_oos["pf"]<1.0 else "    ")
        print(f"  {sym:<8} {tf:<6}  {m_tr['pf']:>10.3f}  {m_oos['pf']:>10.3f}{mk}  "
              f"{drift:>+8.3f}  {verdict}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. MONTE CARLO SIMULATION
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  3. MONTE CARLO SIMULATION  (10,000 runs, resample with replacement)")
    print(f"{'='*W}")

    pnl_all=df_all["pnl"].values
    N_SIMS=10000; N_TRADES=len(pnl_all)
    np.random.seed(42)

    sim_pfs=[]; sim_cums=[]; sim_maxdds=[]; sim_wrs=[]
    for _ in range(N_SIMS):
        sample=np.random.choice(pnl_all, size=N_TRADES, replace=True)
        tp_cnt=np.sum(sample>0); sl_cnt=np.sum(sample<0)
        pf_s=(tp_cnt*TP_PCT*100)/(sl_cnt*SL_PCT*100) if sl_cnt>0 else 999
        cum=np.cumsum(sample); peak=np.maximum.accumulate(cum)
        maxdd=(cum-peak).min()
        sim_pfs.append(pf_s); sim_cums.append(cum[-1])
        sim_maxdds.append(maxdd); sim_wrs.append(tp_cnt/N_TRADES*100)

    sim_pfs=np.array(sim_pfs); sim_cums=np.array(sim_cums)
    sim_maxdds=np.array(sim_maxdds); sim_wrs=np.array(sim_wrs)

    print(f"\n  Metric          {'Actual':>10}  {'MC 5%':>10}  {'MC 50%':>10}  "
          f"{'MC 95%':>10}  {'MC Mean':>10}")
    print(f"  {'-'*65}")
    actual_pf=df_all["outcome"].eq("TP").sum()*TP_PCT*100/(df_all["outcome"].eq("SL").sum()*SL_PCT*100)
    actual_cum=df_all["pnl"].sum()
    actual_wr=df_all["outcome"].eq("TP").sum()/len(df_all)*100
    cum2=np.cumsum(df_all["pnl"].values); peak2=np.maximum.accumulate(cum2)
    actual_maxdd=(cum2-peak2).min()

    rows=[
        ("PF",          f"{actual_pf:.3f}",   np.percentile(sim_pfs,5),   np.percentile(sim_pfs,50),
                                               np.percentile(sim_pfs,95),  sim_pfs.mean()),
        ("Cumul PnL %", f"{actual_cum:+.2f}", np.percentile(sim_cums,5),  np.percentile(sim_cums,50),
                                               np.percentile(sim_cums,95), sim_cums.mean()),
        ("MaxDD %",     f"{actual_maxdd:+.2f}",np.percentile(sim_maxdds,5),np.percentile(sim_maxdds,50),
                                               np.percentile(sim_maxdds,95),sim_maxdds.mean()),
        ("WR %",        f"{actual_wr:.1f}",   np.percentile(sim_wrs,5),   np.percentile(sim_wrs,50),
                                               np.percentile(sim_wrs,95),  sim_wrs.mean()),
    ]
    for label,actual,p5,p50,p95,mean in rows:
        print(f"  {label:<16} {actual:>10}  {p5:>10.2f}  {p50:>10.2f}  {p95:>10.2f}  {mean:>10.2f}")

    prob_profit=np.mean(sim_cums>0)*100
    prob_pf_gt1=np.mean(sim_pfs>1.0)*100
    prob_pf_gt15=np.mean(sim_pfs>1.5)*100
    print(f"\n  Probability profitable (cumul>0):  {prob_profit:.1f}%")
    print(f"  Probability PF > 1.0:              {prob_pf_gt1:.1f}%")
    print(f"  Probability PF > 1.5:              {prob_pf_gt15:.1f}%")
    print(f"  5th pct MaxDD:                     {np.percentile(sim_maxdds,5):>+.2f}%")
    print(f"  Worst case MaxDD (1st pct):        {np.percentile(sim_maxdds,1):>+.2f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. ROLLING 50/100-TRADE PF
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  4. ROLLING PROFIT FACTOR")
    print(f"{'='*W}")

    pnl_ser=df_all["pnl"].values
    dates_ser=df_all["date"].values

    for window in [50, 100]:
        pfs_roll=[]
        for i in range(window, len(pnl_ser)+1):
            w=pnl_ser[i-window:i]
            tp=np.sum(w>0); sl=np.sum(w<0)
            pf_w=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
            pfs_roll.append(pf_w)
        pfs_roll=np.array(pfs_roll)
        pct_above1=np.mean(pfs_roll>1.0)*100
        pct_above15=np.mean(pfs_roll>1.5)*100
        min_pf=pfs_roll.min(); max_pf=pfs_roll.max(); mean_pf=pfs_roll.mean()
        below1=np.sum(pfs_roll<1.0)
        print(f"\n  Rolling {window}-trade window  ({len(pfs_roll)} windows):")
        print(f"  Min PF:          {min_pf:.3f}")
        print(f"  Max PF:          {max_pf:.3f}")
        print(f"  Mean PF:         {mean_pf:.3f}")
        print(f"  Windows PF>1.0:  {pct_above1:.1f}%")
        print(f"  Windows PF>1.5:  {pct_above15:.1f}%")
        print(f"  Windows PF<1.0:  {below1}  ({100-pct_above1:.1f}%)")
        # ASCII sparkline of rolling PF
        print(f"\n  Rolling {window}-trade PF chart (each block = ~10 windows):")
        step=max(1,len(pfs_roll)//60)
        sampled=pfs_roll[::step]
        bar_chars=" ▁▂▃▄▅▆▇█"
        line=""
        for pf_v in sampled:
            idx=min(int((pf_v-0.5)/0.25),8) if pf_v>=0.5 else 0
            idx=max(0,idx)
            line+=bar_chars[idx]
        print(f"  0.5{'─'*5}1.0{'─'*5}1.5{'─'*5}2.0{'─'*5}2.5+")
        print(f"  {line}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. OPTIONS SIMULATION
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  5. OPTIONS SIMULATION  (buy ATM puts on entry signal)")
    print(f"{'='*W}")
    print(f"""
  Assumptions:
  - Buy 1 ATM put per signal at entry
  - Put delta:      0.50  (ATM approximation)
  - IV / day:       1.5%  (typical for these symbols)
  - Hold:           avg 20 bars = ~20 min
  - Theta decay:    ~0.03% per hour (intraday, minimal)
  - Spread cost:    0.05% of premium
  - Put premium:    ~0.8% of stock price (ATM, ~20 min to exp proxy)
  - Win: stock drops 0.50% -> put gains ~0.25% of stock = ~31% of premium
  - Loss: stock rises 0.25% -> put loses ~80% of premium (OTM quickly)
  - Timeout: put loses ~30% of premium (stock flat, theta)
""")
    # Simplified put P&L model based on delta
    PUT_PREMIUM_PCT = 0.008   # 0.8% of stock price
    PUT_DELTA       = 0.50
    PUT_SPREAD      = 0.0005  # 0.05% spread cost
    THETA_TO        = 0.30    # 30% premium lost on timeout

    opt_pnls=[]; stock_pnls=[]
    for _,row in df_all.iterrows():
        ep=row["ep"]; premium=ep*PUT_PREMIUM_PCT
        if row["outcome"]=="TP":
            # stock fell 0.50%, put gains delta * move - spread
            stock_move=ep*TP_PCT
            put_gain=stock_move*PUT_DELTA - premium*PUT_SPREAD
            pnl_opt=put_gain/premium*100  # as % of premium invested
            pnl_norm=TP_PCT*100
        elif row["outcome"]=="SL":
            # stock rose 0.25%, put loses most of value
            put_loss=premium*0.80 + premium*PUT_SPREAD
            pnl_opt=-put_loss/premium*100
            pnl_norm=-SL_PCT*100
        else:  # TO
            put_loss=premium*THETA_TO + premium*PUT_SPREAD
            pnl_opt=-put_loss/premium*100
            pnl_norm=0.0
        opt_pnls.append(pnl_opt); stock_pnls.append(pnl_norm)

    opt_arr=np.array(opt_pnls); stock_arr=np.array(stock_pnls)
    n=len(opt_arr)
    tp_cnt=df_all["outcome"].eq("TP").sum()
    sl_cnt=df_all["outcome"].eq("SL").sum()
    to_cnt=df_all["outcome"].eq("TO").sum()

    # Stock short stats
    stock_tp=stock_arr[stock_arr>0].sum(); stock_sl=abs(stock_arr[stock_arr<0].sum())
    stock_pf=stock_tp/stock_sl if stock_sl>0 else 999
    stock_ev=stock_arr.mean(); stock_cumul=stock_arr.sum()

    # Options stats
    opt_wins=opt_arr[opt_arr>0]
    opt_losses=opt_arr[opt_arr<0]
    opt_pf=opt_wins.sum()/abs(opt_losses.sum()) if len(opt_losses)>0 else 999
    opt_wr=len(opt_wins)/n*100
    opt_ev=opt_arr.mean()
    opt_cum=opt_arr.sum()
    cum_o=np.cumsum(opt_arr); peak_o=np.maximum.accumulate(cum_o)
    opt_maxdd=(cum_o-peak_o).min()

    print(f"  {'Metric':<22} {'Stock Short':>14}  {'Options (puts)':>14}")
    print(f"  {'-'*52}")
    print(f"  {'N trades':<22} {n:>14}  {n:>14}")
    print(f"  {'Win Rate':<22} {tp_cnt/n*100:>13.1f}%  {opt_wr:>13.1f}%")
    print(f"  {'Profit Factor':<22} {stock_pf:>14.3f}  {opt_pf:>14.3f}")
    print(f"  {'EV / signal':<22} {stock_ev:>13.4f}%  {opt_ev:>12.2f}%*")
    print(f"  {'Cumul (all signals)':<22} {stock_cumul:>13.3f}%  {opt_cum:>12.2f}%*")
    print(f"  {'MaxDD':<22} {(cum_o*0+np.cumsum(stock_arr)-np.maximum.accumulate(np.cumsum(stock_arr))).min():>13.2f}%  {opt_maxdd:>12.2f}%*")
    print(f"\n  * Options P&L expressed as % of premium paid per trade")
    print(f"    (not % of stock price — premium is ~0.8% of stock)")
    print(f"\n  Outcome breakdown:")
    print(f"  TP  (stock -0.50%): {tp_cnt:>5} trades  avg opt gain:  "
          f"{opt_arr[stock_arr>0].mean():>+.1f}% of premium")
    print(f"  SL  (stock +0.25%): {sl_cnt:>5} trades  avg opt loss:  "
          f"{opt_arr[stock_arr<0].mean():>+.1f}% of premium")
    print(f"  TO  (timeout):      {to_cnt:>5} trades  avg opt loss:  "
          f"{opt_arr[stock_arr==0].mean():>+.1f}% of premium")
    print(f"\n  Key insight:")
    if opt_pf > stock_pf:
        print(f"  Options IMPROVE the edge: PF {stock_pf:.3f} -> {opt_pf:.3f}")
        print(f"  Asymmetric payoff benefits put buyers — wins are larger % of premium.")
    else:
        print(f"  Options REDUCE the edge vs stock short: PF {stock_pf:.3f} -> {opt_pf:.3f}")
        print(f"  Theta decay on TOs and spread cost drag on options performance.")
    print(f"  At 0.8% premium per trade and {n} trades, total premium deployed:")
    print(f"  = {n} x 0.8% = {n*0.8:.0f}% of 1 share price (normalized)")
