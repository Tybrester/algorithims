import os
import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SYMBOL        = "MU"
API_KEY       = "AKPDLKERTEC2OG42UROO65QMW7"
API_SECRET    = "MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM"
LOOKBACK      = 80
SUPPORT_TOL   = 0.002
SWEEP_BUFFER  = 0.001
COOLDOWN_BARS = 30
MAX_HOLD_BARS = 60
SLIPPAGE      = 0.0002
START_UTC     = "15:30"
END_UTC       = "16:30"

TP1    = 0.005
RUNNER = 0.015
STOP   = 0.003


def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]       = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["avg_vol_20"] = day["volume"].rolling(20).mean()
    day["rvol"]       = day["volume"] / day["avg_vol_20"]
    day["vwap_slope"] = day["vwap"].pct_change(5) * 100
    return day


def find_support(lows):
    best_level, best_touches = None, 0
    for low in lows:
        touches = np.sum(np.abs(lows - low) / low <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = low, touches
    return (best_level, best_touches) if best_touches >= 2 else (None, 0)


def simulate(future, entry_price):
    half_out = False
    pnl = 0.0
    ep = entry_price
    for _, bar in future.iterrows():
        move_h = (bar["high"]  - ep) / ep
        move_l = (bar["low"]   - ep) / ep
        if not half_out:
            if move_l <= -STOP: return -STOP - SLIPPAGE * 2
            if move_h >= TP1:   half_out = True; pnl += TP1 * 0.5
        if half_out:
            if bar["low"] <= ep:        return pnl - SLIPPAGE * 2
            if move_h >= RUNNER:        pnl += RUNNER * 0.5; return pnl - SLIPPAGE * 2
    final = (future.iloc[-1]["close"] - ep) / ep
    return (pnl + final * 0.5 - SLIPPAGE * 2) if half_out else (final - SLIPPAGE * 2)


def load_data():
    cache = f"boof32_data_{SYMBOL}.csv"
    df = pd.read_csv(cache, dtype_backend="numpy_nullable")
    if "datetime" in df.columns: df = df.rename(columns={"datetime": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    for col in ["open","high","low","close","volume"]: df[col] = df[col].astype(float)
    for col in ["vwap","trade_count"]:
        if col in df.columns: df = df.drop(columns=[col])
    df = df.sort_values("timestamp").reset_index(drop=True)

    earliest = df["timestamp"].min()
    target_start = pd.Timestamp("2025-06-13", tz="America/New_York")
    if earliest > target_start:
        print(f"Cache starts {earliest.date()}, fetching back to {target_start.date()}...")
        client = StockHistoricalDataClient(API_KEY, API_SECRET)
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOL,
            timeframe=TimeFrame.Minute,
            start=target_start,
            end=earliest,
            feed="sip"
        )
        bars = client.get_stock_bars(req).df
        if not bars.empty:
            if isinstance(bars.index, pd.MultiIndex): bars = bars.reset_index()
            bars["timestamp"] = pd.to_datetime(bars["timestamp"]).dt.tz_convert("America/New_York")
            for col in ["vwap","trade_count"]:
                if col in bars.columns: bars = bars.drop(columns=[col])
            df = pd.concat([bars, df], ignore_index=True)
            df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
            print(f"Extended to {df['timestamp'].min().date()} — {len(df)} bars total")

    df["date"]     = df["timestamp"].dt.date
    df["time_utc"] = df["timestamp"].dt.strftime("%H:%M")
    df["month"]    = df["timestamp"].dt.to_period("M")
    return df


df = load_data()
print(f"{SYMBOL}  {df['timestamp'].min().date()} -> {df['timestamp'].max().date()}  ({len(df)} bars)\n")

months = sorted(df["month"].unique())
all_rows = []

for month in months:
    mdf = df[df["month"] == month].copy().reset_index(drop=True)
    trades = []
    for date, day in mdf.groupby("date"):
        day = day.copy().reset_index(drop=True)
        if len(day) < 150: continue
        day = add_indicators(day)
        last_i = -999999
        for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - 2):
            t = day["time_utc"].iloc[i]
            if not (START_UTC <= t < END_UTC): continue
            if i - last_i < COOLDOWN_BARS: continue
            bar = day.iloc[i]
            win = day.iloc[max(0, i - LOOKBACK):i]
            sup, _ = find_support(win["low"].values)
            if sup is None: continue
            if (bar["low"]   < sup * (1 - SWEEP_BUFFER) and
                    bar["close"] > sup and
                    bar["close"] < bar["vwap"]):
                entry_i = i + 1
                if entry_i >= len(day): continue
                future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
                if future.empty: continue
                ep = day["open"].iloc[entry_i] * (1 + SLIPPAGE)
                pnl = simulate(future, ep)
                trades.append(pnl)
                last_i = i

    if not trades:
        print(f"  {month}:  no trades")
        continue

    x = pd.Series(trades)
    wins   = x[x > 0]; losses = x[x < 0]
    gw     = wins.sum(); gl = abs(losses.sum())
    pf     = gw / gl if gl > 0 else float("inf")
    cum    = x.cumsum()
    max_dd = (cum - cum.cummax()).min()
    streak = worst = 0
    for v in x:
        if v < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0

    all_rows.append(dict(month=str(month), n=len(x), wr=len(wins)/len(x),
                         pf=pf, ev=x.mean(), total=x.sum(), max_dd=max_dd, worst_streak=worst))

    flag = " ✓" if pf >= 1.20 else ""
    print(f"  {month}  n={len(x):2d}  WR={len(wins)/len(x):5.1%}  PF={pf:5.2f}  "
          f"EV={x.mean():+.4%}  Total={x.sum():+.2%}  MaxDD={max_dd:.2%}  Streak={worst}{flag}")

out = pd.DataFrame(all_rows)
print(f"\n{'='*80}")
print(f"  SUMMARY  ({len(out)} months)")
print(f"{'='*80}")
print(f"  Profitable months: {(out['pf']>=1.0).sum()}/{len(out)}")
print(f"  Avg PF:            {out['pf'].mean():.2f}")
print(f"  Avg WR:            {out['wr'].mean():.1%}")
print(f"  Total trades:      {out['n'].sum()}")
print(f"  Total PnL:         {out['total'].sum():+.2%}")
print(f"  Worst month:       {out.loc[out['total'].idxmin(),'month']}  {out['total'].min():+.2%}")
print(f"  Best month:        {out.loc[out['total'].idxmax(),'month']}  {out['total'].max():+.2%}")
out.to_csv("mu_monthly_results.csv", index=False)
print(f"\nSaved: mu_monthly_results.csv")
