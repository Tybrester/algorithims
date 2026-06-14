"""
BOOF51 Intraday Mean Reversion — SPY & QQQ
Long:  price < VWAP, RSI2 < 5,  dist_from_VWAP > 0.40%  -> target VWAP or +0.25%
Short: price > VWAP, RSI2 > 95, dist_from_VWAP > 0.40%  -> target VWAP or -0.25%
SL: 0.40% (equal to min stretch required to enter)
Entry: next bar open
"""
import datetime
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
SYMBOLS    = ["SPY", "QQQ"]
MIN_DIST   = 0.0040   # 0.40% min distance from VWAP to enter
SL_PCT     = 0.0040   # stop loss 0.40%
TP_FIXED   = 0.0025   # fixed TP 0.25%
MAX_TRADES = 5
COOLDOWN   = 10
TIME_STOP  = 60       # shorter — mean reversion should be quick


def calc_rsi2(s):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))


def compute_1m(df):
    df = df.copy().reset_index(drop=True)
    df["date"]  = df["time"].dt.date
    df["typ"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]    = df["typ"] * df["volume"]
    df["cpv"]   = df.groupby("date")["pv"].cumsum()
    df["cvol"]  = df.groupby("date")["volume"].cumsum()
    df["vwap"]  = df["cpv"] / df["cvol"]
    df["rsi2"]  = calc_rsi2(df["close"])
    df["dist"]  = (df["vwap"] - df["close"]) / df["vwap"]   # positive = below VWAP
    return df


def sim_exit_vwap(ddf, ei, ep, sl, side, vwap_arr):
    """Exit on VWAP touch, fixed TP, or SL."""
    mi = min(ei + TIME_STOP, len(ddf) - 1)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    mfe = mae = 0.0; et = "time"; xp = C[mi]
    tp_fixed = ep * (1 + TP_FIXED) if side == "long" else ep * (1 - TP_FIXED)
    sl_price = ep * (1 - SL_PCT)   if side == "long" else ep * (1 + SL_PCT)

    for j in range(ei, mi + 1):
        vw = vwap_arr[j]
        if side == "long":
            mfe = max(mfe, (H[j] - ep) / ep * 100)
            mae = max(mae, (ep - L[j]) / ep * 100)
            if L[j] <= sl_price:                  et = "sl";   xp = sl_price; break
            if H[j] >= tp_fixed:                  et = "tp";   xp = tp_fixed; break
            if H[j] >= vw and not pd.isna(vw):    et = "vwap"; xp = vw;       break
        else:
            mfe = max(mfe, (ep - L[j]) / ep * 100)
            mae = max(mae, (H[j] - ep) / ep * 100)
            if H[j] >= sl_price:                  et = "sl";   xp = sl_price; break
            if L[j] <= tp_fixed:                  et = "tp";   xp = tp_fixed; break
            if L[j] <= vw and not pd.isna(vw):    et = "vwap"; xp = vw;       break

    pnl = (xp - ep) / ep * 100 if side == "long" else (ep - xp) / ep * 100
    return et, pnl, mfe, mae


def run(df):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        vwap_arr = ddf["vwap"].values
        lc = sc = 0; lcd = scd = None

        for i in range(1, len(ddf) - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:55"): continue
            if pd.isna(row["vwap"]) or pd.isna(row["rsi2"]): continue

            nd   = row["time"]
            dist = abs(row["dist"])

            # Long: below VWAP, RSI2 < 5, stretched > 0.40%
            if (lc < MAX_TRADES and (lcd is None or nd >= lcd) and
                    row["close"] < row["vwap"] and
                    row["rsi2"]  < 5 and
                    dist > MIN_DIST):
                ep = ddf.iloc[i + 1]["open"]
                et, pnl, mfe, mae = sim_exit_vwap(ddf, i+1, ep, None, "long", vwap_arr)
                trades.append({"date": str(date), "side": "long",
                               "et": et, "pnl": pnl, "mfe": mfe, "mae": mae,
                               "dist_entry": dist * 100})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            # Short: above VWAP, RSI2 > 95, stretched > 0.40%
            if (sc < MAX_TRADES and (scd is None or nd >= scd) and
                    row["close"] > row["vwap"] and
                    row["rsi2"]  > 95 and
                    dist > MIN_DIST):
                ep = ddf.iloc[i + 1]["open"]
                et, pnl, mfe, mae = sim_exit_vwap(ddf, i+1, ep, None, "short", vwap_arr)
                trades.append({"date": str(date), "side": "short",
                               "et": et, "pnl": pnl, "mfe": mfe, "mae": mae,
                               "dist_entry": dist * 100})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)

    return trades


def report(trades, label):
    if not trades:
        print(f"\n{label}: No trades"); return
    df    = pd.DataFrame(trades)
    wins  = df[df["et"].isin(["tp", "vwap"])]["pnl"]
    loss  = df[df["et"] == "sl"]["pnl"]
    time_ = df[df["et"] == "time"]
    total_pnl = df["pnl"].sum()
    wr    = len(wins) / len(df) * 100
    pf    = wins.sum() / abs(loss.sum()) if len(loss) and loss.sum() != 0 else 0
    tpd   = len(df) / df["date"].nunique()

    S = "=" * 65
    print(f"\n{S}\n  {label}\n{S}")
    print(f"  Trades:{len(df):>4}  Days:{df['date'].nunique():>4}  TPD:{tpd:.1f}  WR:{wr:.1f}%  PF:{pf:.2f}")
    print(f"  Total PnL: {total_pnl:+.3f}%")
    print(f"\n  EXIT BREAKDOWN")
    vwap_exits = df[df["et"] == "vwap"]
    tp_exits   = df[df["et"] == "tp"]
    print(f"    VWAP touch : {len(vwap_exits):>4}  AvgPnL={vwap_exits['pnl'].mean():.4f}%" if len(vwap_exits) else "    VWAP touch :    0")
    print(f"    Fixed TP   : {len(tp_exits):>4}  AvgPnL={tp_exits['pnl'].mean():.4f}%"   if len(tp_exits)   else "    Fixed TP   :    0")
    print(f"    SL         : {len(loss):>4}  AvgPnL={loss.mean():.4f}%"                  if len(loss)       else "    SL         :    0")
    print(f"    Time stop  : {len(time_):>4}  AvgPnL={time_['pnl'].mean():.4f}%"           if len(time_)      else "    Time stop  :    0")
    print(f"\n  WINNERS ({len(wins)})")
    if len(wins):
        print(f"    Avg Win      : +{wins.mean():.4f}%")
        print(f"    Median Win   : +{wins.median():.4f}%")
        print(f"    Largest Win  : +{wins.max():.4f}%")
    print(f"\n  LOSERS ({len(df) - len(wins)})")
    non_wins = df[~df["et"].isin(["tp","vwap"])]["pnl"]
    if len(non_wins):
        print(f"    Avg Loss     :  {non_wins.mean():.4f}%")
        print(f"    Median Loss  :  {non_wins.median():.4f}%")
        print(f"    Largest Loss :  {non_wins.min():.4f}%")
    print(f"\n  EXCURSION")
    print(f"    Avg MFE      : +{df['mfe'].mean():.4f}%")
    print(f"    Avg MAE      :  {df['mae'].mean():.4f}%")
    print(f"    Avg Entry Dist: {df['dist_entry'].mean():.4f}%")
    print(f"\n  BY SIDE")
    for side in ["long", "short"]:
        s = df[df["side"] == side]
        if s.empty: continue
        sw = s[s["et"].isin(["tp","vwap"])]
        print(f"    {side.upper():5}  N={len(s)}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():.4f}%  AvgMFE={s['mfe'].mean():.4f}%  AvgMAE={s['mae'].mean():.4f}%")


def monthly_report(trades, sym):
    if not trades: return
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    S = "="*75
    print(f"\n{S}")
    print(f"  {sym} | Monthly Breakdown")
    print(f"{S}")
    print(f"  {'Month':<10} {'N':>5} {'WR%':>6} {'PF':>6} {'TotPnL':>9} {'AvgPnL':>8} {'TPD':>5}")
    print(f"  {'-'*65}")
    for month, mdf in df.groupby("month"):
        wins = mdf[mdf["et"].isin(["tp","vwap"])]["pnl"]
        loss = mdf[mdf["et"]=="sl"]["pnl"]
        wr   = len(wins)/len(mdf)*100
        pf   = wins.sum()/abs(loss.sum()) if len(loss) and loss.sum()!=0 else 0
        tot  = mdf["pnl"].sum()
        avg  = mdf["pnl"].mean()
        tpd  = len(mdf)/mdf["date"].nunique()
        print(f"  {str(month):<10} {len(mdf):>5} {wr:>6.1f} {pf:>6.2f} {tot:>9.3f} {avg:>8.4f} {tpd:>5.1f}")
    wins_all = df[df["et"].isin(["tp","vwap"])]["pnl"]
    loss_all = df[df["et"]=="sl"]["pnl"]
    pf_all   = wins_all.sum()/abs(loss_all.sum()) if len(loss_all) and loss_all.sum()!=0 else 0
    print(f"  {'-'*65}")
    print(f"  {'TOTAL':<10} {len(df):>5} {len(wins_all)/len(df)*100:>6.1f} {pf_all:>6.2f} {df['pnl'].sum():>9.3f} {df['pnl'].mean():>8.4f} {len(df)/df['date'].nunique():>5.1f}")


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    for sym in SYMBOLS:
        df = pd.read_csv(f"boof51_{sym}_1m.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_1m(df)
        df = df.dropna(subset=["vwap", "rsi2"])
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

        trades = run(df)
        report(trades, f"{sym} | Mean Reversion | RSI2<5/>95 | dist>0.40% | TP0.25/SL0.40")
        monthly_report(trades, sym)
