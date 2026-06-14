"""
BOOF52 Deep Analysis
1. Monte Carlo  — 1000 reshuffles of trade PnL sequence
2. Walk-Forward — expanding window, monthly OOS test
3. MFE/MAE      — by winners vs losers
4. Options Sim  — 0DTE/1DTE with actual timed exits at median hit windows
"""
import datetime
import numpy as np
import pandas as pd
import pytz
from scipy.stats import norm

ET = pytz.timezone("America/New_York")
TARGETS  = [0.0025, 0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%", "+1.00%"]
TIME_STOP = 60
TP = 0.0075; SL = 0.0050   # best config from sweep


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_rt(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def load_pm(sym):
    df = pd.read_csv(f"boof51_{sym}_pm.csv")
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
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]  = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["open_pos"] = (stats["rth_open"]-stats["pm_low"])/(stats["pm_high"]-stats["pm_low"])
    return stats.dropna(subset=["gap_pct"])

def add_vwap(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]=(df["high"]+df["low"]+df["close"])/3; df["pv"]=df["typ"]*df["volume"]
    df["cpv"]=df.groupby("date")["pv"].cumsum(); df["cvol"]=df.groupby("date")["volume"].cumsum()
    df["vwap"]=df["cpv"]/df["cvol"]
    return df


# ── Signal collection (C1+C2 Loose, deduped) ─────────────────────────────────

def collect_and_dedupe(df, pm_stats):
    pm = pm_stats.set_index("date"); raw = []
    for date, ddf in df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day.get("open_pos")) or pd.isna(day["gap_pct"]): continue
        op=day["open_pos"]; gap=day["gap_pct"]
        pmh=day["pm_high"]; pml=day["pm_low"]; rth_open=day["rth_open"]
        ddf=ddf.reset_index(drop=True)
        rth=ddf[ddf["time"].dt.strftime("%H:%M")>="09:30"].reset_index(drop=True)
        if len(rth)<62: continue
        c1l=op>0.60 and gap>0; c1s=op<0.40 and gap<0
        c2l=rth_open<pml or op<0.15; c2s=rth_open>pmh or op>0.85
        for j in range(len(rth)-61):
            row=rth.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            green=row["close"]>row["open"]; red=row["close"]<row["open"]
            for side,flag,c1,c2 in [("long",green,c1l,c2l),("short",red,c1s,c2s)]:
                if flag and (c1 or c2):
                    ei=j+1; ep=rth.iloc[ei]["open"]
                    fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                    if fi:
                        s="C1" if (c1 and not c2) else ("C2" if (c2 and not c1) else "C1+C2")
                        raw.append({"date":str(date),"side":side,"setup":s,
                                    "entry_time":rth.iloc[j]["time"],"bar_idx":fi[0],"ep":ep})
    rdf = pd.DataFrame(raw) if raw else pd.DataFrame()
    if rdf.empty: return rdf
    out=[]
    for date,grp in rdf.groupby("date"):
        for side in ["long","short"]:
            s=grp[grp["side"]==side].sort_values("entry_time").reset_index(drop=True)
            count=0; last_time=None
            for _,row in s.iterrows():
                if count>=2: break
                if last_time and (row["entry_time"]-last_time).total_seconds()/60<10: continue
                out.append(row); count+=1; last_time=row["entry_time"]
    return pd.DataFrame(out).reset_index(drop=True)


# ── Exit simulation ───────────────────────────────────────────────────────────

def sim_exit(ddf, ei, ep, tp_pct, sl_pct, side):
    mi=min(ei+TIME_STOP, len(ddf)-1)
    H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    tp_p=ep*(1+tp_pct) if side=="long" else ep*(1-tp_pct)
    sl_p=ep*(1-sl_pct) if side=="long" else ep*(1+sl_pct)
    mfe=mae=0.0; et="time"; xp=C[mi]
    for j in range(ei, mi+1):
        if side=="long":
            mfe=max(mfe,(H[j]-ep)/ep*100); mae=max(mae,(ep-L[j])/ep*100)
            if H[j]>=tp_p: et="tp"; xp=tp_p; break
            if L[j]<=sl_p: et="sl"; xp=sl_p; break
        else:
            mfe=max(mfe,(ep-L[j])/ep*100); mae=max(mae,(H[j]-ep)/ep*100)
            if L[j]<=tp_p: et="tp"; xp=tp_p; break
            if H[j]>=sl_p: et="sl"; xp=sl_p; break
    pnl=(xp-ep)/ep*100 if side=="long" else (ep-xp)/ep*100
    return et, round(pnl,4), round(mfe,4), round(mae,4)

def build_trades(df, signals_df, tp_pct=TP, sl_pct=SL):
    df=df.copy(); df["date"]=pd.to_datetime(df["date"])
    day_map={date:ddf.reset_index(drop=True) for date,ddf in df.groupby("date")}
    trades=[]
    for _,sig in signals_df.iterrows():
        date_ts=pd.Timestamp(sig["date"])
        if date_ts not in day_map: continue
        ddf=day_map[date_ts]; ei=int(sig["bar_idx"]); ep=sig["ep"]
        et,pnl,mfe,mae=sim_exit(ddf,ei,ep,tp_pct,sl_pct,sig["side"])
        trades.append({**sig.to_dict(),"et":et,"pnl":pnl,"mfe":mfe,"mae":mae})
    return pd.DataFrame(trades)


# ══════════════════════════════════════════════════════════════════════════════
# 1. MONTE CARLO
# ══════════════════════════════════════════════════════════════════════════════

def monte_carlo(pnl_series, n_sims=1000, seed=42):
    np.random.seed(seed)
    pnl = pnl_series.values
    n   = len(pnl)
    totals=[]; maxdds=[]; sharpes=[]
    for _ in range(n_sims):
        shuffled = np.random.choice(pnl, size=n, replace=True)
        equity   = np.cumsum(shuffled)
        peak     = np.maximum.accumulate(equity)
        dd       = equity - peak
        totals.append(equity[-1])
        maxdds.append(dd.min())
        mu=shuffled.mean(); sd=shuffled.std()
        sharpes.append(mu/sd*np.sqrt(252*2.8) if sd>0 else 0)  # annualized at 2.8 TPD

    totals=np.array(totals); maxdds=np.array(maxdds); sharpes=np.array(sharpes)
    W=60
    print(f"\n{'='*W}")
    print(f"  MONTE CARLO  (n={n} trades, {n_sims} simulations, bootstrap)")
    print(f"{'='*W}")
    print(f"  Total PnL %:")
    print(f"    Mean     : {totals.mean():+.3f}%")
    print(f"    Median   : {np.median(totals):+.3f}%")
    print(f"    p5       : {np.percentile(totals,5):+.3f}%  (worst 5%)")
    print(f"    p95      : {np.percentile(totals,95):+.3f}%  (best 5%)")
    print(f"    % positive: {(totals>0).mean()*100:.1f}%")
    print(f"\n  Max Drawdown %:")
    print(f"    Mean     : {maxdds.mean():.3f}%")
    print(f"    p5 (worst): {np.percentile(maxdds,5):.3f}%")
    print(f"    p95      : {np.percentile(maxdds,95):.3f}%")
    print(f"\n  Annualized Sharpe:")
    print(f"    Mean     : {sharpes.mean():.2f}")
    print(f"    p5       : {np.percentile(sharpes,5):.2f}")
    print(f"    p95      : {np.percentile(sharpes,95):.2f}")

    # Actual equity curve stats
    equity_actual = np.cumsum(pnl)
    peak_actual   = np.maximum.accumulate(equity_actual)
    dd_actual     = equity_actual - peak_actual
    print(f"\n  ACTUAL (in-sample):")
    print(f"    Total PnL : {equity_actual[-1]:+.3f}%")
    print(f"    Max DD    : {dd_actual.min():.3f}%")
    print(f"    Sharpe    : {(pnl.mean()/pnl.std()*np.sqrt(252*2.8)):.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. WALK-FORWARD
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward(trades_df):
    trades_df = trades_df.copy()
    trades_df["date"] = pd.to_datetime(trades_df["date"])
    trades_df["month"] = trades_df["date"].dt.to_period("M")
    months = sorted(trades_df["month"].unique())

    W=68
    print(f"\n{'='*W}")
    print(f"  WALK-FORWARD  (each month = OOS, trained on all prior months)")
    print(f"{'='*W}")
    print(f"  {'Month':<10} {'OOS N':>6} {'OOS WR':>8} {'OOS PF':>8} {'OOS EV':>9} {'CumPnL':>9}")
    print(f"  {'-'*60}")

    cum_pnl = 0.0
    for i, mo in enumerate(months):
        if i == 0: continue   # need at least 1 month of IS data
        oos = trades_df[trades_df["month"]==mo]
        if oos.empty: continue
        wins = oos[oos["et"]=="tp"]; loss = oos[oos["et"]!="tp"]
        wr   = len(wins)/len(oos)*100
        pf   = wins["pnl"].sum()/abs(loss["pnl"].sum()) if len(loss) and loss["pnl"].sum()!=0 else 0
        ev   = oos["pnl"].mean()
        cum_pnl += oos["pnl"].sum()
        print(f"  {str(mo):<10} {len(oos):>6} {wr:>7.1f}% {pf:>8.2f} {ev:>+9.4f}% {cum_pnl:>+9.3f}%")
    print(f"  {'-'*60}")
    total = trades_df["pnl"].sum()
    print(f"  {'TOTAL':<10} {len(trades_df):>6}  {'':>8} {'':>8} {'':>9} {total:>+9.3f}%")


# ══════════════════════════════════════════════════════════════════════════════
# 3. MFE/MAE BY OUTCOME
# ══════════════════════════════════════════════════════════════════════════════

def mfe_mae_analysis(trades_df):
    W=72
    print(f"\n{'='*W}")
    print(f"  MFE / MAE  by Outcome")
    print(f"{'='*W}")
    print(f"  {'Group':<20} {'N':>5}  {'AvgMFE':>8} {'MedMFE':>8} {'AvgMAE':>8} {'MedMAE':>8}  {'MFE/MAE':>8}")
    print(f"  {'-'*68}")

    groups = [
        ("Winners (TP)",    trades_df[trades_df["et"]=="tp"]),
        ("Losers (SL)",     trades_df[trades_df["et"]=="sl"]),
        ("Losers (Time)",   trades_df[trades_df["et"]=="time"]),
        ("All Trades",      trades_df),
        ("Longs",           trades_df[trades_df["side"]=="long"]),
        ("Shorts",          trades_df[trades_df["side"]=="short"]),
    ]
    for lbl, g in groups:
        if g.empty: continue
        amfe=g["mfe"].mean(); mmfe=g["mfe"].median()
        amae=g["mae"].mean(); mmae=g["mae"].median()
        ratio=amfe/amae if amae>0 else 0
        print(f"  {lbl:<20} {len(g):>5}  {amfe:>7.4f}% {mmfe:>7.4f}% {amae:>7.4f}% {mmae:>7.4f}%  {ratio:>8.3f}")

    # Entry quality: % of trades where MFE > MAE (favorable direction)
    print(f"\n  ENTRY QUALITY")
    mfe_gt_mae = (trades_df["mfe"] > trades_df["mae"]).mean()*100
    avg_mfe_at_sl = trades_df[trades_df["et"]=="sl"]["mfe"].mean()
    print(f"    MFE > MAE (favorable direction)  : {mfe_gt_mae:.1f}% of trades")
    print(f"    Avg MFE on SL trades             : {avg_mfe_at_sl:.4f}% (how far they moved right before reversing)")

    # Bucket by MFE
    print(f"\n  MFE BUCKETS → outcome distribution")
    print(f"  {'MFE Bucket':<16} {'N':>5}  {'TP%':>7} {'SL%':>7} {'Time%':>7}  {'AvgPnL':>9}")
    print(f"  {'-'*58}")
    for lo,hi,lbl in [(0,0.1,"0-0.10%"),(0.1,0.25,"0.10-0.25%"),(0.25,0.5,"0.25-0.50%"),(0.5,99,"0.50%+")]:
        g=trades_df[(trades_df["mfe"]>=lo)&(trades_df["mfe"]<hi)]
        if g.empty: continue
        tp_pct=(g["et"]=="tp").mean()*100; sl_pct=(g["et"]=="sl").mean()*100; ti_pct=(g["et"]=="time").mean()*100
        print(f"  {lbl:<16} {len(g):>5}  {tp_pct:>6.1f}% {sl_pct:>6.1f}% {ti_pct:>6.1f}%  {g['pnl'].mean():>+8.4f}%")


# ══════════════════════════════════════════════════════════════════════════════
# 4. OPTIONS SIM WITH ACTUAL TIMED EXITS
# ══════════════════════════════════════════════════════════════════════════════

def bs_price(S, K, T, r, sigma, opt):
    if T <= 1e-6: return max(0.0, S-K) if opt=="call" else max(0.0, K-S)
    d1=(np.log(S/K)+(r+0.5*sigma**2)*T)/(sigma*np.sqrt(T)); d2=d1-sigma*np.sqrt(T)
    return (S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2)) if opt=="call" \
      else (K*np.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1))

def options_sim(df, signals_df):
    """
    Exit rules:
      - If +0.50% hit within 30 bars: exit at that bar (median hit time)
      - If +0.75% hit within 60 bars: exit at that bar
      - Otherwise: exit at 60 bars (time stop)
    0DTE IV = 25% (gap-day assumption), 1DTE IV = 22%
    """
    df=df.copy(); df["date"]=pd.to_datetime(df["date"])
    day_map={date:ddf.reset_index(drop=True) for date,ddf in df.groupby("date")}
    r=0.05

    CONFIGS = [
        {"dte":0, "iv":0.25, "label":"0DTE  IV25%"},
        {"dte":1, "iv":0.22, "label":"1DTE  IV22%"},
    ]

    all_results=[]
    for _,sig in signals_df.iterrows():
        date_ts=pd.Timestamp(sig["date"])
        if date_ts not in day_map: continue
        ddf=day_map[date_ts]; ei=int(sig["bar_idx"]); ep=sig["ep"]; side=sig["side"]
        opt="call" if side=="long" else "put"
        n=len(ddf); H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
        if ei+1>=n: continue

        for cfg in CONFIGS:
            bars_in_day = 390
            bar_fraction = 1.0 / (252 * bars_in_day)
            T_entry = max((cfg["dte"] + (bars_in_day - ei) / bars_in_day) / 252, bar_fraction)
            iv      = cfg["iv"]
            K       = round(ep)   # ATM

            p_entry = bs_price(ep, K, T_entry, r, iv, opt)
            if p_entry < 0.01: continue

            # Determine exit bar: first to hit +0.50% within 30 bars,
            # then +0.75% within 60, else time stop at 60
            exit_bar = None; exit_reason = "time"
            tgt50 = ep*(1+0.005) if side=="long" else ep*(1-0.005)
            tgt75 = ep*(1+0.0075) if side=="long" else ep*(1-0.0075)

            for j in range(ei, min(ei+30, n)):
                if (side=="long" and H[j]>=tgt50) or (side=="short" and L[j]<=tgt50):
                    exit_bar=j; exit_reason="+0.50% hit"; break

            if exit_bar is None:
                for j in range(ei, min(ei+60, n)):
                    if (side=="long" and H[j]>=tgt75) or (side=="short" and L[j]<=tgt75):
                        exit_bar=j; exit_reason="+0.75% hit"; break

            if exit_bar is None:
                exit_bar=min(ei+60, n-1); exit_reason="time"

            bars_held = exit_bar - ei
            xp = C[exit_bar]
            T_exit = max(T_entry - bars_held*bar_fraction, bar_fraction)
            iv_exit = iv * 0.92   # slight IV crush

            p_exit = bs_price(xp, K, T_exit, r, iv_exit, opt)
            pnl_pct    = (p_exit-p_entry)/p_entry*100
            pnl_dollar = (p_exit-p_entry)*100
            und_move   = (xp-ep)/ep*100 if side=="long" else (ep-xp)/ep*100

            all_results.append({
                "date":sig["date"],"side":side,"config":cfg["label"],
                "exit_reason":exit_reason,"bars_held":bars_held,
                "ep":round(ep,2),"K":K,"p_entry":round(p_entry,3),"p_exit":round(p_exit,3),
                "und_move":round(und_move,4),"pnl_pct":round(pnl_pct,2),"pnl_dollar":round(pnl_dollar,2),
            })

    rdf = pd.DataFrame(all_results)
    W=80
    print(f"\n{'='*W}")
    print(f"  OPTIONS SIM  | 0DTE & 1DTE ATM | Timed Exits | C1+C2 Loose Signals")
    print(f"{'='*W}")
    print(f"  {'Config':<14} {'Side':<7} {'N':>5}  {'WR%':>6} {'AvgUnd':>8} "
          f"{'AvgPnL%':>8} {'AvgPnL$':>8} {'Med$':>8} {'Best$':>8} {'Worst$':>8}")
    print(f"  {'-'*78}")

    for config in rdf["config"].unique():
        for side in ["long","short","all"]:
            s=rdf[rdf["config"]==config] if side=="all" else rdf[(rdf["config"]==config)&(rdf["side"]==side)]
            if s.empty: continue
            slbl=side.upper() if side!="all" else "BOTH"
            wr=(s["pnl_dollar"]>0).mean()*100
            print(f"  {config:<14} {slbl:<7} {len(s):>5}  {wr:>6.1f}% "
                  f"{s['und_move'].mean():>+7.3f}% {s['pnl_pct'].mean():>+7.1f}% "
                  f"{s['pnl_dollar'].mean():>+8.2f} {s['pnl_dollar'].median():>+8.2f} "
                  f"{s['pnl_dollar'].max():>+8.2f} {s['pnl_dollar'].min():>+8.2f}")

        # Exit reason breakdown
        cfg_df = rdf[rdf["config"]==config]
        print(f"\n  {config} — exit breakdown:")
        for reason, g in cfg_df.groupby("exit_reason"):
            print(f"    {reason:<16} N={len(g):>3}  AvgPnL${g['pnl_dollar'].mean():>+8.2f}  "
                  f"AvgBarsHeld={g['bars_held'].mean():.1f}")
        print(f"  {'-'*78}")

    return rdf


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading QQQ...", flush=True)
    rt_df    = load_rt("QQQ"); rt_df = add_vwap(rt_df)
    pm_df    = load_pm("QQQ")
    pm_stats = build_pm_stats(pm_df, rt_df)
    signals  = collect_and_dedupe(rt_df, pm_stats)
    print(f"  Signals: {len(signals)}", flush=True)

    print("Building trades (TP0.75/SL0.50)...", flush=True)
    trades = build_trades(rt_df, signals, tp_pct=TP, sl_pct=SL)
    print(f"  Trades: {len(trades)}", flush=True)

    # ── 1. Monte Carlo ────────────────────────────────────────────────────────
    monte_carlo(trades["pnl"])

    # ── 2. Walk-Forward ───────────────────────────────────────────────────────
    walk_forward(trades)

    # ── 3. MFE/MAE Analysis ───────────────────────────────────────────────────
    mfe_mae_analysis(trades)

    # ── 4. Options Sim ────────────────────────────────────────────────────────
    opt_results = options_sim(rt_df, signals)
    opt_results.to_csv("boof52_QQQ_options.csv", index=False)
    print("\n  Saved boof52_QQQ_options.csv")
