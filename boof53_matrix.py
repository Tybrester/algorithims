"""
BOOF53 Symbol x Level Matrix + Recency + 1H/2H Overlap
Test 1: PF matrix — Symbol x Level (PMH, 1H_Res, 2H_Res, 30m, 4H_Res)
Test 2: Recency — never/30m/60m since last touch
Test 3: Fresh 1H_Res + 2H_Res overlap within 0.15%
SHORT only | Gap Up > 0.5% | TP 0.50% / SL 0.25% | 5 symbols | Fresh 1st touch
"""
import pandas as pd
import numpy as np
import pytz

ET        = pytz.timezone("America/New_York")
OVERLAP   = 0.0020
BOUNCE    = 0.0015
NEAR_PCT  = 0.0015
STACK_PCT = 0.0015   # 0.15% for overlap test
TP_PCT    = 0.0050
SL_PCT    = 0.0025
MAX_BARS  = 60
WEEKS     = 19.2
SYMS      = ["APP","SMCI","HIMS","ARM","MU"]
FAMILIES  = ["PMH","1H_Res","2H_Res","30m","4H_Res"]


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

def build_pivots(rth_df, lookback, wing):
    rth_df=rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"]=pd.to_datetime(rth_df["date"]); sr={}
    for d in sorted(rth_df["date"].unique()):
        hist=rth_df[rth_df["date"]<d].tail(lookback)
        if len(hist)<max(wing+1,lookback//4): continue
        H=hist["high"].values; levels=[]
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


# ── Scanner with recency tracking ────────────────────────────────────────────
def scan_level_recency(ddf, level):
    """
    Returns touch events with:
      touch_n, bar_i, ep, fresh (never today),
      mins_since_last (None if fresh, else minutes)
    """
    n=len(ddf); H=ddf["high"].values; C=ddf["close"].values
    events=[]; state="IDLE"; ext=None; touch_num=0
    last_touch_bar=None; i=0

    while i<n-3:
        touching = H[i] >= level*(1-NEAR_PCT)
        if state=="IDLE":
            if touching:
                state="IN"; ext=C[i]; touch_num+=1
        elif state=="IN":
            if touching: ext=min(ext,C[i])
            else:
                bounced = ext is not None and (level-ext)/level >= BOUNCE
                if bounced and i+1 < n:
                    ei=i+1; ep=ddf.iloc[ei]["open"]
                    fresh = last_touch_bar is None
                    if last_touch_bar is not None:
                        mins_since = (ddf.iloc[ei]["time"] - ddf.iloc[last_touch_bar]["time"]).seconds // 60
                    else:
                        mins_since = None
                    events.append({
                        "touch_n": touch_num, "bar_i": ei, "ep": ep,
                        "fresh": fresh, "mins_since": mins_since
                    })
                    last_touch_bar = ei
                state="IDLE"; ext=None
        i+=1
    return events


# ── Main scanner ──────────────────────────────────────────────────────────────
def run_all():
    records = []
    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        rth_df, pm_df = load_sym(sym)
        pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
        if pm_stats.empty: continue
        piv = {
            "30m":    build_pivots(rth_df, 30,  3),
            "1H_Res": build_pivots(rth_df, 60,  3),
            "2H_Res": build_pivots(rth_df, 120, 4),
            "4H_Res": build_pivots(rth_df, 240, 5),
        }
        rth_df = rth_df.copy(); rth_df["date"]=pd.to_datetime(rth_df["date"])

        for date, ddf in rth_df.groupby("date"):
            date_ts = pd.Timestamp(date)
            if date_ts not in pm_stats.index: continue
            day = pm_stats.loc[date_ts]
            if day["gap_pct"] <= 0.5: continue
            ddf = ddf.reset_index(drop=True)
            dk  = date_ts.date()

            # Collect levels
            level_vals = {"PMH": [day["pm_high"]]}
            for fname, pm in piv.items():
                lvls = pm.get(date_ts, pm.get(dk, []))
                level_vals[fname] = lvls

            # Also collect 1H and 2H for overlap test
            res_1h = level_vals.get("1H_Res", [])
            res_2h = level_vals.get("2H_Res", [])

            for fname, lvls in level_vals.items():
                for level in lvls:
                    if pd.isna(level): continue

                    # Is this 1H_Res level within STACK_PCT of any 2H_Res level?
                    overlaps_2h = False
                    if fname == "1H_Res":
                        for lv2 in res_2h:
                            if abs(lv2 - level) / level <= STACK_PCT:
                                overlaps_2h = True
                                break

                    evs = scan_level_recency(ddf, level)
                    for ev in evs:
                        tc = "1st" if ev["touch_n"]==1 else ("2nd" if ev["touch_n"]==2 else "3rd+")
                        mins = ev["mins_since"]
                        # recency bucket
                        if ev["fresh"]:
                            recency = "never_today"
                        elif mins is not None and mins <= 30:
                            recency = "within_30m"
                        elif mins is not None and mins <= 60:
                            recency = "within_60m"
                        else:
                            recency = "over_60m"

                        out, pnl = race(ddf, ev["bar_i"], ev["ep"])
                        records.append({
                            "sym": sym, "family": fname,
                            "touch": tc, "fresh": ev["fresh"],
                            "recency": recency, "mins_since": mins,
                            "overlaps_2h": overlaps_2h,
                            "outcome": out, "pnl": pnl
                        })
    print()
    return pd.DataFrame(records)


# ── Metrics ───────────────────────────────────────────────────────────────────
def met(s):
    if len(s) < 5: return None
    n=len(s); tp=s["outcome"].eq("TP").sum(); sl=s["outcome"].eq("SL").sum()
    wr=tp/n*100
    g_tp = s[s["outcome"]=="TP"]["pnl"].mean() if tp>0 else TP_PCT*100
    g_sl = abs(s[s["outcome"]=="SL"]["pnl"].mean()) if sl>0 else SL_PCT*100
    pf   = (tp*g_tp)/(sl*g_sl) if sl>0 else 999
    ev   = s["pnl"].mean(); tpw = n/WEEKS
    cum  = np.cumsum(s["pnl"].values); peak=np.maximum.accumulate(cum)
    maxdd= (cum-peak).min()
    return dict(n=n, tpw=tpw, wr=wr, tp=int(tp), sl=int(sl), pf=pf, ev=ev, maxdd=maxdd)

def mk_flag(pf):
    if pf >= 2.0: return "<<<" 
    if pf >= 1.5: return "<<" 
    if pf >= 1.2: return "<"  
    if pf <  1.0: return "-"  
    return ""

def prow(label, s, w=30):
    mx=met(s)
    if mx is None:
        print(f"  {label:<{w}} {'--':>5}")
        return
    mk=mk_flag(mx["pf"])
    print(f"  {label:<{w}} {mx['n']:>5} {mx['tpw']:>5.1f}  {mx['wr']:>5.1f}%  "
          f"{mx['tp']:>4}/{mx['sl']:<4}  {mx['pf']:>6.3f}  {mx['ev']:>+7.4f}%  {mx['maxdd']:>+7.2f}%  {mk}")

HDR = (f"  {'Label':<30} {'N':>5} {'T/Wk':>5}  {'WR':>6}  "
       f"{'TP/SL':>9}  {'PF':>6}  {'EV/trade':>9}  {'MaxDD':>7}  {'':>3}")
SEP = f"  {'-'*84}"
W   = 88


if __name__ == "__main__":
    print("Scanning...", flush=True)
    df = run_all()

    # restrict to fresh 1st touch for matrix (cleanest signal)
    fresh1 = df[(df["fresh"]==True) & (df["touch"]=="1st")]
    # all touches for recency
    all_t  = df.copy()

    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  TEST 1 — SYMBOL x LEVEL MATRIX  (fresh 1st touch, short, gap up)")
    print(f"  PF by cell  |  '--' = N<5")
    print(f"{'='*W}")

    # Wide table header
    col_w = 9
    print(f"\n  {'Sym':<6}", end="")
    for fam in FAMILIES:
        print(f"  {fam:>{col_w}}", end="")
    print()
    print(f"  {'-'*6}", end="")
    for _ in FAMILIES:
        print(f"  {'-'*col_w}", end="")
    print()

    for sym in SYMS:
        print(f"  {sym:<6}", end="")
        for fam in FAMILIES:
            s = fresh1[(fresh1["sym"]==sym) & (fresh1["family"]==fam)]
            mx = met(s)
            if mx is None:
                print(f"  {'--':>{col_w}}", end="")
            else:
                cell = f"{mx['pf']:.3f}{mk_flag(mx['pf'])}"
                print(f"  {cell:>{col_w}}", end="")
        print()

    # Also N counts
    print(f"\n  N by cell:")
    print(f"  {'Sym':<6}", end="")
    for fam in FAMILIES:
        print(f"  {fam:>{col_w}}", end="")
    print()
    for sym in SYMS:
        print(f"  {sym:<6}", end="")
        for fam in FAMILIES:
            s = fresh1[(fresh1["sym"]==sym) & (fresh1["family"]==fam)]
            print(f"  {len(s):>{col_w}}", end="")
        print()

    # EV by cell
    print(f"\n  EV/trade by cell:")
    print(f"  {'Sym':<6}", end="")
    for fam in FAMILIES:
        print(f"  {fam:>{col_w}}", end="")
    print()
    for sym in SYMS:
        print(f"  {sym:<6}", end="")
        for fam in FAMILIES:
            s = fresh1[(fresh1["sym"]==sym) & (fresh1["family"]==fam)]
            mx = met(s)
            if mx is None:
                print(f"  {'--':>{col_w}}", end="")
            else:
                print(f"  {mx['ev']:>+{col_w}.4f}%", end="")
        print()

    # Per-symbol best level (fresh 1st)
    print(f"\n  BEST LEVEL per symbol (fresh 1st, highest PF with N>=8):")
    print(HDR); print(SEP)
    for sym in SYMS:
        best_pf=-1; best_lbl=""; best_s=None
        for fam in FAMILIES:
            s=fresh1[(fresh1["sym"]==sym)&(fresh1["family"]==fam)]
            mx=met(s)
            if mx and mx["n"]>=8 and mx["pf"]>best_pf:
                best_pf=mx["pf"]; best_lbl=fam; best_s=s
        if best_s is not None:
            prow(f"  {sym} -> {best_lbl}", best_s)

    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  TEST 2 — RECENCY  (all touches, PMH + 1H_Res + 2H_Res)")
    print(f"  never_today / within_30m / within_60m / over_60m")
    print(f"{'='*W}")
    print(HDR); print(SEP)

    for fam in ["PMH","1H_Res","2H_Res"]:
        s = df[df["family"]==fam]
        print(f"  {fam}")
        for rec, label in [("never_today","  Never today (fresh)"),
                            ("within_30m", "  Touched <30m ago   "),
                            ("within_60m", "  Touched 30-60m ago "),
                            ("over_60m",   "  Touched >60m ago   ")]:
            prow(label, s[s["recency"]==rec])
        print(SEP)

    # recency x touch count for PMH
    print(f"  PMH: recency x 1st vs 2nd vs 3rd+")
    print(HDR); print(SEP)
    pmh = df[df["family"]=="PMH"]
    for rec in ["never_today","within_30m","within_60m","over_60m"]:
        for tc in ["1st","2nd","3rd+"]:
            s = pmh[(pmh["recency"]==rec)&(pmh["touch"]==tc)]
            if len(s)>=5:
                prow(f"  PMH {rec[:12]} {tc}", s)
    print(SEP)

    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  TEST 3 — FRESH 1H_Res + 2H_Res OVERLAP  (within 0.15%)")
    print(f"  1H_Res level that has a 2H_Res within 0.15% = 'confluence zone'")
    print(f"{'='*W}")
    print(HDR); print(SEP)

    lh_all   = df[df["family"]=="1H_Res"]
    lh_ov    = df[(df["family"]=="1H_Res") & (df["overlaps_2h"]==True)]
    lh_no    = df[(df["family"]=="1H_Res") & (df["overlaps_2h"]==False)]
    lh_fresh = df[(df["family"]=="1H_Res") & (df["fresh"]==True)  & (df["touch"]=="1st")]
    lh_ov_f  = df[(df["family"]=="1H_Res") & (df["overlaps_2h"]==True)  & (df["fresh"]==True)  & (df["touch"]=="1st")]
    lh_no_f  = df[(df["family"]=="1H_Res") & (df["overlaps_2h"]==False) & (df["fresh"]==True)  & (df["touch"]=="1st")]

    prow("1H_Res all",                  lh_all)
    prow("1H_Res + 2H overlap (all tc)",lh_ov)
    prow("1H_Res no overlap  (all tc)", lh_no)
    print(SEP)
    prow("1H_Res fresh 1st (all)",      lh_fresh)
    prow("1H_Res + 2H overlap FRESH 1st", lh_ov_f)
    prow("1H_Res no overlap  FRESH 1st",  lh_no_f)
    print(SEP)

    # by symbol for the overlap
    print(f"  1H+2H overlap fresh 1st -- by symbol:")
    for sym in SYMS:
        s = lh_ov_f[lh_ov_f["sym"]==sym]
        prow(f"    {sym}", s)

    # How often does 1H overlap with 2H?
    total_1h_f1 = len(lh_fresh)
    ov_count    = len(lh_ov_f)
    print(f"\n  Overlap hit rate: {ov_count}/{total_1h_f1} = {ov_count/total_1h_f1*100:.0f}% of fresh 1H touches have a nearby 2H level" if total_1h_f1>0 else "")

    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*W}")
    print(f"  SUMMARY — Recency ranking for PMH (all touches combined)")
    print(f"{'='*W}")
    print(HDR); print(SEP)
    pmh_all = df[df["family"]=="PMH"]
    for rec, label in [("never_today","Never today"),
                        ("within_30m", "Touched <30m"),
                        ("within_60m", "Touched 30-60m"),
                        ("over_60m",   "Touched >60m")]:
        prow(label, pmh_all[pmh_all["recency"]==rec])
