"""
BOOF31 Real Backtest — exact live bot logic on real Alpaca cached data
- Pivot zones + trend score + volume conditions
- Core universe: score >= 3
- Extended universe: score >= 6
- Real cached 1m bars, no synthetic data
"""

import os
import time as time_mod
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

API_KEY    = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

CORE_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX",
    "CRM", "NOW", "SNOW", "PLTR", "DDOG", "MDB", "CRWD", "ZS", "NET", "SHOP",
    "ADBE", "INTU", "PANW", "TEAM", "HUBS", "UBER", "ABNB", "BKNG", "RBLX", "DASH",
    "JPM", "GS", "MS", "AXP", "SCHW", "BLK", "SPGI",
]

EXTENDED_UNIVERSE = [
    "MELI", "ETSY", "LLY", "NVO", "ISRG", "VRTX", "REGN", "MRNA", "GILD",
    "RTX", "BA", "CAT", "DE", "ETN", "PH", "TT",
    "XOM", "CVX", "COP", "SLB", "HAL", "OXY", "EOG", "MPC",
    "TMUS", "ROKU", "SPOT", "PINS", "SNAP", "RDDT", "COIN",
    "HUT", "MARA", "RIOT", "CLSK",
    "MSTR", "HOOD", "APP", "SMCI", "ARM", "MU", "QCOM", "MRVL", "TSM", "ASML",
    "AMAT", "LRCX", "KLAC", "MCHP", "ON", "NXPI",
]

ALL_SYMBOLS = CORE_UNIVERSE + EXTENDED_UNIVERSE

PIVOT_LB   = 5
ZONE_TOL   = 0.003
VOL_LB     = 20
COOLDOWN   = 30
MAX_HOLD   = 30
TP         = 0.005
SL         = 0.004
SLIPPAGE   = 0.0002
SCORE_CORE = 3
SCORE_EXT  = 3


def fetch_or_load(symbol):
    cache = f"boof32_data_{symbol}.csv"
    if os.path.exists(cache):
        df = pd.read_csv(cache, dtype_backend='numpy_nullable')
        if 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'timestamp'})
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        for col in ['open','high','low','close','volume']:
            if col in df.columns:
                df[col] = df[col].astype(float)
        for col in ['vwap','trade_count']:
            if col in df.columns:
                df = df.drop(columns=[col])
        return df
    from alpaca.data import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end    = datetime.now()
    start  = end - timedelta(days=182)
    for attempt in range(5):
        try:
            req  = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start, end=end)
            bars = client.get_stock_bars(req)
            df   = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level='symbol')
            df = df.reset_index()
            df['symbol'] = symbol
            df.to_csv(cache, index=False)
            print(f"  {symbol}: {len(df)} bars fetched")
            return df
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  {symbol} retry {attempt+1}: {e.__class__.__name__}, wait {wait}s")
            time_mod.sleep(wait)
    return None


def add_indicators(win):
    """Add indicators — VWAP resets each calendar day"""
    win = win.copy()
    for col in ['vwap', 'vol_avg', 'vwap_slope']:
        if col in win.columns:
            win = win.drop(columns=[col])
    typical = (win['high'] + win['low'] + win['close']) / 3
    # VWAP resets per day
    dates = win['timestamp'].dt.date
    vwap_vals = np.zeros(len(win))
    for d in dates.unique():
        mask = (dates == d).values
        tp_d = typical.values[mask]
        vo_d = win['volume'].values[mask]
        cum_vol = vo_d.cumsum()
        cum_vol[cum_vol == 0] = 1
        vwap_vals[mask] = (tp_d * vo_d).cumsum() / cum_vol
    win['vwap']       = vwap_vals
    win['vol_avg']    = win['volume'].rolling(VOL_LB).mean()
    win['vwap_slope'] = win['vwap'].pct_change(5)
    return win


def find_pivots_np(day):
    lb = PIVOT_LB
    h  = day['high'].values
    l  = day['low'].values
    n  = len(h)
    ph = np.zeros(n, dtype=bool)
    pl = np.zeros(n, dtype=bool)
    for i in range(lb, n - lb):
        if h[i] == h[i-lb:i+lb+1].max(): ph[i] = True
        if l[i] == l[i-lb:i+lb+1].min(): pl[i] = True
    day = day.copy()
    day['pivot_high'] = ph
    day['pivot_low']  = pl
    return day


def simulate_exit(df, entry_i, entry_price):
    for k in range(entry_i, min(entry_i + MAX_HOLD, len(df))):
        bar  = df.iloc[k]
        loss = (bar['high'] - entry_price) / entry_price
        gain = (entry_price - bar['low'])  / entry_price
        if loss >= SL: return -SL - SLIPPAGE * 2
        if gain >= TP: return  TP - SLIPPAGE * 2
    final = (entry_price - df.iloc[min(entry_i + MAX_HOLD - 1, len(df)-1)]['close']) / entry_price
    return final - SLIPPAGE * 2


def backtest_symbol(symbol, df, min_score):
    trades = []
    df = df.copy().sort_values('timestamp').reset_index(drop=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date

    # --- Precompute everything once ---
    df = add_indicators(df)
    df = find_pivots_np(df)

    high   = df['high'].values
    low    = df['low'].values
    close  = df['close'].values
    open_  = df['open'].values
    vol    = df['volume'].values
    vol_avg= df['vol_avg'].values
    vwap   = df['vwap'].values
    vslope = df['vwap_slope'].values
    ph     = df['pivot_high'].values
    pl     = df['pivot_low'].values
    n      = len(df)
    last_i = -9999

    for i in range(100, n - MAX_HOLD - 1):
        if i % 5000 == 0:
            print(f"    {symbol} {(i-100)/(n-MAX_HOLD-101)*100:.0f}%...", flush=True)
        if i - last_i < COOLDOWN:
            continue

        va = vol_avg[i-1]
        if np.isnan(va) or va <= 0:
            continue

        # pivot zone from last 80 bars
        lb = max(0, i - 80)
        res_highs = high[lb:i][ph[lb:i]]
        sup_lows  = low[lb:i][pl[lb:i]]

        score = 0
        if len(res_highs) >= 2 and res_highs[-1] < res_highs[-2]: score += 1
        if len(sup_lows)  >= 2 and sup_lows[-1]  < sup_lows[-2]:  score += 1
        if close[i-1] < vwap[i-1]:                                score += 1
        vs = vslope[i-1]
        if not np.isnan(vs) and vs < 0:                           score += 1

        if score < min_score or len(res_highs) == 0:
            continue
        if not any(abs(high[i-1] - p) / p <= ZONE_TOL for p in res_highs):
            continue

        pav = vol_avg[i-2] if i >= 2 else np.nan
        if np.isnan(pav) or pav <= 0:
            continue
        if not (vol[i-2] < pav):          continue
        if not (vol[i-1] > va):           continue
        if not (close[i-1] < open_[i-1]): continue

        last_i      = i
        entry_price = open_[i] * (1 - SLIPPAGE)
        pnl         = simulate_exit(df, i, entry_price)
        trades.append(dict(symbol=symbol, date=df['date'].iloc[i], pnl=pnl))
    return trades


def print_metrics(label, trades):
    if not trades:
        print(f"\n  {label}: no trades")
        return
    df   = pd.DataFrame(trades)
    pnls = df['pnl']
    wins = (pnls > 0).sum()
    gw   = pnls[pnls > 0].sum()
    gl   = abs(pnls[pnls < 0].sum())
    pf   = gw / gl if gl > 0 else float('inf')
    nd   = df['date'].nunique()
    tpd  = len(df) / nd
    daily      = df.groupby('date')['pnl'].sum()
    worst_day  = daily.min()
    worst_date = daily.idxmin()
    df['week'] = pd.to_datetime(df['date'].astype(str)).dt.to_period('W')
    weekly     = df.groupby('week')['pnl'].sum()
    worst_week = weekly.min()
    worst_wp   = weekly.idxmin()
    cumul  = pnls.cumsum()
    max_dd = (cumul - cumul.cummax()).min()
    streak = ms = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        ms = max(ms, streak)
    print(f"\n  {'─'*52}")
    print(f"  {label}")
    print(f"  {'─'*52}")
    print(f"  Trades:          {len(pnls)}  ({tpd:.2f}/day over {nd} days)")
    print(f"  Win Rate:        {wins/len(pnls):.1%}")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  EV/trade:        {pnls.mean():.4%}")
    print(f"  Total PnL:       {pnls.sum():.2%}")
    print(f"  Max Drawdown:    {max_dd:.2%}")
    print(f"  Worst Day:       {worst_day:.2%}  ({worst_date})")
    print(f"  Worst Week:      {worst_week:.2%}  ({worst_wp})")
    print(f"  Max Loss Streak: {ms} trades")


def run():
    core_trades = []
    ext_trades  = []
    for symbol in ALL_SYMBOLS:
        is_core   = symbol in CORE_UNIVERSE
        min_score = SCORE_CORE if is_core else SCORE_EXT
        df = fetch_or_load(symbol)
        if df is None or len(df) < 5000:
            print(f"  {symbol}: skipped")
            continue
        trades = backtest_symbol(symbol, df, min_score)
        label  = 'core' if is_core else 'ext '
        print(f"  {symbol} ({label}): {len(trades)} trades")
        if is_core:
            core_trades.extend(trades)
        else:
            ext_trades.extend(trades)

    all_trades = core_trades + ext_trades
    print(f"\n{'='*55}")
    print(f"  BOOF31 REAL BACKTEST — 6mo, 1m bars, real data")
    print(f"{'='*55}")
    print_metrics("CORE universe  (score >= 3)", core_trades)
    print_metrics("EXTENDED universe  (score >= 6)", ext_trades)
    print_metrics("COMBINED", all_trades)

    if not all_trades:
        return
    df_all = pd.DataFrame(all_trades)
    print(f"\n{'='*55}")
    print(f"  PER-SYMBOL  (ranked by PF)")
    print(f"{'='*55}")
    print(f"  {'Symbol':<6}  {'U':<4}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    rows = []
    for sym, g in df_all.groupby('symbol'):
        x   = g['pnl']
        w   = (x > 0).sum()
        gw2 = x[x > 0].sum()
        gl2 = abs(x[x < 0].sum())
        pf2 = gw2 / gl2 if gl2 > 0 else float('inf')
        u   = 'core' if sym in CORE_UNIVERSE else 'ext'
        rows.append((sym, u, len(x), w/len(x), pf2, x.mean()))
    for sym, u, n, wr, pf2, ev in sorted(rows, key=lambda r: -r[4]):
        print(f"  {sym:<6}  {u:<4}  {n:4d}  {wr:6.1%}  {pf2:5.2f}  {ev:9.4%}")
    df_all.to_csv('boof31_real_trades.csv', index=False)
    print("\nSaved: boof31_real_trades.csv")


if __name__ == '__main__':
    run()
