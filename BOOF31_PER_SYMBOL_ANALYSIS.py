#!/usr/bin/env python3
"""
BOOF 31 - PER-SYMBOL BREAKDOWN ANALYSIS
Run exact same BOOF 31 rules on each symbol individually
Output: Trades, Win Rate, PF, EV, Sharpe, Avg MFE, Avg MAE
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import logging

logging.basicConfig(level=logging.INFO)

# Test Universe - Individual symbols
SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "META", "AMZN", "MSFT", "AVGO", "PLTR", "AMD"]

# Original BOOF 31 Parameters
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

def simulate_trade_with_mfe_mae(df, entry_i, direction, tp, sl):
    """Simulate trade outcome with MFE/MAE tracking"""
    entry = df['open'].iloc[entry_i]
    future = df.iloc[entry_i:entry_i + MAX_HOLD_BARS]
    
    final_pnl = 0
    mfe = 0
    mae = 0
    
    for _, bar in future.iterrows():
        if direction == 'long':
            favorable = (bar['high'] - entry) / entry
            adverse = (bar['low'] - entry) / entry
            
            mfe = max(mfe, favorable)
            mae = max(mae, -adverse)
            
            if adverse <= -sl:
                final_pnl = -sl
                break
            if favorable >= tp:
                final_pnl = tp
                break
        else:
            favorable = (entry - bar['low']) / entry
            adverse = (entry - bar['high']) / entry
            
            mfe = max(mfe, favorable)
            mae = max(mae, -adverse)
            
            if adverse <= -sl:
                final_pnl = -sl
                break
            if favorable >= tp:
                final_pnl = tp
                break
    
    if final_pnl == 0:  # No TP/SL hit
        last_close = future['close'].iloc[-1]
        if direction == 'long':
            final_pnl = (last_close - entry) / entry
        else:
            final_pnl = (entry - last_close) / entry
    
    return final_pnl, mfe, mae

def fetch_6m_data(symbol):
    """Fetch 6 months of 1m data for single symbol"""
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    end = datetime.now()
    start = end - timedelta(days=180)  # 6 months
    
    try:
        logging.info(f'Fetching {symbol}...')
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
        )
        bars = client.get_stock_bars(request)
        if bars and bars.df is not None:
            df = bars.df.reset_index()
            logging.info(f'  {symbol}: {len(df)} bars')
            return df
    except Exception as e:
        logging.error(f'  {symbol} failed: {e}')
    
    return None

def analyze_symbol(symbol):
    """Analyze single symbol with exact BOOF 31 rules"""
    df = fetch_6m_data(symbol)
    if df is None:
        return None
    
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
                    pnl, mfe, mae = simulate_trade_with_mfe_mae(day, entry_i, direction, tp, sl)
                    results.append({
                        'symbol': symbol,
                        'date': date,
                        'direction': direction,
                        'tp': tp,
                        'sl': sl,
                        'pnl': pnl,
                        'mfe': mfe,
                        'mae': mae
                    })
    
    return results

def calculate_metrics(results):
    """Calculate comprehensive metrics"""
    if not results:
        return None
    
    df = pd.DataFrame(results)
    
    # Basic metrics
    total_trades = len(df)
    win_rate = (df['pnl'] > 0).mean()
    avg_pnl = df['pnl'].mean()
    
    # Profit Factor
    wins = df[df['pnl'] > 0]['pnl'].sum()
    losses = abs(df[df['pnl'] < 0]['pnl'].sum())
    profit_factor = wins / losses if losses > 0 else float('inf')
    
    # Expected Value
    ev = avg_pnl
    
    # Sharpe Ratio (simplified)
    pnl_std = df['pnl'].std()
    sharpe = avg_pnl / pnl_std if pnl_std > 0 else 0
    
    # MFE/MAE
    avg_mfe = df['mfe'].mean()
    avg_mae = df['mae'].mean()
    
    return {
        'trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'ev': ev,
        'sharpe': sharpe,
        'avg_mfe': avg_mfe,
        'avg_mae': avg_mae
    }

def run_per_symbol_analysis():
    """Main analysis runner"""
    logging.info('='*80)
    logging.info('BOOF 31 - PER-SYMBOL BREAKDOWN ANALYSIS')
    logging.info(f'Symbols: {SYMBOLS}')
    logging.info('='*80)
    
    all_results = {}
    
    for symbol in SYMBOLS:
        logging.info(f'\nAnalyzing {symbol}...')
        trades = analyze_symbol(symbol)
        
        if trades:
            metrics = calculate_metrics(trades)
            all_results[symbol] = metrics
            logging.info(f'  {symbol}: {len(trades)} trade rows')
        else:
            logging.warning(f'  {symbol}: No trades found')
    
    # Display results
    print('\n' + '='*100)
    print('BOOF 31 - PER-SYMBOL PERFORMANCE METRICS')
    print('='*100)
    print(f"{'Symbol':<8} {'Trades':<8} {'Win%':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8} {'MFE':<8} {'MAE':<8}")
    print('-'*100)
    
    for symbol in SYMBOLS:
        if symbol in all_results:
            m = all_results[symbol]
            print(f"{symbol:<8} {m['trades']:<8.0f} {m['win_rate']:<8.1%} {m['profit_factor']:<8.2f} {m['ev']:<10.4%} {m['sharpe']:<8.3f} {m['avg_mfe']:<8.3%} {m['avg_mae']:<8.3%}")
    
    # Find best performers
    print('\n' + '='*60)
    print('TOP PERFORMERS BY METRIC')
    print('='*60)
    
    metrics_comparison = {}
    for metric in ['win_rate', 'profit_factor', 'ev', 'sharpe']:
        best_symbol = max(all_results.keys(), key=lambda s: all_results[s][metric])
        best_value = all_results[best_symbol][metric]
        metrics_comparison[metric] = (best_symbol, best_value)
        print(f"Best {metric}: {best_symbol} ({best_value:.4f})")
    
    # Save detailed results
    detailed_results = []
    for symbol, trades in zip(SYMBOLS, [analyze_symbol(s) for s in SYMBOLS]):
        if trades:
            for trade in trades:
                detailed_results.append(trade)
    
    if detailed_results:
        detailed_df = pd.DataFrame(detailed_results)
        detailed_df.to_csv('boof31_per_symbol_trades.csv', index=False)
        print('\nSaved: boof31_per_symbol_trades.csv')
    
    return all_results

if __name__ == '__main__':
    run_per_symbol_analysis()
