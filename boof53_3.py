"""
BOOF53.3 — Multi-Touch Level Pattern
Long:  price touches support (PML/PDL/1H sup), bounces >=0.15%,
       returns to level, reclaims → enter long
Short: price touches resistance (PMH/PDH/1H res), drops >=0.15%,
       returns to level, fails again → enter short
Track: touch count (1st, 2nd, 3rd) × N, MFE30, >=0.50%, >=0.75%
"""
import pandas as pd
import numpy as np
import pytz

ET       = pytz.timezone("America/New_York")
SYM      = "QQQ"
NEAR_PCT = 0.0015    # within 0.15% = touching the level
BOUNCE   = 0.0015    # must bounce/reject at least 0.15% before returning
TARGETS  = [0.0050, 0.0075]
T_LABELS = ["+0.50%", "+0.75%"]


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
    stats = stats.merge(dc[["next_date","prev_close"]].rename(
        columns={"next_date":"date"}), on="date", how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index()
    rth.columns = ["date","rth_open"]
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

def build_1h_sr(rt_df):
    """Rolling 60-bar pivot highs/lows as 1H S/R, clustered within 0.20%."""
    rt_df = rt_df.sort_values("time").reset_index(drop=True)
    sr = {}
    dates = sorted(rt_df["date"].unique())
    for d in dates:
        hist = rt_df[rt_df["date"] < d].tail(60)
        if len(hist) < 20: continue
        H = hist["high"].values; L = hist["low"].values
        levels = []
        for i in range(3, len(hist)-3):
            if H[i] == max(H[max(0,i-3):i+4]):
                levels.append((H[i], "res"))
            if L[i] == min(L[max(0,i-3):i+4]):
                levels.append((L[i], "sup"))
        if not levels: continue
        levels = sorted(levels, key=lambda x: x[0])
        clustered = [list(levels[0])]
        for lv, lt in levels[1:]:
            if abs(lv-clustered[-1][0])/clustered[-1][0] < 0.002:
                clustered[-1][0] = (clustered[-1][0]+lv)/2
            else:
                clustered.append([lv, lt])
        sr[d] = [(c[0], c[1]) for c in clustered]
    return sr

def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars, key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key] = float(max((H[sl]-ep)/ep*100)) if side=="long" \
              else float(max((ep-L[sl])/ep*100))
    end30=min(ei+30,n-1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end30+1]>=ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end30+1]<=ep*(1-tgt)))
    return res


# ── Core pattern detector ─────────────────────────────────────────────────────

def find_touches(ddf, level, direction, t_start="09:00", t_end="12:00"):
    """
    direction: "sup" (long) or "res" (short)
    State machine per level:
      IDLE -> TOUCHING -> BOUNCED -> RETURNING -> ENTRY (triggered)
    Returns list of {bar_idx, touch_num, ep, ...exc}
    """
    n = len(ddf)
    H = ddf["high"].values
    L = ddf["low"].values
    C = ddf["close"].values

    entries    = []
    touch_num  = 0
    state      = "IDLE"
    bounce_extreme = None   # highest close seen after bounce (sup) or lowest (res)

    i = 1
    while i < n - 31:
        t = ddf.iloc[i]["time"].strftime("%H:%M")
        if t < t_start or t >= t_end:
            i += 1; continue

        cl = C[i]; hi = H[i]; lo = L[i]

        if direction == "sup":
            touching = lo <= level * (1 + NEAR_PCT)
            above    = cl > level * (1 + NEAR_PCT)

            if state == "IDLE":
                if touching:
                    state = "TOUCHING"
                    bounce_extreme = cl

            elif state == "TOUCHING":
                if touching:
                    bounce_extreme = max(bounce_extreme, cl) if bounce_extreme else cl
                else:
                    # Left the touch zone
                    if bounce_extreme and (bounce_extreme - level) / level >= BOUNCE:
                        state  = "BOUNCED"
                        touch_num += 1
                    else:
                        state = "IDLE"   # didn't bounce enough
                    bounce_extreme = None

            elif state == "BOUNCED":
                # Waiting for price to return toward level
                if touching:
                    # Returned AND close above level = reclaim → ENTRY
                    if cl > level:
                        state = "IDLE"
                        ei = i + 1
                        if ei < n:
                            ep = ddf.iloc[ei]["open"]
                            entries.append({
                                "bar_idx":  i,
                                "touch_num":touch_num,
                                "ep":       ep,
                                **exc(ddf, ei, ep, "long")
                            })
                    else:
                        # Returned but broke through — reset
                        state = "IDLE"; touch_num = 0

        else:  # direction == "res"
            touching = hi >= level * (1 - NEAR_PCT)
            below    = cl < level * (1 - NEAR_PCT)

            if state == "IDLE":
                if touching:
                    state = "TOUCHING"
                    bounce_extreme = cl

            elif state == "TOUCHING":
                if touching:
                    bounce_extreme = min(bounce_extreme, cl) if bounce_extreme else cl
                else:
                    if bounce_extreme and (level - bounce_extreme) / level >= BOUNCE:
                        state = "BOUNCED"
                        touch_num += 1
                    else:
                        state = "IDLE"
                    bounce_extreme = None

            elif state == "BOUNCED":
                if touching:
                    if cl < level:
                        state = "IDLE"
                        ei = i + 1
                        if ei < n:
                            ep = ddf.iloc[ei]["open"]
                            entries.append({
                                "bar_idx":  i,
                                "touch_num":touch_num,
                                "ep":       ep,
                                **exc(ddf, ei, ep, "short")
                            })
                    else:
                        state = "IDLE"; touch_num = 0

        i += 1

    return entries


def scan(rt_df, pm_stats, prev_day, sr_1h):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm    = pm_stats.set_index("date")
    records = []

    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        gap = day["gap_pct"]
        gap_regime = "Gap Down" if gap < -0.5 else ("Gap Up" if gap > 0.5 else "Flat")

        ddf = ddf.reset_index(drop=True)

        pmh = day["pm_high"]; pml = day["pm_low"]
        pd_info = prev_day.get(date_ts, {})
        pdh = pd_info.get("pdh", np.nan)
        pdl = pd_info.get("pdl", np.nan)

        date_key = date.date() if hasattr(date, "date") else date
        sr = sr_1h.get(date_key, [])
        sup_1h = [lv for lv, lt in sr if lt == "sup"]
        res_1h = [lv for lv, lt in sr if lt == "res"]

        # ── LONG levels (support) ─────────────────────────────────────────────
        long_levels = []
        long_levels.append((pml, "PML"))
        if not pd.isna(pdl): long_levels.append((pdl, "PDL"))
        for lv in sup_1h:
            long_levels.append((lv, "1H_Sup"))

        for level, level_name in long_levels:
            touches = find_touches(ddf, level, "sup")
            for t in touches:
                records.append({
                    "date":       str(date.date()),
                    "side":       "long",
                    "level_name": level_name,
                    "level_px":   round(level, 2),
                    "gap_regime": gap_regime,
                    "gap_pct":    round(gap, 3),
                    "touch_num":  t["touch_num"],
                    "touch_lbl":  "1st" if t["touch_num"]==1 else
                                  ("2nd" if t["touch_num"]==2 else "3rd+"),
                    "ep":         t["ep"],
                    **{k:v for k,v in t.items() if k not in ("bar_idx","touch_num","ep")}
                })

        # ── SHORT levels (resistance) ─────────────────────────────────────────
        short_levels = []
        short_levels.append((pmh, "PMH"))
        if not pd.isna(pdh): short_levels.append((pdh, "PDH"))
        for lv in res_1h:
            short_levels.append((lv, "1H_Res"))

        for level, level_name in short_levels:
            touches = find_touches(ddf, level, "res")
            for t in touches:
                records.append({
                    "date":       str(date.date()),
                    "side":       "short",
                    "level_name": level_name,
                    "level_px":   round(level, 2),
                    "gap_regime": gap_regime,
                    "gap_pct":    round(gap, 3),
                    "touch_num":  t["touch_num"],
                    "touch_lbl":  "1st" if t["touch_num"]==1 else
                                  ("2nd" if t["touch_num"]==2 else "3rd+"),
                    "ep":         t["ep"],
                    **{k:v for k,v in t.items() if k not in ("bar_idx","touch_num","ep")}
                })

    return pd.DataFrame(records) if records else pd.DataFrame()


# ── Report ────────────────────────────────────────────────────────────────────

def prow(label, s, w=30):
    if s.empty:
        print(f"  {label:<{w}} {'--':>5}"); return
    n=len(s); nd=s["date"].nunique()
    m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
    h50=s[f"hit_{T_LABELS[0]}"].mean()*100
    h75=s[f"hit_{T_LABELS[1]}"].mean()*100
    mark = " <<<" if h50 >= 30 else ""
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")


def report(df):
    W = 88
    HDR = (f"  {'Label':<30} {'N':>5} {'Days':>5}  "
           f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP = f"  {'-'*84}"

    print(f"\n{'='*W}")
    print(f"  BOOF53.3 | {SYM} | Multi-Touch Level Pattern")
    print(f"  Bounce required: >={BOUNCE*100:.2f}% | Near threshold: {NEAR_PCT*100:.2f}%")
    print(f"{'='*W}")

    for side, levels in [("long",  ["PML","PDL","1H_Sup"]),
                          ("short", ["PMH","PDH","1H_Res"])]:
        base = df[df["side"]==side]
        print(f"\n{'='*W}")
        print(f"  {'LONG — Support Levels' if side=='long' else 'SHORT — Resistance Levels'}   N={len(base)}")
        print(f"{'='*W}")
        print(HDR); print(SEP)

        # All combined
        prow("ALL", base)
        print(SEP)

        # By level name
        for lname in levels:
            s = base[base["level_name"]==lname]
            prow(lname, s)
        print(SEP)

        # By touch count
        for tlbl in ["1st","2nd","3rd+"]:
            s = base[base["touch_lbl"]==tlbl]
            prow(f"Touch {tlbl}", s)
        print(SEP)

        # Level × touch cross-tab
        print(f"\n  LEVEL × TOUCH COUNT")
        print(f"  {'Level':<10} {'Touch':<8} {'N':>5}  "
              f"{'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*55}")
        for lname in levels:
            for tlbl in ["1st","2nd","3rd+"]:
                s = base[(base["level_name"]==lname)&(base["touch_lbl"]==tlbl)]
                if s.empty: continue
                h50=s[f"hit_{T_LABELS[0]}"].mean()*100
                h75=s[f"hit_{T_LABELS[1]}"].mean()*100
                mark = " <<<" if h50 >= 30 else ""
                print(f"  {lname:<10} {tlbl:<8} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mark}")

        # Gap regime × touch for best level
        best_level = max(levels, key=lambda l:
            base[base["level_name"]==l][f"hit_{T_LABELS[0]}"].mean()
            if not base[base["level_name"]==l].empty else 0)
        bl = base[base["level_name"]==best_level]
        print(f"\n  GAP REGIME × TOUCH  ({best_level} only)")
        print(f"  {'Regime':<14} {'Touch':<8} {'N':>5}  "
              f"{'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*55}")
        for regime in ["Gap Down","Flat","Gap Up"]:
            for tlbl in ["1st","2nd","3rd+"]:
                s = bl[(bl["gap_regime"]==regime)&(bl["touch_lbl"]==tlbl)]
                if s.empty: continue
                h50=s[f"hit_{T_LABELS[0]}"].mean()*100
                h75=s[f"hit_{T_LABELS[1]}"].mean()*100
                mark = " <<<" if h50 >= 35 else ""
                print(f"  {regime:<14} {tlbl:<8} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mark}")


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    prev_day = build_prev_day(rt_df)
    print(f"  Building 1H S/R...", flush=True)
    sr_1h    = build_1h_sr(rt_df)
    print(f"  {len(pm_stats)} days", flush=True)

    df = scan(rt_df, pm_stats, prev_day, sr_1h)
    print(f"  {len(df)} pattern entries found", flush=True)

    if not df.empty:
        report(df)
        df.to_csv(f"boof53_3_{SYM}.csv", index=False)
        print(f"\n  Saved boof53_3_{SYM}.csv")
    else:
        print("  No patterns found — try loosening BOUNCE or NEAR_PCT")
