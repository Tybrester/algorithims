"""
BOOF53 Expansion Test Matrix
Symbols: APP, SMCI, HIMS, ARM, MU
Gap Up > 0.5% only

Tests:
  - Level families: PMH/PML, PDH/PDL, 10m/30m/1H/2H/4H pivots, Daily swing
  - Setup type: Res rejection (short), Res breakout (long), Sup rejection (long), Sup breakdown (short)
  - Touch count: 1st, 2nd, 3rd+
  - Confirmation: A=+1bar, D=0.15% away, E=0.25% away
  - TP/SL: 0.50/0.25, 0.75/0.40, 0.40/0.20
"""
import pandas as pd
import numpy as np
import pytz, warnings
warnings.filterwarnings("ignore")

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
MAX_BARS = 60
WEEKS    = 19.2
SYMS     = ["APP","SMCI","HIMS","ARM","MU"]

CONFIGS = [
    (0.50, 0.25),
    (0.75, 0.40),
    (0.40, 0.20),
]

# Pivot timeframe params: (label, lookback_bars, wing)
PIVOT_TFS = [
    ("10m",  10,  2),
    ("30m",  30,  3),
    ("1H",   60,  3),
    ("2H",  120,  4),
    ("4H",  240,  5),
]


# ── Data loaders ─────────────────────────────────────────────────────────────
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
    return stats.dropna(subset=["gap_pct","pm_high","pm_low"]).set_index("date")

def build_pdhl(rth_df):
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    dates=sorted(rth_df["date"].unique()); prev={}
    for i in range(1,len(dates)):
        d=dates[i]; p=dates[i-1]; g=rth_df[rth_df["date"]==p]
        if not g.empty: prev[d]={"pdh":g["high"].max(),"pdl":g["low"].min()}
    return prev

def build_daily_swings(rth_df, lookback=10):
    """Daily OHLC swing highs/lows"""
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    daily=rth_df.groupby("date").agg(dh=("high","max"),dl=("low","min")).reset_index()
    daily=daily.sort_values("date").reset_index(drop=True); result={}
    for i in range(lookback, len(daily)):
        d=daily.iloc[i]["date"]
        window=daily.iloc[i-lookback:i]
        highs=[(row["dh"],"daily_res") for _,row in window.iterrows()]
        lows =[(row["dl"],"daily_sup") for _,row in window.iterrows()]
        all_lvls=highs+lows
        all_lvls=sorted(all_lvls,key=lambda x:x[0]); cl=[list(all_lvls[0])]
        for lv,lt in all_lvls[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        result[d]=[(c[0],c[1]) for c in cl]
    return result

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


# ── Exit simulator ────────────────────────────────────────────────────────────
def simulate_exit(ddf, ei, ep, side, tp_pct, sl_pct):
    """side: 'short' or 'long'"""
    n=len(ddf); tp=tp_pct/100; sl=sl_pct/100
    if side=="short":
        tp_price=ep*(1-tp); sl_price=ep*(1+sl)
    else:
        tp_price=ep*(1+tp); sl_price=ep*(1-sl)
    for i in range(ei, min(ei+MAX_BARS,n-1)+1):
        hi=ddf.iloc[i]["high"]; lo=ddf.iloc[i]["low"]
        if side=="short":
            if hi>=sl_price: return ("SL",-sl_pct)
            if lo<=tp_price: return ("TP", tp_pct)
        else:
            if lo<=sl_price: return ("SL",-sl_pct)
            if hi>=tp_price: return ("TP", tp_pct)
    last=ddf.iloc[min(ei+MAX_BARS,n-1)]["close"]
    pnl=(last-ep)/ep*100 if side=="long" else (ep-last)/ep*100
    return ("TO", pnl)


# ── Level scanner — all 4 setup types ────────────────────────────────────────
def scan_level(ddf, level, level_type, tp_pct, sl_pct):
    """
    level_type: 'res' or 'sup'
    Returns records for all 4 behaviors:
      res + touching from below → rejection short OR breakout long
      sup + touching from above → rejection long  OR breakdown short
    Confirmation: +1 bar (A), 0.15% away (D), 0.25% away (E)
    Touch count tracked.
    """
    n=len(ddf)
    H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    records=[]; state="IDLE"; ext=None; touch_num=0; i=0

    while i<n-3:
        if level_type=="res":
            touching = H[i] >= level*(1-NEAR_PCT)
        else:
            touching = L[i] <= level*(1+NEAR_PCT)

        if state=="IDLE":
            if touching:
                state="IN"; touch_num+=1
                ext=C[i]
        elif state=="IN":
            if touching:
                if level_type=="res": ext=min(ext,C[i])
                else:                 ext=max(ext,C[i])
            else:
                # Check bounce
                if level_type=="res":
                    bounced = ext is not None and (level-ext)/level >= BOUNCE
                else:
                    bounced = ext is not None and (ext-level)/level >= BOUNCE

                if bounced and i+1 < n:
                    ep_bar = i+1
                    ep_A   = ddf.iloc[ep_bar]["open"]  # confirmation A: +1 bar
                    # confirmation D: 0.15% away
                    ep_D   = None
                    ep_E   = None
                    for j in range(i, min(i+20,n)):
                        c=C[j]
                        if level_type=="res":
                            away_pct=(level-c)/level*100
                        else:
                            away_pct=(c-level)/level*100
                        if ep_D is None and away_pct>=0.15:
                            ep_D=ddf.iloc[min(j+1,n-1)]["open"]; ep_D_bar=min(j+1,n-1)
                        if ep_E is None and away_pct>=0.25:
                            ep_E=ddf.iloc[min(j+1,n-1)]["open"]; ep_E_bar=min(j+1,n-1)
                        if ep_D is not None and ep_E is not None: break

                    tc_label = "1st" if touch_num==1 else ("2nd" if touch_num==2 else "3rd+")

                    for conf, ep_val, ep_idx in [("A",ep_A,ep_bar),
                                                  ("D",ep_D,ep_D_bar if ep_D else ep_bar),
                                                  ("E",ep_E,ep_E_bar if ep_E else ep_bar)]:
                        if ep_val is None: continue
                        # Setup 1: rejection (fade)
                        if level_type=="res": rej_side="short"
                        else:                 rej_side="long"
                        out,pnl=simulate_exit(ddf,ep_idx,ep_val,rej_side,tp_pct,sl_pct)
                        records.append({"setup":"rej","side":rej_side,"conf":conf,
                                        "touch":tc_label,"touch_n":touch_num,
                                        "outcome":out,"pnl":pnl,"ep":ep_val})
                        # Setup 2: continuation (breakout/breakdown)
                        if level_type=="res": brk_side="long"
                        else:                 brk_side="short"
                        out2,pnl2=simulate_exit(ddf,ep_idx,ep_val,brk_side,tp_pct,sl_pct)
                        records.append({"setup":"brk","side":brk_side,"conf":conf,
                                        "touch":tc_label,"touch_n":touch_num,
                                        "outcome":out2,"pnl":pnl2,"ep":ep_val})
                state="IDLE"; ext=None
        i+=1
    return records


# ── Per-symbol runner ─────────────────────────────────────────────────────────
def run_sym(sym, tp_pct, sl_pct):
    import os
    if not os.path.exists(f"boof51_{sym}_1m.csv"): return pd.DataFrame()
    rth_df,pm_df=load_sym(sym)
    pm_stats=build_pm_levels(pm_df if not pm_df.empty else rth_df,rth_df)
    if pm_stats.empty: return pd.DataFrame()
    pdhl=build_pdhl(rth_df)
    daily_sr=build_daily_swings(rth_df)
    pivot_maps={}
    for tf_lbl,lb,wing in PIVOT_TFS:
        pivot_maps[tf_lbl]=build_pivots_clean(rth_df,lookback=lb,wing=wing)
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    records=[]

    for date,ddf in rth_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm_stats.index: continue
        day=pm_stats.loc[date_ts]; gap=day["gap_pct"]
        if gap<=0.5: continue
        ddf=ddf.reset_index(drop=True)
        dk=date_ts.date()

        # Collect all levels with family tag
        all_levels=[]
        # PM high/low
        all_levels.append((day["pm_high"],"PMH","res"))
        all_levels.append((day["pm_low"], "PML","sup"))
        # PD high/low
        pd_info=pdhl.get(date_ts,{}); 
        if "pdh" in pd_info: all_levels.append((pd_info["pdh"],"PDH","res"))
        if "pdl" in pd_info: all_levels.append((pd_info["pdl"],"PDL","sup"))
        # Intraday pivots
        for tf_lbl,_,_ in PIVOT_TFS:
            pm=pivot_maps[tf_lbl]
            lvls=pm.get(date_ts,pm.get(dk,[]))
            for lv,lt in lvls:
                ltype="res" if lt=="res" else "sup"
                all_levels.append((lv,tf_lbl,ltype))
        # Daily swings
        d_lvls=daily_sr.get(date_ts,daily_sr.get(dk,[]))
        for lv,lt in d_lvls:
            ltype="res" if "res" in lt else "sup"
            all_levels.append((lv,"Daily",ltype))

        for level,lname,ltype in all_levels:
            if pd.isna(level): continue
            for r in scan_level(ddf,level,ltype,tp_pct,sl_pct):
                records.append({"sym":sym,"level_family":lname,
                                "level_type":ltype,**r})
    return pd.DataFrame(records)


# ── Metrics + print ───────────────────────────────────────────────────────────
def metrics(s):
    if len(s)<5: return None
    n=len(s); tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    gw=tp*s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else 0
    gl=abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else 1e-9
    pf=(tp/n*abs(s[s["outcome"]=="TP"]["pnl"].mean())) / \
       (sl/n*abs(s[s["outcome"]=="SL"]["pnl"].mean())) if sl>0 else 999
    ev=s["pnl"].mean(); tpw=n/WEEKS
    cum=np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd=(cum-peak).min()
    return dict(n=n,tpw=tpw,wr=wr,tp=tp,sl=sl,pf=pf,ev=ev,maxdd=maxdd)

def prow(label, s, w=26):
    mx=metrics(s)
    if mx is None: return
    mk=" <<<" if mx["pf"]>=2.0 else (" <<" if mx["pf"]>=1.5 else ("  <" if mx["pf"]>=1.2 else ("  -" if mx["pf"]<1.0 else "")))
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%{mk}")

HDR=(f"  {'Label':<26} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
     f"{'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*76}"
W=80

LEVEL_FAMILIES=["PMH","PML","PDH","PDL","10m","30m","1H","2H","4H","Daily"]
SETUP_MAP={
    ("res","rej"): "Res rejection (short)",
    ("res","brk"): "Res breakout (long)",
    ("sup","rej"): "Sup rejection (long)",
    ("sup","brk"): "Sup breakdown (short)",
}

if __name__=="__main__":
    for tp_pct,sl_pct in CONFIGS:
        print(f"\nRunning TP={tp_pct} / SL={sl_pct}...",flush=True)
        frames=[]
        for sym in SYMS:
            print(f"  {sym}",end=" ",flush=True)
            df=run_sym(sym,tp_pct,sl_pct)
            if not df.empty: frames.append(df)
        print()
        if not frames: continue
        all_df=pd.concat(frames,ignore_index=True)

        print(f"\n{'='*W}")
        print(f"  TP{tp_pct:.2f}% / SL{sl_pct:.2f}%  |  5 symbols  |  Gap Up  |  All levels  |  Conf A (+1 bar)")
        print(f"{'='*W}")

        # ── 1. Setup family (conf A only) ─────────────────────────────────────
        df_A=all_df[all_df["conf"]=="A"]
        print(f"\n  -- SETUP FAMILY --")
        print(HDR); print(SEP)
        for (ltype,setup),label in SETUP_MAP.items():
            s=df_A[(df_A["level_type"]==ltype)&(df_A["setup"]==setup)]
            prow(label, s)

        # -- 2. By level family
        print(f"\n  -- BY LEVEL FAMILY  (rejection setups, conf A) --")
        print(HDR); print(SEP)
        df_rej=df_A[df_A["setup"]=="rej"]
        for lf in LEVEL_FAMILIES:
            s=df_rej[df_rej["level_family"]==lf]
            prow(lf, s)

        # -- 3. Touch count
        print(f"\n  -- TOUCH COUNT  (rejection, conf A, all levels) --")
        print(HDR); print(SEP)
        for tc in ["1st","2nd","3rd+"]:
            prow(tc, df_rej[df_rej["touch"]==tc])

        # -- 4. Confirmation style
        print(f"\n  -- CONFIRMATION STYLE  (rejection, 1st touch) --")
        print(HDR); print(SEP)
        df_1st=all_df[(all_df["setup"]=="rej")&(all_df["touch"]=="1st")]
        for conf,label in [("A","+1 bar"),("D","0.15% away"),("E","0.25% away")]:
            prow(f"Conf {conf}: {label}", df_1st[df_1st["conf"]==conf])

        # -- 5. Best combos
        print(f"\n  -- TOP COMBOS: level x setup x touch (conf A, PF>=1.5) --")
        print(HDR); print(SEP)
        rows=[]
        for lf in LEVEL_FAMILIES:
            for setup in ["rej","brk"]:
                for tc in ["1st","2nd","3rd+"]:
                    s=df_A[(df_A["level_family"]==lf)&(df_A["setup"]==setup)&(df_A["touch"]==tc)]
                    mx=metrics(s)
                    if mx and mx["pf"]>=1.5 and mx["n"]>=10:
                        rows.append((lf,setup,tc,mx))
        rows.sort(key=lambda x:-x[3]["pf"])
        for lf,setup,tc,mx in rows[:20]:
            side_lbl="short" if setup=="rej" and lf in ["PMH","PDH","10m","30m","1H","2H","4H","Daily"] else "long" if setup=="rej" else "long/short"
            prow(f"{lf} {setup} {tc}", all_df[(all_df["level_family"]==lf)&
                                               (all_df["setup"]==setup)&
                                               (all_df["touch"]==tc)&
                                               (all_df["conf"]=="A")])
