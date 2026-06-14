# BOOF31 standalone backtest — all day, 1m bars
# Uses actual deployed logic: pivot zones + trend score + volume conditions
# Score >= 3 for core universe (matches BOOF31_LIVE_DEPLOY.py)

import os
import pandas as pd
import numpy as np

# Core universe — same as deployed bot (score >= 3)
CORE_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "META", "AMZN",
    "PLTR", "HOOD", "CRWD", "AVGO", "TSLA", "SOFI",
]

# Extended universe — higher score threshold (>= 6)
EXTENDED_UNIVERSE = [
    "ZS", "NET", "DDOG", "MDB", "PANW",
    "COIN", "MU", "QCOM", "MRVL", "APP", "SMCI", "NFLX",
]

PIVOT_LOOKBACK  = 5
ZONE_TOL        = 0.002
VOL_LOOKBACK    = 20
COOLDOWN_BARS   = 30
MAX_HOLD_BARS   = 30
TREND_SCORE_MIN_CORE = 3
TREND_SCORE_MIN_EXT  = 6
TP              = 0.005
SL              = 0.004
SLIPPAGE        = 0.0002

START_UTC = "14:30"
END_UTC   = "21:00"


def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]      = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["vol_avg"]   = day["volume"].rolling(VOL_LOOKBACK).mean()
    day["rvol"]      = day["volume"] / day["vol_avg"]
    day["vwap_slope"] = day["vwap"].pct_change(5)
    return day


def find_pivots(day):
    lb = PIVOT_LOOKBACK
    ph = np.zeros(len(day), dtype=bool)
    pl = np.zeros(len(day), dtype=bool)
    highs = day["high"].values
    lows  = day["low"].values
    for i in range(lb, len(day) - lb):
        if highs[i] == highs[i-lb:i+lb+1].max():
            ph[i] = True
        if lows[i] == lows[i-lb:i+lb+1].min():
            pl[i] = True
    day = day.copy()
    day["pivot_high"] = ph
    day["pivot_low"]  = pl
    return day


def recent_pivots(day, i, lookback=40):
    chunk = day.iloc[max(0, i - lookback):i]
    highs = chunk[chunk["pivot_high"] == True]
    lows  = chunk[chunk["pivot_low"]  == True]
    return highs, lows


def is_near_zone(price, prices):
    for p in prices:
        if abs(price - p) / p <= ZONE_TOL:
            return True
    return False


def trend_score_short(day, i, highs, lows):
    score = 0
    if len(highs) >= 2:
        if highs["high"].iloc[-1] < highs["high"].iloc[-2]:
            score += 1
    if len(lows) >= 2:
        if lows["low"].iloc[-1] < lows["low"].iloc[-2]:
            score += 1
    if day["close"].iloc[i] < day["vwap"].iloc[i]:
        score += 1
    if day["vwap_slope"].iloc[i] < 0:
        score += 1
    return score


def detect_short(day, i, min_score):
    if i < 40:
        return False
    highs, lows = recent_pivots(day, i)
    score = trend_score_short(day, i, highs, lows)
    if score < min_score:
        return False
    res_prices = highs["high"].values if len(highs) else []
    near_res = is_near_zone(day["high"].iloc[i], res_prices)
    if not near_res:
        return False
    vol_avg = day["vol_avg"].iloc[i]
    if pd.isna(vol_avg) or vol_avg <= 0:
        return False
    pullback_dry     = day["volume"].iloc[i-1] < day["vol_avg"].iloc[i-1]
    rejection_volume = day["volume"].iloc[i] > vol_avg
    red_candle       = day["close"].iloc[i] < day["open"].iloc[i]
    return pullback_dry and rejection_volume and red_candle


def exit_short(future, entry_price):
    for _, bar in future.iterrows():
        loss = (bar["high"] - entry_price) / entry_price
        gain = (entry_price - bar["low"]) / entry_price
        if loss >= SL:
            return -SL - SLIPPAGE * 2
        if gain >= TP:
            return TP - SLIPPAGE * 2
    final = (entry_price - future.iloc[-1]["close"]) / entry_price
    return final - SLIPPAGE * 2


def run():
    all_trades = []
    all_symbols = list(set(CORE_UNIVERSE + EXTENDED_UNIVERSE))

    for symbol in all_symbols:
        cache_file = f"boof32_data_{symbol}.csv"
        if not os.path.exists(cache_file):
            print(f"  {symbol}: no cache, skipping")
            continue

        is_core   = symbol in CORE_UNIVERSE
        min_score = TREND_SCORE_MIN_CORE if is_core else TREND_SCORE_MIN_EXT

        df = pd.read_csv(cache_file, parse_dates=["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["date"]     = df["datetime"].dt.date
        df["time_utc"] = df["datetime"].dt.strftime("%H:%M")

        for date, day in df.groupby("date"):
            day = day.copy().reset_index(drop=True)
            if len(day) < 150:
                continue
            day = add_indicators(day)
            day = find_pivots(day)
            last_i = -999999

            for i in range(PIVOT_LOOKBACK + 40, len(day) - MAX_HOLD_BARS - 2):
                t = day["time_utc"].iloc[i]
                if not (START_UTC <= t < END_UTC):
                    continue
                if i - last_i < COOLDOWN_BARS:
                    continue
                if not detect_short(day, i, min_score):
                    continue
                entry_i = i + 1
                if entry_i >= len(day):
                    continue
                entry_price = day["open"].iloc[entry_i] * (1 - SLIPPAGE)
                future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
                if future.empty:
                    continue
                pnl = exit_short(future, entry_price)
                all_trades.append(dict(
                    symbol=symbol, date=date, pnl=pnl,
                    universe="core" if is_core else "ext"
                ))
                last_i = i

        sym_trades = [t for t in all_trades if t["symbol"] == symbol]
        print(f"  {symbol} ({'core' if is_core else 'ext '}): {len(sym_trades)} trades")

    df_t = pd.DataFrame(all_trades)
    if df_t.empty:
        print("No trades found.")
        return

    def print_metrics(label, subset):
        if subset.empty:
            return
        pnls   = subset["pnl"]
        wins   = (pnls > 0).sum()
        gw     = pnls[pnls > 0].sum()
        gl     = abs(pnls[pnls < 0].sum())
        pf     = gw / gl if gl > 0 else float("inf")
        n_days = subset["date"].nunique()
        tpd    = len(subset) / n_days

        daily        = subset.groupby("date")["pnl"].sum()
        worst_day    = daily.min()
        worst_date   = daily.idxmin()

        subset = subset.copy()
        subset["week"] = pd.to_datetime(subset["date"].astype(str)).dt.to_period("W")
        weekly       = subset.groupby("week")["pnl"].sum()
        worst_week   = weekly.min()
        worst_week_p = weekly.idxmin()

        cumul  = pnls.cumsum()
        max_dd = (cumul - cumul.cummax()).min()

        streak = max_streak = 0
        for p in pnls:
            if p < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        print(f"\n  {'─'*50}")
        print(f"  {label}")
        print(f"  {'─'*50}")
        print(f"  Trades:          {len(pnls)}  ({tpd:.2f}/day over {n_days} days)")
        print(f"  Win Rate:        {wins/len(pnls):.1%}")
        print(f"  Profit Factor:   {pf:.2f}")
        print(f"  EV/trade:        {pnls.mean():.4%}")
        print(f"  Total PnL:       {pnls.sum():.2%}")
        print(f"  Max Drawdown:    {max_dd:.2%}")
        print(f"  Worst Day:       {worst_day:.2%}  ({worst_date})")
        print(f"  Worst Week:      {worst_week:.2%}  ({worst_week_p})")
        print(f"  Max Loss Streak: {max_streak} trades")

    print(f"\n{'='*55}")
    print(f"  BOOF31  All Day  (9:30-4:00 ET, 6mo, 1m bars)")
    print(f"  Pivot zones + Trend score + Volume — DEPLOYED LOGIC")
    print(f"{'='*55}")

    print_metrics("CORE universe  (score >= 3)", df_t[df_t["universe"] == "core"])
    print_metrics("EXTENDED universe  (score >= 6)", df_t[df_t["universe"] == "ext"])
    print_metrics("COMBINED", df_t)

    print(f"\n{'='*55}")
    print(f"  PER-SYMBOL  (ranked by PF)")
    print(f"{'='*55}")
    print(f"  {'Symbol':<6}  {'U':<4}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    rows = []
    for sym, g in df_t.groupby("symbol"):
        x = g["pnl"]
        w = (x > 0).sum()
        gw2 = x[x > 0].sum()
        gl2 = abs(x[x < 0].sum())
        pf2 = gw2 / gl2 if gl2 > 0 else float("inf")
        u = g["universe"].iloc[0]
        rows.append((sym, u, len(x), w/len(x), pf2, x.mean()))
    for sym, u, n, wr, pf2, ev in sorted(rows, key=lambda r: -r[4]):
        print(f"  {sym:<6}  {u:<4}  {n:4d}  {wr:6.1%}  {pf2:5.2f}  {ev:9.4%}")


if __name__ == "__main__":
    run()
