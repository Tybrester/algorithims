"""
BOOF53 Version F+ — 22-symbol routed portfolio
Each symbol uses its best setup (PMH / 30m / 1H2H overlap)
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
STACK_PCT = 0.0015
TP_PCT    = 0.0050
SL_PCT    = 0.0025
MAX_BARS  = 60
WEEKS     = 19.2

# Routing table: symbol -> setup
ROUTING = {
    # PMH group
    "UPST":  "PMH",
    "APP":   "PMH",
    "SMCI":  "PMH",
    "CRM":   "PMH",
    "HIMS":  "PMH",
    "ARM":   "PMH",
    "HOOD":  "PMH",
    "RIOT":  "PMH",
    # 30m group
    "ADBE":  "30m",
    "PANW":  "30m",
    "MU":    "30m",
    "TSLA":  "30m",
    "AMD":   "30m",
    "CLSK":  "30m",
    "COIN":  "30m",
    "GOOGL": "30m",
    # 1H2H overlap group
    "NVDA":  "1H2H",
    "PLTR":  "1H2H",
    "META":  "1H2H",
    "AFRM":  "1H2H",
    "MRVL":  "1H2H",
    "AVGO":  "1H2H",
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

HDR=(f"  {'Label':<28} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}  {'Cumul PnL':>9}")
SEP=f"  {'-'*92}"
W  =96

def prow(label, s, w=28, show_cumul=True):
    mx=metrics(s)
    if mx is None: print(f"  {label:<{w}} (n<5)"); return mx
    mk=(" <<<" if mx["pf"]>=2.0 else " <<" if mx["pf"]>=1.5 else
        "  <" if mx["pf"]>=1.2 else "  -" if mx["pf"]<1.0 else "   ")
    cumul_str=f"{s['pnl'].sum():>+9.3f}%" if show_cumul else ""
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  "
          f"{mx['maxdd']:>+7.2f}%{mk}  {cumul_str}")
    return mx


if __name__=="__main__":
    print("Scanning Version F+...", flush=True)
    records = []

    for sym, setup in ROUTING.items():
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        if rth_df is None: continue
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue

        piv_30m = build_pivots(rth_df, 30, 3)  if setup in ("30m","1H2H") else {}
        piv_1h  = build_pivots(rth_df, 60, 3)  if setup == "1H2H" else {}
        piv_2h  = build_pivots(rth_df, 120, 4) if setup == "1H2H" else {}
        rth_df  = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        for date, ddf in rth_df.groupby("date"):
            date_ts=pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day=pm_stats.loc[date_ts]
            if day["gap_pct"]<=0.5: continue
            ddf=ddf.reset_index(drop=True); dk=date_ts.date()

            if setup == "PMH":
                ev=scan_fresh_1st(ddf, day["pm_high"])
                if ev:
                    out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                    records.append({"sym":sym,"setup":setup,"outcome":out,
                                    "pnl":pnl,"date":pd.Timestamp(dk)})

            elif setup == "30m":
                for level in piv_30m.get(date_ts, piv_30m.get(dk,[])):
                    if pd.isna(level): continue
                    ev=scan_fresh_1st(ddf,level)
                    if ev:
                        out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                        records.append({"sym":sym,"setup":setup,"outcome":out,
                                        "pnl":pnl,"date":pd.Timestamp(dk)})

            elif setup == "1H2H":
                res_1h=piv_1h.get(date_ts,piv_1h.get(dk,[]))
                res_2h=piv_2h.get(date_ts,piv_2h.get(dk,[]))
                for level in res_1h:
                    if pd.isna(level): continue
                    if any(abs(lv2-level)/level<=STACK_PCT for lv2 in res_2h):
                        ev=scan_fresh_1st(ddf,level)
                        if ev:
                            out,pnl=race(ddf,ev["bar_i"],ev["ep"])
                            records.append({"sym":sym,"setup":setup,"outcome":out,
                                            "pnl":pnl,"date":pd.Timestamp(dk)})

    print()
    df=pd.DataFrame(records); df["month"]=df["date"].dt.to_period("M")

    # ── Top-line metrics card ─────────────────────────────────────────────────
    mx=metrics(df)
    print(f"\n{'='*W}")
    print(f"  BOOF53 VERSION F+  |  22-symbol routed portfolio")
    print(f"  SHORT | Gap Up > 0.5% | TP 0.50% / SL 0.25% | Fresh 1st touch")
    print(f"{'='*W}")
    print(f"\n  {'Metric':<18} {'Value':>12}")
    print(f"  {'-'*32}")
    print(f"  {'Trades total':<18} {mx['n']:>12}")
    print(f"  {'Trades/week':<18} {mx['tpw']:>12.1f}")
    print(f"  {'Win Rate':<18} {mx['wr']:>11.1f}%")
    print(f"  {'Profit Factor':<18} {mx['pf']:>12.3f}")
    print(f"  {'EV/trade':<18} {mx['ev']:>+11.4f}%")
    print(f"  {'MaxDD':<18} {mx['maxdd']:>+11.2f}%")
    print(f"  {'Cumul PnL':<18} {df['pnl'].sum():>+11.3f}%")

    # ── By setup group ────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BY SETUP GROUP")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version F+ (all 22)", df)
    print(SEP)
    prow("  PMH group  (8 syms)", df[df["setup"]=="PMH"])
    prow("  30m group  (8 syms)", df[df["setup"]=="30m"])
    prow("  1H2H group (6 syms)", df[df["setup"]=="1H2H"])

    # ── Per symbol contribution ────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  PER SYMBOL CONTRIBUTION  (sorted by Cumul PnL)")
    print(f"{'='*W}")
    print(HDR); print(SEP)

    sym_stats=[]
    for sym in ROUTING:
        s=df[df["sym"]==sym]
        if len(s)>=5:
            mx_s=metrics(s)
            sym_stats.append((sym, ROUTING[sym], mx_s, s["pnl"].sum()))
    sym_stats.sort(key=lambda x:-x[3])

    print(f"  --- Top performers ---")
    for sym,setup,mx_s,cumul in sym_stats:
        if mx_s and mx_s["pf"]>=1.5:
            prow(f"  {sym} ({setup})", df[df["sym"]==sym])
    print(SEP)
    print(f"  --- Mid tier ---")
    for sym,setup,mx_s,cumul in sym_stats:
        if mx_s and 1.2<=mx_s["pf"]<1.5:
            prow(f"  {sym} ({setup})", df[df["sym"]==sym])
    print(SEP)
    print(f"  --- Below 1.2 ---")
    for sym,setup,mx_s,cumul in sym_stats:
        if mx_s and mx_s["pf"]<1.2:
            prow(f"  {sym} ({setup})", df[df["sym"]==sym])

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MONTHLY BREAKDOWN")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'TP':>4}/{' SL':<4}  "
          f"{'PF':>6}  {'EV':>8}  {'Mo PnL':>8}  {'Cumul':>8}  "
          f"  {'PMH':>6}  {'30m':>6}  {'1H2H':>6}")
    print(f"  {'-'*88}")
    cumul=0.0; mo_pnls=[]
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]; n=len(s)
        tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
        wr=tp/n*100 if n>0 else 0
        pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        ev=s["pnl"].mean(); mo_pnl=s["pnl"].sum(); cumul+=mo_pnl; mo_pnls.append(mo_pnl)
        # per-group monthly PF
        def gpf(grp):
            sg=s[s["setup"]==grp]; tp_=sg["outcome"].eq("TP").sum(); sl_=sg["outcome"].eq("SL").sum()
            return f"{(tp_*TP_PCT*100)/(sl_*SL_PCT*100):.2f}" if sl_>0 and tp_>0 else "--"
        flag=" v" if mo_pnl>=0 else " x"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {tp:>4}/{sl:<4}  "
              f"{pf:>6.3f}  {ev:>+7.4f}%  {mo_pnl:>+7.3f}%  {cumul:>+7.3f}%{flag}"
              f"  {gpf('PMH'):>6}  {gpf('30m'):>6}  {gpf('1H2H'):>6}")
    print(f"  {'-'*88}")
    n=len(df); tp=df["outcome"].eq("TP").sum(); sl=df["outcome"].eq("SL").sum()
    pf_all=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    print(f"  {'TOTAL':<10} {n:>4}  {tp/n*100:>5.1f}%  {tp:>4}/{sl:<4}  "
          f"{pf_all:>6.3f}  {df['pnl'].mean():>+7.4f}%  {df['pnl'].sum():>+7.3f}%  {cumul:>+7.3f}%")
    wins=sum(1 for p in mo_pnls if p>0); total=len(mo_pnls)
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    print(f"  Best:  {max(mo_pnls):>+.3f}%   Worst: {min(mo_pnls):>+.3f}%   Avg: {np.mean(mo_pnls):>+.3f}%")

    # ── Equity curve (text) ───────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  CUMULATIVE EQUITY CURVE  (per trade)")
    print(f"{'='*W}")
    cum=0.0; bar_w=40
    for mo in sorted(df["month"].unique()):
        s=df[df["month"]==mo]
        mo_pnl=s["pnl"].sum(); cum+=mo_pnl
        bar=int(abs(mo_pnl)/0.5); bar=min(bar,bar_w)
        fill="+" if mo_pnl>=0 else "-"
        print(f"  {str(mo)}  {cum:>+8.3f}%  {'|'}{fill*bar}")

    # ── Comparison vs Version F ───────────────────────────────────────────────
    # Version F hardcoded from prior run
    print(f"\n{'='*W}")
    print(f"  VERSION F+ vs VERSION F  (14 syms)")
    print(f"{'='*W}")
    print(f"  {'Metric':<18} {'F+ (22 sym)':>14}  {'F (14 sym)':>12}  {'Delta':>10}")
    print(f"  {'-'*58}")
    VF=dict(n=326,tpw=17.0,wr=46.9,pf=1.811,ev=0.1051,maxdd=-2.00,cumul=34.25,months="7/7")
    mx_fp=metrics(df)
    rows2=[
        ("Trades total", str(mx_fp['n']),        str(VF['n']),        f"{mx_fp['n']-VF['n']:>+d}"),
        ("Trades/week",  f"{mx_fp['tpw']:.1f}",  f"{VF['tpw']:.1f}", f"{mx_fp['tpw']-VF['tpw']:>+.1f}"),
        ("Win Rate",     f"{mx_fp['wr']:.1f}%",  f"{VF['wr']:.1f}%", f"{mx_fp['wr']-VF['wr']:>+.1f}%"),
        ("PF",           f"{mx_fp['pf']:.3f}",   f"{VF['pf']:.3f}",  f"{mx_fp['pf']-VF['pf']:>+.3f}"),
        ("EV/trade",     f"{mx_fp['ev']:+.4f}%", f"{VF['ev']:+.4f}%",f"{mx_fp['ev']-VF['ev']:>+.4f}%"),
        ("MaxDD",        f"{mx_fp['maxdd']:+.2f}%",f"{VF['maxdd']:+.2f}%",f"{mx_fp['maxdd']-VF['maxdd']:>+.2f}%"),
        ("Cumul PnL",    f"{df['pnl'].sum():+.3f}%", f"{VF['cumul']:+.3f}%", f"{df['pnl'].sum()-VF['cumul']:>+.3f}%"),
    ]
    for label,vfp,vf,delta in rows2:
        print(f"  {label:<18} {vfp:>14}  {vf:>12}  {delta:>10}")
