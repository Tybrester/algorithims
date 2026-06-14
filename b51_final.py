"""
BOOF51 Final Strategy — QQQ + SPY
Window: 9:00–12:00 ET only
Signals: OR15 Break + VWAP Slope Accel (either fires = entry)
TP/SL combos: 0.25/0.25, 0.50/0.25, 0.50/0.50, 0.75/0.50
"""
import datetime
import pandas as pd
import pytz

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]

TP_SL_COMBOS = [
    {"tp": 0.0025, "sl": 0.0025, "label": "TP0.25/SL0.25"},
    {"tp": 0.0050, "sl": 0.0025, "label": "TP0.50/SL0.25"},
    {"tp": 0.0050, "sl": 0.0050, "label": "TP0.50/SL0.50"},
    {"tp": 0.0075, "sl": 0.0050, "label": "TP0.75/SL0.50"},
]

WINDOW_START = "09:00"
WINDOW_END   = "12:00"
MAX_TRADES   = 3
COOLDOWN     = 10
TIME_STOP    = 60


def compute(df):
    df = df.copy().reset_index(drop=True)
    df["date"]       = df["time"].dt.date
    df["typ"]        = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]         = df["typ"] * df["volume"]
    df["cpv"]        = df.groupby("date")["pv"].cumsum()
    df["cvol"]       = df.groupby("date")["volume"].cumsum()
    df["vwap"]       = df["cpv"] / df["cvol"]
    df["vol_ma20"]   = df["volume"].rolling(20).mean()
    df["vwap_slope"] = df["vwap"].diff(5)
    df["prev_c"]     = df["close"].shift(1)
    return df


def sim_exit(ddf, ei, ep, tp_pct, sl_pct, side):
    mi = min(ei + TIME_STOP, len(ddf) - 1)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    tp = ep * (1 + tp_pct) if side == "long" else ep * (1 - tp_pct)
    sl = ep * (1 - sl_pct) if side == "long" else ep * (1 + sl_pct)
    mfe = mae = 0.0; et = "time"; xp = C[mi]
    for j in range(ei, mi + 1):
        if side == "long":
            mfe = max(mfe, (H[j]-ep)/ep*100); mae = max(mae, (ep-L[j])/ep*100)
            if H[j] >= tp: et="tp"; xp=tp; break
            if L[j] <= sl: et="sl"; xp=sl; break
        else:
            mfe = max(mfe, (ep-L[j])/ep*100); mae = max(mae, (H[j]-ep)/ep*100)
            if L[j] <= tp: et="tp"; xp=tp; break
            if H[j] >= sl: et="sl"; xp=sl; break
    pnl = (xp-ep)/ep*100 if side=="long" else (ep-xp)/ep*100
    return et, pnl, mfe, mae


def run(df, tp_pct, sl_pct):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)

        # OR15 range
        or_b = ddf[ddf["time"].dt.strftime("%H:%M") < "09:45"]
        orh  = or_b["high"].max()  if len(or_b) >= 3 else None
        orl  = or_b["low"].min()   if len(or_b) >= 3 else None
        or15_long_fired = or15_short_fired = False

        lc = sc = 0; lcd = scd = None

        for i in range(20, len(ddf) - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < WINDOW_START or t >= WINDOW_END: continue
            if pd.isna(row["vwap"]) or pd.isna(row["vwap_slope"]): continue

            nd    = row["time"]
            slope = row["vwap_slope"]
            ps    = ddf.iloc[i-5]["vwap_slope"] if i >= 5 and not pd.isna(ddf.iloc[i-5]["vwap_slope"]) else 0

            # Signal A: OR15 break
            or_long  = (orh is not None and not or15_long_fired  and
                        row["close"] > orh and row["close"] > row["vwap"])
            or_short = (orl is not None and not or15_short_fired and
                        row["close"] < orl and row["close"] < row["vwap"])

            # Signal B: VWAP slope acceleration
            accel      = ps != 0 and abs(slope) > 2 * abs(ps)
            slope_long  = accel and slope > 0 and row["close"] > row["vwap"]
            slope_short = accel and slope < 0 and row["close"] < row["vwap"]

            go_long  = or_long  or slope_long
            go_short = or_short or slope_short

            if or_long:  or15_long_fired  = True
            if or_short: or15_short_fired = True

            if lc < MAX_TRADES and (lcd is None or nd >= lcd) and go_long:
                ep = ddf.iloc[i+1]["open"]
                et, pnl, mfe, mae = sim_exit(ddf, i+1, ep, tp_pct, sl_pct, "long")
                sig = "or15" if or_long else "slope"
                trades.append({"date":str(date),"side":"long","sig":sig,
                               "et":et,"pnl":pnl,"mfe":mfe,"mae":mae})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            if sc < MAX_TRADES and (scd is None or nd >= scd) and go_short:
                ep = ddf.iloc[i+1]["open"]
                et, pnl, mfe, mae = sim_exit(ddf, i+1, ep, tp_pct, sl_pct, "short")
                sig = "or15" if or_short else "slope"
                trades.append({"date":str(date),"side":"short","sig":sig,
                               "et":et,"pnl":pnl,"mfe":mfe,"mae":mae})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)

    return trades


def report(trades, label):
    if not trades: print(f"\n{label}: No trades"); return
    df   = pd.DataFrame(trades)
    wins = df[df["et"]=="tp"]["pnl"]; loss = df[df["et"]!="tp"]["pnl"]
    wr   = len(wins)/len(df)*100
    pf   = wins.sum()/abs(loss.sum()) if len(loss) and loss.sum()!=0 else 0
    ev   = df["pnl"].mean()
    tpd  = len(df)/df["date"].nunique()
    S    = "="*62
    print(f"\n{S}\n  {label}\n{S}")
    print(f"  Trades:{len(df):>4}  Days:{df['date'].nunique():>4}  TPD:{tpd:.1f}  WR:{wr:.1f}%  PF:{pf:.2f}  EV:{ev:+.4f}%")
    print(f"\n  WINNERS ({len(wins)})")
    if len(wins):
        print(f"    Avg Win      : +{wins.mean():.4f}%")
        print(f"    Largest Win  : +{wins.max():.4f}%")
    print(f"\n  LOSERS ({len(loss)})")
    if len(loss):
        print(f"    Avg Loss     :  {loss.mean():.4f}%")
        print(f"    Largest Loss :  {loss.min():.4f}%")
    print(f"\n  EXCURSION")
    print(f"    Avg MFE : +{df['mfe'].mean():.4f}%   Avg MAE : {df['mae'].mean():.4f}%")
    print(f"\n  BY SIDE")
    for side in ["long","short"]:
        s=df[df["side"]==side]
        if s.empty: continue
        sw=s[s["et"]=="tp"]
        print(f"    {side.upper():5}  N={len(s)}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():+.4f}%  AvgMFE={s['mfe'].mean():.4f}%")
    print(f"\n  BY SIGNAL SOURCE")
    for sig in ["or15","slope"]:
        s=df[df["sig"]==sig]
        if s.empty: continue
        sw=s[s["et"]=="tp"]
        print(f"    {sig.upper():6}  N={len(s)}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():+.4f}%")


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        df = pd.read_csv(f"boof51_{sym}_1m.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute(df).dropna(subset=["vwap"])
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    # Sweep all TP/SL combos
    print("\n" + "="*80)
    print("  SWEEP — OR15 Break + VWAP Slope Accel | 9:00–12:00 ET | QQQ & SPY")
    print("="*80)
    print(f"  {'Sym':<5} {'TP/SL':<18} {'N':>5} {'WR%':>6} {'PF':>6} {'EV':>8} {'TPD':>5}")
    print(f"  {'-'*60}")
    for sym in SYMBOLS:
        for combo in TP_SL_COMBOS:
            trades = run(bars[sym], combo["tp"], combo["sl"])
            if not trades: continue
            df = pd.DataFrame(trades)
            wins = df[df["et"]=="tp"]["pnl"]; loss = df[df["et"]!="tp"]["pnl"]
            wr  = len(wins)/len(df)*100
            pf  = wins.sum()/abs(loss.sum()) if len(loss) and loss.sum()!=0 else 0
            ev  = df["pnl"].mean()
            tpd = len(df)/df["date"].nunique()
            print(f"  {sym:<5} {combo['label']:<18} {len(df):>5} {wr:>6.1f} {pf:>6.2f} {ev:>+8.4f}% {tpd:>5.1f}")

    # Deep report for best combos
    print("\n\n--- DEEP REPORTS ---")
    for sym in SYMBOLS:
        best = TP_SL_COMBOS[1]  # TP0.50/SL0.25 — highest asymmetry
        trades = run(bars[sym], best["tp"], best["sl"])
        report(trades, f"{sym} | OR15+Slope | 9-12 ET | {best['label']}")
