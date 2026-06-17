#!/usr/bin/env python3
"""
BOOF 31 - FILTERED BACKTEST TESTS
Test 1: ATR percentile > 50
Test 2: RVOL > 1.5 (not 7)
Test 3: Market alignment (SPY/QQQ vs VWAP)
Test 4: Time windows 10:00-12:00, 14:00-15:30
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import logging

logging.basicConfig(level=logging.INFO)

# Test Universe
CORE_UNIVERSE = [
    "NVDA", "TSLA", "AMD", "META", "PLTR", "CRWD", "HOOD", "COIN",
    "MSTR", "APP", "SMCI", "MU", "MRVL", "NET", "DDOG",
]

EXTENDED_UNIVERSE = [
    "NFLX", "AMZN", "MSFT", "PANW", "ZS", "MDB",
    "QCOM", "MARA", "RIOT", "CLSK", "RDDT", "SNAP",
]

SYMBOLS = CORE_UNIVERSE + EXTENDED_UNIVERSE
TREND_SCORE_MIN_CORE = 3
TREND_SCORE_MIN_EXT  = 3

# Test Parameters
TP_LIST = [0.0025, 0.005, 0.0075]  # 0.25%, 0.50%, 0.75%
SL_LIST = [0.0025, 0.004, 0.005]  # 0.25%, 0.40%, 0.50%

MAX_HOLD_BARS = 30
PIVOT_LOOKBACK = 5
ZONE_TOLERANCE = 0.003  # 0.30%
VOL_LOOKBACK = 20
TREND_SCORE_MIN = 3  # default, overridden per symbol below

API_KEY = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

# FILTER TESTS
TEST_ATR_FILTER = False     # Not in live bot
TEST_RVOL_FILTER = False    # Not in live bot
TEST_MARKET_FILTER = False  # Test 3: Market alignment (not in live bot)
TEST_TIME_FILTER = False     # Test 4: Time windows (live bot runs all day)


def add_indicators(df):
    """Add VWAP, RVOL, ATR, slope"""
    df = df.copy()
    typical = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (typical * df['volume']).cumsum() / df['volume'].cumsum()
    df['vol_avg'] = df['volume'].rolling(VOL_LOOKBACK).mean()
    df['rvol'] = df['volume'] / df['vol_avg']
    df['vwap_slope'] = df['vwap'].pct_change(5)
    
    # ATR calculation
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = df['tr'].rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close']
    
    return df


def find_pivots(df):
    """Find pivot highs and lows — vectorized"""
    df = df.copy()
    lb = PIVOT_LOOKBACK
    highs = df['high'].values
    lows  = df['low'].values
    n = len(df)
    ph = np.zeros(n, dtype=bool)
    pl = np.zeros(n, dtype=bool)
    for i in range(lb, n - lb):
        if highs[i] == highs[i-lb:i+lb+1].max():
            ph[i] = True
        if lows[i] == lows[i-lb:i+lb+1].min():
            pl[i] = True
    df['pivot_high'] = ph
    df['pivot_low']  = pl
    return df


def recent_pivots(df, idx, lookback=80):
    """Get recent pivot highs/lows"""
    start = max(0, idx - lookback)
    chunk = df.iloc[start:idx]
    highs = chunk[chunk['pivot_high'].to_numpy()]
    lows  = chunk[chunk['pivot_low'].to_numpy()]
    return highs, lows


def is_near_zone(price, pivot_prices):
    """Check if price is near pivot zone"""
    if len(pivot_prices) == 0:
        return False
    for p in pivot_prices:
        if abs(price - p) / price <= ZONE_TOLERANCE:
            return True
    return False


def trend_score_long(df, i, highs, lows):
    """Calculate long trend score (0-4)"""
    score = 0
    
    if len(highs) >= 2:
        last_highs = highs['high'].tail(2).values
        if last_highs[-1] > last_highs[-2]:
            score += 1
    
    if len(lows) >= 2:
        last_lows = lows['low'].tail(2).values
        if last_lows[-1] > last_lows[-2]:
            score += 1
    
    if df['close'].iloc[i] > df['vwap'].iloc[i]:
        score += 1
    
    if df['vwap_slope'].iloc[i] > 0:
        score += 1
    
    return score


def trend_score_short(df, i, highs, lows):
    """Calculate short trend score (0-4)"""
    score = 0
    
    if len(highs) >= 2:
        last_highs = highs['high'].tail(2).values
        if last_highs[-1] < last_highs[-2]:
            score += 1
    
    if len(lows) >= 2:
        last_lows = lows['low'].tail(2).values
        if last_lows[-1] < last_lows[-2]:
            score += 1
    
    if df['close'].iloc[i] < df['vwap'].iloc[i]:
        score += 1
    
    if df['vwap_slope'].iloc[i] < 0:
        score += 1
    
    return score


def check_time_filter(timestamp):
    """Test 4: Only trade 10:00-12:00 and 14:00-15:30 ET"""
    if not TEST_TIME_FILTER:
        return True
    
    hour = timestamp.hour
    minute = timestamp.minute
    
    # 10:00-12:00
    if (hour == 10 and minute >= 0) or (hour == 11):
        return True
    
    # 14:00-15:30
    if (hour == 14) or (hour == 15 and minute <= 30):
        return True
    
    return False


def check_market_alignment(market_data, direction, timestamp):
    """Test 3: Market alignment with SPY/QQQ VWAP"""
    if not TEST_MARKET_FILTER:
        return True
    
    # Get current market state
    current_time = pd.to_datetime(timestamp)
    market_slice = market_data[market_data['timestamp'] <= current_time]
    
    if market_slice.empty:
        return True
    
    latest = market_slice.iloc[-1]
    
    if direction == 'long':
        return latest['SPY_vwap'] < latest['SPY_close'] and latest['QQQ_vwap'] < latest['QQQ_close']
    else:  # short
        return latest['SPY_vwap'] > latest['SPY_close'] and latest['QQQ_vwap'] > latest['QQQ_close']


def check_long_signal(df, i, highs, lows, market_data):
    """Check for long entry signal with filters"""
    if i < 40:
        return False
    
    # Time filter
    if not check_time_filter(df['timestamp'].iloc[i]):
        return False
    
    # Market alignment
    if not check_market_alignment(market_data, 'long', df['timestamp'].iloc[i]):
        return False
    
    score = trend_score_long(df, i, highs, lows)
    support_prices = lows['low'].values if len(lows) else []
    near_support = is_near_zone(df['low'].iloc[i], support_prices)
    
    pullback_dry = df['volume'].iloc[i-1] < df['vol_avg'].iloc[i-1]
    bounce_volume = df['volume'].iloc[i] > df['vol_avg'].iloc[i]
    green_candle = df['close'].iloc[i] > df['open'].iloc[i]
    
    # Test 2: RVOL filter
    rvol_ok = True
    if TEST_RVOL_FILTER:
        rvol_ok = df['rvol'].iloc[i] > 1.5
    
    # Test 1: ATR percentile filter
    atr_ok = True
    if TEST_ATR_FILTER:
        atr_pct_current = df['atr_pct'].iloc[i]
        atr_pct_history = df['atr_pct'].iloc[max(0, i-100):i]
        if len(atr_pct_history) > 0:
            atr_percentile = (atr_pct_history < atr_pct_current).mean()
            atr_ok = atr_percentile > 0.5
    
    return (
        score >= TREND_SCORE_MIN
        and near_support
        and pullback_dry
        and bounce_volume
        and green_candle
        and rvol_ok
        and atr_ok
    )


def check_short_signal(df, i, highs, lows, market_data):
    """Check for short entry signal with filters"""
    if i < 40:
        return False
    
    # Time filter
    if not check_time_filter(df['timestamp'].iloc[i]):
        return False
    
    # Market alignment
    if not check_market_alignment(market_data, 'short', df['timestamp'].iloc[i]):
        return False
    
    score = trend_score_short(df, i, highs, lows)
    resistance_prices = highs['high'].values if len(highs) else []
    near_resistance = is_near_zone(df['high'].iloc[i], resistance_prices)
    
    pullback_dry = df['volume'].iloc[i-1] < df['vol_avg'].iloc[i-1]
    rejection_volume = df['volume'].iloc[i] > df['vol_avg'].iloc[i]
    red_candle = df['close'].iloc[i] < df['open'].iloc[i]
    
    # Test 2: RVOL filter
    rvol_ok = True
    if TEST_RVOL_FILTER:
        rvol_ok = df['rvol'].iloc[i] > 1.5
    
    # Test 1: ATR percentile filter
    atr_ok = True
    if TEST_ATR_FILTER:
        atr_pct_current = df['atr_pct'].iloc[i]
        atr_pct_history = df['atr_pct'].iloc[max(0, i-100):i]
        if len(atr_pct_history) > 0:
            atr_percentile = (atr_pct_history < atr_pct_current).mean()
            atr_ok = atr_percentile > 0.5
    
    return (
        score >= TREND_SCORE_MIN
        and near_resistance
        and pullback_dry
        and rejection_volume
        and red_candle
        and rvol_ok
        and atr_ok
    )


def simulate_trade(df, entry_i, direction, tp, sl):
    """Simulate trade outcome"""
    entry = df['open'].iloc[entry_i]
    future = df.iloc[entry_i:entry_i + MAX_HOLD_BARS]
    
    for _, bar in future.iterrows():
        if direction == 'long':
            favorable = (bar['high'] - entry) / entry
            adverse = (bar['low'] - entry) / entry
            
            if adverse <= -sl:
                return -sl
            if favorable >= tp:
                return tp
        else:
            favorable = (entry - bar['low']) / entry
            adverse = (entry - bar['high']) / entry
            
            if adverse <= -sl:
                return -sl
            if favorable >= tp:
                return tp
    
    last_close = future['close'].iloc[-1]
    if direction == 'long':
        return (last_close - entry) / entry
    return (entry - last_close) / entry


def fetch_6m_data(symbols):
    """Load from cached CSV files (boof32_data_<symbol>.csv)"""
    import os, time as time_mod
    from alpaca.data import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end   = datetime.now()
    start = end - timedelta(days=182)

    all_data = []
    for symbol in symbols:
        cache = f'boof32_data_{symbol}.csv'
        if os.path.exists(cache):
            df = pd.read_csv(cache)
            if 'datetime' in df.columns:
                df = df.rename(columns={'datetime': 'timestamp'})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['symbol'] = symbol
            all_data.append(df)
            logging.info(f'  {symbol}: {len(df)} bars (cache)')
            continue
        logging.info(f'Fetching {symbol}...')
        for attempt in range(5):
            try:
                req  = StockBarsRequest(symbol_or_symbols=symbol,
                                        timeframe=TimeFrame.Minute,
                                        start=start, end=end)
                bars = client.get_stock_bars(req)
                df   = bars.df
                if isinstance(df.index, pd.MultiIndex):
                    df = df.xs(symbol, level='symbol')
                df = df.reset_index().rename(columns={'timestamp': 'timestamp'})
                df['symbol'] = symbol
                df.rename(columns={'timestamp': 'timestamp'}, inplace=True)
                df.to_csv(cache, index=False)
                all_data.append(df)
                logging.info(f'  {symbol}: {len(df)} bars (fetched)')
                break
            except Exception as e:
                wait = 10 * (attempt + 1)
                logging.warning(f'  {symbol} retry {attempt+1}: {e.__class__.__name__}, waiting {wait}s')
                time_mod.sleep(wait)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None


def create_market_data(df):
    """Create market alignment data from SPY/QQQ"""
    market_symbols = ['SPY', 'QQQ']
    market_data = []
    
    for symbol in market_symbols:
        sdf = df[df['symbol'] == symbol].copy()
        if not sdf.empty:
            sdf = add_indicators(sdf)
            sdf = sdf[['timestamp', 'close', 'vwap']].rename(columns={
                'close': f'{symbol}_close',
                'vwap': f'{symbol}_vwap'
            })
            market_data.append(sdf)
    
    if len(market_data) == 2:
        market_df = pd.merge(market_data[0], market_data[1], on='timestamp', how='outer')
        market_df = market_df.sort_values('timestamp').ffill().bfill()
        return market_df
    
    return None


def backtest_symbol(symbol, df, market_data):
    """Backtest BOOF31 using rolling 100-bar window — mirrors live bot exactly"""
    results = []
    min_score = TREND_SCORE_MIN_CORE if symbol in CORE_UNIVERSE else TREND_SCORE_MIN_EXT
    WINDOW = 100  # live bot fetches 100 bars

    df = df.copy().sort_values('timestamp').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    n = len(df)
    last_trade_i = -999

    for i in range(WINDOW, n - MAX_HOLD_BARS - 1):
        if i - last_trade_i < 30:
            continue

        # Simulate exactly what the live bot sees: last 100 bars
        window = df.iloc[i - WINDOW:i].copy().reset_index(drop=True)
        window = add_indicators(window)
        window = find_pivots(window)

        # Scan the last complete bar (index -2 like the live bot)
        j = len(window) - 2
        if j < 40:
            continue

        bar       = window.iloc[j]
        prev_bar  = window.iloc[j - 1]
        vol_avg_j = bar.get('vol_avg', np.nan)
        if np.isnan(vol_avg_j) or vol_avg_j <= 0:
            continue

        # Pivot zone
        lb_start  = max(0, j - 80)
        chunk     = window.iloc[lb_start:j]
        res_highs = chunk['high'].values[chunk['pivot_high'].to_numpy()]
        sup_lows  = chunk['low'].values[chunk['pivot_low'].to_numpy()]

        # Trend score short
        score = 0
        if len(res_highs) >= 2 and res_highs[-1] < res_highs[-2]: score += 1
        if len(sup_lows)  >= 2 and sup_lows[-1]  < sup_lows[-2]:  score += 1
        if bar['close'] < bar['vwap']:                             score += 1
        vs = bar.get('vwap_slope', np.nan)
        if not np.isnan(vs) and vs < 0:                           score += 1

        if score < min_score:
            continue

        # Near resistance zone
        if len(res_highs) == 0:
            continue
        near_res = any(abs(bar['high'] - p) / p <= ZONE_TOLERANCE for p in res_highs)
        if not near_res:
            continue

        # Volume conditions
        vol_avg_prev = prev_bar.get('vol_avg', np.nan)
        if np.isnan(vol_avg_prev) or vol_avg_prev <= 0:
            continue
        pullback_dry     = prev_bar['volume'] < vol_avg_prev
        rejection_volume = bar['volume'] > vol_avg_j
        red_candle       = bar['close'] < bar['open']

        if not (pullback_dry and rejection_volume and red_candle):
            continue

        last_trade_i = i
        entry_i = i  # next bar in full df
        date = df['date'].iloc[i]

        for tp in TP_LIST:
            for sl in SL_LIST:
                pnl = simulate_trade(df, entry_i, 'short', tp, sl)
                results.append({
                    'symbol': symbol,
                    'date': date,
                    'direction': 'short',
                    'tp': tp,
                    'sl': sl,
                    'pnl': pnl
                })

    return results


def run_backtest():
    """Main backtest runner"""
    logging.info('='*80)
    logging.info('BOOF 31 - FILTERED BACKTEST TESTS')
    logging.info(f'Symbols: {SYMBOLS}')
    logging.info(f'Test 1 - ATR percentile > 50: {TEST_ATR_FILTER}')
    logging.info(f'Test 2 - RVOL > 1.5: {TEST_RVOL_FILTER}')
    logging.info(f'Test 3 - Market alignment: {TEST_MARKET_FILTER}')
    logging.info(f'Test 4 - Time windows: {TEST_TIME_FILTER}')
    logging.info('='*80)
    
    # Fetch data
    df = fetch_6m_data(SYMBOLS)
    if df is None:
        logging.error('No data fetched')
        return
    
    logging.info(f'Total bars: {len(df)}')
    
    # Create market alignment data (only needed if TEST_MARKET_FILTER is True)
    market_data = create_market_data(df) if TEST_MARKET_FILTER else pd.DataFrame()
    if TEST_MARKET_FILTER and market_data is None:
        logging.error('Failed to create market data')
        return
    
    # Run backtest
    all_results = []
    
    for symbol in SYMBOLS:
        sdf = df[df['symbol'] == symbol].copy()
        if sdf.empty:
            logging.warning(f'{symbol}: no data')
            continue
        
        trades = backtest_symbol(symbol, sdf, market_data)
        all_results.extend(trades)
        logging.info(f'{symbol}: {len(trades)} trade rows')
    
    results = pd.DataFrame(all_results)
    
    if results.empty:
        logging.error('No trades found')
        return
    
    # Summary by TP/SL
    summary = (
        results.groupby(['tp', 'sl'])
        .agg(
            total_trades=('pnl', 'count'),
            win_rate=('pnl', lambda x: (x > 0).mean()),
            avg_pnl=('pnl', 'mean'),
            median_pnl=('pnl', 'median'),
            total_return=('pnl', 'sum'),
            pf=('pnl', lambda x: abs(x[x > 0].sum()) / abs(x[x < 0].sum()) if x[x < 0].sum() != 0 else float('inf'))
        )
        .reset_index()
        .sort_values('avg_pnl', ascending=False)
    )
    
    print('\n' + '='*80)
    print('BOOF 31 - FILTERED BACKTEST RESULTS')
    print('='*80)
    print(f"{'TP':<8} {'SL':<8} {'Trades':<10} {'Win%':<8} {'Avg PnL':<10} {'Median':<10} {'Total':<12} {'PF':<6}")
    print('-'*80)
    
    for _, row in summary.iterrows():
        print(f"{row['tp']:<8.2%} {row['sl']:<8.2%} {row['total_trades']:<10.0f} {row['win_rate']:<8.1%} {row['avg_pnl']:<10.2%} {row['median_pnl']:<10.2%} {row['total_return']:<12.2%} {row['pf']:<6.2f}")
    
    # Symbol breakdown
    symbol_summary = (
        results.groupby('symbol')
        .agg(
            trades=('pnl', 'count'),
            win_rate=('pnl', lambda x: (x > 0).mean()),
            avg_pnl=('pnl', 'mean'),
            total=('pnl', 'sum')
        )
        .reset_index()
        .sort_values('avg_pnl', ascending=False)
    )
    
    print('\n' + '='*60)
    print('BY SYMBOL (Best TP/SL combo)')
    print('='*60)
    print(symbol_summary.to_string(index=False))
    
    # Save results
    results.to_csv('boof31_filtered_trades.csv', index=False)
    summary.to_csv('boof31_filtered_summary.csv', index=False)
    
    print('\nSaved: boof31_filtered_trades.csv, boof31_filtered_summary.csv')
    
    # Compare with original
    print('\n' + '='*60)
    print('FILTER IMPACT')
    print('='*60)
    total_trades = len(results)
    trades_per_day = total_trades / (6 * 21)  # 6 months, ~21 trading days/month
    print(f'Total trades: {total_trades:,.0f}')
    print(f'Trades per day: {trades_per_day:.1f}')
    print(f'Original was ~270 trades/day')
    print(f'Reduction: {(270 - trades_per_day)/270:.1%}')

if __name__ == '__main__':
    run_backtest()
