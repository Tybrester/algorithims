"""Version B — monthly breakdown"""
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

VERSION_B_LEVELS = {
    "APP":  {"1H_Res","PMH"},
    "SMCI": {"1H_Res","PMH"},
    "HIMS": {"1H_Res","PMH"},
    "ARM":  {"PMH","4H_Res"},
    "MU":   {"1H_Res"},
}

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
        if gap<=0.5: continue
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
                            records.append({"sym":sym,"level":lname,
                                            "date":pd.Timestamp(dk),
                                            "outcome":out,"pnl":pnl})
                        state="IDLE"; ext=None
                i+=1
    return pd.DataFrame(records)


if __name__=="__main__":
    print("Scanning Version B...",flush=True)
    frames=[]
    for sym,lvls in VERSION_B_LEVELS.items():
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym,lvls)
        if not df.empty: frames.append(df)
    print()
    all_df=pd.concat(frames,ignore_index=True)
    all_df["month"]=all_df["date"].dt.to_period("M")

    W=72
    print(f"\n{'='*W}")
    print(f"  VERSION B — MONTHLY BREAKDOWN")
    print(f"  SHORT | Gap Up | Symbol-aware levels | TP+0.50% / SL-0.25%")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'N':>4}  {'WR':>6}  {'TP':>4}/{' SL':<4}  {'PF':>6}  {'EV/tr':>7}  {'Month PnL':>10}  {'Cumul':>8}")
    print(f"  {'-'*68}")

    months = sorted(all_df["month"].unique())
    cumul  = 0.0
    monthly_pnl = []

    for mo in months:
        s   = all_df[all_df["month"]==mo]
        n   = len(s)
        tp  = s["outcome"].eq("TP First").sum()
        sl  = s["outcome"].eq("SL First").sum()
        ne  = s["outcome"].eq("Neither").sum()
        wr  = tp/n*100 if n>0 else 0
        pf  = (tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
        ev  = s["pnl"].mean()
        mo_pnl = s["pnl"].sum()
        cumul += mo_pnl
        monthly_pnl.append(mo_pnl)
        sign = "+" if mo_pnl>=0 else ""
        win_flag = " ✓" if mo_pnl>0 else " ✗"
        print(f"  {str(mo):<10} {n:>4}  {wr:>5.1f}%  {tp:>4}/{sl:<4}  "
              f"{pf:>6.3f}  {ev:>+6.4f}%  {sign}{mo_pnl:>8.3f}%  {cumul:>+7.3f}%{win_flag}")

    print(f"  {'-'*68}")
    n=len(all_df); tp=all_df["outcome"].eq("TP First").sum(); sl=all_df["outcome"].eq("SL First").sum()
    pf_all=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    print(f"  {'TOTAL':<10} {n:>4}  {tp/n*100:>5.1f}%  {tp:>4}/{sl:<4}  "
          f"{pf_all:>6.3f}  {all_df['pnl'].mean():>+6.4f}%  {all_df['pnl'].sum():>+9.3f}%  {cumul:>+7.3f}%")

    wins  = sum(1 for p in monthly_pnl if p>0)
    total = len(monthly_pnl)
    print(f"\n  Profitable months: {wins}/{total}  ({wins/total*100:.0f}%)")
    print(f"  Best month:  +{max(monthly_pnl):.3f}%")
    print(f"  Worst month: {min(monthly_pnl):+.3f}%")
    print(f"  Avg monthly: +{np.mean(monthly_pnl):.3f}%")

    # Per-symbol monthly consistency
    print(f"\n{'='*W}")
    print(f"  PER-SYMBOL — profitable months")
    print(f"{'='*W}")
    print(f"  {'Sym':<6}  {'Win Mo':>6}  {'Tot Mo':>6}  {'Win%':>6}  {'Total PnL':>10}")
    print(f"  {'-'*40}")
    for sym in ["APP","SMCI","HIMS","ARM","MU"]:
        s=all_df[all_df["sym"]==sym]
        if s.empty: continue
        s=s.copy(); s["month"]=s["date"].dt.to_period("M")
        mo_pnl=s.groupby("month")["pnl"].sum()
        w=int((mo_pnl>0).sum()); t=len(mo_pnl)
        print(f"  {sym:<6}  {w:>6}  {t:>6}  {w/t*100:>5.0f}%  {s['pnl'].sum():>+10.3f}%")
