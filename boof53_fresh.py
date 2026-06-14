"""
BOOF53 Freshness Deep Dive
Test 1: Fresh vs Used for every level family
Test 2: Fresh composite (PMH + 1H_Res + 2H_Res)
Test 3: Zone width sensitivity for PMH
Test 4: Time-of-day for Fresh PMH
SHORT only | Gap Up > 0.5% | TP 0.50% / SL 0.25% | 5 symbols
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
OVERLAP  = 0.0020
BOUNCE   = 0.0015
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60
WEEKS    = 19.2
SYMS     = ["APP","SMCI","HIMS","ARM","MU"]

LEVEL_FAMILIES = {
    "PMH":    dict(kind="pm_high"),
    "PDH":    dict(kind="pd_high"),
    "10m":    dict(kind="pivot", lb=10,  wing=2),
    "30m":    dict(kind="pivot", lb=30,  wing=3),
    "1H_Res": dict(kind="pivot", lb=60,  wing=3),
    "2H_Res": dict(kind="pivot", lb=120, wing=4),
    "4H_Res": dict(kind="pivot", lb=240, wing=5),
}

# ── Loaders ───────────────────────────────────────────────────────────────────
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
    pm_agg=pm_df.groupby("date").agg(pm_high=("high","max")).reset_index()
    pc=rth_df.groupby("date")["close"].last().reset_index()
    pc.columns=["date","prev_close"]; pc["next_date"]=pc["date"]+pd.Timedelta(days=1)
    ro=rth_df.groupby("date")["open"].first().reset_index(); ro.columns=["date","rth_open"]
    stats=pm_agg.merge(pc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
                       on="date",how="left").merge(ro,on="date",how="left")
    stats["gap_pct"]=(stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct","pm_high"]).set_index("date")

def build_pdh(rth_df):
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    dates=sorted(rth_df["date"].unique()); prev={}
    for i in range(1,len(dates)):
        d=dates[i]; p=dates[i-1]; g=rth_df[rth_df["date"]==p]
        if not g.empty: prev[d]=g["high"].max()
    return prev

def build_pivots(rth_df, lookback, wing):
    rth_df=rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"]=pd.to_datetime(rth_df["date"]); sr={}
    for d in sorted(rth_df["date"].unique()):
        hist=rth_df[rth_df["date"]<d].tail(lookback)
        if len(hist)<max(wing+1,lookback//4): continue
        H=hist["high"].values; L=hist["low"].values; levels=[]
        for i in range(wing,len(hist)):
            if H[i]==H[i-wing:i+1].max(): levels.append(H[i])
        if not levels: continue
        levels=sorted(levels); cl=[levels[0]]
        for lv in levels[1:]:
            if abs(lv-cl[-1])/cl[-1]<OVERLAP: cl[-1]=(cl[-1]+lv)/2
            else: cl.append(lv)
        sr[d]=cl
    return sr

# ── Exit ──────────────────────────────────────────────────────────────────────
def race(ddf, ei, ep):
    n=len(ddf); tp_p=ep*(1-TP_PCT); sl_p=ep*(1+SL_PCT)
    for i in range(ei, min(ei+MAX_BARS, n-1)+1):
        if ddf.iloc[i]["high"]>=sl_p: return "SL", -SL_PCT*100
        if ddf.iloc[i]["low"] <=tp_p: return "TP",  TP_PCT*100
    return "TO", 0.0

# ── Scanner with configurable near_pct and freshness tracking ─────────────────
def scan_level(ddf, level, near_pct=0.0015):
    """Returns list of (touch_n, bar_after_bounce, ep, fresh, hour_bucket, bounce_depth_pct)"""
    n=len(ddf); H=ddf["high"].values; C=ddf["close"].values
    events=[]; state="IDLE"; ext=None; touch_num=0; touched_today=False; i=0
    while i<n-3:
        touching = H[i] >= level*(1-near_pct)
        if state=="IDLE":
            if touching: state="IN"; ext=C[i]; touch_num+=1
        elif state=="IN":
            if touching: ext=min(ext,C[i])
            else:
                bounced = ext is not None and (level-ext)/level >= BOUNCE
                if bounced and i+1 < n:
                    ei=i+1; ep=ddf.iloc[ei]["open"]
                    hm=ddf.iloc[ei]["time"].strftime("%H:%M")
                    if   hm < "10:30": tod="09:30-10:30"
                    elif hm < "12:00": tod="10:30-12:00"
                    elif hm < "14:00": tod="12:00-14:00"
                    else:              tod="14:00-close"
                    bounce_depth=(level-ext)/level*100
                    events.append({"touch_n":touch_num,"bar_i":ei,"ep":ep,
                                   "fresh":not touched_today,"tod":tod,
                                   "bounce_depth":bounce_depth})
                    touched_today=True
                state="IDLE"; ext=None
        i+=1
    return events

# ── Main runner ───────────────────────────────────────────────────────────────
def run_all():
    # pre-build all pivot maps per sym
    sym_data = {}
    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        pdh_map  = build_pdh(rth_df)
        pivots   = {}
        for fname, cfg in LEVEL_FAMILIES.items():
            if cfg["kind"]=="pivot":
                pivots[fname] = build_pivots(rth_df, cfg["lb"], cfg["wing"])
        sym_data[sym] = dict(rth=rth_df, pm=pm_stats, pdh=pdh_map, pivots=pivots)
    print()

    records = []
    for sym in SYMS:
        d = sym_data[sym]
        rth_df = d["rth"].copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
        pm_stats = d["pm"]; pdh_map = d["pdh"]; pivots = d["pivots"]

        for date, ddf in rth_df.groupby("date"):
            date_ts = pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day = pm_stats.loc[date_ts]
            if day["gap_pct"] <= 0.5: continue
            ddf = ddf.reset_index(drop=True)
            dk  = date_ts.date()

            level_vals = {}
            level_vals["PMH"] = [day["pm_high"]]
            level_vals["PDH"] = [pdh_map[date_ts]] if date_ts in pdh_map else []
            for fname in ["10m","30m","1H_Res","2H_Res","4H_Res"]:
                pm = pivots.get(fname,{})
                lvls = pm.get(date_ts, pm.get(dk,[]))
                level_vals[fname] = lvls if lvls else []

            for fname, lvls in level_vals.items():
                for level in lvls:
                    if pd.isna(level): continue
                    evs = scan_level(ddf, level, near_pct=0.0015)
                    for ev in evs:
                        out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                        tc = "1st" if ev["touch_n"]==1 else ("2nd" if ev["touch_n"]==2 else "3rd+")
                        records.append({
                            "sym": sym, "family": fname,
                            "touch": tc, "fresh": ev["fresh"],
                            "tod": ev["tod"], "bounce_depth": ev["bounce_depth"],
                            "outcome": out, "pnl": pnl
                        })

            # Zone width test for PMH — multiple near_pct values
            pmh = day["pm_high"]
            for near_pct, zlabel in [(0.0005,"0.05%"),(0.0010,"0.10%"),
                                      (0.0015,"0.15%"),(0.0020,"0.20%")]:
                evs = scan_level(ddf, pmh, near_pct=near_pct)
                for ev in evs:
                    if ev["touch_n"] != 1: continue  # 1st touch only for zone test
                    out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                    records.append({
                        "sym": sym, "family": f"PMH_zone_{zlabel}",
                        "touch": "1st", "fresh": ev["fresh"],
                        "tod": ev["tod"], "bounce_depth": ev["bounce_depth"],
                        "outcome": out, "pnl": pnl
                    })

    return pd.DataFrame(records)

# ── Metrics + print ───────────────────────────────────────────────────────────
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

HDR = (f"  {'Label':<32} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
       f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP = f"  {'-'*82}"
W   = 86

def prow(label, s, w=32):
    mx=metrics(s)
    if mx is None:
        print(f"  {label:<{w}} {'(n<5)':>5}")
        return
    mk=(" <<<" if mx["pf"]>=2.0 else
        " <<" if mx["pf"]>=1.5 else
        "  <" if mx["pf"]>=1.2 else
        "  -" if mx["pf"]<1.0 else "   ")
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%{mk}")


if __name__ == "__main__":
    print("Scanning...", flush=True)
    df = run_all()

    # ── TEST 1: Fresh vs Used per level family ────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  TEST 1 — Fresh vs Used  |  SHORT  |  Gap Up  |  All touch counts")
    print(f"  Fresh = level not yet touched this session")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for fname in ["PMH","PDH","10m","30m","1H_Res","2H_Res","4H_Res"]:
        s = df[df["family"]==fname]
        sf = s[s["fresh"]==True];  su = s[s["fresh"]==False]
        prow(f"{fname}  FRESH", sf)
        prow(f"{fname}  USED",  su)
        print(SEP)

    # ── TEST 1b: Fresh 1st touch only ────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  TEST 1b — Fresh 1st touch vs Used 2nd+ touch  (by family)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for fname in ["PMH","PDH","10m","30m","1H_Res","2H_Res","4H_Res"]:
        s = df[df["family"]==fname]
        sf1 = s[(s["fresh"]==True) &(s["touch"]=="1st")]
        su2 = s[(s["fresh"]==False)&(s["touch"].isin(["2nd","3rd+"]))]
        prow(f"{fname}  Fresh 1st", sf1)
        prow(f"{fname}  Used 2nd+", su2)
        print(SEP)

    # ── TEST 2: Fresh composite ───────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  TEST 2 — Fresh Composite  (PMH + 1H_Res + 2H_Res, 1st touch only)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    comp = df[(df["family"].isin(["PMH","1H_Res","2H_Res"]))&
              (df["fresh"]==True)&(df["touch"]=="1st")]
    prow("Composite: PMH+1H+2H fresh 1st", comp, w=36)
    print(SEP)
    for fname in ["PMH","1H_Res","2H_Res"]:
        s=comp[comp["family"]==fname]
        prow(f"  {fname}", s, w=36)

    # also: all 7 families fresh 1st
    all_fresh1 = df[(df["fresh"]==True)&(df["touch"]=="1st")&
                    ~df["family"].str.startswith("PMH_zone")]
    print(SEP)
    prow("All families fresh 1st", all_fresh1, w=36)

    # ── TEST 3: Zone width (PMH, 1st touch, fresh only) ──────────────────────
    print(f"\n{'='*W}")
    print(f"  TEST 3 — Zone Width  (PMH 1st touch)")
    print(f"  Wider zone = more touches qualify but looser rejection")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    for zlabel in ["0.05%","0.10%","0.15%","0.20%"]:
        fname = f"PMH_zone_{zlabel}"
        s = df[df["family"]==fname]
        sf = s[s["fresh"]==True]
        su = s[s["fresh"]==False]
        prow(f"Zone {zlabel}  (all)",   s,  w=32)
        prow(f"Zone {zlabel}  fresh",   sf, w=32)
        prow(f"Zone {zlabel}  used",    su, w=32)
        print(SEP)

    # ── TEST 4: Time of day (PMH, fresh, 1st touch) ───────────────────────────
    print(f"\n{'='*W}")
    print(f"  TEST 4 — Time of Day  (PMH fresh 1st touch, short)")
    print(f"{'='*W}")
    pmh_fresh1 = df[(df["family"]=="PMH")&(df["fresh"]==True)&(df["touch"]=="1st")]
    print(HDR); print(SEP)
    prow("PMH fresh 1st  (all day)", pmh_fresh1)
    print(SEP)
    for tod in ["09:30-10:30","10:30-12:00","12:00-14:00","14:00-close"]:
        prow(f"  {tod}", pmh_fresh1[pmh_fresh1["tod"]==tod])

    # also by symbol
    print(f"\n  -- PMH fresh 1st by symbol --")
    print(HDR); print(SEP)
    for sym in SYMS:
        prow(f"  {sym}", pmh_fresh1[pmh_fresh1["sym"]==sym])

    # ── BONUS: best fresh 1st combos ranked ──────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BONUS — Best fresh 1st touch setups ranked by PF (N>=10)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    rows=[]
    base_fams = ["PMH","PDH","10m","30m","1H_Res","2H_Res","4H_Res"]
    for fname in base_fams:
        s=df[(df["family"]==fname)&(df["fresh"]==True)&(df["touch"]=="1st")]
        mx=metrics(s)
        if mx and mx["n"]>=10: rows.append((fname,s,mx))
    rows.sort(key=lambda x:-x[2]["pf"])
    for fname,s,mx in rows:
        prow(f"{fname} fresh 1st", s)
