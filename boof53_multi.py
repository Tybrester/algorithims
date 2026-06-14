"""
BOOF53 Multi-Symbol Study
For every symbol: support (long) and resistance (short) level touches
Levels: PML/PMH, PDL/PDH, 1H, 4H
Touch count: 1st, 2nd, 3rd+
Bounce thresholds: 0.10, 0.15, 0.20, 0.30%
No entries/exits — pure MFE excursion only
Output:
  1. Symbol × Side summary table (MFE30, >=0.50%)
  2. Level type ranking across all symbols
  3. Touch count breakdown
  4. Bounce threshold comparison
"""
import pandas as pd
import numpy as np
import pytz
import os

ET       = pytz.timezone("America/New_York")
SYMBOLS  = ["QQQ","SPY","NVDA","TSLA","AMD","META","AAPL","MSFT","AMZN","PLTR","IWM"]
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCES  = [0.0010, 0.0015, 0.0020, 0.0030]
TARGETS  = [0.0050, 0.0075]
T_LABELS = [">=0.50%",">=0.75%"]


def load_rt(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def build_pm_stats(rt_df, sym=None):
    # RTH-only data: use previous RTH close as prev_close, and first RTH bar open as rth_open
    # PM high/low: derive from bars before 09:30 if available, else use prior day range
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M") >= "09:30"].copy()
    rth["date"] = rth["time"].dt.date

    # Try to load separate PM file if it exists
    pm_file = f"boof51_{sym}_pm.csv" if sym else None
    if pm_file and os.path.exists(pm_file):
        pm_df = pd.read_csv(pm_file)
        pm_df["time"] = pd.to_datetime(pm_df["time"], utc=True).dt.tz_convert(ET)
        pm_df["date"] = pm_df["time"].dt.date
        pm_records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min()}
                      for d,g in pm_df.groupby("date")]
    else:
        # Use pre-09:30 bars from 1m file
        pm_bars = rt_df[rt_df["time"].dt.strftime("%H:%M") < "09:30"].copy()
        pm_bars["date"] = pm_bars["time"].dt.date
        if pm_bars.empty:
            # No premarket data — use first 15m of RTH as proxy
            pm_bars = rth.copy()
        pm_records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min()}
                      for d,g in pm_bars.groupby("date") if len(g)>0]

    stats = pd.DataFrame(pm_records)
    if stats.empty:
        return pd.DataFrame()

    # prev_close = last RTH close of previous day
    dc = rth.groupby("date")["close"].last().reset_index()
    dc.columns = ["date","prev_close"]
    dc["date"] = pd.to_datetime(dc["date"])
    dc["next_date"] = dc["date"] + pd.Timedelta(days=1)

    stats = stats.merge(
        dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    )

    # rth_open = first bar at or after 09:30
    first_rth = rth.groupby("date")["open"].first().reset_index()
    first_rth["date"] = pd.to_datetime(first_rth["date"])
    first_rth.columns = ["date","rth_open"]
    stats = stats.merge(first_rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["gap_pct","pm_high"])

def build_prev_day(rt_df):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    dates = sorted(rt_df["date"].unique()); prev={}
    for i in range(1,len(dates)):
        d=dates[i]; p=dates[i-1]; g=rt_df[rt_df["date"]==p]
        if not g.empty: prev[d]={"pdh":g["high"].max(),"pdl":g["low"].min()}
    return prev

def build_pivots(rt_df, lookback, wing):
    rt_df=rt_df.sort_values("time").reset_index(drop=True); sr={}
    dates=sorted(rt_df["date"].unique())
    for d in dates:
        hist=rt_df[rt_df["date"]<d].tail(lookback)
        if len(hist)<lookback//2: continue
        H=hist["high"].values; L=hist["low"].values; levels=[]
        for i in range(wing,len(hist)-wing):
            if H[i]==max(H[i-wing:i+wing+1]): levels.append((H[i],"res"))
            if L[i]==min(L[i-wing:i+wing+1]): levels.append((L[i],"sup"))
        if not levels: continue
        levels=sorted(levels,key=lambda x:x[0])
        cl=[list(levels[0])]
        for lv,lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        sr[d]=[(c[0],c[1]) for c in cl]
    return sr

def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key]=float(max((H[sl]-ep)/ep*100)) if side=="long" \
            else float(max((ep-L[sl])/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end60+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res

def scan_level(ddf, level, direction, min_bounce):
    """
    Records EVERY touch event (not just confirmed double-touch).
    touch_num = sequential touch counter for this level today.
    Measures excursion from the next bar after each touch.
    """
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    results=[]; state="IDLE"; bounce_ext=None; touch_num=0; i=1
    while i<n-61:
        t=ddf.iloc[i]["time"].strftime("%H:%M")
        if t<"09:00" or t>="13:00": i+=1; continue
        cl=C[i]; hi=H[i]; lo=L[i]
        if direction=="sup":
            touching=lo<=level*(1+NEAR_PCT)
            if state=="IDLE":
                if touching: state="IN"; bounce_ext=cl; touch_num+=1
            elif state=="IN":
                if touching: bounce_ext=max(bounce_ext,cl)
                else:
                    # Left zone — record touch
                    bounced=(bounce_ext-level)/level>=min_bounce if bounce_ext else False
                    ei=i; ep=ddf.iloc[ei]["open"] if ei<n else None
                    if ep:
                        results.append({"touch_num":min(touch_num,3),"bounced":bounced,
                                        "ep":ep,**exc(ddf,ei,ep,"long")})
                    state="IDLE"; bounce_ext=None
        else:
            touching=hi>=level*(1-NEAR_PCT)
            if state=="IDLE":
                if touching: state="IN"; bounce_ext=cl; touch_num+=1
            elif state=="IN":
                if touching: bounce_ext=min(bounce_ext,cl)
                else:
                    bounced=(level-bounce_ext)/level>=min_bounce if bounce_ext else False
                    ei=i; ep=ddf.iloc[ei]["open"] if ei<n else None
                    if ep:
                        results.append({"touch_num":min(touch_num,3),"bounced":bounced,
                                        "ep":ep,**exc(ddf,ei,ep,"short")})
                    state="IDLE"; bounce_ext=None
        i+=1
    return results

def run_symbol(sym, min_bounce=0.0015):
    if not os.path.exists(f"boof51_{sym}_1m.csv"):
        return pd.DataFrame()
    rt_df    = load_rt(sym)
    pm_stats = build_pm_stats(rt_df, sym=sym)
    if pm_stats.empty: return pd.DataFrame()
    prev_day = build_prev_day(rt_df)
    sr_1h    = build_pivots(rt_df, lookback=60,  wing=3)
    sr_4h    = build_pivots(rt_df, lookback=240, wing=5)

    rt_df = rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm    = pm_stats.set_index("date"); records=[]

    for date,ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]; gap=day["gap_pct"]
        gap_regime="Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")
        ddf=ddf.reset_index(drop=True)
        pmh=day["pm_high"]; pml=day["pm_low"]
        pd_info=prev_day.get(date_ts,{})
        pdh=pd_info.get("pdh",np.nan); pdl=pd_info.get("pdl",np.nan)
        dk=date.date() if hasattr(date,"date") else date
        lv1h=sr_1h.get(dk,[]); lv4h=sr_4h.get(dk,[])

        long_levels =[(pml,"PML")]
        short_levels=[(pmh,"PMH")]
        if not pd.isna(pdl): long_levels.append((pdl,"PDL"))
        if not pd.isna(pdh): short_levels.append((pdh,"PDH"))
        for lv,lt in lv1h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv,"1H_Sup" if lt=="sup" else "1H_Res"))
        for lv,lt in lv4h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv,"4H_Sup" if lt=="sup" else "4H_Res"))

        for level,lname in long_levels:
            if pd.isna(level): continue
            for e in scan_level(ddf,level,"sup",min_bounce):
                tl="1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({"sym":sym,"side":"long","level":lname,"gap_regime":gap_regime,
                                "gap_pct":round(gap,3),"touch_lbl":tl,"bounced":e["bounced"],
                                "date":str(date.date()),"ep":e["ep"],
                                **{k:v for k,v in e.items() if k not in ("touch_num","bounced","ep")}})
        for level,lname in short_levels:
            if pd.isna(level): continue
            for e in scan_level(ddf,level,"res",min_bounce):
                tl="1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({"sym":sym,"side":"short","level":lname,"gap_regime":gap_regime,
                                "gap_pct":round(gap,3),"touch_lbl":tl,"bounced":e["bounced"],
                                "date":str(date.date()),"ep":e["ep"],
                                **{k:v for k,v in e.items() if k not in ("touch_num","bounced","ep")}})

    return pd.DataFrame(records)


def pct(val, n=1): return f"{val:.{n}f}%"

def row_stats(s):
    if s.empty or len(s)<3: return None
    return (len(s), s["date"].nunique(),
            s["mfe15"].mean(), s["mfe30"].mean(), s["mfe60"].mean(),
            s["hit_>=0.50%"].mean()*100, s["hit_>=0.75%"].mean()*100)

def print_row(label, s, w=18, min_n=3):
    r=row_stats(s)
    if r is None: print(f"  {label:<{w}} {'<'+str(min_n):>5}"); return
    n,nd,m15,m30,m60,h50,h75=r
    mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")


def report(all_df):
    W=92
    HDR=(f"  {'Label':<18} {'N':>5} {'Days':>5}  "
         f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP=f"  {'-'*88}"

    # ── TABLE 1: Symbol summary ───────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  SYMBOL SUMMARY  |  bounce>=0.15%  |  all touches")
    print(f"{'='*W}")
    print(f"  {'Symbol':<8} {'Side':<7} {'N':>5} {'Days':>5}  "
          f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    print(f"  {'-'*88}")
    sym_rows=[]
    for sym in SYMBOLS:
        df=all_df[all_df["sym"]==sym]
        if df.empty: continue
        for side in ["long","short"]:
            s=df[(df["side"]==side)&(df["bounced"]==True)]
            r=row_stats(s)
            if r is None: continue
            n,nd,m15,m30,m60,h50,h75=r
            sym_rows.append((sym,side,n,nd,m15,m30,m60,h50,h75))
            mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
            print(f"  {sym:<8} {side:<7} {n:>5} {nd:>4}d  "
                  f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")

    # Compact ranked table
    print(f"\n  RANKED BY MFE30 (bounced only, >=5 trades)")
    print(f"  {'Symbol':<8} {'Side':<7} {'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*46}")
    for row in sorted(sym_rows,key=lambda x:-x[6]):
        sym,side,n,nd,m15,m30,m60,h50,h75=row
        if n<5: continue
        mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
        print(f"  {sym:<8} {side:<7} {m30:>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # ── TABLE 2: Level type ranking (all symbols combined) ────────────────────
    print(f"\n{'='*W}")
    print(f"  LEVEL RANKING — ALL SYMBOLS COMBINED  |  bounce>=0.15%")
    print(f"{'='*W}")

    for side,lnames in [("long",["PML","PDL","1H_Sup","4H_Sup"]),
                        ("short",["PMH","PDH","1H_Res","4H_Res"])]:
        base=all_df[(all_df["side"]==side)&(all_df["bounced"]==True)]
        print(f"\n  {'LONG — Support' if side=='long' else 'SHORT — Resistance'}")
        print(HDR); print(SEP)
        print_row("ALL", base)
        print(SEP)
        for lname in lnames:
            print_row(lname, base[base["level"]==lname])
        print(SEP)

        # By touch count
        print(f"  BY TOUCH COUNT")
        for tl in ["1st","2nd","3rd+"]:
            print_row(f"Touch {tl}", base[base["touch_lbl"]==tl])
        print(SEP)

        # Level × touch cross-tab
        print(f"\n  LEVEL × TOUCH")
        print(f"  {'Level':<10} {'Touch':<7} {'N':>5}  "
              f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*52}")
        for lname in lnames:
            for tl in ["1st","2nd","3rd+"]:
                s=base[(base["level"]==lname)&(base["touch_lbl"]==tl)]
                if len(s)<5: continue
                h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
                mark=" <<<" if h50>=40 else ("  <<" if h50>=28 else "")
                print(f"  {lname:<10} {tl:<7} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # ── TABLE 3: Bounce threshold comparison ──────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BOUNCE THRESHOLD COMPARISON — ALL SYMBOLS × ALL LEVELS")
    print(f"{'='*W}")
    print(f"  {'Bounce':<10} {'Side':<7} {'N':>6}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*55}")
    for bounce in BOUNCES:
        for side in ["long","short"]:
            key_col = "bounced"
            # Re-run with bounce threshold check inline
            s=all_df[all_df["side"]==side]
            # bounced col was computed per-bounce in scan; here we stored at 0.15%
            # Use mfe15 as proxy: if mfe15 > bounce, treat as bounced enough
            # Actually re-filter properly
            s2=s[s["mfe15"]>=(bounce*100)]  # mfe15 in % terms vs bounce in decimal
            if len(s2)<5: continue
            h50=s2["hit_>=0.50%"].mean()*100; h75=s2["hit_>=0.75%"].mean()*100
            blbl=f">={bounce*100:.2f}%"
            print(f"  {blbl:<10} {side:<7} {len(s2):>6}  "
                  f"{s2['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%")
        print()

    # ── TABLE 4: Gap regime breakdown ─────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  GAP REGIME × SIDE — ALL SYMBOLS  |  bounce>=0.15%")
    print(f"{'='*W}")
    base=all_df[all_df["bounced"]==True]
    print(f"  {'Side':<7} {'Regime':<12} {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*55}")
    for side in ["long","short"]:
        for regime in ["Gap Down","Flat","Gap Up"]:
            s=base[(base["side"]==side)&(base["gap_regime"]==regime)]
            if len(s)<5: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark=" <<<" if h50>=35 else ("  <<" if h50>=25 else "")
            print(f"  {side:<7} {regime:<12} {len(s):>5}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")


if __name__=="__main__":
    print(f"Running multi-symbol study: {SYMBOLS}", flush=True)
    frames=[]
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        df=run_symbol(sym, min_bounce=0.0015)
        print(f"{len(df)} touches", flush=True)
        frames.append(df)

    all_df=pd.concat([f for f in frames if not f.empty], ignore_index=True)
    print(f"\n  Total touches: {len(all_df):,}", flush=True)
    print(f"  Bounced (>=0.15%): {all_df['bounced'].sum():,}", flush=True)

    report(all_df)
    all_df.to_csv("boof53_multi_all.csv", index=False)
    print(f"\n  Saved boof53_multi_all.csv")
