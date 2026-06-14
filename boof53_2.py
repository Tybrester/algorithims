"""
BOOF53.2 — PMH Rejection Short + PML Rejection Long
Break down by:
  1. Gap regime (Gap Down / Flat / Gap Up)
  2. Touch count (1st / 2nd / 3rd+ touch of that level today)
Pure excursion: N, MFE15, MFE30, >=0.50%, >=0.75%
"""
import pandas as pd
import numpy as np
import pytz

ET  = pytz.timezone("America/New_York")
SYM = "QQQ"
NEAR_PCT = 0.0015

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
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["gap_pct"])


def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars, key in [(15,"mfe15"),(30,"mfe30")]:
        end=min(ei+bars, n-1); sl=slice(ei, end+1)
        res[key] = float(max((H[sl]-ep)/ep*100)) if side=="long" \
              else float(max((ep-L[sl])/ep*100))
    end30 = min(ei+30, n-1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end30+1] >= ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end30+1] <= ep*(1-tgt)))
    return res


def scan(rt_df, pm_stats):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm    = pm_stats.set_index("date")
    records = []

    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        pmh = day["pm_high"]; pml = day["pm_low"]
        gap = day["gap_pct"]
        gap_regime = "Gap Down" if gap < -0.5 else ("Gap Up" if gap > 0.5 else "Flat")

        ddf = ddf.reset_index(drop=True)
        n   = len(ddf)

        pmh_touch_count = 0
        pml_touch_count = 0
        pmh_in_touch    = False   # currently inside a touch zone (debounce)
        pml_in_touch    = False

        for i in range(1, n - 31):
            row  = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue

            hi = row["high"]; lo = row["low"]; cl = row["close"]

            # ── PMH Rejection (short) ─────────────────────────────────────────
            # Touch: high reaches within NEAR_PCT of PMH
            touching_pmh = hi >= pmh * (1 - NEAR_PCT)

            if touching_pmh and not pmh_in_touch:
                pmh_in_touch = True
                pmh_touch_count += 1
                # Rejection: closed below PMH (failed to break)
                if cl < pmh:
                    touch_n = min(pmh_touch_count, 3)  # cap at 3+
                    ei = i + 1
                    if ei < n:
                        ep = ddf.iloc[ei]["open"]
                        records.append({
                            "date":       str(date.date()),
                            "time":       t,
                            "level":      "PMH",
                            "event":      "Rejection",
                            "side":       "short",
                            "gap_regime": gap_regime,
                            "gap_pct":    round(gap, 3),
                            "touch_n":    touch_n,
                            "touch_lbl":  "1st" if touch_n==1 else ("2nd" if touch_n==2 else "3rd+"),
                            "level_px":   round(pmh, 2),
                            "ep":         round(ep, 2),
                            **exc(ddf, ei, ep, "short")
                        })
            elif not touching_pmh:
                pmh_in_touch = False   # reset debounce when price leaves zone

            # ── PML Rejection (long) ──────────────────────────────────────────
            touching_pml = lo <= pml * (1 + NEAR_PCT)

            if touching_pml and not pml_in_touch:
                pml_in_touch = True
                pml_touch_count += 1
                # Rejection: closed above PML (held the level)
                if cl > pml:
                    touch_n = min(pml_touch_count, 3)
                    ei = i + 1
                    if ei < n:
                        ep = ddf.iloc[ei]["open"]
                        records.append({
                            "date":       str(date.date()),
                            "time":       t,
                            "level":      "PML",
                            "event":      "Rejection",
                            "side":       "long",
                            "gap_regime": gap_regime,
                            "gap_pct":    round(gap, 3),
                            "touch_n":    touch_n,
                            "touch_lbl":  "1st" if touch_n==1 else ("2nd" if touch_n==2 else "3rd+"),
                            "level_px":   round(pml, 2),
                            "ep":         round(ep, 2),
                            **exc(ddf, ei, ep, "long")
                        })
            elif not touching_pml:
                pml_in_touch = False

    return pd.DataFrame(records) if records else pd.DataFrame()


def print_row(label, s, indent="  "):
    if s.empty:
        print(f"{indent}  {label:<30} {'--':>5}"); return
    n   = len(s); nd = s["date"].nunique()
    m15 = s["mfe15"].mean(); m30 = s["mfe30"].mean()
    h50 = s[f"hit_{T_LABELS[0]}"].mean()*100
    h75 = s[f"hit_{T_LABELS[1]}"].mean()*100
    print(f"{indent}  {label:<30} {n:>5} {nd:>4}d  {m15:>6.3f}%  {m30:>6.3f}%   {h50:>6.1f}%   {h75:>6.1f}%")


def report(df):
    W = 76
    print(f"\n{'='*W}")
    print(f"  BOOF53.2 | {SYM} | PMH Rejection Short + PML Rejection Long")
    print(f"{'='*W}")
    hdr = f"  {'Label':<32} {'N':>5} {'Days':>5}  {'MFE15':>7}  {'MFE30':>7}   {'>=0.50%':>7}   {'>=0.75%':>7}"
    sep = f"  {'-'*72}"

    for level, side in [("PMH","short"), ("PML","long")]:
        base = df[(df["level"]==level) & (df["event"]=="Rejection")]
        print(f"\n{'='*W}")
        print(f"  {level} Rejection ({side.upper()})  — ALL: N={len(base)}")
        print(f"{'='*W}")
        print(hdr); print(sep)

        # Overall
        print_row("ALL", base)
        print(sep)

        # By gap regime
        for regime in ["Gap Down", "Flat", "Gap Up"]:
            rg = base[base["gap_regime"]==regime]
            print_row(regime, rg)
        print(sep)

        # By touch count
        for tlbl in ["1st", "2nd", "3rd+"]:
            tc = base[base["touch_lbl"]==tlbl]
            print_row(f"Touch {tlbl}", tc)
        print(sep)

        # Gap regime x touch count cross-tab
        print(f"\n  CROSS-TAB: Gap Regime × Touch Count")
        print(f"  {'Regime':<14} {'Touch':<8} {'N':>5}  {'MFE30':>7}   {'>=0.50%':>7}   {'>=0.75%':>7}")
        print(f"  {'-'*60}")
        for regime in ["Gap Down", "Flat", "Gap Up"]:
            for tlbl in ["1st", "2nd", "3rd+"]:
                s = base[(base["gap_regime"]==regime) & (base["touch_lbl"]==tlbl)]
                if s.empty: continue
                h50 = s[f"hit_{T_LABELS[0]}"].mean()*100
                h75 = s[f"hit_{T_LABELS[1]}"].mean()*100
                marker = " <<<" if h50 >= 30 else ("")
                print(f"  {regime:<14} {tlbl:<8} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%   {h50:>6.1f}%   {h75:>6.1f}%{marker}")


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    print(f"  {len(pm_stats)} days", flush=True)

    df = scan(rt_df, pm_stats)
    print(f"  {len(df)} rejection events", flush=True)

    report(df)
    df.to_csv(f"boof53_2_{SYM}.csv", index=False)
    print(f"\n  Saved boof53_2_{SYM}.csv")
