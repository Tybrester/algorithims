"""
BOOF51 Combo Event Study
Combo A: Gap-down day + VWAP reclaim + prev-day low reclaim (long)
         Gap-down day + VWAP rejection + prev-day high rejection (short)
Combo B: Prev-day H/L break + premarket energy
Pure excursion only — N, MFE15, MFE30, MFE60, >=0.50%, >=0.75% in 30m
"""
import pandas as pd
import numpy as np
import pytz

ET  = pytz.timezone("America/New_York")
SYM = "QQQ"

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
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min(),
                "pm_range_pct":(g["high"].max()-g["low"].min())/g["low"].min()*100,
                "pm_vol":g["volume"].sum()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]      = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["pm_vol_ma20"]  = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"] = stats["pm_vol"]/stats["pm_vol_ma20"]
    stats["has_energy"]   = (
        (stats["pm_range_pct"] >= 0.50) |
        (stats["gap_pct"].abs() >= 0.50) |
        (stats["pm_vol_ratio"] >= 1.50)
    )
    return stats.dropna(subset=["gap_pct"])

def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]=(df["high"]+df["low"]+df["close"])/3
    df["pv"]=df["typ"]*df["volume"]
    df["cpv"]=df.groupby("date")["pv"].cumsum()
    df["cvol"]=df.groupby("date")["volume"].cumsum()
    df["vwap"]=df["cpv"]/df["cvol"]
    return df

def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key]=float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
    end30=min(ei+30,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end30+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end30+1]<=ep*(1-tgt)))
    return res


# ══════════════════════════════════════════════════════════════════════════════
# COMBO A
# Long:  gap-down day + VWAP reclaim + prev-day low reclaim (all 3 at once)
# Short: gap-down day + VWAP rejection + prev-day high rejection
# ══════════════════════════════════════════════════════════════════════════════

def combo_A(rt_df, pm_stats):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm = pm_stats.set_index("date")
    dates = sorted(rt_df["date"].unique())
    trades = []

    for idx in range(1, len(dates)):
        curr_d = dates[idx]; prev_d = dates[idx-1]
        date_ts = pd.Timestamp(curr_d)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if day["gap_pct"] >= -0.5: continue      # gap-down only

        prev_df = rt_df[rt_df["date"] == prev_d]
        if prev_df.empty: continue
        pdh = prev_df["high"].max()               # prev-day high
        pdl = prev_df["low"].min()                # prev-day low

        ddf = rt_df[rt_df["date"] == curr_d].reset_index(drop=True)
        lf = sf = False

        for j in range(1, len(ddf) - 61):
            row = ddf.iloc[j]; prev = ddf.iloc[j-1]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            if pd.isna(row.get("vwap")): continue

            # LONG: VWAP reclaim AND prev-day low reclaim simultaneously
            if not lf:
                vwap_reclaim = prev["close"] < prev["vwap"] and row["close"] > row["vwap"]
                pdl_reclaim  = prev["close"] < pdl and row["close"] > pdl
                if vwap_reclaim and pdl_reclaim:
                    lf = True; ei = j+1; ep = ddf.iloc[ei]["open"]
                    trades.append({"date":str(curr_d.date()),"combo":"A","side":"long",
                                   "gap_pct":round(day["gap_pct"],3),"ep":ep,
                                   "trigger":"VWAP+PDL reclaim",**exc(ddf,ei,ep,"long")})

            # LONG: VWAP reclaim alone (no PDL requirement — for comparison)
            # tracked separately as A_vwap_only
            # SHORT: VWAP rejection AND prev-day high rejection simultaneously
            if not sf:
                vwap_reject = prev["close"] > prev["vwap"] and row["close"] < row["vwap"]
                pdh_reject  = prev["close"] > pdh and row["close"] < pdh
                if vwap_reject and pdh_reject:
                    sf = True; ei = j+1; ep = ddf.iloc[ei]["open"]
                    trades.append({"date":str(curr_d.date()),"combo":"A","side":"short",
                                   "gap_pct":round(day["gap_pct"],3),"ep":ep,
                                   "trigger":"VWAP+PDH reject",**exc(ddf,ei,ep,"short")})

            if lf and sf: break

    # Also collect looser versions for comparison
    trades_vwap_only = []
    for idx in range(1, len(dates)):
        curr_d = dates[idx]; date_ts = pd.Timestamp(curr_d)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if day["gap_pct"] >= -0.5: continue
        ddf = rt_df[rt_df["date"] == curr_d].reset_index(drop=True)
        lf = sf = False
        for j in range(1, len(ddf) - 61):
            row = ddf.iloc[j]; prev = ddf.iloc[j-1]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            if pd.isna(row.get("vwap")): continue
            if not lf and prev["close"] < prev["vwap"] and row["close"] > row["vwap"]:
                lf = True; ei = j+1; ep = ddf.iloc[ei]["open"]
                trades_vwap_only.append({"date":str(curr_d.date()),"combo":"A_vwap","side":"long",
                                         "gap_pct":round(day["gap_pct"],3),"ep":ep,
                                         "trigger":"VWAP reclaim only",**exc(ddf,ei,ep,"long")})
            if not sf and prev["close"] > prev["vwap"] and row["close"] < row["vwap"]:
                sf = True; ei = j+1; ep = ddf.iloc[ei]["open"]
                trades_vwap_only.append({"date":str(curr_d.date()),"combo":"A_vwap","side":"short",
                                         "gap_pct":round(day["gap_pct"],3),"ep":ep,
                                         "trigger":"VWAP reject only",**exc(ddf,ei,ep,"short")})
            if lf and sf: break

    return trades, trades_vwap_only


# ══════════════════════════════════════════════════════════════════════════════
# COMBO B
# Prev-day H/L break + premarket energy filter
# ══════════════════════════════════════════════════════════════════════════════

def combo_B(rt_df, pm_stats):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    pm = pm_stats.set_index("date")
    dates = sorted(rt_df["date"].unique())
    trades_all = []   # no energy filter
    trades_nrg = []   # energy filter

    for idx in range(1, len(dates)):
        curr_d = dates[idx]; prev_d = dates[idx-1]
        date_ts = pd.Timestamp(curr_d)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        energy = bool(day["has_energy"])

        prev_df = rt_df[rt_df["date"] == prev_d]
        if prev_df.empty: continue
        pdh = prev_df["high"].max()
        pdl = prev_df["low"].min()

        ddf = rt_df[rt_df["date"] == curr_d].reset_index(drop=True)
        lf = sf = False

        for j in range(len(ddf) - 61):
            row = ddf.iloc[j]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue

            if not lf and row["close"] > pdh:
                lf = True; ei = j+1; ep = ddf.iloc[ei]["open"]
                rec = {"date":str(curr_d.date()),"combo":"B","side":"long",
                       "gap_pct":round(day["gap_pct"],3),"energy":energy,
                       "ep":ep,"trigger":"PDH break",**exc(ddf,ei,ep,"long")}
                trades_all.append(rec)
                if energy: trades_nrg.append(rec)

            if not sf and row["close"] < pdl:
                sf = True; ei = j+1; ep = ddf.iloc[ei]["open"]
                rec = {"date":str(curr_d.date()),"combo":"B","side":"short",
                       "gap_pct":round(day["gap_pct"],3),"energy":energy,
                       "ep":ep,"trigger":"PDL break",**exc(ddf,ei,ep,"short")}
                trades_all.append(rec)
                if energy: trades_nrg.append(rec)

            if lf and sf: break

    return trades_all, trades_nrg


# ── Report ────────────────────────────────────────────────────────────────────

def print_block(trades, label):
    if not trades:
        print(f"  {label:<42} -- no trades"); return
    df = pd.DataFrame(trades)
    for side in ["long","short","all"]:
        s = df if side=="all" else df[df["side"]==side]
        if s.empty: continue
        n=len(s); nd=s["date"].nunique()
        m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
        h50=s[f"hit_{T_LABELS[0]}"].mean()*100
        h75=s[f"hit_{T_LABELS[1]}"].mean()*100
        slbl=side.upper() if side!="all" else "BOTH"
        name=label if side=="long" else ""
        print(f"  {name:<42} {slbl:<7} {n:>4} {nd:>4}d  "
              f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%")


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt(); rt_df = add_indicators(rt_df)
    pm_stats = build_pm_stats(pm_df, rt_df)

    gap_days = (pm_stats["gap_pct"] <= -0.5).sum()
    nrg_days = pm_stats["has_energy"].sum()
    print(f"  {len(pm_stats)} total days | {gap_days} gap-down days | {nrg_days} energy days", flush=True)

    A_combo, A_vwap = combo_A(rt_df, pm_stats)
    B_all,   B_nrg  = combo_B(rt_df, pm_stats)

    W = 100
    print(f"\n{'='*W}")
    print(f"  BOOF51 Combo Events | {SYM} | 9:00-12:00 ET | Pure Excursion")
    print(f"{'='*W}")
    print(f"  {'Label':<42} {'Side':<7} {'N':>4} {'Days':>5}  "
          f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    print(f"  {'-'*94}")

    print(f"\n  ── COMBO A: Gap-Down Days ──────────────────────────────────────────────")
    print_block(A_vwap,  "  A1  VWAP reclaim/reject only")
    print(f"  {'-'*94}")
    print_block(A_combo, "  A2  VWAP + Prev-Day L/H reclaim/reject")
    print(f"  {'-'*94}")

    print(f"\n  ── COMBO B: Prev-Day H/L Break ─────────────────────────────────────────")
    print_block(B_all,  "  B1  PDH/L break (all days)")
    print(f"  {'-'*94}")
    print_block(B_nrg,  "  B2  PDH/L break + PM energy")
    print(f"  {'-'*94}")

    # Gap regime breakdown for best combos
    for label, trades in [("A2 Combo", A_combo), ("B2 Energy", B_nrg)]:
        if not trades: continue
        df = pd.DataFrame(trades)
        print(f"\n  {label} — BY GAP REGIME")
        print(f"  {'Regime':<22} {'Side':<7} {'N':>4}  {'MFE30':>7}  {'>=0.50%':>7}  {'>=0.75%':>7}")
        print(f"  {'-'*60}")
        for rlbl, mask in [("Gap Down <-0.5%", df["gap_pct"]<-0.5),
                            ("Flat",            (df["gap_pct"]>=-0.5)&(df["gap_pct"]<=0.5)),
                            ("Gap Up >+0.5%",   df["gap_pct"]>0.5)]:
            for side in ["long","short"]:
                s = df[mask & (df["side"]==side)]
                if s.empty: continue
                print(f"  {rlbl:<22} {side.upper():<7} {len(s):>4}  "
                      f"{s['mfe30'].mean():>6.3f}%  "
                      f"{s[f'hit_{T_LABELS[0]}'].mean()*100:>6.1f}%  "
                      f"{s[f'hit_{T_LABELS[1]}'].mean()*100:>6.1f}%")
