"""
BOOF53.5 — Double-Touch + Confirmation Entry
Long:  touch support, bounce >= X%, return, hold level, confirm entry
Short: touch resistance, reject >= X%, return, fail level, confirm entry

Levels: PML, PDL, 1H sup/res, 4H sup/res
Bounce test: 0.10, 0.15, 0.20, 0.30%
Confirmation versions:
  A: break previous 1m swing high (long) / low (short)
  B: break previous 5m swing high / low
  C: move 0.15% away from level
  D: move 0.25% away from level

Measure: MFE15, MFE30, MFE60, >=0.40%, >=0.50%, >=0.60%, >=0.75%
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYM      = "QQQ"
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCES  = [0.0010, 0.0015, 0.0020, 0.0030]
TARGETS  = [0.0040, 0.0050, 0.0060, 0.0075]
T_LABELS = [">=0.40%",">=0.50%",">=0.60%",">=0.75%"]


def load_rt():
    df = pd.read_csv(f"boof51_{SYM}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def load_pm():
    df = pd.read_csv(f"boof51_{SYM}_pm.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df

def build_pm_stats(pm_df, rt_df):
    pm_df = pm_df.copy(); pm_df["date"] = pm_df["time"].dt.date
    dc = rt_df.groupby("date")["close"].last().reset_index()
    dc.columns = ["date","prev_close"]; dc["date"] = pd.to_datetime(dc["date"])
    dc["next_date"] = dc["date"] + pd.Timedelta(days=1)
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct"])

def build_prev_day(rt_df):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    dates = sorted(rt_df["date"].unique())
    prev = {}
    for i in range(1, len(dates)):
        d = dates[i]; p = dates[i-1]
        g = rt_df[rt_df["date"]==p]
        if not g.empty:
            prev[d] = {"pdh": g["high"].max(), "pdl": g["low"].min()}
    return prev

def build_pivots(rt_df, lookback, wing):
    rt_df = rt_df.sort_values("time").reset_index(drop=True)
    sr = {}
    dates = sorted(rt_df["date"].unique())
    for d in dates:
        hist = rt_df[rt_df["date"] < d].tail(lookback)
        if len(hist) < lookback // 2: continue
        H = hist["high"].values; L = hist["low"].values
        levels = []
        for i in range(wing, len(hist)-wing):
            if H[i] == max(H[i-wing:i+wing+1]): levels.append((H[i],"res"))
            if L[i] == min(L[i-wing:i+wing+1]): levels.append((L[i],"sup"))
        if not levels: continue
        levels = sorted(levels, key=lambda x: x[0])
        cl = [list(levels[0])]
        for lv, lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0] < OVERLAP:
                cl[-1][0] = (cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        sr[d] = [(c[0],c[1]) for c in cl]
    return sr


def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key] = float(max((H[sl]-ep)/ep*100)) if side=="long" \
              else float(max((ep-L[sl])/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end60+1]>=ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res


def swing_high(ddf, idx, lookback=5):
    """Highest high over lookback bars ending at idx."""
    start = max(0, idx-lookback)
    return ddf["high"].values[start:idx+1].max()

def swing_low(ddf, idx, lookback=5):
    start = max(0, idx-lookback)
    return ddf["low"].values[start:idx+1].min()

def swing_high_5m(ddf, idx):
    """Highest high over last 5 bars (proxy for 5m swing)."""
    return swing_high(ddf, idx, lookback=5)

def swing_low_5m(ddf, idx):
    return swing_low(ddf, idx, lookback=5)


def find_double_touch(ddf, level, direction, min_bounce):
    """
    State machine:
    IDLE -> T1_TOUCHING -> T1_BOUNCED -> T2_RETURNING -> T2_TOUCHING -> CONFIRM_WAIT -> ENTRY

    Returns list of entries, each with confirmation method A/B/C/D.
    """
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    entries=[]; state="IDLE"
    bounce_extreme=None     # peak of bounce after T1
    swing_ref=None          # swing high/low to break for confirmation
    i=1

    while i < n-61:
        t=ddf.iloc[i]["time"].strftime("%H:%M")
        if t<"09:00" or t>="12:00": i+=1; continue
        cl=C[i]; hi=H[i]; lo=L[i]

        if direction=="sup":
            touching = lo <= level*(1+NEAR_PCT)
            away     = cl > level*(1+NEAR_PCT*2)

            if state=="IDLE":
                if touching: state="T1_TOUCHING"; bounce_extreme=cl

            elif state=="T1_TOUCHING":
                if touching:
                    bounce_extreme = max(bounce_extreme, cl)
                else:
                    # Left touch zone
                    if bounce_extreme and (bounce_extreme-level)/level >= min_bounce:
                        state="T1_BOUNCED"
                        swing_ref = bounce_extreme   # swing high to break = peak of T1 bounce
                    else:
                        state="IDLE"
                    bounce_extreme=None

            elif state=="T1_BOUNCED":
                # Waiting to return toward level
                if touching:
                    if cl > level:   # held on T2 touch → look for confirm
                        state="CONFIRM_WAIT"
                    else:
                        state="IDLE"  # broke through on T2 → reset

            elif state=="CONFIRM_WAIT":
                if touching: i+=1; continue   # still at level, keep waiting
                # Off the level — check confirmation
                fired = False
                ep_bar = i+1
                if ep_bar >= n: break

                # Version A: break 1m swing high (5-bar lookback)
                sw1 = swing_high(ddf, i, lookback=5)
                if cl > sw1:
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"A","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"long")}); fired=True

                # Version B: break 5m swing high (use 5-bar lookback same granularity)
                sw5 = swing_high_5m(ddf, i)
                if cl > sw5:
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"B","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"long")}); fired=True

                # Version C: moved 0.15% above level
                if cl >= level*(1+0.0015):
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"C","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"long")}); fired=True

                # Version D: moved 0.25% above level
                if cl >= level*(1+0.0025):
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"D","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"long")}); fired=True

                state="IDLE"  # reset after confirm attempt

        else:  # resistance short
            touching = hi >= level*(1-NEAR_PCT)

            if state=="IDLE":
                if touching: state="T1_TOUCHING"; bounce_extreme=cl

            elif state=="T1_TOUCHING":
                if touching:
                    bounce_extreme = min(bounce_extreme, cl)
                else:
                    if bounce_extreme and (level-bounce_extreme)/level >= min_bounce:
                        state="T1_BOUNCED"
                        swing_ref = bounce_extreme
                    else:
                        state="IDLE"
                    bounce_extreme=None

            elif state=="T1_BOUNCED":
                if touching:
                    if cl < level:
                        state="CONFIRM_WAIT"
                    else:
                        state="IDLE"

            elif state=="CONFIRM_WAIT":
                if touching: i+=1; continue
                ep_bar = i+1
                if ep_bar >= n: break

                sw1 = swing_low(ddf, i, lookback=5)
                if cl < sw1:
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"A","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"short")})

                sw5 = swing_low_5m(ddf, i)
                if cl < sw5:
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"B","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"short")})

                if cl <= level*(1-0.0015):
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"C","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"short")})

                if cl <= level*(1-0.0025):
                    ep = ddf.iloc[ep_bar]["open"]
                    entries.append({"conf":"D","ep":ep,"bar_idx":i,
                                    **exc(ddf,ep_bar,ep,"short")})

                state="IDLE"

        i+=1
    return entries


def scan(rt_df, pm_stats, prev_day, sr_1h, sr_4h):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm    = pm_stats.set_index("date")
    all_records = {b: [] for b in BOUNCES}

    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        gap = day["gap_pct"]
        gap_regime = "Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")

        ddf = ddf.reset_index(drop=True)
        pmh=day["pm_high"]; pml=day["pm_low"]
        pd_info=prev_day.get(date_ts,{})
        pdh=pd_info.get("pdh",np.nan); pdl=pd_info.get("pdl",np.nan)

        dk = date.date() if hasattr(date,"date") else date
        lv1h  = sr_1h.get(dk,[])
        lv4h  = sr_4h.get(dk,[])

        long_levels  = [(pml,"PML")]
        short_levels = [(pmh,"PMH")]
        if not pd.isna(pdl): long_levels.append((pdl,"PDL"))
        if not pd.isna(pdh): short_levels.append((pdh,"PDH"))
        for lv,lt in lv1h:
            if lt=="sup": long_levels.append((lv,"1H_Sup"))
            else:         short_levels.append((lv,"1H_Res"))
        for lv,lt in lv4h:
            if lt=="sup": long_levels.append((lv,"4H_Sup"))
            else:         short_levels.append((lv,"4H_Res"))

        for min_bounce in BOUNCES:
            for level, level_name in long_levels:
                for e in find_double_touch(ddf, level, "sup", min_bounce):
                    all_records[min_bounce].append({
                        "date":str(date.date()),"side":"long","level":level_name,
                        "gap_regime":gap_regime,"gap_pct":round(gap,3),
                        "bounce_req":min_bounce,"conf":e["conf"],"ep":e["ep"],
                        **{k:v for k,v in e.items() if k not in ("conf","ep","bar_idx")}
                    })
            for level, level_name in short_levels:
                for e in find_double_touch(ddf, level, "res", min_bounce):
                    all_records[min_bounce].append({
                        "date":str(date.date()),"side":"short","level":level_name,
                        "gap_regime":gap_regime,"gap_pct":round(gap,3),
                        "bounce_req":min_bounce,"conf":e["conf"],"ep":e["ep"],
                        **{k:v for k,v in e.items() if k not in ("conf","ep","bar_idx")}
                    })

    return {b: pd.DataFrame(v) for b,v in all_records.items()}


def prow(label, s, w=22):
    if s.empty or len(s)<3:
        print(f"  {label:<{w}} {'<3':>5}"); return
    n=len(s); nd=s["date"].nunique()
    m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    hits=[s[f"hit_{l}"].mean()*100 for l in T_LABELS]
    mark=" <<<" if hits[1]>=35 else ("  <<" if hits[1]>=25 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
          f"{hits[0]:>6.1f}% {hits[1]:>6.1f}% {hits[2]:>6.1f}% {hits[3]:>6.1f}%{mark}")


def report(all_dfs):
    W=108
    HDR=(f"  {'Label':<22} {'N':>5} {'Days':>5}  "
         f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
         f"{'>=0.40%':>8} {'>=0.50%':>8} {'>=0.60%':>8} {'>=0.75%':>8}")
    SEP=f"  {'-'*104}"

    print(f"\n{'='*W}")
    print(f"  BOOF53.5 | {SYM} | Double-Touch + Confirmation")
    print(f"  Levels: PML/PDL/1H/4H (long)  PMH/PDH/1H/4H (short)")
    print(f"{'='*W}")

    # Main table: bounce threshold × confirmation version
    for side in ["long","short"]:
        print(f"\n{'='*W}")
        print(f"  {'LONG — Support' if side=='long' else 'SHORT — Resistance'}")
        print(f"{'='*W}")
        print(HDR); print(SEP)

        for bounce in BOUNCES:
            df = all_dfs[bounce]
            if df.empty: continue
            base = df[df["side"]==side]
            b_lbl = f"Bounce>={bounce*100:.2f}%"
            # All confirmations combined
            prow(b_lbl+" ALL", base)
            # Per confirmation version
            for conf in ["A","B","C","D"]:
                s = base[base["conf"]==conf]
                prow(f"  {b_lbl} {conf}", s)
            print(SEP)

    # Best bounce: drill into conf × level × gap regime
    print(f"\n{'='*W}")
    print(f"  DRILL DOWN — Best bounce per side × Conf × Level × Gap Regime")
    print(f"{'='*W}")

    for side, best_bounce in [("long", 0.0015), ("short", 0.0015)]:
        df = all_dfs[best_bounce][all_dfs[best_bounce]["side"]==side]
        print(f"\n  {side.upper()}  bounce>={best_bounce*100:.2f}%  N={len(df)}")
        print(HDR); print(SEP)

        for conf in ["A","B","C","D"]:
            cs = df[df["conf"]==conf]
            if cs.empty: continue
            prow(f"Conf {conf} ALL", cs)
            for level in cs["level"].unique():
                ls = cs[cs["level"]==level]
                prow(f"  {conf} {level}", ls)
            for regime in ["Gap Down","Flat","Gap Up"]:
                rs = cs[cs["gap_regime"]==regime]
                prow(f"  {conf} {regime}", rs)
            print(SEP)


if __name__=="__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    prev_day = build_prev_day(rt_df)
    print("  Building pivots...", flush=True)
    sr_1h = build_pivots(rt_df, lookback=60,  wing=3)
    sr_4h = build_pivots(rt_df, lookback=240, wing=5)
    print(f"  {len(pm_stats)} days", flush=True)

    print("  Scanning (4 bounce thresholds × all levels)...", flush=True)
    all_dfs = scan(rt_df, pm_stats, prev_day, sr_1h, sr_4h)
    for b, df in all_dfs.items():
        print(f"  Bounce>={b*100:.2f}%: {len(df)} entries", flush=True)

    report(all_dfs)

    # Save best
    best = all_dfs[0.0015]
    if not best.empty:
        best.to_csv(f"boof53_5_{SYM}.csv", index=False)
        print(f"\n  Saved boof53_5_{SYM}.csv")
