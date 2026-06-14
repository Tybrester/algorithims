"""
BOOF53 TP/SL Simulation — Locked Universe (18 symbols)
Uses saved boof53_leaderboard_all.csv touch events.
Entry: open[i+1] after zone exit (already stored as ep in CSV).
Exit: scan forward bar-by-bar from entry for TP or SL hit.
Reports: Win Rate, Profit Factor, EV, Max Drawdown, Trades/Week
per TP/SL config and per tier.
"""
import pandas as pd
import numpy as np
import pytz, os

# ── Config ──────────────────────────────────────────────────────────────────
S_TIER = ["RKLB","HIMS","MU","ARM","APP","SMCI"]
A_TIER = ["COIN","AMD","PLTR","HOOD","CRM","AVGO"]
B_TIER = ["TSLA","NVDA","META","AMZN","LLY","ADBE"]
UNIVERSE = S_TIER + A_TIER + B_TIER

CONFIGS = [
    (0.50, 0.25),
    (0.75, 0.40),
    (1.00, 0.50),
]

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015


# ── Data loaders (same as leaderboard) ──────────────────────────────────────
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
    pc = rth_df.groupby("date")["close"].last().reset_index()
    pc.columns = ["date","prev_close"]; pc["next_date"] = pc["date"] + pd.Timedelta(days=1)
    ro = rth_df.groupby("date")["open"].first().reset_index(); ro.columns = ["date","rth_open"]
    stats = pm_agg.merge(pc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
                         on="date", how="left").merge(ro, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    return stats.dropna(subset=["gap_pct","pm_high"]).set_index("date")

def build_pivots_clean(rth_df, lookback, wing):
    rth_df = rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"] = pd.to_datetime(rth_df["date"]); sr = {}
    for d in sorted(rth_df["date"].unique()):
        hist = rth_df[rth_df["date"] < d].tail(lookback)
        if len(hist) < max(wing+1, lookback//4): continue
        H = hist["high"].values; L = hist["low"].values; levels = []
        for i in range(wing, len(hist)):
            if H[i] == H[i-wing:i+1].max(): levels.append((H[i],"res"))
            if L[i] == L[i-wing:i+1].min(): levels.append((L[i],"sup"))
        if not levels: continue
        levels = sorted(levels, key=lambda x: x[0]); cl = [list(levels[0])]
        for lv,lt in levels[1:]:
            if abs(lv-cl[-1][0])/cl[-1][0] < OVERLAP: cl[-1][0]=(cl[-1][0]+lv)/2
            else: cl.append([lv,lt])
        sr[d] = [(c[0],c[1]) for c in cl]
    return sr


# ── TP/SL exit scanner ───────────────────────────────────────────────────────
def simulate_exit(ddf, ei, ep, side, tp_pct, sl_pct):
    """
    Scan bar-by-bar from ei forward.
    Long: TP = ep*(1+tp), SL = ep*(1-sl)
    Short: TP = ep*(1-tp), SL = ep*(1+sl)
    Returns: ('win'|'loss'|'timeout', bars_held, pnl_pct)
    Max hold = 60 bars (rest of session).
    Uses bar HIGH for long TP/SHORT SL, LOW for long SL/SHORT TP.
    Checks SL first on same bar to be conservative.
    """
    n = len(ddf)
    tp = tp_pct / 100; sl = sl_pct / 100
    tp_price = ep*(1+tp) if side=="long" else ep*(1-tp)
    sl_price = ep*(1-sl) if side=="long" else ep*(1+sl)
    max_bar  = min(ei+60, n-1)

    for i in range(ei, max_bar+1):
        hi = ddf.iloc[i]["high"]; lo = ddf.iloc[i]["low"]
        if side == "long":
            if lo <= sl_price: return ("loss", i-ei, -sl_pct)
            if hi >= tp_price: return ("win",  i-ei,  tp_pct)
        else:
            if hi >= sl_price: return ("loss", i-ei, -sl_pct)
            if lo <= tp_price: return ("win",  i-ei,  tp_pct)

    # timeout — use close of last bar
    last_close = ddf.iloc[max_bar]["close"]
    pnl = (last_close-ep)/ep*100 if side=="long" else (ep-last_close)/ep*100
    return ("timeout", max_bar-ei, pnl)


# ── Touch scanner with TP/SL ─────────────────────────────────────────────────
def scan_level_tpsl(ddf, level, direction, tp_pct, sl_pct):
    n = len(ddf)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    results = []; state = "IDLE"; ext = None; touch_num = 0; i = 0
    side = "long" if direction=="sup" else "short"

    while i < n-3:
        cl=C[i]; hi=H[i]; lo=L[i]
        if direction == "sup":
            touching = lo <= level*(1+NEAR_PCT)
            if state=="IDLE":
                if touching: state="IN"; ext=cl; touch_num+=1
            elif state=="IN":
                if touching: ext=max(ext,cl)
                else:
                    bounced = ext is not None and (ext-level)/level >= BOUNCE
                    if bounced and touch_num==1:  # 1st touch only
                        ei = i+1; ep = ddf.iloc[ei]["open"]
                        outcome, bars, pnl = simulate_exit(ddf, ei, ep, side, tp_pct, sl_pct)
                        results.append({"outcome":outcome,"bars":bars,"pnl":pnl,
                                        "ep":ep,"side":side,"touch_num":touch_num})
                    state="IDLE"; ext=None
        else:
            touching = hi >= level*(1-NEAR_PCT)
            if state=="IDLE":
                if touching: state="IN"; ext=cl; touch_num+=1
            elif state=="IN":
                if touching: ext=min(ext,cl)
                else:
                    bounced = ext is not None and (level-ext)/level >= BOUNCE
                    if bounced and touch_num==1:
                        ei = i+1; ep = ddf.iloc[ei]["open"]
                        outcome, bars, pnl = simulate_exit(ddf, ei, ep, side, tp_pct, sl_pct)
                        results.append({"outcome":outcome,"bars":bars,"pnl":pnl,
                                        "ep":ep,"side":side,"touch_num":touch_num})
                    state="IDLE"; ext=None
        i+=1
    return results


# ── Per-symbol runner ────────────────────────────────────────────────────────
def run_symbol(sym, tp_pct, sl_pct):
    if not os.path.exists(f"boof51_{sym}_1m.csv"): return pd.DataFrame()
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
        gap_regime = "Gap Down" if gap<-0.5 else ("Gap Up" if gap>0.5 else "Flat")
        ddf = ddf.reset_index(drop=True)
        pmh=day["pm_high"]; pml=day["pm_low"]
        pd_info=pdhl.get(date_ts,{})
        pdh=pd_info.get("pdh",np.nan); pdl=pd_info.get("pdl",np.nan)
        dk=date_ts.date()
        lv1h=sr_1h.get(date_ts, sr_1h.get(dk,[]))
        lv4h=sr_4h.get(date_ts, sr_4h.get(dk,[]))

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
            for e in scan_level_tpsl(ddf, level, "sup", tp_pct, sl_pct):
                records.append({"sym":sym,"level":lname,"date":str(dk),
                                "gap_regime":gap_regime, **e})
        for level,lname in short_levels:
            if pd.isna(level): continue
            for e in scan_level_tpsl(ddf, level, "res", tp_pct, sl_pct):
                records.append({"sym":sym,"level":lname,"date":str(dk),
                                "gap_regime":gap_regime, **e})

    return pd.DataFrame(records)


# ── Metrics ──────────────────────────────────────────────────────────────────
def metrics(df, weeks):
    if df.empty or len(df)<5: return None
    n      = len(df)
    wins   = df[df["outcome"]=="win"]
    losses = df[df["outcome"]=="loss"]
    wr     = len(wins)/n*100
    gross_w= wins["pnl"].sum()
    gross_l= abs(losses["pnl"].sum()) if len(losses) else 1e-9
    pf     = gross_w/gross_l if gross_l>0 else 999
    ev     = df["pnl"].mean()
    tpw    = n/weeks

    # Max drawdown on cumulative PnL curve
    cum   = df["pnl"].cumsum().values
    peak  = np.maximum.accumulate(cum)
    dd    = cum - peak
    maxdd = dd.min()

    return dict(n=n, wr=wr, pf=pf, ev=ev, tpw=tpw, maxdd=maxdd,
                avg_win=wins["pnl"].mean() if len(wins) else 0,
                avg_loss=losses["pnl"].mean() if len(losses) else 0)


def print_results(results, weeks):
    W = 90
    print(f"\n{'='*W}")
    print(f"  BOOF53 TP/SL SIMULATION — 18-symbol locked universe")
    print(f"  1st touch only  |  bounce>=0.15%  |  entry=open[i+1]  |  max hold=60 bars")
    print(f"{'='*W}")
    print(f"  {'Config':<14} {'Tier':<10} {'N':>5} {'T/Wk':>6}  "
          f"{'WR':>6}  {'PF':>6}  {'EV':>7}  {'AvgW':>7}  {'AvgL':>7}  {'MaxDD':>8}")
    print(f"  {'-'*86}")

    for (tp,sl), tier_data in results.items():
        cfg = f"TP{tp:.2f}/SL{sl:.2f}"
        first = True
        for tier_lbl, m in tier_data.items():
            if m is None: continue
            prefix = f"  {cfg:<14}" if first else f"  {'':14}"
            first = False
            mark = " <<<" if m["pf"]>=1.5 else ("  <<" if m["pf"]>=1.2 else "")
            print(f"{prefix} {tier_lbl:<10} {m['n']:>5} {m['tpw']:>6.1f}  "
                  f"{m['wr']:>5.1f}%  {m['pf']:>6.3f}  {m['ev']:>+6.3f}%  "
                  f"{m['avg_win']:>+6.3f}%  {m['avg_loss']:>+6.3f}%  "
                  f"{m['maxdd']:>+7.2f}%{mark}")
        print(f"  {'-'*86}")


if __name__ == "__main__":
    WEEKS = 19.2  # from dataset

    tier_map = {"S": S_TIER, "A": A_TIER, "B": B_TIER,
                "S+A": S_TIER+A_TIER, "ALL18": UNIVERSE}

    results = {}
    for tp, sl in CONFIGS:
        print(f"\nRunning TP={tp}% / SL={sl}%...", flush=True)
        all_trades = []
        for sym in UNIVERSE:
            print(f"  {sym}", end=" ", flush=True)
            df = run_symbol(sym, tp, sl)
            if not df.empty:
                all_trades.append(df)
        print()

        combined = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
        combined.to_csv(f"boof53_tpsl_{int(tp*100)}_{int(sl*100)}.csv", index=False)

        tier_results = {}
        for lbl, syms in tier_map.items():
            sub = combined[combined["sym"].isin(syms)] if not combined.empty else pd.DataFrame()
            tier_results[lbl] = metrics(sub, WEEKS)
        results[(tp,sl)] = tier_results

    print_results(results, WEEKS)

    # Also print gap regime breakdown for best config
    print(f"\n{'='*90}")
    print(f"  GAP REGIME BREAKDOWN — TP0.75/SL0.40  |  ALL 18 symbols")
    print(f"{'='*90}")
    try:
        df075 = pd.read_csv("boof53_tpsl_75_40.csv")
        print(f"  {'Regime':<12} {'N':>5} {'T/Wk':>6}  {'WR':>6}  {'PF':>6}  {'EV':>7}  {'MaxDD':>8}")
        print(f"  {'-'*60}")
        for regime in ["Gap Down","Flat","Gap Up"]:
            s = df075[df075["gap_regime"]==regime]
            m = metrics(s, WEEKS)
            if m:
                print(f"  {regime:<12} {m['n']:>5} {m['tpw']:>6.1f}  "
                      f"{m['wr']:>5.1f}%  {m['pf']:>6.3f}  {m['ev']:>+6.3f}%  "
                      f"{m['maxdd']:>+7.2f}%")
    except: pass

    # Per-symbol breakdown for TP0.75/SL0.40
    print(f"\n{'='*90}")
    print(f"  PER-SYMBOL — TP0.75/SL0.40  |  sorted by PF")
    print(f"{'='*90}")
    try:
        df075 = pd.read_csv("boof53_tpsl_75_40.csv")
        sym_rows = []
        for sym in UNIVERSE:
            s = df075[df075["sym"]==sym]
            m = metrics(s, WEEKS)
            if m: sym_rows.append((sym, m))
        sym_rows.sort(key=lambda x: -x[1]["pf"])
        print(f"  {'Sym':<6} {'Tier':<5} {'N':>5} {'T/Wk':>6}  {'WR':>6}  {'PF':>6}  {'EV':>7}  {'MaxDD':>8}")
        print(f"  {'-'*64}")
        tier_of = {s:"S" for s in S_TIER}
        tier_of.update({s:"A" for s in A_TIER})
        tier_of.update({s:"B" for s in B_TIER})
        for sym, m in sym_rows:
            mk = " <<<" if m["pf"]>=1.5 else ("  <<" if m["pf"]>=1.2 else "")
            print(f"  {sym:<6} {tier_of[sym]:<5} {m['n']:>5} {m['tpw']:>6.1f}  "
                  f"{m['wr']:>5.1f}%  {m['pf']:>6.3f}  {m['ev']:>+6.3f}%  "
                  f"{m['maxdd']:>+7.2f}%{mk}")
    except Exception as e:
        print(f"  Error: {e}")
