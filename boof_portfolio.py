"""
Combined Portfolio Backtest: BOOF31 (short) + BOOF33 (long)
Metrics: Combined PF, Max Drawdown, Worst Day, Worst Week,
         Max Loss Streak, Trades/Day
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import time as time_mod

API_KEY    = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

# ── BOOF33 Universe (long) ─────────────────────────────────────
B33_SYMBOLS = [
    "FCX", "NEM", "MU", "SCCO", "KLAC", "PANW",
    "TSLA", "CRWD", "QCOM", "HOOD", "TER", "CORZ",
    "APP", "DDOG", "COIN", "MDB", "NET", "ZS",
]

# ── BOOF31 Universe (short) ────────────────────────────────────
B31_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "AMD", "NFLX",
    "CRWD", "ZS", "NET", "DDOG", "MDB", "PLTR", "PANW",
    "COIN", "MU", "QCOM", "MRVL", "HOOD", "APP", "SMCI",
]

ALL_SYMBOLS = list(set(B33_SYMBOLS + B31_SYMBOLS))

# ── Shared parameters ──────────────────────────────────────────
LOOKBACK      = 80
SUPPORT_TOL   = 0.002
SWEEP_BUFFER  = 0.001
COOLDOWN_BARS = 30
MAX_HOLD_BARS = 60
SLIPPAGE      = 0.0002

# BOOF33 (long) exit params
B33_TP1 = 0.005
B33_TP2 = 0.015
B33_SL  = 0.003

# BOOF31 (short) exit params
B31_TP1       = 0.005
B31_TP2       = 0.015
B31_SL        = 0.003
B31_SWEEP_BUF = 0.002
B31_RES_TOL   = 0.002
B31_MIN_SCORE = 4
B31_MAX_CONFIRM = 5

# Time windows UTC
B33_START = "15:30"
B33_END   = "16:30"
B31_START = "14:30"  # 9:30 ET (market open)
B31_END   = "21:00"  # 4:00 PM ET (market close)


# ── Data fetching ──────────────────────────────────────────────
def fetch_data(symbol):
    cache_file = f'boof32_data_{symbol}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=['datetime'])
    print(f"  Fetching {symbol}...")
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end   = datetime.now()
    start = end - timedelta(days=182)
    req   = StockBarsRequest(symbol_or_symbols=symbol,
                             timeframe=TimeFrame.Minute,
                             start=start, end=end)
    for attempt in range(5):
        try:
            bars = client.get_stock_bars(req)
            df = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level='symbol')
            df = df.reset_index().rename(columns={'timestamp': 'datetime'})
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.sort_values('datetime').reset_index(drop=True)
            df.to_csv(cache_file, index=False)
            print(f"  Saved {len(df):,} bars")
            return df
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  {symbol} retry {attempt+1}: {e.__class__.__name__}, waiting {wait}s")
            time_mod.sleep(wait)
    print(f"  {symbol}: all retries failed")
    return None


# ── Indicators ─────────────────────────────────────────────────
def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]       = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["avg_vol_20"] = day["volume"].rolling(20).mean()
    return day


# ── BOOF33: Support sweep/reclaim long ─────────────────────────
def find_support(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 30:
        return None, 0
    lows = window["low"].values
    best_level, best_touches = None, 0
    for low in lows:
        touches = np.sum(np.abs(lows - low) / low <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = low, touches
    if best_touches < 2:
        return None, 0
    return best_level, best_touches


def detect_b33(day, i):
    support, _ = find_support(day, i)
    if support is None:
        return False, {}
    bar = day.iloc[i]
    if (bar["low"]   < support * (1 - SWEEP_BUFFER) and
            bar["close"] > support and
            bar["close"] < bar["vwap"]):
        return True, {"entry_i": i + 1}
    return False, {}


def exit_b33(future, entry_price):
    """Long: 50% at TP1, runner to TP2, BE stop after TP1."""
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        hm = (bar["high"]  - entry_price) / entry_price
        lm = (bar["low"]   - entry_price) / entry_price
        if not half_out and lm <= -B33_SL:
            return -B33_SL - SLIPPAGE * 2
        if half_out and bar["close"] <= entry_price:
            return pnl - SLIPPAGE * 2
        if not half_out and hm >= B33_TP1:
            pnl += 0.5 * B33_TP1
            half_out = True
        if half_out and hm >= B33_TP2:
            pnl += 0.5 * B33_TP2
            return pnl - SLIPPAGE * 2
    final = (future.iloc[-1]["close"] - entry_price) / entry_price
    if half_out:
        pnl += 0.5 * final
        return pnl - SLIPPAGE * 2
    return final - SLIPPAGE * 2


# ── BOOF31: Resistance sweep/breakdown short ───────────────────
def find_resistance(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 20:
        return None, 0
    highs = window["high"].values
    best_level, best_touches = None, 0
    for h in highs:
        touches = np.sum(np.abs(highs - h) / h <= B31_RES_TOL)
        if touches > best_touches:
            best_touches = touches
            best_level = h
    if best_touches < 2:
        return None, 0
    return best_level, best_touches


def score_b31(day, sweep_i, break_i, resistance, touches):
    score = 0
    sweep_bar = day.iloc[sweep_i]
    break_bar = day.iloc[break_i]
    avg_vol = day["avg_vol_20"].iloc[break_i]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return 0
    if sweep_bar["volume"] > avg_vol:
        score += 1
    if break_bar["volume"] > avg_vol:
        score += 1
    upper_wick = sweep_bar["high"] - max(sweep_bar["open"], sweep_bar["close"])
    body = abs(sweep_bar["close"] - sweep_bar["open"])
    if body > 0 and upper_wick > body * 1.5:
        score += 1
    if sweep_bar["close"] < sweep_bar["open"]:
        score += 1
    if sweep_bar["close"] < resistance:
        score += 1
    if touches >= 3:
        score += 1
    if 0 <= break_i - sweep_i <= B31_MAX_CONFIRM:
        score += 1
    return score


def detect_b31(day, i):
    resistance, touches = find_resistance(day, i)
    if resistance is None:
        return False, {}
    bar = day.iloc[i]
    swept = bar["high"] > resistance * (1 + B31_SWEEP_BUF)
    closed_below = bar["close"] < resistance
    if not (swept and closed_below):
        return False, {}
    swing_low = day["low"].iloc[max(0, i - 20):i].min()
    for j in range(i + 1, min(i + 1 + B31_MAX_CONFIRM, len(day) - 1)):
        if day["close"].iloc[j] < swing_low:
            score = score_b31(day, i, j, resistance, touches)
            if score >= B31_MIN_SCORE:
                return True, {"entry_i": j + 1}
    return False, {}


def exit_b31(future, entry_price):
    """Short: 50% at TP1, runner to TP2, BE stop after TP1."""
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        hm = (entry_price - bar["low"])  / entry_price   # short: profit on down
        lm = (bar["high"] - entry_price) / entry_price   # short: loss on up
        if not half_out and lm >= B31_SL:
            return -B31_SL - SLIPPAGE * 2
        if half_out and bar["close"] >= entry_price:
            return pnl - SLIPPAGE * 2
        if not half_out and hm >= B31_TP1:
            pnl += 0.5 * B31_TP1
            half_out = True
        if half_out and hm >= B31_TP2:
            pnl += 0.5 * B31_TP2
            return pnl - SLIPPAGE * 2
    final = (entry_price - future.iloc[-1]["close"]) / entry_price
    if half_out:
        pnl += 0.5 * final
        return pnl - SLIPPAGE * 2
    return final - SLIPPAGE * 2


# ── Portfolio metrics ──────────────────────────────────────────
def portfolio_metrics(trades_df):
    if trades_df.empty:
        return {}

    trades_df = trades_df.sort_values("date")
    pnls = trades_df["pnl"]

    # Basic
    wins    = (pnls > 0).sum()
    gross_w = pnls[pnls > 0].sum()
    gross_l = abs(pnls[pnls < 0].sum())
    pf      = gross_w / gross_l if gross_l > 0 else float("inf")
    ev      = pnls.mean()
    wr      = wins / len(pnls)

    # Trades/day
    n_days = trades_df["date"].nunique()
    tpd    = len(trades_df) / n_days if n_days else 0

    # Daily P&L
    daily = trades_df.groupby("date")["pnl"].sum()

    # Worst day / worst week
    worst_day = daily.min()
    worst_day_date = daily.idxmin()

    trades_df["week"] = pd.to_datetime(trades_df["date"].astype(str)).dt.to_period("W")
    weekly = trades_df.groupby("week")["pnl"].sum()
    worst_week     = weekly.min()
    worst_week_per = weekly.idxmin()

    # Max drawdown (cumulative)
    cumulative = pnls.cumsum()
    rolling_max = cumulative.cummax()
    drawdown = cumulative - rolling_max
    max_dd = drawdown.min()

    # Max loss streak
    streak = 0
    max_streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return dict(
        n=len(pnls), n_days=n_days, tpd=tpd,
        wr=wr, pf=pf, ev=ev,
        worst_day=worst_day, worst_day_date=worst_day_date,
        worst_week=worst_week, worst_week_per=str(worst_week_per),
        max_dd=max_dd, max_loss_streak=max_streak,
        total_pnl=pnls.sum(),
    )


# ── Scan one symbol for one strategy ──────────────────────────
def scan_symbol(symbol, strategy):
    cache_file = f"boof32_data_{symbol}.csv"
    if not os.path.exists(cache_file):
        return []

    df = pd.read_csv(cache_file, parse_dates=["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df["date"]     = df["datetime"].dt.date
    df["time_utc"] = df["datetime"].dt.strftime("%H:%M")

    start_utc = B33_START if strategy == "b33" else B31_START
    end_utc   = B33_END   if strategy == "b33" else B31_END

    trades = []
    for date, day in df.groupby("date"):
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_i = -999999

        for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - 2):
            t = day["time_utc"].iloc[i]
            if not (start_utc <= t < end_utc):
                continue
            if i - last_i < COOLDOWN_BARS:
                continue

            if strategy == "b33":
                found, sig = detect_b33(day, i)
            else:
                found, sig = detect_b31(day, i)

            if not found:
                continue

            entry_i = sig["entry_i"]
            if entry_i >= len(day):
                continue

            if strategy == "b33":
                entry_price = day["open"].iloc[entry_i] * (1 + SLIPPAGE)
            else:
                entry_price = day["open"].iloc[entry_i] * (1 - SLIPPAGE)

            future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
            if future.empty:
                continue

            if strategy == "b33":
                pnl = exit_b33(future, entry_price)
            else:
                pnl = exit_b31(future, entry_price)

            trades.append(dict(symbol=symbol, date=date,
                               strategy=strategy, pnl=pnl))
            last_i = i

    return trades


# ── Main ───────────────────────────────────────────────────────
def run():
    for sym in ALL_SYMBOLS:
        fetch_data(sym)

    all_trades = []

    print("\nScanning BOOF33 (long)...")
    for sym in B33_SYMBOLS:
        t = scan_symbol(sym, "b33")
        print(f"  {sym}: {len(t)} trades")
        all_trades.extend(t)

    print("\nScanning BOOF31 (short)...")
    for sym in B31_SYMBOLS:
        t = scan_symbol(sym, "b31")
        print(f"  {sym}: {len(t)} trades")
        all_trades.extend(t)

    df = pd.DataFrame(all_trades)
    df.to_csv("boof_portfolio_trades.csv", index=False)

    b33_df   = df[df["strategy"] == "b33"]
    b31_df   = df[df["strategy"] == "b31"]
    combo_df = df.copy()

    def print_metrics(label, m):
        print(f"\n  {'─'*50}")
        print(f"  {label}")
        print(f"  {'─'*50}")
        print(f"  Trades:          {m['n']}  ({m['tpd']:.2f}/day over {m['n_days']} days)")
        print(f"  Win Rate:        {m['wr']:.1%}")
        print(f"  Profit Factor:   {m['pf']:.2f}")
        print(f"  EV/trade:        {m['ev']:.4%}")
        print(f"  Total PnL:       {m['total_pnl']:.2%}")
        print(f"  Max Drawdown:    {m['max_dd']:.2%}")
        print(f"  Worst Day:       {m['worst_day']:.2%}  ({m['worst_day_date']})")
        print(f"  Worst Week:      {m['worst_week']:.2%}  ({m['worst_week_per']})")
        print(f"  Max Loss Streak: {m['max_loss_streak']} trades")

    print(f"\n{'='*55}")
    print(f"  COMBINED PORTFOLIO BACKTEST  (9:30-10:30 ET, 6mo)")
    print(f"{'='*55}")

    if not b33_df.empty:
        print_metrics("BOOF33  (Long — Support Sweep Reclaim)", portfolio_metrics(b33_df))
    if not b31_df.empty:
        print_metrics("BOOF31  (Short — Resistance Sweep Breakdown)", portfolio_metrics(b31_df))
    if not combo_df.empty:
        print_metrics("COMBINED PORTFOLIO", portfolio_metrics(combo_df))

    # Per-symbol breakdown
    print(f"\n{'='*55}")
    print(f"  PER-SYMBOL BREAKDOWN")
    print(f"{'='*55}")
    print(f"  {'Symbol':<6}  {'Strat':<5}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    sym_rows = []
    for (sym, strat), g in df.groupby(["symbol", "strategy"]):
        x = g["pnl"]
        wins = (x > 0).sum()
        gw = x[x > 0].sum()
        gl = abs(x[x < 0].sum())
        pf_v = gw / gl if gl > 0 else float("inf")
        sym_rows.append((sym, strat, len(x), wins/len(x), pf_v, x.mean()))
    sym_rows.sort(key=lambda r: r[4], reverse=True)
    for sym, strat, n, wr, pf_v, ev in sym_rows:
        print(f"  {sym:<6}  {strat:<5}  {n:4d}  {wr:6.1%}  {pf_v:5.2f}  {ev:9.4%}")

    print(f"\nTrades saved to boof_portfolio_trades.csv")


if __name__ == "__main__":
    run()
