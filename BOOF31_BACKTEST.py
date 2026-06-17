#!/usr/bin/env python3
"""
BOOF 31 - 6 MONTH BACKTEST
Symbols: SPY, QQQ, NVDA, TSLA, META, AMZN, MSFT, AVGO, PLTR, AMD
Timeframe: 1-minute bars, 6 months
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import logging

logging.basicConfig(level=logging.INFO)

# Test Universe - Original 10 Symbols
SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "META", "AMZN", "MSFT", "AVGO", "PLTR", "AMD"]

# Test Parameters
TP_LIST = [0.0025, 0.005, 0.0075]  # 0.25%, 0.50%, 0.75%
SL_LIST = [0.0025, 0.004, 0.005]  # 0.25%, 0.40%, 0.50%

MAX_HOLD_BARS = 30
PIVOT_LOOKBACK = 5
ZONE_TOLERANCE = 0.003  # 0.30%
VOL_LOOKBACK = 20
TREND_SCORE_MIN = 3

API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'


def add_indicators(df):
    """Add VWAP, RVOL, slope"""
    df = df.copy()
    typical = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (typical * df['volume']).cumsum() / df['volume'].cumsum()
    df['vol_avg'] = df['volume'].rolling(VOL_LOOKBACK).mean()
    df['rvol'] = df['volume'] / df['vol_avg']
    df['vwap_slope'] = df['vwap'].pct_change(5)
    return df


def find_pivots(df):
    """Find pivot highs and lows"""
    df = df.copy()
    df['pivot_high'] = False
    df['pivot_low'] = False
    
    for i in range(PIVOT_LOOKBACK, len(df) - PIVOT_LOOKBACK):
        high_window = df['high'].iloc[i-PIVOT_LOOKBACK:i+PIVOT_LOOKBACK+1]
        low_window = df['low'].iloc[i-PIVOT_LOOKBACK:i+PIVOT_LOOKBACK+1]
        
        if df['high'].iloc[i] == high_window.max():
            df.at[df.index[i], 'pivot_high'] = True
        if df['low'].iloc[i] == low_window.min():
            df.at[df.index[i], 'pivot_low'] = True
    
    return df


def recent_pivots(df, idx, lookback=80):
    """Get recent pivot highs/lows"""
    start = max(0, idx - lookback)
    chunk = df.iloc[start:idx]
    highs = chunk[chunk['pivot_high']]
    lows = chunk[chunk['pivot_low']]
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


def check_long_signal(df, i, highs, lows):
    """Check for long entry signal"""
    if i < 40:
        return False
    
    score = trend_score_long(df, i, highs, lows)
    support_prices = lows['low'].values if len(lows) else []
    near_support = is_near_zone(df['low'].iloc[i], support_prices)
    
    pullback_dry = df['volume'].iloc[i-1] < df['vol_avg'].iloc[i-1]
    bounce_volume = df['volume'].iloc[i] > df['vol_avg'].iloc[i]
    green_candle = df['close'].iloc[i] > df['open'].iloc[i]
    
    return (
        score >= TREND_SCORE_MIN
        and near_support
        and pullback_dry
        and bounce_volume
        and green_candle
    )


def check_short_signal(df, i, highs, lows):
    """Check for short entry signal"""
    if i < 40:
        return False
    
    score = trend_score_short(df, i, highs, lows)
    resistance_prices = highs['high'].values if len(highs) else []
    near_resistance = is_near_zone(df['high'].iloc[i], resistance_prices)
    
    pullback_dry = df['volume'].iloc[i-1] < df['vol_avg'].iloc[i-1]
    rejection_volume = df['volume'].iloc[i] > df['vol_avg'].iloc[i]
    red_candle = df['close'].iloc[i] < df['open'].iloc[i]
    
    return (
        score >= TREND_SCORE_MIN
        and near_resistance
        and pullback_dry
        and rejection_volume
        and red_candle
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
    """Load 6 months of 5m data from cached files"""
    import os
    
    all_data = []
    
    for symbol in symbols:
        try:
            # Load from cached 5m parquet file
            cache_file = f'boof_data/{symbol}_5m_2025-12-01_to_2026-05-31.parquet'
            
            if os.path.exists(cache_file):
                logging.info(f'Loading {symbol} from cache...')
                df = pd.read_parquet(cache_file)
                df['symbol'] = symbol  # Add symbol column
                all_data.append(df)
                logging.info(f'  {symbol}: {len(df)} bars (5m data)')
            else:
                logging.warning(f'  {symbol}: No cached data found')
        except Exception as e:
            logging.error(f'  {symbol} failed: {e}')
    
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None


def backtest_symbol(symbol, df):
    """Backtest single symbol"""
    results = []
    
    df = df.copy().sort_values('timestamp')
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    
    for date, day in df.groupby('date'):
        if len(day) < 100:
            continue
        
        day = day.reset_index(drop=True)
        day = add_indicators(day)
        day = find_pivots(day)
        
        for i in range(50, len(day) - MAX_HOLD_BARS - 1):
            highs, lows = recent_pivots(day, i)
            
            direction = None
            if check_long_signal(day, i, highs, lows):
                direction = 'long'
            elif check_short_signal(day, i, highs, lows):
                direction = 'short'
            
            if direction is None:
                continue
            
            entry_i = i + 1
            
            for tp in TP_LIST:
                for sl in SL_LIST:
                    pnl = simulate_trade(day, entry_i, direction, tp, sl)
                    results.append({
                        'symbol': symbol,
                        'date': date,
                        'direction': direction,
                        'tp': tp,
                        'sl': sl,
                        'pnl': pnl
                    })
    
    return results


def run_backtest():
    """Main backtest runner"""
    logging.info('='*60)
    logging.info('BOOF 31 - 6 MONTH BACKTEST')
    logging.info(f'Symbols: {SYMBOLS}')
    logging.info('='*60)
    
    # Fetch data
    df = fetch_6m_data(SYMBOLS)
    if df is None:
        logging.error('No data fetched')
        return
    
    logging.info(f'Total bars: {len(df)}')
    
    # Run backtest
    all_results = []
    
    for symbol in SYMBOLS:
        sdf = df[df['symbol'] == symbol].copy()
        if sdf.empty:
            logging.warning(f'{symbol}: no data')
            continue
        
        trades = backtest_symbol(symbol, sdf)
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
    print('BOOF 31 - 6 MONTH BACKTEST RESULTS')
    print('='*80)
    print(f"{'TP':<8} {'SL':<8} {'Trades':<10} {'Win%':<8} {'Avg PnL':<10} {'Median':<10} {'Total':<12} {'PF':<6}")
    print('-'*80)
    
    for _, row in summary.iterrows():
        print(f"{row['tp']:<8.2%} {row['sl']:<8.2%} {row['total_trades']:<10.0f} {row['win_rate']:<8.1%} {row['avg_pnl']:<10.2%} {row['median_pnl']:<10.2%} {row['total_return']:<12.2%} {row['pf']:<6.2f}")
    
    # Symbol breakdown with enhanced metrics
    symbol_summary = (
        results.groupby('symbol')
        .agg(
            trades=('pnl', 'count'),
            win_rate=('pnl', lambda x: (x > 0).mean()),
            avg_pnl=('pnl', 'mean'),
            total=('pnl', 'sum'),
            pf=('pnl', lambda x: abs(x[x > 0].sum()) / abs(x[x < 0].sum()) if x[x < 0].sum() != 0 else float('inf')),
            sharpe=('pnl', lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0)
        )
        .reset_index()
        .sort_values('avg_pnl', ascending=False)
    )
    
    print('\n' + '='*80)
    print('SYMBOL PERFORMANCE BREAKDOWN')
    print('='*80)
    print(f"{'Symbol':<8} {'Trades':<8} {'WR':<8} {'PF':<8} {'EV':<8} {'Sharpe':<8}")
    print('-'*60)
    
    for _, row in symbol_summary.iterrows():
        ev = row['avg_pnl']  # Expected Value = Average PnL
        print(f"{row['symbol']:<8} {row['trades']:<8.0f} {row['win_rate']:<8.1%} {row['pf']:<8.2f} {ev:<8.2%} {row['sharpe']:<8.2f}")
    
    # Overall best performing symbols by different metrics
    print('\n' + '='*60)
    print('TOP PERFORMERS BY METRIC')
    print('='*60)
    
    best_trades = symbol_summary.loc[symbol_summary['trades'].idxmax()]
    best_wr = symbol_summary.loc[symbol_summary['win_rate'].idxmax()]
    best_pf = symbol_summary.loc[symbol_summary['pf'].idxmax()]
    best_ev = symbol_summary.loc[symbol_summary['avg_pnl'].idxmax()]
    best_sharpe = symbol_summary.loc[symbol_summary['sharpe'].idxmax()]
    
    print(f"Most Trades: {best_trades['symbol']} ({best_trades['trades']:.0f} trades)")
    print(f"Best Win Rate: {best_wr['symbol']} ({best_wr['win_rate']:.1%})")
    print(f"Best Profit Factor: {best_pf['symbol']} ({best_pf['pf']:.2f})")
    print(f"Best EV: {best_ev['symbol']} ({best_ev['avg_pnl']:.2%})")
    print(f"Best Sharpe: {best_sharpe['symbol']} ({best_sharpe['sharpe']:.2f})")
    
    # Save results to .txt to bypass .gitignore
    results.to_csv('boof31_10symbols_trades.txt', index=False)
    summary.to_csv('boof31_10symbols_summary.txt', index=False)
    
    print('\nSaved: boof31_10symbols_trades.txt, boof31_10symbols_summary.txt')

if __name__ == '__main__':
    run_backtest()
