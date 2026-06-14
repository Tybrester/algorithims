"""
BOOF51 Opening Range Breakout + VWAP Filter — SPY & QQQ
Opening Range: first N minutes (9:30 - 9:45, 9:30 - 10:00, 9:30 - 10:30)
Long:  price breaks above OR high AND close > VWAP
Short: price breaks below OR low  AND close < VWAP
Entry: next bar open
Tests TP/SL: (0.50/0.25), (0.75/0.50), (1.00/0.50)
"""
import datetime
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
SYMBOLS = ["SPY", "QQQ"]

TP_SL_COMBOS = [
    {"tp": 0.0050, "sl": 0.0025, "label": "TP0.50/SL0.25"},
    {"tp": 0.0075, "sl": 0.0050, "label": "TP0.75/SL0.50"},
    {"tp": 0.0100, "sl": 0.0050, "label": "TP1.00/SL0.50"},
]

OR_WINDOWS = [
    {"end": "09:45", "label": "OR15"},
    {"end": "10:00", "label": "OR30"},
    {"end": "10:30", "label": "OR60"},
]

MAX_TRADES = 3
COOLDOWN   = 15
TIME_STOP  = 120


def compute_1m(df):
    df = df.copy().reset_index(drop=True)
    df["date"]  = df["time"].dt.date
    df["typ"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]    = df["typ"] * df["volume"]
    df["cpv"]   = df.groupby("date")["pv"].cumsum()
    df["cvol"]  = df.groupby("date")["volume"].cumsum()
    df["vwap"]  = df["cpv"] / df["cvol"]
    return df


def sim_exit(ddf, ei, ep, tp, sl, side):
    mi = min(ei + TIME_STOP, len(ddf) - 1)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    mfe = mae = 0.0; et = "time"; xp = C[mi]
    for j in range(ei, mi + 1):
        if side == "long":
            mfe = max(mfe, (H[j] - ep) / ep * 100)
            mae = max(mae, (ep - L[j]) / ep * 100)
            if H[j] >= tp: et = "tp"; xp = tp; break
            if L[j] <= sl: et = "sl"; xp = sl; break
        else:
            mfe = max(mfe, (ep - L[j]) / ep * 100)
            mae = max(mae, (H[j] - ep) / ep * 100)
            if L[j] <= tp: et = "tp"; xp = tp; break
            if H[j] >= sl: et = "sl"; xp = sl; break
    pnl = (xp - ep) / ep * 100 if side == "long" else (ep - xp) / ep * 100
    return et, pnl, mfe, mae


def run(df, or_end, tp_pct, sl_pct):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)

        # Build opening range
        or_bars = ddf[ddf["time"].dt.strftime("%H:%M") < or_end]
        if len(or_bars) < 3:
            continue
        or_high = or_bars["high"].max()
        or_low  = or_bars["low"].min()

        lc = sc = 0; lcd = scd = None
        long_triggered = short_triggered = False

        # Only trade after OR is complete
        trade_bars = ddf[ddf["time"].dt.strftime("%H:%M") >= or_end].reset_index(drop=True)

        for i in range(len(trade_bars) - 1):
            row = trade_bars.iloc[i]
            t   = row["time"].strftime("%H:%M")
            if t >= "15:55":
                break
            if pd.isna(row.get("vwap")):
                continue

            nd = row["time"]

            # Long: breakout above OR high + above VWAP (only first breakout per day)
            if (not long_triggered and lc < MAX_TRADES and
                    (lcd is None or nd >= lcd) and
                    row["close"] > or_high and
                    row["close"] > row["vwap"]):
                long_triggered = True
                ep = trade_bars.iloc[i + 1]["open"]
                # Use full day df for exit simulation (need index in full ddf)
                full_i = ddf.index[ddf["time"] == trade_bars.iloc[i + 1]["time"]].tolist()
                if not full_i:
                    continue
                et, pnl, mfe, mae = sim_exit(ddf, full_i[0], ep,
                                             ep * (1 + tp_pct), ep * (1 - sl_pct), "long")
                trades.append({"date": str(date), "side": "long", "or": or_end,
                               "et": et, "pnl": pnl, "mfe": mfe, "mae": mae})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            # Short: breakdown below OR low + below VWAP (only first breakdown per day)
            if (not short_triggered and sc < MAX_TRADES and
                    (scd is None or nd >= scd) and
                    row["close"] < or_low and
                    row["close"] < row["vwap"]):
                short_triggered = True
                ep = trade_bars.iloc[i + 1]["open"]
                full_i = ddf.index[ddf["time"] == trade_bars.iloc[i + 1]["time"]].tolist()
                if not full_i:
                    continue
                et, pnl, mfe, mae = sim_exit(ddf, full_i[0], ep,
                                             ep * (1 - tp_pct), ep * (1 + sl_pct), "short")
                trades.append({"date": str(date), "side": "short", "or": or_end,
                               "et": et, "pnl": pnl, "mfe": mfe, "mae": mae})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)

    return trades


def report(trades, label):
    if not trades:
        print(f"\n{label}: No trades")
        return
    df   = pd.DataFrame(trades)
    wins = df[df["et"] == "tp"]["pnl"]
    loss = df[df["et"] != "tp"]["pnl"]
    wr   = len(wins) / len(df) * 100
    pf   = wins.sum() / abs(loss.sum()) if len(loss) and loss.sum() != 0 else 0
    tpd  = len(df) / df["date"].nunique()
    S    = "=" * 62
    print(f"\n{S}\n  {label}\n{S}")
    print(f"  Trades:{len(df):>4}  Days:{df['date'].nunique():>4}  TPD:{tpd:.2f}  WR:{wr:.1f}%  PF:{pf:.2f}")
    print(f"\n  WINNERS ({len(wins)})")
    if len(wins):
        print(f"    Avg Win      : +{wins.mean():.4f}%")
        print(f"    Median Win   : +{wins.median():.4f}%")
        print(f"    Largest Win  : +{wins.max():.4f}%")
    print(f"\n  LOSERS ({len(loss)})")
    if len(loss):
        print(f"    Avg Loss     :  {loss.mean():.4f}%")
        print(f"    Median Loss  :  {loss.median():.4f}%")
        print(f"    Largest Loss :  {loss.min():.4f}%")
    print(f"\n  EXCURSION")
    print(f"    Avg MFE      : +{df['mfe'].mean():.4f}%")
    print(f"    Avg MAE      :  {df['mae'].mean():.4f}%")
    print(f"    Median MFE   : +{df['mfe'].median():.4f}%")
    print(f"    Median MAE   :  {df['mae'].median():.4f}%")
    print(f"\n  BY SIDE")
    for side in ["long", "short"]:
        s = df[df["side"] == side]
        if s.empty: continue
        sw = s[s["et"] == "tp"]
        print(f"    {side.upper():5}  N={len(s)}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():.4f}%  AvgMFE={s['mfe'].mean():.4f}%  AvgMAE={s['mae'].mean():.4f}%")


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        df = pd.read_csv(f"boof51_{sym}_1m.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_1m(df)
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    # Summary sweep table
    sweep = []
    for sym in SYMBOLS:
        for orw in OR_WINDOWS:
            for combo in TP_SL_COMBOS:
                trades = run(bars[sym], orw["end"], combo["tp"], combo["sl"])
                if trades:
                    df = pd.DataFrame(trades)
                    wins = df[df["et"] == "tp"]["pnl"]; loss = df[df["et"] != "tp"]["pnl"]
                    wr  = len(wins) / len(df) * 100
                    pf  = wins.sum() / abs(loss.sum()) if len(loss) and loss.sum() != 0 else 0
                    tpd = len(df) / df["date"].nunique()
                    sweep.append({"sym": sym, "or": orw["label"], "tpsl": combo["label"],
                                  "n": len(df), "wr": wr, "pf": pf, "tpd": tpd,
                                  "tot": df["pnl"].sum()})

    sdf = pd.DataFrame(sweep).sort_values("pf", ascending=False)
    sdf.to_csv("boof51_orb_sweep.csv", index=False)

    W = 80
    print(f"\n{'='*W}")
    print("  ORB + VWAP FILTER — ALL COMBOS (sorted by PF)")
    print(f"{'='*W}")
    print(f"{'Sym':<5} {'OR':<6} {'TP/SL':<18} {'N':>5} {'WR%':>6} {'PF':>6} {'Tot%':>8} {'TPD':>5}")
    print(f"{'-'*W}")
    for _, r in sdf.iterrows():
        print(f"{r['sym']:<5} {r['or']:<6} {r['tpsl']:<18} {r['n']:>5} {r['wr']:>6.1f} "
              f"{r['pf']:>6.2f} {r['tot']:>8.3f} {r['tpd']:>5.2f}")

    # Deep report for best config per symbol
    print("\n\n--- DEEP REPORTS ---")
    for sym in SYMBOLS:
        best = sdf[sdf["sym"] == sym].iloc[0]
        or_end  = OR_WINDOWS[["OR15","OR30","OR60"].index(best["or"])]["end"]
        tp_combo = next(c for c in TP_SL_COMBOS if c["label"] == best["tpsl"])
        trades = run(bars[sym], or_end, tp_combo["tp"], tp_combo["sl"])
        report(trades, f"{sym} | ORB+VWAP | {best['or']} | {best['tpsl']}")
