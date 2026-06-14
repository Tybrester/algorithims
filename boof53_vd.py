"""
Version B vs D — 15 symbols
B: Gap Up > 0.5% (all)
D: Gap Up 0.5–1.0% OR 2.0–3.0% only
Symbol-aware levels, SHORT only, TP 0.50% / SL 0.25%
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60
WEEKS    = 19.2

# Symbol-aware levels (extend Version B rules to new symbols)
SYM_LEVELS = {
    "APP":  {"1H_Res","PMH"},
    "SMCI": {"1H_Res","PMH"},
    "HIMS": {"1H_Res","PMH"},
    "ARM":  {"PMH","4H_Res"},
    "MU":   {"1H_Res"},
    "PLTR": {"1H_Res","PMH"},
    "HOOD": {"1H_Res","PMH"},
    "COIN": {"1H_Res","PMH"},
    "AMD":  {"1H_Res","PMH"},
    "RKLB": {"1H_Res","PMH"},
    "NVDA": {"1H_Res","PMH"},
    "META": {"1H_Res","PMH"},
    "AMZN": {"1H_Res","PMH"},
    "AVGO": {"1H_Res","PMH"},
    "CRM":  {"1H_Res","PMH"},
}

TIER1 = ["APP","SMCI","HIMS","ARM","MU"]
TIER2 = ["PLTR","HOOD","COIN","AMD","RKLB"]
TIER3 = ["NVDA","META","AMZN","AVGO","CRM"]
ALL15 = TIER1 + TIER2 + TIER3

def load_sym(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
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
    pm_agg=pm_df.groupby("date").agg(pm_high=("high","max"),pm_low=("low","min")).reset_index()
    pc=rth_df.groupby("date")["close"].last().reset_index()
    pc.columns=["date","prev_close"]; pc["next_date"]=pc["date"]+pd.Timedelta(days=1)
    ro=rth_df.groupby("date")["open"].first().reset_index(); ro.columns=["date","rth_open"]
    stats=pm_agg.merge(pc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
                       on="date",how="left").merge(ro,on="date",how="left")
    stats["gap_pct"]=(stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct","pm_high"]).set_index("date")

def build_pivots_clean(rth_df, lookback, wing):
    rth_df=rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"]=pd.to_datetime(rth_df["date"]); sr={}
    for d in sorted(rth_df["date"].unique()):
        hist=rth_df[rth_df["date"]<d].tail(lookback)
        if len(hist)<max(wing+1,lookback//4): continue
        H=hist["high"].values; L=hist["low"].values; levels=[]
        for i in range(wing,len(hist)):
            if H[i]==H[i-wing:i+1].max(): levels.append((H[i],"res"))
            if L[i]==L[i-wing:i+1].min(): levels.append((L[i],"sup"))
        if not levels: continue
        levels=sorted(levels,key=lambda x:x[0]); cl=[list(levels[0])]
        for lv,lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        sr[d]=[(c[0],c[1]) for c in cl]
    return sr

def race(ddf, ei, ep):
    n=len(ddf); tp_price=ep*(1-TP_PCT); sl_price=ep*(1+SL_PCT)
    for i in range(ei, min(ei+MAX_BARS, n-1)+1):
        if ddf.iloc[i]["high"] >= sl_price: return "SL First"
        if ddf.iloc[i]["low"]  <= tp_price: return "TP First"
    return "Neither"

def scan_sym(sym, allowed_levels):
    if not __import__("os").path.exists(f"boof51_{sym}_1m.csv"): return pd.DataFrame()
    rth_df,pm_df=load_sym(sym)
    pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df,rth_df)
    if pm_stats.empty: return pd.DataFrame()
    sr_1h=build_pivots_clean(rth_df,lookback=60, wing=3)
    sr_4h=build_pivots_clean(rth_df,lookback=240,wing=5)
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    records=[]
    for date,ddf in rth_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm_stats.index: continue
        day=pm_stats.loc[date_ts]; gap=day["gap_pct"]
        if gap <= 0.5: continue          # Gap Up only
        ddf=ddf.reset_index(drop=True)
        pmh=day["pm_high"]
        dk=date_ts.date()
        lv1h=sr_1h.get(date_ts,sr_1h.get(dk,[]))
        lv4h=sr_4h.get(date_ts,sr_4h.get(dk,[]))
        res_levels=[(pmh,"PMH")]
        for lv,lt in lv1h:
            if lt=="res": res_levels.append((lv,"1H_Res"))
        for lv,lt in lv4h:
            if lt=="res": res_levels.append((lv,"4H_Res"))
        H=ddf["high"].values; C=ddf["close"].values; n=len(ddf)
        for level,lname in res_levels:
            if pd.isna(level) or lname not in allowed_levels: continue
            state="IDLE"; ext=None; touch_num=0; i=0
            while i<n-3:
                touching=H[i]>=level*(1-NEAR_PCT)
                if state=="IDLE":
                    if touching: state="IN"; ext=C[i]; touch_num+=1
                elif state=="IN":
                    if touching: ext=min(ext,C[i])
                    else:
                        bounced=ext is not None and (level-ext)/level>=BOUNCE
                        if bounced and touch_num==1:
                            ei=i+1; ep=ddf.iloc[ei]["open"]
                            out=race(ddf,ei,ep)
                            pnl=TP_PCT*100 if out=="TP First" else (-SL_PCT*100 if out=="SL First" else 0.0)
                            records.append({"sym":sym,"level":lname,"date":pd.Timestamp(dk),
                                            "gap_pct":gap,"outcome":out,"pnl":pnl})
                        state="IDLE"; ext=None
                i+=1
    return pd.DataFrame(records)

def m(s):
    if len(s)<3: return None
    n=len(s); tp=s["outcome"].eq("TP First").sum(); sl=s["outcome"].eq("SL First").sum()
    wr=tp/n*100; pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/WEEKS
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=n,tpw=tpw,wr=wr,tp=tp,sl=sl,pf=pf,ev=ev,maxdd=maxdd)

def prow(label, s, w=22):
    mx=m(s)
    if mx is None: return
    mk=" <<<" if mx["pf"]>=2.0 else (" <<" if mx["pf"]>=1.5 else ("  <" if mx["pf"]>=1.2 else ("  -" if mx["pf"]<1.0 else "")))
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%{mk}")

HDR=(f"  {'Label':<22} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*80}"
W=84

def ver_d(df):
    return df[(( df["gap_pct"]>0.5)&(df["gap_pct"]<=1.0)) |
              ((df["gap_pct"]>2.0)&(df["gap_pct"]<=3.0))]

if __name__=="__main__":
    print("Scanning 15 symbols...",flush=True)
    frames=[]
    for sym in ALL15:
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym, SYM_LEVELS[sym])
        if not df.empty: frames.append(df)
    print()
    all_df=pd.concat(frames,ignore_index=True)

    b_df = all_df                          # Gap Up > 0.5% — all
    d_df = ver_d(all_df)                   # Gap Up 0.5–1.0% OR 2.0–3.0%

    # ═══ TOP-LINE COMPARISON ═════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  VERSION B vs D  |  15 symbols  |  SHORT  |  TP+0.50% / SL-0.25%")
    print(f"  B = Gap Up >0.5%  |  D = Gap Up 0.5–1.0% OR 2.0–3.0%")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version B (all Gap Up)", b_df)
    prow("Version D (filtered)",   d_df)
    print(SEP)
    # D excluded bucket
    excl = all_df[(all_df["gap_pct"]>1.0)&(all_df["gap_pct"]<=2.0) | (all_df["gap_pct"]>3.0)]
    prow("  D excluded (1-2% + >3%)", excl)

    # ═══ PER-TIER ════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  PER TIER  —  Version B vs D")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for tier_lbl, tier in [("Tier1 (S)",TIER1),("Tier2 (A)",TIER2),("Tier3 (B)",TIER3)]:
        tb=b_df[b_df["sym"].isin(tier)]; td=ver_d(tb)
        prow(f"B {tier_lbl}", tb)
        prow(f"D {tier_lbl}", td)
        print(SEP)

    # ═══ PER-SYMBOL  ═════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  PER SYMBOL  —  Version B vs D  (sorted by D PF)")
    print(f"{'='*W}")
    print(f"  {'Sym':<6} {'Tier':<5}  {'--- B ---':^30}  {'--- D ---':^30}")
    print(f"  {'':11}  {'N':>4} {'T/Wk':>5} {'WR':>5} {'PF':>6} {'EV':>8}    "
          f"{'N':>4} {'T/Wk':>5} {'WR':>5} {'PF':>6} {'EV':>8}")
    print(f"  {'-'*78}")
    tier_of={s:"S" for s in TIER1}; tier_of.update({s:"A" for s in TIER2}); tier_of.update({s:"B" for s in TIER3})

    rows=[]
    for sym in ALL15:
        sb=b_df[b_df["sym"]==sym]; sd=ver_d(sb)
        mb=m(sb); md=m(sd)
        rows.append((sym,mb,md))
    rows.sort(key=lambda x: -(x[2]["pf"] if x[2] else 0))

    def frow(mx):
        if mx is None: return f"{'':>4} {'':>5} {'':>5} {'':>6} {'':>8}"
        return f"{mx['n']:>4} {mx['tpw']:>5.1f} {mx['wr']:>4.0f}% {mx['pf']:>6.3f} {mx['ev']:>+7.4f}%"

    for sym,mb,md in rows:
        mk=""
        if md and md["pf"]>=2.0: mk=" <<<"
        elif md and md["pf"]>=1.5: mk=" <<"
        elif md and md["pf"]>=1.2: mk="  <"
        print(f"  {sym:<6} {tier_of[sym]:<5}  {frow(mb)}    {frow(md)}{mk}")

    # ═══ GAP BUCKET DETAIL ═══════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  GAP SIZE BUCKETS — all 15 symbols, Gap Up only")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    BUCKETS=[("0.50–1.00%",0.5,1.0),("1.00–2.00%",1.0,2.0),
             ("2.00–3.00%",2.0,3.0),(">3.00%",3.0,99.0)]
    for lbl,lo,hi in BUCKETS:
        s=all_df[(all_df["gap_pct"]>lo)&(all_df["gap_pct"]<=hi)]
        prow(lbl, s)
    print(SEP)
    print(f"  Version D buckets combined:")
    prow("  0.50–1.00% + 2.00–3.00%", d_df)
