"""
BOOF53 Symbol Leaderboard
All levels: PML, PDL, PMH, PDH, 1H, 4H
All 1st touches, bounce >= 0.15%
Clean RTH-only pivots, left-edge confirmation
Reports per symbol: N, T/Week, MFE30, >=0.50%, >=0.75%
Then separate leaderboards for Long / Short / 1H+4H only
"""
import pandas as pd
import numpy as np
import pytz
import os

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
TARGETS  = [0.0050, 0.0075]
T_LABELS = [">=0.50%",">=0.75%"]

SYMBOLS = [
    "NVDA","TSLA","AMD","META","AAPL","MSFT","AMZN","PLTR","IWM",
    "AVGO","NFLX","CRM","MU","ARM","COIN","SMCI","GOOGL",
    "ORCL","ADBE","APP","HIMS","RKLB","HOOD","TEM","JPM",
    "COST","WMT","LLY","UNH",
]


def load_sym(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm >= "09:30") & (hm <= "16:00")].copy()
    pm  = df[(hm >= "04:00") & (hm <  "09:30")].copy()
    rth["date"] = rth["time"].dt.date
    pm["date"]  = pm["time"].dt.date
    return rth, pm

def build_pdhl(rth_df):
    rth_df = rth_df.copy(); rth_df["date"] = pd.to_datetime(rth_df["date"])
    dates = sorted(rth_df["date"].unique()); prev = {}
    for i in range(1, len(dates)):
        d = dates[i]; p = dates[i-1]; g = rth_df[rth_df["date"]==p]
        if not g.empty:
            prev[d] = {"pdh": g["high"].max(), "pdl": g["low"].min()}
    return prev

def build_pm_levels(pm_df, rth_df):
    pm_df  = pm_df.copy();  pm_df["date"]  = pd.to_datetime(pm_df["date"])
    rth_df = rth_df.copy(); rth_df["date"] = pd.to_datetime(rth_df["date"])
    pm_agg = pm_df.groupby("date").agg(pm_high=("high","max"), pm_low=("low","min")).reset_index()
    prev_close = rth_df.groupby("date")["close"].last().reset_index()
    prev_close.columns = ["date","prev_close"]
    prev_close["next_date"] = prev_close["date"] + pd.Timedelta(days=1)
    rth_open = rth_df.groupby("date")["open"].first().reset_index()
    rth_open.columns = ["date","rth_open"]
    stats = pm_agg.merge(
        prev_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    ).merge(rth_open, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["gap_pct","pm_high"]).set_index("date")

def build_pivots_clean(rth_df, lookback, wing):
    rth_df = rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"] = pd.to_datetime(rth_df["date"])
    sr = {}
    for d in sorted(rth_df["date"].unique()):
        hist = rth_df[rth_df["date"] < d].tail(lookback)
        if len(hist) < max(wing+1, lookback//4): continue
        H = hist["high"].values; L = hist["low"].values; levels = []
        for i in range(wing, len(hist)):
            if H[i] == H[i-wing:i+1].max(): levels.append((H[i],"res"))
            if L[i] == L[i-wing:i+1].min(): levels.append((L[i],"sup"))
        if not levels: continue
        levels = sorted(levels, key=lambda x: x[0])
        cl = [list(levels[0])]
        for lv, lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0] < OVERLAP: cl[-1][0] = (cl[-1][0]+lv)/2
            else: cl.append([lv, lt])
        sr[d] = [(c[0],c[1]) for c in cl]
    return sr

def exc(ddf, ei, ep, side):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values; res = {}
    for bars, key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end = min(ei+bars, n-1); sl = slice(ei, end+1)
        res[key] = float(max((H[sl]-ep)/ep*100)) if side=="long" \
              else float(max((ep-L[sl])/ep*100))
    end60 = min(ei+60, n-1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end60+1] >= ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end60+1] <= ep*(1-tgt)))
    return res

def scan_level(ddf, level, direction):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    results = []; state = "IDLE"; ext = None; touch_num = 0; i = 0
    while i < n-3:
        cl = C[i]; hi = H[i]; lo = L[i]
        if direction == "sup":
            touching = lo <= level*(1+NEAR_PCT)
            if state == "IDLE":
                if touching: state = "IN"; ext = cl; touch_num += 1
            elif state == "IN":
                if touching: ext = max(ext, cl)
                else:
                    bounced = ext is not None and (ext-level)/level >= BOUNCE
                    ei = i + 1
                    ep = ddf.iloc[ei]["open"]
                    results.append({"touch_num":min(touch_num,3),"bounced":bounced,
                                    "ep":ep, **exc(ddf,ei,ep,"long")})
                    state = "IDLE"; ext = None
        else:
            touching = hi >= level*(1-NEAR_PCT)
            if state == "IDLE":
                if touching: state = "IN"; ext = cl; touch_num += 1
            elif state == "IN":
                if touching: ext = min(ext, cl)
                else:
                    bounced = ext is not None and (level-ext)/level >= BOUNCE
                    ei = i + 1
                    ep = ddf.iloc[ei]["open"]
                    results.append({"touch_num":min(touch_num,3),"bounced":bounced,
                                    "ep":ep, **exc(ddf,ei,ep,"short")})
                    state = "IDLE"; ext = None
        i += 1
    return results

def run_symbol(sym):
    if not os.path.exists(f"boof51_{sym}_1m.csv"): return pd.DataFrame()
    rth_df, pm_df = load_sym(sym)
    if pm_df.empty:
        pm_stats = build_pm_levels(rth_df, rth_df)
    else:
        pm_stats = build_pm_levels(pm_df, rth_df)
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
        gap_regime = "Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")
        ddf = ddf.reset_index(drop=True)
        pmh = day["pm_high"]; pml = day["pm_low"]
        pd_info = pdhl.get(date_ts, {})
        pdh = pd_info.get("pdh", np.nan); pdl = pd_info.get("pdl", np.nan)
        dk = date_ts.date()
        lv1h = sr_1h.get(date_ts, sr_1h.get(dk, []))
        lv4h = sr_4h.get(date_ts, sr_4h.get(dk, []))
        long_levels  = [(pml,"PML")]
        short_levels = [(pmh,"PMH")]
        if not pd.isna(pdl): long_levels.append((pdl,"PDL"))
        if not pd.isna(pdh): short_levels.append((pdh,"PDH"))
        for lv,lt in lv1h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv,"1H_Sup" if lt=="sup" else "1H_Res"))
        for lv,lt in lv4h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv,"4H_Sup" if lt=="sup" else "4H_Res"))
        for level,lname in long_levels:
            if pd.isna(level): continue
            for e in scan_level(ddf, level, "sup"):
                tl = "1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({"sym":sym,"side":"long","level":lname,
                                "gap_regime":gap_regime,"touch_lbl":tl,"bounced":e["bounced"],
                                "date":str(dk), **{k:v for k,v in e.items()
                                if k not in ("touch_num","bounced","ep")}})
        for level,lname in short_levels:
            if pd.isna(level): continue
            for e in scan_level(ddf, level, "res"):
                tl = "1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({"sym":sym,"side":"short","level":lname,
                                "gap_regime":gap_regime,"touch_lbl":tl,"bounced":e["bounced"],
                                "date":str(dk), **{k:v for k,v in e.items()
                                if k not in ("touch_num","bounced","ep")}})
    return pd.DataFrame(records)


def leaderboard(all_df, title, filt, sort_col="mfe30", min_n=20):
    W = 80
    df = all_df[filt & (all_df["bounced"]==True) & (all_df["touch_lbl"]=="1st")]
    DAYS  = all_df["date"].nunique()
    WEEKS = DAYS / 5
    rows = []
    for sym in sorted(df["sym"].unique()):
        s = df[df["sym"]==sym]
        if len(s) < min_n: continue
        rows.append({
            "sym":   sym,
            "n":     len(s),
            "days":  s["date"].nunique(),
            "t_wk":  len(s) / WEEKS,
            "mfe15": s["mfe15"].mean(),
            "mfe30": s["mfe30"].mean(),
            "mfe60": s["mfe60"].mean(),
            "h50":   s["hit_>=0.50%"].mean()*100,
            "h75":   s["hit_>=0.75%"].mean()*100,
        })
    rows = sorted(rows, key=lambda x: -x[sort_col.replace("%","").replace(">=0.","h")])
    print(f"\n{'='*W}")
    print(f"  {title}  |  1st touch  bounce>={BOUNCE*100:.2f}%  |  ranked by {sort_col}")
    print(f"  {DAYS} trading days  (~{WEEKS:.1f} weeks)")
    print(f"{'='*W}")
    print(f"  {'Rank':<5} {'Sym':<6} {'N':>5}  {'T/Wk':>6}  "
          f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*76}")
    for rank, r in enumerate(rows, 1):
        mark = " <<<" if r["h50"]>=55 else ("  <<" if r["h50"]>=40 else "")
        print(f"  {rank:<5} {r['sym']:<6} {r['n']:>5}  {r['t_wk']:>6.2f}  "
              f"{r['mfe15']:>6.3f}%  {r['mfe30']:>6.3f}%  {r['mfe60']:>6.3f}%   "
              f"{r['h50']:>7.1f}%  {r['h75']:>7.1f}%{mark}")
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(f"Running {len(SYMBOLS)} symbols...", flush=True)
    frames = []
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        df = run_symbol(sym)
        print(f"{len(df)}", flush=True)
        frames.append(df)

    all_df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    DAYS  = all_df["date"].nunique()
    WEEKS = DAYS / 5
    print(f"\n  Total: {len(all_df):,} touches across {len(SYMBOLS)} symbols  "
          f"({DAYS}d / {WEEKS:.1f}wk)", flush=True)

    # Overall leaderboard — all levels combined, 1st touch
    lb_all   = leaderboard(all_df, "ALL LEVELS — Long + Short combined",
                           all_df["sym"].isin(SYMBOLS), sort_col="mfe30")

    lb_long  = leaderboard(all_df, "LONG — All support levels",
                           all_df["side"]=="long", sort_col="mfe30")

    lb_short = leaderboard(all_df, "SHORT — All resistance levels",
                           all_df["side"]=="short", sort_col="mfe30")

    lb_1h4h  = leaderboard(all_df, "HIGH-VALUE — 1H+4H levels only (long+short)",
                           all_df["level"].isin(["1H_Res","4H_Res","1H_Sup","4H_Sup"]),
                           sort_col="h50", min_n=5)

    lb_pml   = leaderboard(all_df, "PML 1st touch",
                           all_df["level"]=="PML", sort_col="mfe30", min_n=5)

    lb_pmh   = leaderboard(all_df, "PMH 1st touch",
                           all_df["level"]=="PMH", sort_col="mfe30", min_n=5)

    all_df.to_csv("boof53_leaderboard_all.csv", index=False)
    print(f"\n  Saved boof53_leaderboard_all.csv")
