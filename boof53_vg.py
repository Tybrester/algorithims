"""
BOOF53 Version G — 22-symbol optimally-routed portfolio
Symbol-routed levels based on Phase 1 matrix analysis.
SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch | +1 bar confirmation

ROUTING (best PF per symbol from full matrix):
  PMH : UPST, APP, SMCI, CRM, HIMS, ARM, RIOT
  10m : HOOD, TSLA, CLSK, GOOGL
  30m : ADBE, PANW, MU, AMD, COIN, NVDA
  1H  : META
  2H  : AFRM, MRVL, AVGO
  4H  : PLTR
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

# Optimal routing from Phase 1 matrix
ROUTING = {
    # PMH
    "UPST":  ("PMH", None,  None),
    "APP":   ("PMH", None,  None),
    "SMCI":  ("PMH", None,  None),
    "CRM":   ("PMH", None,  None),
    "HIMS":  ("PMH", None,  None),
    "ARM":   ("PMH", None,  None),
    "RIOT":  ("PMH", None,  None),
    # 10m pivots (lookback=10, wing=2)
    "HOOD":  ("PIV", 10,    2),
    "TSLA":  ("PIV", 10,    2),
    "CLSK":  ("PIV", 10,    2),
    "GOOGL": ("PIV", 10,    2),
    # 30m pivots (lookback=30, wing=3)
    "ADBE":  ("PIV", 30,    3),
    "PANW":  ("PIV", 30,    3),
    "MU":    ("PIV", 30,    3),
    "AMD":   ("PIV", 30,    3),
    "COIN":  ("PIV", 30,    3),
    "NVDA":  ("PIV", 30,    3),
    # 1H pivots (lookback=60, wing=3)
    "META":  ("PIV", 60,    3),
    # 2H pivots (lookback=120, wing=4)
    "AFRM":  ("PIV", 120,   4),
    "MRVL":  ("PIV", 120,   4),
    "AVGO":  ("PIV", 120,   4),
    # 4H pivots (lookback=240, wing=5)
    "PLTR":  ("PIV", 240,   5),
}

# Version F+ routing for comparison
FP_ROUTING = {
    "UPST":"PMH","APP":"PMH","SMCI":"PMH","CRM":"PMH",
    "HIMS":"PMH","ARM":"PMH","HOOD":"PMH","RIOT":"PMH",
    "ADBE":"30m","PANW":"30m","MU":"30m","TSLA":"30m",
    "AMD":"30m","CLSK":"30m","COIN":"30m","GOOGL":"30m",
    "NVDA":"1H2H","PLTR":"1H2H","META":"1H2H",
    "AFRM":"1H2H","MRVL":"1H2H","AVGO":"1H2H",
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

HDR=(f"  {'Label':<30} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}  {'Cumul':>8}")
SEP=f"  {'-'*90}"
W  =94

def prow(label, s, w=30):
    mx=metrics(s)
    if mx is None: print(f"  {label:<{w}} (n<5)"); return mx
    mk=(" <<<" if mx["pf"]>=2.0 else "  <<" if mx["pf"]>=1.5 else
        "   <" if mx["pf"]>=1.2 else "   -" if mx["pf"]<1.0 else "    ")
    cumul=s["pnl"].sum()
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
          f"{mx['maxdd']:>+7.2f}%{mk}  {cumul:>+7.3f}%")
    return mx


if __name__=="__main__":
    print("Scanning Version G...", flush=True)
    records = []

    for sym, (rtype, lb, wing) in ROUTING.items():
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue
        pivots = build_pivots(rth_df, lb, wing) if rtype=="PIV" else {}
        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

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
                    tf_label="PMH"
                    records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                    "pnl":pnl,"date":pd.Timestamp(dk)})
            else:
                tf_label=f"{lb}m" if lb<60 else f"{lb//60}H"
                for level in pivots.get(date_ts, pivots.get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        records.append({"sym":sym,"setup":tf_label,"outcome":out,
                                        "pnl":pnl,"date":pd.Timestamp(dk)})

    print()
    df=pd.DataFrame(records); df["month"]=df["date"].dt.to_period("M")

    # ── Top-line card ─────────────────────────────────────────────────────────
    mx=metrics(df)
    print(f"\n{'='*W}")
    print(f"  BOOF53 VERSION G  |  22-symbol optimally-routed portfolio")
    print(f"  SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch")
    print(f"{'='*W}")

    print(f"\n  Routing:")
    print(f"    PMH : UPST, APP, SMCI, CRM, HIMS, ARM, RIOT")
    print(f"    10m : HOOD, TSLA, CLSK, GOOGL")
    print(f"    30m : ADBE, PANW, MU, AMD, COIN, NVDA")
    print(f"    1H  : META")
    print(f"    2H  : AFRM, MRVL, AVGO")
    print(f"    4H  : PLTR")

    print(f"\n  {'Metric':<18} {'Vers G':>12}  {'Vers F+':>12}  {'Delta':>10}")
    print(f"  {'-'*56}")
    FP=dict(n=564,tpw=29.4,wr=45.6,pf=1.696,ev=0.0935,maxdd=-3.25,cumul=52.75)
    rows2=[
        ("Trades total", str(mx['n']),         str(FP['n']),         f"{mx['n']-FP['n']:>+d}"),
        ("Trades/week",  f"{mx['tpw']:.1f}",   f"{FP['tpw']:.1f}",  f"{mx['tpw']-FP['tpw']:>+.1f}"),
        ("Win Rate",     f"{mx['wr']:.1f}%",   f"{FP['wr']:.1f}%",  f"{mx['wr']-FP['wr']:>+.1f}%"),
        ("PF",           f"{mx['pf']:.3f}",    f"{FP['pf']:.3f}",   f"{mx['pf']-FP['pf']:>+.3f}"),
        ("EV/trade",     f"{mx['ev']:+.4f}%",  f"{FP['ev']:+.4f}%", f"{mx['ev']-FP['ev']:>+.4f}%"),
        ("MaxDD",        f"{mx['maxdd']:+.2f}%",f"{FP['maxdd']:+.2f}%",f"{mx['maxdd']-FP['maxdd']:>+.2f}%"),
        ("Cumul PnL",    f"{df['pnl'].sum():+.3f}%",f"{FP['cumul']:+.3f}%",f"{df['pnl'].sum()-FP['cumul']:>+.3f}%"),
    ]
    for label,vg,vfp,delta in rows2:
        print(f"  {label:<18} {vg:>12}  {vfp:>12}  {delta:>10}")

    # ── By setup group ────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BY SETUP GROUP")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version G  (all 22)",  df)
    print(SEP)
    for setup in ["PMH","10m","30m","1H","2H","4H"]:
        s=df[df["setup"]==setup]
        if len(s)>0:
            prow(f"  {setup} group", s)

    # ── Per symbol ────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PER SYMBOL  (sorted by PF)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    sym_rows=[]
    for sym in ROUTING:
        s=df[df["sym"]==sym]
        mx_s=metrics(s)
        if mx_s: sym_rows.append((sym,ROUTING[sym],mx_s,s))
    sym_rows.sort(key=lambda x:-x[2]["pf"])
    for sym,route,mx_s,s in sym_rows:
        tf=route[0] if route[0]=="PMH" else (f"{route[1]}m" if route[1]<60 else f"{route[1]//60}H")
        prow(f"  {sym} ({tf})", s)

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MONTHLY BREAKDOWN  |  Version G vs F+")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'PF':>6}  {'Mo PnL':>8}  {'Cumul':>8}  "
          f"  F+ MoPnL")
    print(f"  {'-'*72}")

    # F+ monthly hardcoded from prior run
    FP_MO={
        "2025-12":3.500,"2026-01":5.500,"2026-02":10.750,
        "2026-03":4.750,"2026-04":15.250,"2026-05":2.250,"2026-06":10.750
    }

    cumul=0.0; mo_pnls=[]
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; n=len(s)
        tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
        wr=tp/n*100 if n>0 else 0
        pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        mo_pnl=s["pnl"].sum(); cumul+=mo_pnl; mo_pnls.append(mo_pnl)
        fp_mo=FP_MO.get(str(mo),0)
        delta=mo_pnl-fp_mo
        flag=" v" if mo_pnl>=0 else " x"
        delta_str=f"{delta:>+7.3f}%"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {pf:>6.3f}  "
              f"{mo_pnl:>+7.3f}%  {cumul:>+7.3f}%{flag}  "
              f"{fp_mo:>+7.3f}%  ({delta_str})")
    print(f"  {'-'*72}")
    n=len(df); tp=df["outcome"].eq("TP").sum(); sl=df["outcome"].eq("SL").sum()
    pf_all=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    wins=sum(1 for p in mo_pnls if p>0); total=len(mo_pnls)
    print(f"  {'TOTAL':<10} {n:>4}  {tp/n*100:>5.1f}%  {pf_all:>6.3f}  "
          f"{df['pnl'].sum():>+7.3f}%  {cumul:>+7.3f}%")
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    print(f"  Best:  {max(mo_pnls):>+.3f}%   Worst: {min(mo_pnls):>+.3f}%   Avg: {np.mean(mo_pnls):>+.3f}%")

    # ── Equity curve ─────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  EQUITY CURVE")
    print(f"{'='*W}")
    cum=0.0
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; mo_pnl=s["pnl"].sum(); cum+=mo_pnl
        bar=min(int(abs(mo_pnl)/0.4),42)
        fill="+" if mo_pnl>=0 else "-"
        print(f"  {str(mo)}  {cum:>+8.3f}%  |{fill*bar}")
