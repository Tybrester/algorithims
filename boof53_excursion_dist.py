"""
Excursion distribution for SHORT 1st-touch trades
5 symbols (no RKLB), Gap Up + Gap Down only
Shows for each target: Hit%, and minutes-to-hit distribution
Uses the raw 1m bar data to measure exact bars-to-target
"""
import pandas as pd
import numpy as np
import pytz, os

SYMS     = ["SMCI","HIMS","ARM","MU","APP"]
WEEKS    = 19.2
ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
TARGETS  = [0.0025, 0.0040, 0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.25%","+0.40%","+0.50%","+0.75%","+1.00%"]


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


def scan_res_excursion(ddf, level):
    """
    Find 1st-touch short entries, then for each target measure:
    - whether it was hit within 60 bars
    - how many bars (minutes) it took to hit
    """
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; ext=None; touch_num=0; i=0

    while i < n-3:
        touching = H[i] >= level*(1-NEAR_PCT)
        if state=="IDLE":
            if touching: state="IN"; ext=C[i]; touch_num+=1
        elif state=="IN":
            if touching: ext=min(ext,C[i])
            else:
                bounced = ext is not None and (level-ext)/level >= BOUNCE
                if bounced and touch_num==1:
                    ei=i+1; ep=ddf.iloc[ei]["open"]
                    max_bar=min(ei+60, n-1)
                    lows=ddf.iloc[ei:max_bar+1]["low"].values

                    row={"ep":ep}
                    for tgt, lbl in zip(TARGETS, T_LABELS):
                        tp_price=ep*(1-tgt)
                        hit_bars=[b for b,lo in enumerate(lows) if lo<=tp_price]
                        if hit_bars:
                            row[f"hit_{lbl}"]   = True
                            row[f"mins_{lbl}"]  = hit_bars[0] + 1   # bars = minutes
                        else:
                            row[f"hit_{lbl}"]   = False
                            row[f"mins_{lbl}"]  = np.nan
                    results.append(row)
                state="IDLE"; ext=None
        i+=1
    return results


def run_symbol(sym):
    rth_df,pm_df=load_sym(sym)
    pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
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
        if abs(gap)<=0.5: continue
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
            for e in scan_res_excursion(ddf,level):
                records.append({"sym":sym,"level":lname,"date":str(dk),**e})
    return pd.DataFrame(records)


if __name__=="__main__":
    print("Scanning...",flush=True)
    frames=[]
    for sym in SYMS:
        print(f"  {sym}",end=" ",flush=True)
        df=run_symbol(sym)
        if not df.empty: frames.append(df)
    print()
    all_df=pd.concat(frames,ignore_index=True)
    N=len(all_df)

    W=80
    print(f"\n{'='*W}")
    print(f"  SHORT EXCURSION DISTRIBUTION — {', '.join(SYMS)}")
    print(f"  Gap Up + Gap Down  |  1st touch resistance  |  N={N}  (~{N/WEEKS:.1f}/wk)")
    print(f"  All times in minutes (bars) from entry")
    print(f"{'='*W}")
    print(f"  {'Target':<9} {'Hit%':>6}  {'Hits':>5}  {'AvgMin':>7}  "
          f"{'Median':>7}  {'p25':>6}  {'p75':>6}  {'p90':>6}")
    print(f"  {'-'*66}")

    for tgt, lbl in zip(TARGETS, T_LABELS):
        hits  = all_df[all_df[f"hit_{lbl}"]==True]
        hit_pct = len(hits)/N*100
        mins  = hits[f"mins_{lbl}"].dropna()
        if len(mins):
            avg = mins.mean()
            med = mins.median()
            p25 = mins.quantile(0.25)
            p75 = mins.quantile(0.75)
            p90 = mins.quantile(0.90)
        else:
            avg=med=p25=p75=p90=np.nan
        print(f"  {lbl:<9} {hit_pct:>5.1f}%  {len(hits):>5}  "
              f"{avg:>7.1f}  {med:>7.1f}  {p25:>6.1f}  {p75:>6.1f}  {p90:>6.1f}")

    # Also by level
    print(f"\n{'='*W}")
    print(f"  BY LEVEL  (TP+0.50% only)")
    print(f"{'='*W}")
    print(f"  {'Level':<10} {'N':>5}  {'Hit%':>6}  {'AvgMin':>7}  "
          f"{'Median':>7}  {'p25':>6}  {'p75':>6}  {'p90':>6}")
    print(f"  {'-'*62}")
    for lv in ["PMH","PDH","1H_Res","4H_Res"]:
        s=all_df[all_df["level"]==lv]
        if len(s)<5: continue
        hits=s[s["hit_+0.50%"]==True]
        hp=len(hits)/len(s)*100
        mins=hits["mins_+0.50%"].dropna()
        if len(mins):
            print(f"  {lv:<10} {len(s):>5}  {hp:>5.1f}%  "
                  f"{mins.mean():>7.1f}  {mins.median():>7.1f}  "
                  f"{mins.quantile(0.25):>6.1f}  {mins.quantile(0.75):>6.1f}  "
                  f"{mins.quantile(0.90):>6.1f}")

    # Also by symbol
    print(f"\n{'='*W}")
    print(f"  BY SYMBOL  (TP+0.50% only)")
    print(f"{'='*W}")
    print(f"  {'Sym':<7} {'N':>5}  {'Hit%':>6}  {'AvgMin':>7}  "
          f"{'Median':>7}  {'p25':>6}  {'p75':>6}  {'p90':>6}")
    print(f"  {'-'*62}")
    for sym in SYMS:
        s=all_df[all_df["sym"]==sym]
        if len(s)<5: continue
        hits=s[s["hit_+0.50%"]==True]
        hp=len(hits)/len(s)*100
        mins=hits["mins_+0.50%"].dropna()
        if len(mins):
            print(f"  {sym:<7} {len(s):>5}  {hp:>5.1f}%  "
                  f"{mins.mean():>7.1f}  {mins.median():>7.1f}  "
                  f"{mins.quantile(0.25):>6.1f}  {mins.quantile(0.75):>6.1f}  "
                  f"{mins.quantile(0.90):>6.1f}")
