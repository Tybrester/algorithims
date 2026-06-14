"""March 2026 deep dive — what went wrong"""
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

def day_atr(ddf):
    """Rough intraday range as volatility proxy"""
    return ddf["high"].max() - ddf["low"].min()

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
        d_range=day_atr(ddf)
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
                                            "gap_pct":round(gap,3),
                                            "day_range":round(d_range,4),
                                            "ep":round(ep,4),
                                            "outcome":out,"pnl":pnl})
                        state="IDLE"; ext=None
                i+=1
    return pd.DataFrame(records)


def breakdown(s, label, W=70):
    n=len(s); tp=s["outcome"].eq("TP First").sum(); sl=s["outcome"].eq("SL First").sum()
    wr=tp/n*100; pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    print(f"  {label:<28}  N={n:>3}  WR={wr:>4.0f}%  TP={tp:>2}/SL={sl:<2}  PF={pf:.3f}")


if __name__=="__main__":
    print("Scanning...",flush=True)
    frames=[]
    for sym,lvls in VERSION_B_LEVELS.items():
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym,lvls)
        if not df.empty: frames.append(df)
    print()
    all_df=pd.concat(frames,ignore_index=True)
    all_df["month"]=all_df["date"].dt.to_period("M")

    mar  = all_df[all_df["month"]=="2026-03"]
    rest = all_df[all_df["month"]!="2026-03"]
    W=72

    print(f"\n{'='*W}")
    print(f"  MARCH 2026 vs REST  |  Version B  |  SHORT  |  Gap Up")
    print(f"{'='*W}")
    breakdown(all_df, "ALL MONTHS")
    breakdown(mar,    "March 2026  ← BAD")
    breakdown(rest,   "All other months")

    # ── By symbol ─────────────────────────────────────────────────────────────
    print(f"\n  BY SYMBOL")
    print(f"  {'-'*60}")
    print(f"  {'Sym':<8}  {'--- March ---':^22}  {'--- Rest ---':^22}")
    print(f"  {'':8}  {'N':>3} {'WR':>5} {'PF':>6}    {'N':>3} {'WR':>5} {'PF':>6}")
    print(f"  {'-'*60}")
    for sym in ["APP","SMCI","HIMS","ARM","MU"]:
        m=mar[mar["sym"]==sym]; r=rest[rest["sym"]==sym]
        def row(s):
            if len(s)<1: return "  -    -      -  "
            n=len(s); tp=s["outcome"].eq("TP First").sum(); sl=s["outcome"].eq("SL First").sum()
            pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
            return f"{n:>3} {tp/n*100:>4.0f}%  {pf:>5.3f}"
        print(f"  {sym:<8}  {row(m)}    {row(r)}")

    # ── By level ──────────────────────────────────────────────────────────────
    print(f"\n  BY LEVEL")
    print(f"  {'-'*60}")
    print(f"  {'Level':<10}  {'--- March ---':^22}  {'--- Rest ---':^22}")
    print(f"  {'':10}  {'N':>3} {'WR':>5} {'PF':>6}    {'N':>3} {'WR':>5} {'PF':>6}")
    print(f"  {'-'*60}")
    for lv in ["1H_Res","PMH","4H_Res"]:
        m=mar[mar["level"]==lv]; r=rest[rest["level"]==lv]
        def row(s):
            if len(s)<1: return "  -    -      -  "
            n=len(s); tp=s["outcome"].eq("TP First").sum(); sl=s["outcome"].eq("SL First").sum()
            pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
            return f"{n:>3} {tp/n*100:>4.0f}%  {pf:>5.3f}"
        print(f"  {lv:<10}  {row(m)}    {row(r)}")

    # ── Gap size in March vs rest ─────────────────────────────────────────────
    print(f"\n  GAP SIZE (Gap Up days only)")
    print(f"  {'-'*40}")
    print(f"  {'':20}  {'Avg Gap%':>8}  {'Med Gap%':>9}  {'Trades':>7}")
    m_gaps=mar.drop_duplicates("date")[["date","gap_pct"]]
    r_gaps=rest.drop_duplicates("date")[["date","gap_pct"]]
    print(f"  {'March 2026':<20}  {m_gaps['gap_pct'].mean():>8.2f}%  {m_gaps['gap_pct'].median():>9.2f}%  {len(mar):>7}")
    print(f"  {'Rest of dataset':<20}  {r_gaps['gap_pct'].mean():>8.2f}%  {r_gaps['gap_pct'].median():>9.2f}%  {len(rest):>7}")

    # ── Day range / volatility ────────────────────────────────────────────────
    print(f"\n  INTRADAY RANGE (volatility proxy)")
    print(f"  {'-'*40}")
    print(f"  {'':20}  {'Avg Range':>9}  {'Med Range':>9}")
    m_rng=mar.drop_duplicates("date")[["date","day_range"]]
    r_rng=rest.drop_duplicates("date")[["date","day_range"]]
    print(f"  {'March 2026':<20}  {m_rng['day_range'].mean():>9.4f}  {m_rng['day_range'].median():>9.4f}")
    print(f"  {'Rest of dataset':<20}  {r_rng['day_range'].mean():>9.4f}  {r_rng['day_range'].median():>9.4f}")

    # ── Full March trade log ──────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  MARCH 2026 — EVERY TRADE")
    print(f"{'='*W}")
    print(f"  {'Date':<12} {'Sym':<6} {'Level':<8} {'Gap%':>6}  {'EP':>8}  {'Outcome':<10} {'PnL':>7}")
    print(f"  {'-'*64}")
    mar_sorted=mar.sort_values("date")
    for _,row in mar_sorted.iterrows():
        print(f"  {str(row['date'].date()):<12} {row['sym']:<6} {row['level']:<8} "
              f"{row['gap_pct']:>5.2f}%  {row['ep']:>8.4f}  {row['outcome']:<10} {row['pnl']:>+6.3f}%")
    print(f"  {'-'*64}")
    print(f"  Total PnL: {mar['pnl'].sum():+.3f}%")
