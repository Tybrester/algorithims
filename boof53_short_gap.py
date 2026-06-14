"""
BOOF53 — SHORT only, Gap Up/Down only, 5 symbols (no RKLB)
Resistance levels: PMH, PDH, 1H_Res, 4H_Res
TP/SL configs: 0.50/0.25, 0.40/0.20, 0.30/0.15
Uses re-scan with new TP/SL since 0.40/0.20 and 0.30/0.15 weren't run yet.
"""
import pandas as pd
import numpy as np
import pytz, os

SYMS  = ["SMCI","HIMS","ARM","MU","APP"]
WEEKS = 19.2
ET    = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
RES_LEVELS = {"PMH","PDH","1H_Res","4H_Res"}

CONFIGS = [
    (0.50, 0.25),
    (0.40, 0.20),
    (0.30, 0.15),
]


# ── Loaders (identical to leaderboard) ──────────────────────────────────────
def load_sym(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm>="09:30")&(hm<="16:00")].copy()
    pm  = df[(hm>="04:00")&(hm< "09:30")].copy()
    rth["date"] = rth["time"].dt.date; pm["date"] = pm["time"].dt.date
    return rth, pm

def build_pdhl(rth_df):
    rth_df = rth_df.copy(); rth_df["date"] = pd.to_datetime(rth_df["date"])
    dates = sorted(rth_df["date"].unique()); prev = {}
    for i in range(1, len(dates)):
        d=dates[i]; p=dates[i-1]; g=rth_df[rth_df["date"]==p]
        if not g.empty: prev[d]={"pdh":g["high"].max(),"pdl":g["low"].min()}
    return prev

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


# ── TP/SL exit ───────────────────────────────────────────────────────────────
def simulate_exit(ddf, ei, ep, tp_pct, sl_pct):
    n=len(ddf); tp=tp_pct/100; sl=sl_pct/100
    tp_price=ep*(1-tp); sl_price=ep*(1+sl)
    max_bar=min(ei+60,n-1)
    for i in range(ei, max_bar+1):
        hi=ddf.iloc[i]["high"]; lo=ddf.iloc[i]["low"]
        if hi>=sl_price: return ("loss",i-ei,-sl_pct)
        if lo<=tp_price: return ("win", i-ei, tp_pct)
    last=ddf.iloc[max_bar]["close"]
    pnl=(ep-last)/ep*100
    return ("timeout",max_bar-ei,pnl)


# ── Resistance scanner — short only, 1st touch ───────────────────────────────
def scan_res(ddf, level, tp_pct, sl_pct):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; ext=None; touch_num=0; i=0
    while i<n-3:
        hi=H[i]
        touching=hi>=level*(1-NEAR_PCT)
        if state=="IDLE":
            if touching: state="IN"; ext=C[i]; touch_num+=1
        elif state=="IN":
            if touching: ext=min(ext,C[i])
            else:
                bounced=ext is not None and (level-ext)/level>=BOUNCE
                if bounced and touch_num==1:
                    ei=i+1; ep=ddf.iloc[ei]["open"]
                    outcome,bars,pnl=simulate_exit(ddf,ei,ep,tp_pct,sl_pct)
                    results.append({"outcome":outcome,"bars":bars,"pnl":pnl,"ep":ep})
                state="IDLE"; ext=None
        i+=1
    return results


# ── Per-symbol runner ────────────────────────────────────────────────────────
def run_symbol(sym, tp_pct, sl_pct):
    rth_df,pm_df=load_sym(sym)
    pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df,rth_df)
    if pm_stats.empty: return pd.DataFrame()
    pdhl =build_pdhl(rth_df)
    sr_1h=build_pivots_clean(rth_df,lookback=60, wing=3)
    sr_4h=build_pivots_clean(rth_df,lookback=240,wing=5)
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    records=[]
    for date,ddf in rth_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm_stats.index: continue
        day=pm_stats.loc[date_ts]; gap=day["gap_pct"]
        if abs(gap)<=0.5: continue          # skip flat
        regime="Gap Down" if gap<-0.5 else "Gap Up"
        ddf=ddf.reset_index(drop=True)
        pmh=day["pm_high"]
        pd_info=pdhl.get(date_ts,{}); pdh=pd_info.get("pdh",np.nan)
        dk=date_ts.date()
        lv1h=sr_1h.get(date_ts,sr_1h.get(dk,[]))
        lv4h=sr_4h.get(date_ts,sr_4h.get(dk,[]))
        res_levels=[(pmh,"PMH")]
        if not pd.isna(pdh): res_levels.append((pdh,"PDH"))
        for lv,lt in lv1h:
            if lt=="res": res_levels.append((lv,"1H_Res"))
        for lv,lt in lv4h:
            if lt=="res": res_levels.append((lv,"4H_Res"))
        for level,lname in res_levels:
            if pd.isna(level): continue
            for e in scan_res(ddf,level,tp_pct,sl_pct):
                records.append({"sym":sym,"level":lname,"date":str(dk),
                                "gap_regime":regime,**e})
    return pd.DataFrame(records)


# ── Metrics ──────────────────────────────────────────────────────────────────
def metrics(s):
    if len(s)<5: return None
    wins=s[s["outcome"]=="win"]; losses=s[s["outcome"]=="loss"]
    wr=len(wins)/len(s)*100
    gw=wins["pnl"].sum(); gl=abs(losses["pnl"].sum()) if len(losses) else 1e-9
    pf=gw/gl; ev=s["pnl"].mean(); tpw=len(s)/WEEKS
    cum=s["pnl"].cumsum().values; peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=len(s),tpw=tpw,wr=wr,pf=pf,ev=ev,maxdd=maxdd)

def prow(label, s, w=24):
    m=metrics(s)
    if m is None: return
    mk=" <<<" if m["pf"]>=2.0 else (" <<" if m["pf"]>=1.5 else ("  <" if m["pf"]>=1.2 else ""))
    print(f"  {label:<{w}} {m['n']:>5} {m['tpw']:>6.1f}  "
          f"{m['wr']:>5.1f}%  {m['pf']:>6.3f}  {m['ev']:>+7.4f}%  {m['maxdd']:>+8.2f}%{mk}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__=="__main__":
    W=82
    all_data={}
    for tp,sl in CONFIGS:
        print(f"Running TP={tp} / SL={sl}...",flush=True)
        frames=[]
        for sym in SYMS:
            print(f"  {sym}",end=" ",flush=True)
            df=run_symbol(sym,tp,sl)
            if not df.empty: frames.append(df)
        print()
        combined=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
        all_data[(tp,sl)]=combined

    HDR=(f"  {'Label':<24} {'N':>5} {'T/Wk':>6}  "
         f"{'WR':>6}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>8}")
    SEP=f"  {'-'*78}"

    for tp,sl in CONFIGS:
        df=all_data[(tp,sl)]
        print(f"\n{'='*W}")
        print(f"  TP{tp:.2f}% / SL{sl:.2f}%  |  SHORT  |  Gap Up + Gap Down  |  5 symbols")
        print(f"{'='*W}")
        print(HDR); print(SEP)
        prow("ALL",df)
        print(SEP)

        # By symbol
        print(f"  -- By Symbol --")
        for sym in SYMS:
            prow(sym, df[df["sym"]==sym])
        print(SEP)

        # By regime
        print(f"  -- By Gap Regime --")
        for regime in ["Gap Down","Gap Up"]:
            prow(regime, df[df["gap_regime"]==regime])
        print(SEP)

        # By level
        print(f"  -- By Level --")
        for lv in ["PMH","PDH","1H_Res","4H_Res"]:
            prow(lv, df[df["level"]==lv])
        print(SEP)

        # Sym × Regime
        print(f"  -- Symbol × Regime --")
        for regime in ["Gap Down","Gap Up"]:
            print(f"  {regime}:")
            for sym in SYMS:
                prow(f"    {sym}", df[(df["sym"]==sym)&(df["gap_regime"]==regime)])
