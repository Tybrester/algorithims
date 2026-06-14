"""
BOOF53 New Ideas Test
- Idea 1: PMH rejection vs PMH breakout
- Idea 2: First-30m-high rejection (dynamic intraday level)
- Idea 3: Level stacking (PMH + 10m/30m/2H/Daily within 0.15%)
- Idea 4: Level freshness (untouched vs already touched today)

SHORT only | Gap Up > 0.5% | TP 0.50% / SL 0.25% | 5 symbols
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
STACK_PCT= 0.0015   # levels within 0.15% = "stacked"
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60
WEEKS    = 19.2
SYMS     = ["APP","SMCI","HIMS","ARM","MU"]


# ── Data loaders ──────────────────────────────────────────────────────────────
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

def build_pivots(rth_df, lookback, wing):
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

def build_daily_swings(rth_df, lookback=10):
    rth_df=rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])
    daily=rth_df.groupby("date").agg(dh=("high","max"),dl=("low","min")).reset_index()
    daily=daily.sort_values("date").reset_index(drop=True); result={}
    for i in range(lookback, len(daily)):
        d=daily.iloc[i]["date"]
        window=daily.iloc[i-lookback:i]
        levels=[(row["dh"],"res") for _,row in window.iterrows()] + \
               [(row["dl"],"sup") for _,row in window.iterrows()]
        levels=sorted(levels,key=lambda x:x[0]); cl=[list(levels[0])]
        for lv,lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0]<OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        result[d]=[(c[0],c[1]) for c in cl]
    return result


# ── Exit ──────────────────────────────────────────────────────────────────────
def race(ddf, ei, ep, side="short"):
    n=len(ddf)
    tp_p = ep*(1-TP_PCT) if side=="short" else ep*(1+TP_PCT)
    sl_p = ep*(1+SL_PCT) if side=="short" else ep*(1-SL_PCT)
    for i in range(ei, min(ei+MAX_BARS, n-1)+1):
        hi=ddf.iloc[i]["high"]; lo=ddf.iloc[i]["low"]
        if side=="short":
            if hi>=sl_p: return "SL", -SL_PCT*100
            if lo<=tp_p: return "TP",  TP_PCT*100
        else:
            if lo<=sl_p: return "SL", -SL_PCT*100
            if hi>=tp_p: return "TP",  TP_PCT*100
    return "TO", 0.0


# ── Core level scanner ────────────────────────────────────────────────────────
def scan_resistance(ddf, level, side="short"):
    """
    Returns list of touch events:
    {touch_n, bar_i, ep, touched_before (freshness)}
    For rejection (short) or breakout (long).
    """
    n=len(ddf); H=ddf["high"].values; C=ddf["close"].values
    events=[]; state="IDLE"; ext=None; touch_num=0; touched_today=False; i=0
    while i<n-3:
        touching=H[i]>=level*(1-NEAR_PCT)
        if state=="IDLE":
            if touching:
                state="IN"; ext=C[i]; touch_num+=1
        elif state=="IN":
            if touching: ext=min(ext,C[i])
            else:
                bounced=ext is not None and (level-ext)/level>=BOUNCE
                if bounced:
                    ei=i+1; ep=ddf.iloc[ei]["open"]
                    events.append({"touch_n":touch_num,"bar_i":ei,"ep":ep,
                                   "fresh":not touched_today})
                    touched_today=True
                state="IDLE"; ext=None
        i+=1
    return events


# ── Metrics ───────────────────────────────────────────────────────────────────
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

HDR=(f"  {'Label':<34} {'N':>5} {'T/Wk':>6}  {'WR':>6}  "
     f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}")
SEP=f"  {'-'*84}"
W=88

def prow(label, s, w=34):
    mx=metrics(s)
    if mx is None: return
    mk=" <<<" if mx["pf"]>=2.0 else (" <<" if mx["pf"]>=1.5 else ("  <" if mx["pf"]>=1.2 else ("  -" if mx["pf"]<1.0 else "   ")))
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>6.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%{mk}")


# ── Main scan ─────────────────────────────────────────────────────────────────
def run_all():
    records = []
    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue
        piv_10m  = build_pivots(rth_df, lookback=10,  wing=2)
        piv_30m  = build_pivots(rth_df, lookback=30,  wing=3)
        piv_2h   = build_pivots(rth_df, lookback=120, wing=4)
        daily_sr = build_daily_swings(rth_df)
        rth_df   = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        for date, ddf in rth_df.groupby("date"):
            date_ts = pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day = pm_stats.loc[date_ts]; gap = day["gap_pct"]
            if gap <= 0.5: continue
            ddf = ddf.reset_index(drop=True)
            pmh = day["pm_high"]
            dk  = date_ts.date()

            # Other resistance levels for stacking check
            def get_res(pmap):
                lvls = pmap.get(date_ts, pmap.get(dk, []))
                return [lv for lv,lt in lvls if lt=="res"]

            res_10m   = get_res(piv_10m)
            res_30m   = get_res(piv_30m)
            res_2h    = get_res(piv_2h)
            res_daily = [lv for lv,lt in daily_sr.get(date_ts, daily_sr.get(dk,[]))
                         if "res" in lt]

            # Is PMH stacked with another level?
            def stacked_with(pmh, other_levels):
                for lv in other_levels:
                    if abs(lv - pmh) / pmh <= STACK_PCT:
                        return True
                return False

            stk_10m   = stacked_with(pmh, res_10m)
            stk_30m   = stacked_with(pmh, res_30m)
            stk_2h    = stacked_with(pmh, res_2h)
            stk_daily = stacked_with(pmh, res_daily)
            any_stack = stk_10m or stk_30m or stk_2h or stk_daily

            # First-30m high (dynamic level)
            first_30m_bars = ddf[ddf["time"].dt.strftime("%H:%M") < "10:00"]
            f30h = first_30m_bars["high"].max() if not first_30m_bars.empty else None

            # Scan PMH rejections (SHORT)
            events = scan_resistance(ddf, pmh, side="short")
            for ev in events:
                ei = ev["bar_i"]; ep = ev["ep"]
                out, pnl = race(ddf, ei, ep, "short")
                tc = "1st" if ev["touch_n"]==1 else ("2nd" if ev["touch_n"]==2 else "3rd+")
                records.append({
                    "sym": sym, "idea": "pmh_rej", "setup": "short",
                    "touch": tc, "fresh": ev["fresh"],
                    "stk_10m": stk_10m, "stk_30m": stk_30m,
                    "stk_2h": stk_2h, "stk_daily": stk_daily,
                    "outcome": out, "pnl": pnl
                })

            # Scan PMH breakout (LONG) — same touch events, opposite side
            events_brk = scan_resistance(ddf, pmh, side="long")
            for ev in events_brk:
                ei = ev["bar_i"]; ep = ev["ep"]
                out, pnl = race(ddf, ei, ep, "long")
                tc = "1st" if ev["touch_n"]==1 else ("2nd" if ev["touch_n"]==2 else "3rd+")
                records.append({
                    "sym": sym, "idea": "pmh_brk", "setup": "long",
                    "touch": tc, "fresh": ev["fresh"],
                    "stk_10m": stk_10m, "stk_30m": stk_30m,
                    "stk_2h": stk_2h, "stk_daily": stk_daily,
                    "outcome": out, "pnl": pnl
                })

            # First-30m high rejection (SHORT)
            if f30h is not None and not pd.isna(f30h):
                # Only scan bars AFTER 10:00
                ddf_after = ddf[ddf["time"].dt.strftime("%H:%M") >= "10:00"].reset_index(drop=True)
                if len(ddf_after) > 4:
                    evs = scan_resistance(ddf_after, f30h, side="short")
                    for ev in evs:
                        ei = ev["bar_i"]; ep = ddf_after.iloc[ei]["open"]
                        out, pnl = race(ddf_after, ei, ep, "short")
                        tc = "1st" if ev["touch_n"]==1 else ("2nd" if ev["touch_n"]==2 else "3rd+")
                        records.append({
                            "sym": sym, "idea": "f30h_rej", "setup": "short",
                            "touch": tc, "fresh": ev["fresh"],
                            "stk_10m": False, "stk_30m": False,
                            "stk_2h": False, "stk_daily": False,
                            "outcome": out, "pnl": pnl
                        })
    print()
    return pd.DataFrame(records)


if __name__ == "__main__":
    print("Scanning...", flush=True)
    df = run_all()
    rej = df[df["idea"]=="pmh_rej"]
    brk = df[df["idea"]=="pmh_brk"]
    f30 = df[df["idea"]=="f30h_rej"]

    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  IDEA 1 — PMH Rejection (short) vs PMH Breakout (long)")
    print(f"  Gap Up | TP 0.50% / SL 0.25% | 5 symbols")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("PMH Rejection  (short)",    rej)
    prow("PMH Breakout   (long)",     brk)
    print(SEP)
    print(f"  -- by touch count --")
    for tc in ["1st","2nd","3rd+"]:
        prow(f"  Rejection {tc}",  rej[rej["touch"]==tc])
        prow(f"  Breakout  {tc}",  brk[brk["touch"]==tc])
        print()

    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  IDEA 2 — First-30m High Rejection (short, after 10:00)")
    print(f"  Gap Up | TP 0.50% / SL 0.25% | 5 symbols")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("F30H Rejection (all)",        f30)
    prow("  1st touch",                 f30[f30["touch"]=="1st"])
    prow("  2nd touch",                 f30[f30["touch"]=="2nd"])
    prow("  3rd+",                      f30[f30["touch"]=="3rd+"])

    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  IDEA 3 — Level Stacking  (PMH rejection, short, 1st touch)")
    print(f"  Stacked = another res level within 0.15% of PMH")
    print(f"{'='*W}")
    r1 = rej[rej["touch"]=="1st"]
    print(HDR); print(SEP)
    prow("PMH rej 1st  (all)",          r1)
    prow("  + stacked any level",       r1[r1["stk_10m"]|r1["stk_30m"]|r1["stk_2h"]|r1["stk_daily"]])
    prow("  + NOT stacked",             r1[~(r1["stk_10m"]|r1["stk_30m"]|r1["stk_2h"]|r1["stk_daily"])])
    print(SEP)
    prow("  PMH + 10m stacked",         r1[r1["stk_10m"]])
    prow("  PMH + 30m stacked",         r1[r1["stk_30m"]])
    prow("  PMH + 2H stacked",          r1[r1["stk_2h"]])
    prow("  PMH + Daily stacked",       r1[r1["stk_daily"]])

    # also all touches stacked
    print(f"\n  -- All touch counts, stacked vs not --")
    print(HDR); print(SEP)
    prow("Stacked (any, all touches)",  rej[rej["stk_10m"]|rej["stk_30m"]|rej["stk_2h"]|rej["stk_daily"]])
    prow("Not stacked (all touches)",   rej[~(rej["stk_10m"]|rej["stk_30m"]|rej["stk_2h"]|rej["stk_daily"])])

    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  IDEA 4 — Level Freshness  (PMH rejection, short)")
    print(f"  Fresh = level NOT touched earlier today")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("PMH rej  FRESH  (1st touch)", rej[rej["fresh"]==True])
    prow("PMH rej  USED   (2nd+ touch)",rej[rej["fresh"]==False])
    print(SEP)
    prow("  Fresh 1st",                 rej[(rej["fresh"]==True) &(rej["touch"]=="1st")])
    prow("  Used  2nd",                 rej[(rej["fresh"]==False)&(rej["touch"]=="2nd")])
    prow("  Used  3rd+",                rej[(rej["fresh"]==False)&(rej["touch"]=="3rd+")])

    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  FAVORITE REPORT — PMH rejection + stacking combos")
    print(f"  SHORT | Gap Up | TP 0.50% / SL 0.25% | 1st touch only")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    prow("PMH rejection (baseline)",    r1)
    print(SEP)
    prow("PMH + 10m overlap",           r1[r1["stk_10m"]])
    prow("PMH + 30m overlap",           r1[r1["stk_30m"]])
    prow("PMH + 2H overlap",            r1[r1["stk_2h"]])
    prow("PMH + Daily overlap",         r1[r1["stk_daily"]])
    print(SEP)
    # Per symbol breakdown for stacked
    print(f"  -- PMH + any overlap, by symbol --")
    stacked_r1 = r1[r1["stk_10m"]|r1["stk_30m"]|r1["stk_2h"]|r1["stk_daily"]]
    for sym in SYMS:
        prow(f"  {sym}", stacked_r1[stacked_r1["sym"]==sym])
    print(SEP)
    prow("PMH + any stack  (all)",      stacked_r1)
    prow("PMH baseline  (all)",         r1)

    # Stacking frequency
    print(f"\n  Stacking hit rates (how often PMH has a co-level):")
    total_days = rej["sym"].count()  # proxy
    for lbl,col in [("10m",r1["stk_10m"]),("30m",r1["stk_30m"]),
                    ("2H", r1["stk_2h"]),("Daily",r1["stk_daily"])]:
        n_stk=col.sum(); pct=n_stk/len(r1)*100 if len(r1)>0 else 0
        print(f"    PMH + {lbl:<6}: {n_stk:>4} / {len(r1)}  ({pct:.0f}%)")
