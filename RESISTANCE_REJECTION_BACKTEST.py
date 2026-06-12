#!/usr/bin/env python3
"""
RESISTANCE REJECTION STRATEGY BACKTEST
1-minute timeframe, 6 months
Analyzes resistance touches, rejections, structure breaks, and volume
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
SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "META", "AMZN", "MSFT", "AVGO", "PLTR", "AMD"]

API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

def resistance_score(touches):
    """Step 1: Detect Resistance"""
    if touches >= 4:
        return 3
    elif touches == 3:
        return 2
    elif touches == 2:
        return 1
    return 0

def rejection_score(open_, high, low, close, resistance):
    """Step 2: Rejection Score"""
    score = 0
    
    body = abs(close - open_)
    wick = high - max(open_, close)
    
    if wick > body * 1.5:
        score += 1
    
    if close < open_:
        score += 1
    
    if close < resistance:
        score += 1
    
    return score

def structure_score(close, prev_swing_low, vwap, vwap_slope):
    """Step 3: Structure Break"""
    score = 0
    
    if close < prev_swing_low:
        score += 1
    
    if close < vwap:
        score += 1
    
    if vwap_slope < 0:
        score += 1
    
    return score

def volume_score(rejection_vol, breakdown_vol, expansion_vol, avg_vol):
    """Step 4: Volume"""
    score = 0
    
    if rejection_vol > avg_vol:
        score += 1
    
    if breakdown_vol > avg_vol:
        score += 1
    
    if expansion_vol > avg_vol:
        score += 1
    
    return score

def find_resistance_levels(df, lookback=20, min_touches=2):
    """Find resistance levels with touch counts"""
    df = df.copy()
    df['resistance'] = np.nan
    df['resistance_touches'] = 0
    
    # Find potential resistance levels
    for i in range(lookback, len(df) - lookback):
        current_high = df['high'].iloc[i]
        
        # Check if this is a local high
        is_local_high = True
        for j in range(i - lookback, i + lookback + 1):
            if j != i and df['high'].iloc[j] >= current_high:
                is_local_high = False
                break
        
        if is_local_high:
            # Count touches within tolerance
            tolerance = current_high * 0.005  # 0.5% tolerance
            touches = 0
            
            for j in range(max(0, i - 50), min(len(df), i + 50)):
                if abs(df['high'].iloc[j] - current_high) <= tolerance:
                    touches += 1
            
            if touches >= min_touches:
                # Mark this resistance level
                for j in range(max(0, i - 50), min(len(df), i + 50)):
                    if abs(df['high'].iloc[j] - current_high) <= tolerance:
                        if pd.isna(df.loc[df.index[j], 'resistance']) or touches > df.loc[df.index[j], 'resistance_touches']:
                            df.loc[df.index[j], 'resistance'] = current_high
                            df.loc[df.index[j], 'resistance_touches'] = touches
    
    return df

def find_swing_lows(df, lookback=10):
    """Find swing lows"""
    df = df.copy()
    df['swing_low'] = np.nan
    
    for i in range(lookback, len(df) - lookback):
        current_low = df['low'].iloc[i]
        
        # Check if this is a local low
        is_local_low = True
        for j in range(i - lookback, i + lookback + 1):
            if j != i and df['low'].iloc[j] <= current_low:
                is_local_low = False
                break
        
        if is_local_low:
            df.loc[df.index[i], 'swing_low'] = current_low
    
    return df

def add_indicators(df):
    """Add VWAP and volume indicators"""
    df = df.copy()
    typical = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (typical * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_slope'] = df['vwap'].pct_change(5)
    df['avg_vol'] = df['volume'].rolling(20).mean()
    
    return df

def fetch_6m_data(symbols):
    """Fetch 6 months of 1m data from Alpaca"""
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    end = datetime.now()
    start = end - timedelta(days=180)  # 6 months
    
    all_data = []
    
    for symbol in symbols:
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
                all_data.append(df)
                logging.info(f'  {symbol}: {len(df)} bars')
        except Exception as e:
            logging.error(f'  {symbol} failed: {e}')
    
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None

def analyze_symbol(symbol, df):
    """Analyze resistance rejection setups for a symbol"""
    results = []
    
    df = df.copy().sort_values('timestamp')
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    
    for date, day in df.groupby('date'):
        if len(day) < 100:
            continue
        
        day = day.reset_index(drop=True)
        day = add_indicators(day)
        day = find_resistance_levels(day)
        day = find_swing_lows(day)
        
        for i in range(50, len(day) - 31):  # Need 31 bars for MFE/MAE calculation
            
            # Check if we have resistance at this bar
            if pd.isna(day.loc[day.index[i], 'resistance']):
                continue
            
            resistance = day.loc[day.index[i], 'resistance']
            resistance_touches = day.loc[day.index[i], 'resistance_touches']
            
            # Get previous swing low
            prev_swing_lows = day.loc[:day.index[i-1], 'swing_low'].dropna()
            if len(prev_swing_lows) == 0:
                continue
            prev_swing_low = prev_swing_lows.iloc[-1]
            
            # Get volumes
            if i < 2:
                continue
            rejection_vol = day.loc[day.index[i], 'volume']
            breakdown_vol = day.loc[day.index[i-1], 'volume'] if i > 0 else rejection_vol
            expansion_vol = day.loc[day.index[i-2], 'volume'] if i > 1 else rejection_vol
            avg_vol = day.loc[day.index[i], 'avg_vol']
            
            # Calculate scores
            res_score = resistance_score(resistance_touches)
            rej_score = rejection_score(
                day.loc[day.index[i], 'open'],
                day.loc[day.index[i], 'high'],
                day.loc[day.index[i], 'low'],
                day.loc[day.index[i], 'close'],
                resistance
            )
            struct_score = structure_score(
                day.loc[day.index[i], 'close'],
                prev_swing_low,
                day.loc[day.index[i], 'vwap'],
                day.loc[day.index[i], 'vwap_slope']
            )
            vol_score = volume_score(rejection_vol, breakdown_vol, expansion_vol, avg_vol)
            
            total_score = res_score + rej_score + struct_score + vol_score
            
            # Only analyze setups with minimum score
            if total_score >= 3:  # Minimum threshold
                # Step 6: Measure MFE/MAE for shorts
                future = day.iloc[i+1:i+31]
                entry = day.loc[day.index[i], 'close']
                
                mfe = (entry - future['low'].min()) / entry  # Maximum favorable excursion
                mae = (future['high'].max() - entry) / entry  # Maximum adverse excursion
                
                results.append({
                    "symbol": symbol,
                    "datetime": day.loc[day.index[i], 'timestamp'],
                    "score": total_score,
                    "resistance_score": res_score,
                    "rejection_score": rej_score,
                    "structure_score": struct_score,
                    "volume_score": vol_score,
                    "mfe": mfe,
                    "mae": mae,
                    "entry": entry,
                    "resistance": resistance,
                    "resistance_touches": resistance_touches
                })
    
    return results

def run_backtest():
    """Main backtest runner"""
    logging.info('='*80)
    logging.info('RESISTANCE REJECTION STRATEGY BACKTEST')
    logging.info(f'Symbols: {SYMBOLS}')
    logging.info('='*80)
    
    # Fetch data
    df = fetch_6m_data(SYMBOLS)
    if df is None:
        logging.error('No data fetched')
        return
    
    logging.info(f'Total bars: {len(df)}')
    
    # Analyze each symbol
    all_results = []
    
    for symbol in SYMBOLS:
        sdf = df[df['symbol'] == symbol].copy()
        if sdf.empty:
            logging.warning(f'{symbol}: no data')
            continue
        
        results = analyze_symbol(symbol, sdf)
        all_results.extend(results)
        logging.info(f'{symbol}: {len(results)} setups found')
    
    if not all_results:
        logging.error('No setups found')
        return
    
    results = pd.DataFrame(all_results)
    
    # Analysis by score
    score_analysis = results.groupby("score").agg({
        "mfe": ["mean", "median", "count"],
        "mae": ["mean", "median"]
    }).round(4)
    
    print('\n' + '='*80)
    print('RESISTANCE REJECTION - SCORE ANALYSIS')
    print('='*80)
    print(score_analysis)
    
    # Component analysis
    component_analysis = {}
    for component in ['resistance_score', 'rejection_score', 'structure_score', 'volume_score']:
        comp_data = results[results[component] > 0]
        if len(comp_data) > 0:
            component_analysis[component] = {
                'setups': len(comp_data),
                'avg_mfe': comp_data['mfe'].mean(),
                'avg_mae': comp_data['mae'].mean(),
                'mfe_mae_ratio': comp_data['mfe'].mean() / comp_data['mae'].mean() if comp_data['mae'].mean() > 0 else 0
            }
    
    print('\n' + '='*60)
    print('COMPONENT ANALYSIS')
    print('='*60)
    for comp, stats in component_analysis.items():
        print(f"{comp}:")
        print(f"  Setups: {stats['setups']}")
        print(f"  Avg MFE: {stats['avg_mfe']:.3%}")
        print(f"  Avg MAE: {stats['mae']:.3%}")
        print(f"  MFE/MAE Ratio: {stats['mfe_mae_ratio']:.2f}")
        print()
    
    # Symbol breakdown
    symbol_analysis = results.groupby('symbol').agg({
        'score': 'count',
        'mfe': 'mean',
        'mae': 'mean'
    }).round(4)
    symbol_analysis.columns = ['setups', 'avg_mfe', 'avg_mae']
    symbol_analysis = symbol_analysis.sort_values('avg_mfe', ascending=False)
    
    print('\n' + '='*60)
    print('BY SYMBOL')
    print('='*60)
    print(symbol_analysis)
    
    # Save results
    results.to_csv('resistance_rejection_results.csv', index=False)
    
    print('\nSaved: resistance_rejection_results.csv')
    print(f'Total setups analyzed: {len(results)}')

if __name__ == '__main__':
    run_backtest()
