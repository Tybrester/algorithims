"""
BOOF53.1 — PM High/Low Touch Classification
For every bar that touches PM high or PM low:
  Rejection: touches level, closes back away (fails)
  Breakout:  closes through level
Measure: N, MFE15, MFE30, >=0.50% in 30m
Direction: Rejection from PMH = short, Rejection from PML = long
           Breakout above PMH = long,  Breakout below PML = short
"""
import pandas as pd
import numpy as np
import pytz

ET  = pytz.timezone("America/New_York")
SYM = "QQQ"

NEAR_PCT = 0.0015      # within 0.15% = "touching" the level
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

        ddf = ddf.reset_index(drop=True)
        n   = len(ddf)

        # Track first occurrence of each event to avoid duplicate signals
        pmh_reject_fired = pmh_break_fired = False
        pml_reject_fired = pml_break_fired = False

        for i in range(1, n - 31):
            row  = ddf.iloc[i]
            prev = ddf.iloc[i-1]
            t    = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue

            hi = row["high"]; lo = row["low"]; cl = row["close"]; op = row["open"]

            touching_pmh = hi >= pmh and lo <= pmh * (1 + NEAR_PCT)
            touching_pml = lo <= pml and hi >= pml * (1 - NEAR_PCT)

            # ── PM HIGH ───────────────────────────────────────────────────────
            if touching_pmh:
                # Rejection: high touches/exceeds PMH but close is below PMH
                if not pmh_reject_fired and cl < pmh:
                    pmh_reject_fired = True
                    ei = i + 1
                    if ei < n:
                        ep = ddf.iloc[ei]["open"]
                        records.append({
                            "date":    str(date.date()),
                            "level":   "PMH",
                            "event":   "Rejection",
                            "side":    "short",
                            "gap_pct": round(gap, 3),
                            "ep":      round(ep, 2),
                            "level_px":round(pmh, 2),
                            **exc(ddf, ei, ep, "short")
                        })

                # Breakout: close above PMH
                if not pmh_break_fired and cl > pmh:
                    pmh_break_fired = True
                    ei = i + 1
                    if ei < n:
                        ep = ddf.iloc[ei]["open"]
                        records.append({
                            "date":    str(date.date()),
                            "level":   "PMH",
                            "event":   "Breakout",
                            "side":    "long",
                            "gap_pct": round(gap, 3),
                            "ep":      round(ep, 2),
                            "level_px":round(pmh, 2),
                            **exc(ddf, ei, ep, "long")
                        })

            # ── PM LOW ────────────────────────────────────────────────────────
            if touching_pml:
                # Rejection: low touches/breaks PML but close is above PML
                if not pml_reject_fired and cl > pml:
                    pml_reject_fired = True
                    ei = i + 1
                    if ei < n:
                        ep = ddf.iloc[ei]["open"]
                        records.append({
                            "date":    str(date.date()),
                            "level":   "PML",
                            "event":   "Rejection",
                            "side":    "long",
                            "gap_pct": round(gap, 3),
                            "ep":      round(ep, 2),
                            "level_px":round(pml, 2),
                            **exc(ddf, ei, ep, "long")
                        })

                # Breakout: close below PML
                if not pml_break_fired and cl < pml:
                    pml_break_fired = True
                    ei = i + 1
                    if ei < n:
                        ep = ddf.iloc[ei]["open"]
                        records.append({
                            "date":    str(date.date()),
                            "level":   "PML",
                            "event":   "Breakout",
                            "side":    "short",
                            "gap_pct": round(gap, 3),
                            "ep":      round(ep, 2),
                            "level_px":round(pml, 2),
                            **exc(ddf, ei, ep, "short")
                        })

    return pd.DataFrame(records) if records else pd.DataFrame()


def report(df, pm_stats):
    n_days = len(pm_stats)
    W = 72

    print(f"\n{'='*W}")
    print(f"  BOOF53.1 | {SYM} | PM High/Low Touch Classification")
    print(f"  {n_days} trading days | Near threshold: {NEAR_PCT*100:.2f}%")
    print(f"{'='*W}")
    print(f"  {'Event':<26} {'N':>5} {'Days':>5}  {'MFE15':>7} {'MFE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
    print(f"  {'-'*68}")

    order = [
        ("PMH", "Rejection", "short"),
        ("PMH", "Breakout",  "long"),
        ("PML", "Rejection", "long"),
        ("PML", "Breakout",  "short"),
    ]

    for level, event, side in order:
        s = df[(df["level"]==level) & (df["event"]==event)]
        if s.empty:
            print(f"  {level+' '+event+' ('+side+')':<26} {'--':>5}"); continue
        nd   = s["date"].nunique()
        m15  = s["mfe15"].mean(); m30 = s["mfe30"].mean()
        h50  = s[f"hit_{T_LABELS[0]}"].mean()*100
        h75  = s[f"hit_{T_LABELS[1]}"].mean()*100
        lbl  = f"{level} {event} ({side})"
        print(f"  {lbl:<26} {len(s):>5} {nd:>5}d  {m15:>6.3f}% {m30:>6.3f}%  {h50:>7.1f}% {h75:>7.1f}%")

    # Gap regime breakdown
    print(f"\n  BY GAP REGIME")
    print(f"  {'Event':<26} {'Regime':<18} {'N':>5}  {'MFE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
    print(f"  {'-'*72}")
    regimes = [
        ("Gap Down",  df["gap_pct"] <  -0.5),
        ("Flat",     (df["gap_pct"] >= -0.5) & (df["gap_pct"] <= 0.5)),
        ("Gap Up",    df["gap_pct"] >   0.5),
    ]
    for level, event, side in order:
        s = df[(df["level"]==level) & (df["event"]==event)]
        lbl = f"{level} {event}"
        for rlbl, rmask in regimes:
            g = s[rmask]
            if g.empty: continue
            print(f"  {lbl:<26} {rlbl:<18} {len(g):>5}  "
                  f"{g['mfe30'].mean():>6.3f}%  "
                  f"{g[f'hit_{T_LABELS[0]}'].mean()*100:>7.1f}% "
                  f"{g[f'hit_{T_LABELS[1]}'].mean()*100:>7.1f}%")

    # Time of day breakdown
    print(f"\n  BY TIME WINDOW")
    print(f"  {'Event':<26} {'Window':<12} {'N':>5}  {'MFE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
    print(f"  {'-'*68}")
    windows = [("09:00-09:30","09:00","09:30"),("09:30-10:00","09:30","10:00"),
               ("10:00-11:00","10:00","11:00"),("11:00-12:00","11:00","12:00")]
    for level, event, side in order:
        s = df[(df["level"]==level) & (df["event"]==event)].copy()
        lbl = f"{level} {event}"
        for wlbl, wstart, wend in windows:
            g = s[(s["time"]>=wstart) & (s["time"]<wend)] if "time" in s.columns else s
            # time column not saved — use date proxy; skip time breakdown if unavailable
            break
        # Just show combined for now — time col not in records
        print(f"  (add time col to records for time-of-day breakdown)")
        break

    print(f"\n  {'='*68}")
    print(f"  SUMMARY: best signal = ", end="")
    best = None; best_h50 = 0
    for level, event, side in order:
        s = df[(df["level"]==level) & (df["event"]==event)]
        if s.empty: continue
        h50 = s[f"hit_{T_LABELS[0]}"].mean()*100
        if h50 > best_h50: best_h50=h50; best=f"{level} {event} ({side}) — {h50:.1f}% reach +0.50%, N={len(s)}"
    print(best)


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt()
    pm_stats = build_pm_stats(pm_df, rt_df)
    print(f"  {len(pm_stats)} days", flush=True)

    df = scan(rt_df, pm_stats)
    # Save time into records for later use
    print(f"  {len(df)} events classified", flush=True)

    report(df, pm_stats)

    df.to_csv(f"boof53_1_{SYM}.csv", index=False)
    print(f"\n  Saved boof53_1_{SYM}.csv")
