"""
BOOF53 Version A vs B
A: APP/SMCI/HIMS/ARM | 1H_Res+PMH | Gap Up only
B: Symbol-aware levels | Gap Up only | MU included
TP 0.50% / SL 0.25%
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

# Symbol-aware level map for Version B
VERSION_B_LEVELS = {
    "APP":  {"1H_Res", "PMH"},
    "SMCI": {"1H_Res", "PMH"},
    "HIMS": {"1H_Res", "PMH"},
    "ARM":  {"PMH", "4H_Res"},
    "MU":   {"1H_Res"},
}
VERSION_A_SYMS   = ["APP","SMCI","HIMS","ARM"]
VERSION_A_LEVELS = {"1H_Res","PMH"}


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
        if gap <= 0.5: continue           # Gap Up only
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
                            records.append({"sym":sym,"level":lname,
                                            "date":str(dk),"outcome":out})
                        state="IDLE"; ext=None
                i+=1
    return pd.DataFrame(records)

def metrics(s):
    if len(s)<3: return None
    n=len(s); tp=s["outcome"].eq("TP First").sum(); sl=s["outcome"].eq("SL First").sum()
    ne=s["outcome"].eq("Neither").sum()
    pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    ev=(tp/n*TP_PCT - sl/n*SL_PCT)*100
    cum=np.cumsum(np.where(s["outcome"]=="TP First",TP_PCT*100,
                  np.where(s["outcome"]=="SL First",-SL_PCT*100,0.0)))
    maxdd=(cum-np.maximum.accumulate(cum)).min()
    return dict(n=n,tpw=n/WEEKS,tp=tp,sl=sl,ne=ne,wr=tp/n*100,pf=pf,ev=ev,maxdd=maxdd)

def prow(label, s, w=24):
    m=metrics(s)
    if m is None: return
    mk=" <<<" if m["pf"]>=1.8 else (" <<" if m["pf"]>=1.4 else ("  <" if m["pf"]>=1.1 else ""))
    print(f"  {label:<{w}} {m['n']:>4} {m['tpw']:>5.1f}  "
          f"{m['wr']:>5.1f}%  {m['tp']:>4}/{m['sl']:<4}  "
          f"{m['pf']:>6.3f}  {m['ev']:>+7.4f}%  {m['maxdd']:>+7.2f}%{mk}")

HDR=(f"  {'Label':<24} {'N':>4} {'T/Wk':>5}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*80}"
W=84


if __name__=="__main__":
    # ── Build Version A ───────────────────────────────────────────────────────
    print("Scanning Version A...",flush=True)
    a_frames=[]
    for sym in VERSION_A_SYMS:
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym, VERSION_A_LEVELS)
        if not df.empty: a_frames.append(df)
    print()
    a_df=pd.concat(a_frames,ignore_index=True) if a_frames else pd.DataFrame()

    # ── Build Version B ───────────────────────────────────────────────────────
    print("Scanning Version B...",flush=True)
    b_frames=[]
    for sym,lvls in VERSION_B_LEVELS.items():
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym, lvls)
        if not df.empty: b_frames.append(df)
    print()
    b_df=pd.concat(b_frames,ignore_index=True) if b_frames else pd.DataFrame()

    # ═══ VERSION A ═══════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  VERSION A  |  APP SMCI HIMS ARM  |  1H_Res + PMH  |  Gap Up only")
    print(f"  SHORT  |  TP+0.50% / SL-0.25%  |  1st touch, +1 bar entry")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("VERSION A TOTAL", a_df)
    print(SEP)
    for sym in VERSION_A_SYMS:
        prow(sym, a_df[a_df["sym"]==sym])
    print(SEP)
    for lv in ["1H_Res","PMH"]:
        prow(lv, a_df[a_df["level"]==lv])
    print(SEP)
    print(f"  -- Symbol × Level --")
    for sym in VERSION_A_SYMS:
        for lv in ["1H_Res","PMH"]:
            s=a_df[(a_df["sym"]==sym)&(a_df["level"]==lv)]
            if len(s)>=3: prow(f"  {sym} {lv}", s)

    # ═══ VERSION B ═══════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  VERSION B  |  Symbol-aware levels  |  Gap Up only  |  MU included")
    print(f"  APP/SMCI/HIMS: 1H_Res+PMH  |  ARM: PMH+4H_Res  |  MU: 1H_Res")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("VERSION B TOTAL", b_df)
    print(SEP)
    b_sym_order=["APP","SMCI","HIMS","ARM","MU"]
    for sym in b_sym_order:
        prow(sym, b_df[b_df["sym"]==sym])
    print(SEP)
    for lv in ["1H_Res","PMH","4H_Res"]:
        s=b_df[b_df["level"]==lv]
        if len(s)>=3: prow(lv, s)
    print(SEP)
    print(f"  -- Symbol × Level --")
    for sym,lvls in VERSION_B_LEVELS.items():
        for lv in sorted(lvls):
            s=b_df[(b_df["sym"]==sym)&(b_df["level"]==lv)]
            if len(s)>=3: prow(f"  {sym} {lv}", s)

    # ═══ HEAD-TO-HEAD ════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  HEAD-TO-HEAD SUMMARY")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("Version A", a_df)
    prow("Version B", b_df)
