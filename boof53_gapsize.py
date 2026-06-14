"""
Version B vs C + gap size breakdown
B: Gap Up only (current champion)
C: Gap Up + Gap Down (generalization test)
Plus gap size buckets across all gap-up trades
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

def scan_sym(sym, allowed_levels, gap_filter="up"):
    """gap_filter: 'up', 'down', 'both'"""
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
        # Apply gap filter
        if gap_filter=="up"   and gap <= 0.5: continue
        if gap_filter=="down" and gap >= -0.5: continue
        if gap_filter=="both" and abs(gap) <= 0.5: continue
        regime = "Gap Up" if gap > 0.5 else "Gap Down"
        abs_gap = abs(gap)
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
                                            "gap_pct":gap,"abs_gap":abs_gap,
                                            "regime":regime,"outcome":out,"pnl":pnl})
                        state="IDLE"; ext=None
                i+=1
    return pd.DataFrame(records)

def mrow(s, weeks=None):
    if len(s)<3: return None
    n=len(s); tp=s["outcome"].eq("TP First").sum(); sl=s["outcome"].eq("SL First").sum()
    wr=tp/n*100; pf=(tp*TP_PCT*100)/(sl*SL_PCT*100) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/(weeks or WEEKS)
    return dict(n=n,tpw=tpw,wr=wr,tp=tp,sl=sl,pf=pf,ev=ev)

def prow(label, m, w=20):
    if m is None: return
    mk=" <<<" if m["pf"]>=2.0 else (" <<" if m["pf"]>=1.5 else ("  <" if m["pf"]>=1.2 else ("  -" if m["pf"]<1.0 else "")))
    print(f"  {label:<{w}} {m['n']:>5} {m['tpw']:>6.1f}  {m['wr']:>5.1f}%  "
          f"{m['tp']:>4}/{m['sl']:<4}  {m['pf']:>6.3f}  {m['ev']:>+7.4f}%{mk}")

HDR=(f"  {'Label':<20} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}")
SEP=f"  {'-'*72}"
W=76


if __name__=="__main__":
    # ── Scan both versions ────────────────────────────────────────────────────
    print("Scanning Version B (Gap Up)...",flush=True)
    b_frames=[]
    for sym,lvls in VERSION_B_LEVELS.items():
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym,lvls,gap_filter="up")
        if not df.empty: b_frames.append(df)
    print()
    b_df=pd.concat(b_frames,ignore_index=True)

    print("Scanning Version C (Gap Up + Down)...",flush=True)
    c_frames=[]
    for sym,lvls in VERSION_B_LEVELS.items():
        print(f"  {sym}",end=" ",flush=True)
        df=scan_sym(sym,lvls,gap_filter="both")
        if not df.empty: c_frames.append(df)
    print()
    c_df=pd.concat(c_frames,ignore_index=True)
    c_down=c_df[c_df["regime"]=="Gap Down"]

    # ═══ HEAD TO HEAD ════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  VERSION B vs C  |  Symbol-aware levels  |  TP+0.50% / SL-0.25%")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("B: Gap Up only",      mrow(b_df))
    prow("C: Gap Up+Down",      mrow(c_df))
    print(SEP)
    prow("  Gap Up  subset",    mrow(c_df[c_df["regime"]=="Gap Up"]))
    prow("  Gap Down subset",   mrow(c_down))

    # By symbol — Gap Down
    print(f"\n  GAP DOWN by symbol:")
    print(HDR); print(SEP)
    for sym in ["APP","SMCI","HIMS","ARM","MU"]:
        s=c_down[c_down["sym"]==sym]
        prow(f"  {sym}", mrow(s))

    # By level — Gap Down
    print(f"\n  GAP DOWN by level:")
    print(HDR); print(SEP)
    for lv in ["1H_Res","PMH","4H_Res"]:
        s=c_down[c_down["level"]==lv]
        if len(s)>=3: prow(f"  {lv}", mrow(s))

    # ═══ GAP SIZE BUCKETS ════════════════════════════════════════════════════
    BUCKETS = [
        ("0.50–1.00%", 0.50,  1.00),
        ("1.00–2.00%", 1.00,  2.00),
        ("2.00–3.00%", 2.00,  3.00),
        (">3.00%",     3.00, 99.00),
    ]

    print(f"\n{'='*W}")
    print(f"  GAP SIZE BUCKETS — Version B (Gap Up only)")
    print(f"  abs(gap_pct) bucketed")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for lbl,lo,hi in BUCKETS:
        s=b_df[(b_df["abs_gap"]>lo)&(b_df["abs_gap"]<=hi)]
        prow(lbl, mrow(s))

    print(f"\n{'='*W}")
    print(f"  GAP SIZE BUCKETS — Version C (Gap Up + Down combined)")
    print(f"  abs(gap_pct) bucketed")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for lbl,lo,hi in BUCKETS:
        s=c_df[(c_df["abs_gap"]>lo)&(c_df["abs_gap"]<=hi)]
        prow(lbl, mrow(s))

    # ── Granular: gap buckets × regime for C ─────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  GAP SIZE × REGIME — Version C")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for regime in ["Gap Up","Gap Down"]:
        print(f"  -- {regime} --")
        for lbl,lo,hi in BUCKETS:
            s=c_df[(c_df["regime"]==regime)&(c_df["abs_gap"]>lo)&(c_df["abs_gap"]<=hi)]
            prow(f"  {lbl}", mrow(s))
        print(SEP)

    # ── Best gap range summary ────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  SUMMARY — where does the edge concentrate?")
    print(f"{'='*W}")
    print(f"  Avg gap on winning trades:  {b_df[b_df['outcome']=='TP First']['abs_gap'].mean():.2f}%")
    print(f"  Avg gap on losing trades:   {b_df[b_df['outcome']=='SL First']['abs_gap'].mean():.2f}%")
    print(f"  Median gap all trades:      {b_df['abs_gap'].median():.2f}%")
    q25=b_df['abs_gap'].quantile(0.25); q75=b_df['abs_gap'].quantile(0.75)
    print(f"  Gap p25/p75:                {q25:.2f}% / {q75:.2f}%")
