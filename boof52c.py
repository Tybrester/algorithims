"""
BOOF52c — C1 Loose + C2 Loose combined, deduped
If both C1 and C2 fire within 10 minutes on same side same day → keep first signal only
Full 6-month backtest with TP/SL sweep + monthly breakdown
"""
import datetime
import pandas as pd
import numpy as np
import pytz

ET = pytz.timezone("America/New_York")

TARGETS  = [0.0025, 0.0050, 0.0075]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%"]
TIME_STOP = 60


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
    daily_close = rt_df.groupby("date")["close"].last().reset_index()
    daily_close.columns = ["date","prev_close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"])
    daily_close["next_date"] = daily_close["date"] + pd.Timedelta(days=1)
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min(),
                "pm_vol":g["volume"].sum()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(daily_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]  = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["open_pos"] = (stats["rth_open"]-stats["pm_low"])/(stats["pm_high"]-stats["pm_low"])
    return stats.dropna(subset=["gap_pct"])


def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]  = (df["high"]+df["low"]+df["close"])/3
    df["pv"]   = df["typ"]*df["volume"]
    df["cpv"]  = df.groupby("date")["pv"].cumsum()
    df["cvol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"] = df["cpv"]/df["cvol"]
    return df


def excursion(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"15m"),(30,"30m"),(60,"60m")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[f"mfe_{key}"]=float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
        res[f"mae_{key}"]=float(max((ep-L[sl])/ep*100)) if side=="long" else float(max((H[sl]-ep)/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end60+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res


def sim_exit(ddf, ei, ep, tp_pct, sl_pct, side):
    mi=min(ei+TIME_STOP, len(ddf)-1)
    H=ddf["high"].values; L=ddf["low"].values; C=ddf["close"].values
    tp=ep*(1+tp_pct) if side=="long" else ep*(1-tp_pct)
    sl=ep*(1-sl_pct) if side=="long" else ep*(1+sl_pct)
    mfe=mae=0.0; et="time"; xp=C[mi]
    for j in range(ei, mi+1):
        if side=="long":
            mfe=max(mfe,(H[j]-ep)/ep*100); mae=max(mae,(ep-L[j])/ep*100)
            if H[j]>=tp: et="tp"; xp=tp; break
            if L[j]<=sl: et="sl"; xp=sl; break
        else:
            mfe=max(mfe,(ep-L[j])/ep*100); mae=max(mae,(H[j]-ep)/ep*100)
            if L[j]<=tp: et="tp"; xp=tp; break
            if H[j]>=sl: et="sl"; xp=sl; break
    pnl=(xp-ep)/ep*100 if side=="long" else (ep-xp)/ep*100
    return et, round(pnl,4), round(mfe,4), round(mae,4)


def collect_signals(df, pm_stats):
    """Collect all C1+C2 signals with timestamps — before dedup."""
    pm = pm_stats.set_index("date")
    raw = []

    for date, ddf in df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day.get("open_pos")) or pd.isna(day["gap_pct"]): continue

        op  = day["open_pos"]; gap = day["gap_pct"]
        pmh = day["pm_high"];  pml = day["pm_low"]
        rth_open = day["rth_open"]

        ddf = ddf.reset_index(drop=True)
        rth = ddf[ddf["time"].dt.strftime("%H:%M")>="09:30"].reset_index(drop=True)
        if len(rth) < 62: continue

        # C1 Loose: op_thresh=0.40
        c1_long  = op > 0.60 and gap > 0
        c1_short = op < 0.40 and gap < 0

        # C2 Loose: outer 15% of range OR outside range
        c2_long  = rth_open < pml or op < 0.15
        c2_short = rth_open > pmh or op > 0.85

        # Collect candidate signals with bar index + time
        for j in range(len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break

            green = row["close"] > row["open"]
            red   = row["close"] < row["open"]

            if (c1_long or c2_long) and green:
                ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    setup = "C1" if c1_long else "C2"
                    if c1_long and c2_long: setup = "C1+C2"
                    raw.append({"date":str(date),"side":"long","setup":setup,
                                "entry_time":rth.iloc[j]["time"],"bar_idx":fi[0],
                                "ep":ep,**excursion(ddf,fi[0],ep,"long")})

            if (c1_short or c2_short) and red:
                ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    setup = "C1" if c1_short else "C2"
                    if c1_short and c2_short: setup = "C1+C2"
                    raw.append({"date":str(date),"side":"short","setup":setup,
                                "entry_time":rth.iloc[j]["time"],"bar_idx":fi[0],
                                "ep":ep,**excursion(ddf,fi[0],ep,"short")})

    return pd.DataFrame(raw) if raw else pd.DataFrame()


def dedupe(raw_df, max_per_side=2, cooldown_min=10):
    """Keep only the first signal per side per cooldown window per day."""
    if raw_df.empty: return raw_df
    out = []
    for date, grp in raw_df.groupby("date"):
        for side in ["long","short"]:
            s = grp[grp["side"]==side].sort_values("entry_time").reset_index(drop=True)
            count = 0; last_time = None
            for _, row in s.iterrows():
                if count >= max_per_side: break
                if last_time is not None:
                    gap_min = (row["entry_time"] - last_time).total_seconds() / 60
                    if gap_min < cooldown_min: continue
                out.append(row)
                count += 1; last_time = row["entry_time"]
    return pd.DataFrame(out).reset_index(drop=True) if out else pd.DataFrame()


def run_backtest(df, signals_df, tp_pct, sl_pct):
    """Re-simulate exits using actual bar data for each deduped signal."""
    df = df.copy(); df["date"] = pd.to_datetime(df["date"])
    day_map = {date: ddf.reset_index(drop=True) for date, ddf in df.groupby("date")}

    trades = []
    for _, sig in signals_df.iterrows():
        date_ts = pd.Timestamp(sig["date"])
        if date_ts not in day_map: continue
        ddf = day_map[date_ts]
        ei  = int(sig["bar_idx"]); ep = sig["ep"]
        if ei >= len(ddf): continue
        et, pnl, mfe, mae = sim_exit(ddf, ei, ep, tp_pct, sl_pct, sig["side"])
        trades.append({**sig.to_dict(), "tp":tp_pct,"sl":sl_pct,
                       "et":et,"pnl":pnl,"mfe":mfe,"mae":mae})
    return pd.DataFrame(trades)


def full_report(trades_df, label):
    if trades_df.empty: print(f"\n{label}: no trades"); return
    df = trades_df
    wins = df[df["et"]=="tp"]; loss = df[df["et"]!="tp"]
    n    = len(df); nd = df["date"].nunique(); tpd = n/nd
    wr   = len(wins)/n*100
    pf   = wins["pnl"].sum()/abs(loss["pnl"].sum()) if len(loss) and loss["pnl"].sum()!=0 else 0
    ev   = df["pnl"].mean()
    tot  = df["pnl"].sum()

    S="="*68
    print(f"\n{S}\n  {label}\n{S}")
    print(f"  Trades:{n:>4}  Days:{nd:>4}  TPD:{tpd:.1f}  WR:{wr:.1f}%  PF:{pf:.2f}  EV:{ev:+.4f}%  Total:{tot:+.3f}%")
    print(f"\n  WINNERS ({len(wins)}): Avg={wins['pnl'].mean():+.4f}%  Largest={wins['pnl'].max():+.4f}%")
    print(f"  LOSERS  ({len(loss)}): Avg={loss['pnl'].mean():+.4f}%  Largest={loss['pnl'].min():+.4f}%")
    print(f"  MFE: {df['mfe'].mean():.4f}%   MAE: {df['mae'].mean():.4f}%")

    print(f"\n  BY SIDE")
    for side in ["long","short"]:
        s=df[df["side"]==side]
        if s.empty: continue
        sw=s[s["et"]=="tp"]
        print(f"    {side.upper():<6} N={len(s):>3}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():+.4f}%  MFE={s['mfe'].mean():.4f}%  MAE={s['mae'].mean():.4f}%")

    print(f"\n  BY SETUP SOURCE")
    for setup in df["setup"].unique():
        s=df[df["setup"]==setup]; sw=s[s["et"]=="tp"]
        print(f"    {setup:<8} N={len(s):>3}  WR={len(sw)/len(s)*100:.1f}%  AvgPnL={s['pnl'].mean():+.4f}%")

    print(f"\n  MONTHLY")
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    print(f"  {'Month':<10} {'N':>5} {'WR%':>6} {'PF':>6} {'TotPnL':>9} {'EV':>9}")
    print(f"  {'-'*50}")
    for mo, g in df.groupby("month"):
        w=g[g["et"]=="tp"]; l=g[g["et"]!="tp"]
        mwr=len(w)/len(g)*100
        mpf=w["pnl"].sum()/abs(l["pnl"].sum()) if len(l) and l["pnl"].sum()!=0 else 0
        print(f"  {str(mo):<10} {len(g):>5} {mwr:>6.1f} {mpf:>6.2f} {g['pnl'].sum():>+9.3f}% {g['pnl'].mean():>+9.4f}%")
    print(f"  {'-'*50}")
    print(f"  {'TOTAL':<10} {n:>5} {wr:>6.1f} {pf:>6.2f} {tot:>+9.3f}% {ev:>+9.4f}%")


if __name__ == "__main__":
    print("Loading QQQ...", flush=True)
    pm_df    = load_pm("QQQ")
    rt_df    = load_rt("QQQ")
    rt_df    = add_indicators(rt_df)
    pm_stats = build_pm_stats(pm_df, rt_df)

    print("Collecting C1+C2 signals...", flush=True)
    raw = collect_signals(rt_df, pm_stats)
    print(f"  Raw signals: {len(raw)}", flush=True)

    deduped = dedupe(raw, max_per_side=2, cooldown_min=10)
    print(f"  After dedup: {len(deduped)}", flush=True)

    # Signal source breakdown
    if not deduped.empty:
        print(f"\n  Signal source breakdown:")
        for setup, g in deduped.groupby("setup"):
            print(f"    {setup}: {len(g)} ({len(g[g['side']=='long'])} long / {len(g[g['side']=='short'])} short)")

    # TP/SL sweep
    TP_SL = [
        (0.0025, 0.0025, "TP0.25/SL0.25"),
        (0.0050, 0.0025, "TP0.50/SL0.25"),
        (0.0050, 0.0050, "TP0.50/SL0.50"),
        (0.0075, 0.0050, "TP0.75/SL0.50"),
        (0.0100, 0.0050, "TP1.00/SL0.50"),
    ]

    print(f"\n{'='*70}")
    print(f"  QQQ | C1+C2 Loose Combined (deduped) | TP/SL Sweep")
    print(f"{'='*70}")
    print(f"  {'TP/SL':<18} {'N':>5} {'WR%':>6} {'PF':>6} {'EV':>9} {'Total':>9}")
    print(f"  {'-'*55}")

    best_combo = None; best_pf = 0
    for tp, sl, lbl in TP_SL:
        t = run_backtest(rt_df, deduped, tp, sl)
        if t.empty: continue
        wins=t[t["et"]=="tp"]; loss=t[t["et"]!="tp"]
        wr=len(wins)/len(t)*100
        pf=wins["pnl"].sum()/abs(loss["pnl"].sum()) if len(loss) and loss["pnl"].sum()!=0 else 0
        ev=t["pnl"].mean(); tot=t["pnl"].sum()
        print(f"  {lbl:<18} {len(t):>5} {wr:>6.1f} {pf:>6.2f} {ev:>+9.4f}% {tot:>+9.3f}%")
        if pf > best_pf: best_pf=pf; best_combo=(tp,sl,lbl,t)

    # Deep report on best
    if best_combo:
        tp,sl,lbl,t = best_combo
        full_report(t, f"QQQ | C1+C2 Loose | {lbl}")
        t.to_csv("boof52_QQQ_combined.csv", index=False)
        print("\n  Saved boof52_QQQ_combined.csv")
