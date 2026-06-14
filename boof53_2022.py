"""
BOOF53 Version H — 2022 Out-of-Sample Backtest
21-symbol routed portfolio on full year 2022 data.
ARM skipped (IPO 2023). 20 symbols tested.
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch | +1 bar confirmation
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

# Version H routing (ARM omitted — not public in 2022)
ROUTING = {
    # PMH
    "UPST":  ("PMH", None, None),
    "APP":   ("PMH", None, None),
    "SMCI":  ("PMH", None, None),
    "HIMS":  ("PMH", None, None),
    "GOOGL": ("PMH", None, None),
    # PDH
    "META":  ("PDH", None, None),
    "AFRM":  ("PDH", None, None),
    # 10m
    "TSLA":  ("PIV", 10,   2),
    "CLSK":  ("PIV", 10,   2),
    "HOOD":  ("PIV", 10,   2),
    # 30m
    "ADBE":  ("PIV", 30,   3),
    "PANW":  ("PIV", 30,   3),
    "MU":    ("PIV", 30,   3),
    "AMD":   ("PIV", 30,   3),
    "COIN":  ("PIV", 30,   3),
    "NVDA":  ("PIV", 30,   3),
    # 2H
    "MRVL":  ("PIV", 120,  4),
    "AVGO":  ("PIV", 120,  4),
    # 4H
    "PLTR":  ("PIV", 240,  5),
    # Daily
    "CRM":   ("PIV", 390,  5),
}


def load_sym(sym):
    path = f"boof53_{sym}_1m_2022.csv"
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

def metrics(s, weeks):
    if len(s)<5: return None
    n=len(s); tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp=s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf=(tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/weeks
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=n,tpw=tpw,wr=wr,tp=int(tp),sl=int(sl),pf=pf,ev=ev,maxdd=maxdd,cumul=s["pnl"].sum())

HDR=(f"  {'Label':<28} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}  {'Cumul':>8}")
SEP="  " + "-"*88
W  =92

def prow(label, s, weeks, w=28):
    mx=metrics(s, weeks)
    if mx is None: print(f"  {label:<{w}} (n<5)"); return mx
    mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
        "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
          f"{mx['maxdd']:>+7.2f}%{mk}  {mx['cumul']:>+7.3f}%")
    return mx


if __name__=="__main__":
    print("Scanning 2022 backtest...", flush=True)
    records = []

    for sym, (rtype, lb, wing) in ROUTING.items():
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None:
            print(f"(no data)", end=" ")
            continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue

        pdh_map = build_pdh(rth_df) if rtype=="PDH" else {}
        pivots  = build_pivots(rth_df, lb, wing) if rtype=="PIV" else {}
        rth_df  = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        tf_label = ("PMH" if rtype=="PMH" else "PDH" if rtype=="PDH"
                    else f"{lb}m" if lb<60 else f"{lb//60}H" if lb<390 else "Daily")

        for date, ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()

            if rtype=="PMH":
                ev=scan_fresh_1st(ddf, day["pm_high"])
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                    "pnl":pnl,"date":date_ts})
            elif rtype=="PDH":
                level=pdh_map.get(date_ts)
                if level and not pd.isna(level):
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                        "pnl":pnl,"date":date_ts})
            else:
                for level in pivots.get(date_ts, pivots.get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                        "pnl":pnl,"date":date_ts})

    print()
    df=pd.DataFrame(records)
    df["month"]=df["date"].dt.to_period("M")

    # compute weeks in dataset
    dates=sorted(df["date"].unique())
    weeks=(pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days/7 if len(dates)>1 else 52

    # ── Top-line ──────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BOOF53 VERSION H — 2022 OUT-OF-SAMPLE BACKTEST")
    print(f"  20 symbols (ARM excluded — IPO 2023) | Full year 2022")
    print(f"  SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version H  (2022, 20 sym)", df, weeks)

    # ── By setup group ────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BY SETUP GROUP")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("All 20 symbols", df, weeks)
    print(SEP)
    for setup in ["PMH","PDH","10m","30m","2H","4H","Daily"]:
        s=df[df["setup"]==setup]
        if len(s)>=5: prow(f"  {setup}", s, weeks)

    # ── Per symbol ────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PER SYMBOL  (sorted by PF)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    sym_rows=[]
    for sym in ROUTING:
        s=df[df["sym"]==sym]
        mx=metrics(s, weeks)
        if mx: sym_rows.append((sym,ROUTING[sym],mx,s))
    sym_rows.sort(key=lambda x:-x[2]["pf"])
    for sym,route,mx_s,s in sym_rows:
        tf=(route[0] if route[0] in ("PMH","PDH")
            else f"{route[1]}m" if route[1] and route[1]<60
            else f"{route[1]//60}H" if route[1] and route[1]<390
            else "Daily")
        prow(f"  {sym} ({tf})", s, weeks)

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MONTHLY BREAKDOWN — 2022")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'PF':>6}  {'Mo PnL':>8}  {'Cumul':>8}")
    print(f"  {'-'*56}")

    cumul=0.0; mo_pnls=[]
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; n=len(s)
        tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
        wr=tp/n*100 if n>0 else 0
        pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        mo_pnl=s["pnl"].sum(); cumul+=mo_pnl; mo_pnls.append(mo_pnl)
        flag=" v" if mo_pnl>=0 else " x"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {pf:>6.3f}  "
              f"{mo_pnl:>+7.3f}%  {cumul:>+7.3f}%{flag}")
    print(f"  {'-'*56}")
    wins=sum(1 for p in mo_pnls if p>0); total=len(mo_pnls)
    print(f"  {'TOTAL':<10} {len(df):>4}  {df['outcome'].eq('TP').sum()/len(df)*100:>5.1f}%"
          f"        {df['pnl'].sum():>+7.3f}%  {cumul:>+7.3f}%")
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    print(f"  Best: {max(mo_pnls):>+.3f}%   Worst: {min(mo_pnls):>+.3f}%   Avg: {np.mean(mo_pnls):>+.3f}%")

    # ── Equity curve ─────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  EQUITY CURVE — 2022")
    print(f"{'='*W}")
    cumul=0.0
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; mo_pnl=s["pnl"].sum(); cumul+=mo_pnl
        bar=min(int(abs(mo_pnl)/0.3),44)
        fill="+" if mo_pnl>=0 else "-"
        print(f"  {str(mo)}  {cumul:>+8.3f}%  |{fill*bar}")

    # ── Context note ──────────────────────────────────────────────────────────
    print(f"\n  NOTE: 2022 was a severe bear market year.")
    print(f"  S&P 500: -19.4%  |  NASDAQ: -33.1%  |  Most growth stocks -50% to -80%")
    print(f"  Strategy is SHORT on gap-up days — bear market = more gap-ups to short.")
