"""
For every short trade: did +0.50% TP hit before -0.25% SL?
Uses conservative same-bar rule: SL checked before TP on same bar.
"""
import pandas as pd
import numpy as np
import pytz, os

SYMS     = ["SMCI","HIMS","ARM","MU","APP"]
WEEKS    = 19.2
ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
TP_PCT   = 0.0050   # +0.50%
SL_PCT   = 0.0025   # -0.25%
MAX_BARS = 60


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

def build_pdhl(rth_df):
    rth_df = rth_df.copy(); rth_df["date"] = pd.to_datetime(rth_df["date"])
    dates = sorted(rth_df["date"].unique()); prev = {}
    for i in range(1, len(dates)):
        d=dates[i]; p=dates[i-1]; g=rth_df[rth_df["date"]==p]
        if not g.empty: prev[d]={"pdh":g["high"].max(),"pdl":g["low"].min()}
    return prev

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


def race(ddf, ei, ep):
    """Bar-by-bar: SL checked first (conservative), then TP."""
    n = len(ddf)
    tp_price = ep * (1 - TP_PCT)
    sl_price = ep * (1 + SL_PCT)
    max_bar  = min(ei + MAX_BARS, n - 1)
    for i in range(ei, max_bar + 1):
        hi = ddf.iloc[i]["high"]
        lo = ddf.iloc[i]["low"]
        if hi >= sl_price: return "SL First"
        if lo <= tp_price: return "TP First"
    return "Neither"


def scan_sym(sym):
    rth_df, pm_df = load_sym(sym)
    pm_stats = build_pm_levels(pm_df if not pm_df.empty else rth_df, rth_df)
    if pm_stats.empty: return pd.DataFrame()
    pdhl  = build_pdhl(rth_df)
    sr_1h = build_pivots_clean(rth_df, lookback=60,  wing=3)
    sr_4h = build_pivots_clean(rth_df, lookback=240, wing=5)
    rth_df = rth_df.copy(); rth_df["date"] = pd.to_datetime(rth_df["date"])
    records = []

    for date, ddf in rth_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm_stats.index: continue
        day = pm_stats.loc[date_ts]; gap = day["gap_pct"]
        if abs(gap) <= 0.5: continue
        regime = "Gap Down" if gap < -0.5 else "Gap Up"
        ddf = ddf.reset_index(drop=True)
        pmh = day["pm_high"]
        pd_info = pdhl.get(date_ts, {}); pdh = pd_info.get("pdh", np.nan)
        dk = date_ts.date()
        lv1h = sr_1h.get(date_ts, sr_1h.get(dk, []))
        lv4h = sr_4h.get(date_ts, sr_4h.get(dk, []))
        res_levels = [(pmh, "PMH")]
        if not pd.isna(pdh): res_levels.append((pdh, "PDH"))
        for lv, lt in lv1h:
            if lt == "res": res_levels.append((lv, "1H_Res"))
        for lv, lt in lv4h:
            if lt == "res": res_levels.append((lv, "4H_Res"))

        H = ddf["high"].values; C = ddf["close"].values
        n = len(ddf)

        for level, lname in res_levels:
            if pd.isna(level): continue
            state = "IDLE"; ext = None; touch_num = 0; i = 0
            while i < n - 3:
                touching = H[i] >= level * (1 - NEAR_PCT)
                if state == "IDLE":
                    if touching: state = "IN"; ext = C[i]; touch_num += 1
                elif state == "IN":
                    if touching: ext = min(ext, C[i])
                    else:
                        bounced = ext is not None and (level - ext) / level >= BOUNCE
                        if bounced and touch_num == 1:
                            ei  = i + 1
                            ep  = ddf.iloc[ei]["open"]
                            out = race(ddf, ei, ep)
                            records.append({"sym": sym, "level": lname,
                                            "gap_regime": regime, "date": str(dk),
                                            "outcome": out, "ep": ep})
                        state = "IDLE"; ext = None
                i += 1
    return pd.DataFrame(records)


if __name__ == "__main__":
    print("Scanning...", flush=True)
    frames = []
    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        df = scan_sym(sym)
        if not df.empty: frames.append(df)
    print()

    all_df = pd.concat(frames, ignore_index=True)
    N = len(all_df)
    W = 72

    def print_breakdown(label, s):
        if len(s) < 3: return
        counts = s["outcome"].value_counts()
        tp = counts.get("TP First", 0)
        sl = counts.get("SL First", 0)
        ne = counts.get("Neither",  0)
        n  = len(s)
        print(f"\n  {label}  (N={n}, ~{n/WEEKS:.1f}/wk)")
        print(f"  {'Outcome':<12} {'Count':>6}  {'%':>6}")
        print(f"  {'-'*28}")
        print(f"  {'TP First':<12} {tp:>6}  {tp/n*100:>5.1f}%")
        print(f"  {'SL First':<12} {sl:>6}  {sl/n*100:>5.1f}%")
        print(f"  {'Neither':<12} {ne:>6}  {ne/n*100:>5.1f}%")
        wins = tp; losses = sl
        if losses > 0:
            pf = (tp * TP_PCT*100) / (sl * SL_PCT*100)
            ev = (tp/n * TP_PCT - sl/n * SL_PCT) * 100
            print(f"  {'---'}")
            print(f"  PF={pf:.3f}   EV/trade={ev:+.4f}%")

    print(f"\n{'='*W}")
    print(f"  TP+0.50% vs SL-0.25% RACE  |  SHORT  |  Gap Up+Down  |  5 symbols")
    print(f"  SL checked before TP on same bar (conservative)")
    print(f"{'='*W}")

    # Overall
    print_breakdown("ALL", all_df)

    # By symbol
    print(f"\n  {'='*W}")
    print(f"  BY SYMBOL")
    for sym in SYMS:
        print_breakdown(sym, all_df[all_df["sym"]==sym])

    # By gap regime
    print(f"\n  {'='*W}")
    print(f"  BY GAP REGIME")
    for regime in ["Gap Down", "Gap Up"]:
        print_breakdown(regime, all_df[all_df["gap_regime"]==regime])

    # By level
    print(f"\n  {'='*W}")
    print(f"  BY LEVEL")
    for lv in ["PMH", "PDH", "1H_Res", "4H_Res"]:
        print_breakdown(lv, all_df[all_df["level"]==lv])
