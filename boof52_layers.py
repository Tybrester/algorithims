"""
BOOF52 Layered Filter Study — QQQ
Base: loose impulse (vol>1.5x, body>0.10%, close near high/low, 9:00-12:00 ET)
Layer 1: impulse only
Layer 2: impulse + PM energy (range>=0.50% OR gap>=0.50% OR vol_ratio>=1.5)
Layer 3: impulse + PM proximity (within 0.30% of PM high/low at entry)
Layer 4: impulse + PM energy + PM proximity
Measure: MFE30, MAE30, >=0.50%, >=0.75% within 30 bars
"""
import pandas as pd
import numpy as np
import pytz

ET  = pytz.timezone("America/New_York")
SYM = "QQQ"

TARGETS  = [0.0050, 0.0075]
T_LABELS = ["+0.50%", "+0.75%"]
PROXIMITY = 0.0030   # within 0.30% of PM high/low


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
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),
                "pm_low":g["low"].min(),"pm_range_pct":(g["high"].max()-g["low"].min())/g["low"].min()*100,
                "pm_vol":g["volume"].sum()} for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]      = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["pm_vol_ma20"]  = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"] = stats["pm_vol"]/stats["pm_vol_ma20"]
    stats["has_energy"]   = ((stats["pm_range_pct"]>=0.50)|(stats["gap_pct"].abs()>=0.50)|(stats["pm_vol_ratio"]>=1.50))
    return stats.dropna(subset=["gap_pct"])

def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]=(df["high"]+df["low"]+df["close"])/3; df["pv"]=df["typ"]*df["volume"]
    df["cpv"]=df.groupby("date")["pv"].cumsum(); df["cvol"]=df.groupby("date")["volume"].cumsum()
    df["vwap"]=df["cpv"]/df["cvol"]
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["body_pct"] = (df["close"]-df["open"]).abs()/df["open"]*100
    df["near_high"]= (df["close"]-df["low"])/(df["high"]-df["low"]+1e-9)
    df["near_low"] = (df["high"]-df["close"])/(df["high"]-df["low"]+1e-9)
    return df

def excursion(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    end=min(ei+30,n-1); sl=slice(ei,end+1)
    mfe=float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
    mae=float(max((ep-L[sl])/ep*100)) if side=="long" else float(max((H[sl]-ep)/ep*100))
    res={"mfe_30m":mfe,"mae_30m":mae}
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end+1]<=ep*(1-tgt)))
    return res

def impulse_ok(row, side, vol_ma):
    if vol_ma<=0 or pd.isna(vol_ma): return False
    vol_ok  = row["volume"] > 1.5*vol_ma
    body_ok = row["body_pct"] > 0.10
    if side=="long":
        return vol_ok and body_ok and row["close"]>row["open"] and row["near_high"]>0.50
    else:
        return vol_ok and body_ok and row["close"]<row["open"] and row["near_low"]>0.50

def proximity_ok(price, pm_high, pm_low, side):
    """Price is within PROXIMITY % of the relevant PM level."""
    if side=="long":
        return abs(price - pm_high) / pm_high <= PROXIMITY
    else:
        return abs(price - pm_low) / pm_low <= PROXIMITY


def collect(rt_df, pm_stats):
    """Collect all impulse signals with day metadata — filter in report."""
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm = pm_stats.set_index("date")
    raw = []

    for date, ddf in rt_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day["pm_high"]): continue

        pm_high = day["pm_high"]; pm_low = day["pm_low"]
        energy  = bool(day["has_energy"])

        ddf = ddf.reset_index(drop=True)
        long_fired = short_fired = False

        for i in range(20, len(ddf)-31):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            vol_ma = row["vol_ma20"]

            for side, fired in [("long", long_fired), ("short", short_fired)]:
                if fired: continue
                if not impulse_ok(row, side, vol_ma): continue

                ei = i+1
                if ei >= len(ddf): continue
                ep = ddf.iloc[ei]["open"]

                prox = proximity_ok(row["close"], pm_high, pm_low, side)

                exc = excursion(ddf, ei, ep, side)
                raw.append({
                    "date":    str(date.date()),
                    "side":    side,
                    "time":    t,
                    "energy":  energy,
                    "prox":    prox,
                    "gap_pct": round(day["gap_pct"],3),
                    "pm_range":round(day["pm_range_pct"],3),
                    "vol_ratio":round(float(day["pm_vol_ratio"]),2),
                    "ep":      ep,
                    **exc
                })
                if side=="long":  long_fired  = True
                else:             short_fired = True

    return pd.DataFrame(raw) if raw else pd.DataFrame()


def stats_row(s, label, side_lbl):
    if s.empty: return None
    nd   = s["date"].nunique(); tpd = len(s)/nd
    m30  = s["mfe_30m"].mean(); ma30 = s["mae_30m"].mean()
    h50  = s[f"hit_{T_LABELS[0]}"].mean()*100
    h75  = s[f"hit_{T_LABELS[1]}"].mean()*100
    return (label, side_lbl, len(s), nd, tpd, m30, ma30, h50, h75)


def report(df):
    W = 96
    print(f"\n{'='*W}")
    print(f"  BOOF52 Layered Filters | {SYM} | Loose Impulse Base")
    print(f"  Filters: Energy=(pm_range>=0.5% OR gap>=0.5% OR vol_ratio>=1.5)")
    print(f"           Proximity=within {PROXIMITY*100:.1f}% of PM high/low at entry")
    print(f"{'='*W}")
    print(f"  {'Layer':<36} {'Side':<7} {'N':>5} {'Days':>5} {'TPD':>5}  "
          f"{'MFE30':>7} {'MAE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
    print(f"  {'-'*90}")

    LAYERS = [
        ("L1 Impulse only",               df),
        ("L2 + PM Energy",                df[df["energy"]==True]),
        ("L3 + PM Proximity",             df[df["prox"]==True]),
        ("L4 + Energy + Proximity",       df[(df["energy"]==True) & (df["prox"]==True)]),
    ]

    for lbl, subset in LAYERS:
        if subset.empty:
            print(f"  {lbl:<36} -- no trades"); continue
        for side in ["long","short","all"]:
            s = subset if side=="all" else subset[subset["side"]==side]
            if s.empty: continue
            r = stats_row(s, lbl, side.upper() if side!="all" else "BOTH")
            if r is None: continue
            label,slbl,n,nd,tpd,m30,ma30,h50,h75 = r
            name = label if side=="long" else ""
            print(f"  {name:<36} {slbl:<7} {n:>5} {nd:>5} {tpd:>5.1f}  "
                  f"{m30:>6.3f}% {ma30:>6.3f}%  {h50:>7.1f}% {h75:>7.1f}%")
        print(f"  {'-'*90}")

    # Gap regime for best layer
    best = df[(df["energy"]==True) & (df["prox"]==True)]
    if not best.empty:
        print(f"\n  L4 BY GAP REGIME")
        print(f"  {'Regime':<22} {'N':>5}  {'MFE30':>7} {'MAE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
        print(f"  {'-'*65}")
        for lbl, mask in [("Gap Down <-0.5%", best["gap_pct"]<-0.5),
                           ("Flat",            (best["gap_pct"]>=-0.5)&(best["gap_pct"]<=0.5)),
                           ("Gap Up >+0.5%",   best["gap_pct"]>0.5)]:
            s = best[mask]
            if s.empty: continue
            print(f"  {lbl:<22} {len(s):>5}  {s['mfe_30m'].mean():>6.3f}% {s['mae_30m'].mean():>6.3f}%  "
                  f"{s[f'hit_{T_LABELS[0]}'].mean()*100:>7.1f}% {s[f'hit_{T_LABELS[1]}'].mean()*100:>7.1f}%")

        print(f"\n  L4 BY SIDE")
        print(f"  {'Side':<10} {'N':>5}  {'MFE30':>7} {'MAE30':>7}  {'>=0.50%':>8} {'>=0.75%':>8}")
        print(f"  {'-'*55}")
        for side in ["long","short"]:
            s = best[best["side"]==side]
            if s.empty: continue
            print(f"  {side.upper():<10} {len(s):>5}  {s['mfe_30m'].mean():>6.3f}% {s['mae_30m'].mean():>6.3f}%  "
                  f"{s[f'hit_{T_LABELS[0]}'].mean()*100:>7.1f}% {s[f'hit_{T_LABELS[1]}'].mean()*100:>7.1f}%")


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt(); rt_df = add_indicators(rt_df)
    pm_stats = build_pm_stats(pm_df, rt_df)
    print(f"  {len(pm_stats)} days, {pm_stats['has_energy'].sum()} energy days", flush=True)

    print("Collecting signals...", flush=True)
    df = collect(rt_df, pm_stats)
    print(f"  Raw impulse signals: {len(df)}", flush=True)
    if not df.empty:
        print(f"  Energy days hits:    {df['energy'].sum()}", flush=True)
        print(f"  Proximity hits:      {df['prox'].sum()}", flush=True)
        print(f"  Both:                {(df['energy']&df['prox']).sum()}", flush=True)

    report(df)
