#!/usr/bin/env python3
"""
BOOF 31 v2 - RESISTANCE SWEEP SETUP TEST
For each symbol/day, scan bar by bar for resistance sweep failures
Output: Trades, Avg MFE, Median MFE, Avg MAE, % hit TP levels by score
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

# BOOF 31 v2 Parameters
RES_TOL = 0.002        # 0.20% zone tolerance
SWEEP_BUFFER = 0.0005  # must trade 0.05% above resistance
LOOKBACK = 80
MAX_CONFIRM_BARS = 5
MAX_HOLD_BARS = 30

API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

def find_resistance(day, i):
    """Find resistance zone with touch count"""
    window = day.iloc[max(0, i-LOOKBACK):i]
    highs = window["high"].values
    
    levels = []
    for h in highs:
        touches = sum(abs(highs - h) / h < RES_TOL)
        if touches >= 2:
            levels.append((h, touches))
    
    if not levels:
        return None, 0
    
    level, touches = max(levels, key=lambda x: x[1])
    return level, touches

def prior_swing_low(day, i, lookback=20):
    """Find prior swing low"""
    return day["low"].iloc[max(0, i-lookback):i].min()

def boof31_short_signal(day, i):
    """Check for BOOF 31 v2 short setup"""
    resistance, touches = find_resistance(day, i)
    
    if resistance is None:
        return False, {}
    
    bar = day.iloc[i]
    
    # 1. multi-touch resistance
    multi_touch = touches >= 2
    
    # 2. break above resistance
    swept = bar["high"] > resistance * (1 + SWEEP_BUFFER)
    
    # 3. close back below resistance
    failed_breakout = swept and bar["close"] < resistance
    
    if not (multi_touch and failed_breakout):
        return False, {}
    
    swing_low = prior_swing_low(day, i)
    
    # 4. break prior swing low within next few bars
    for j in range(i+1, min(i+1+MAX_CONFIRM_BARS, len(day))):
        confirm_bar = day.iloc[j]
        
        if confirm_bar["close"] < swing_low:
            return True, {
                "entry_i": j + 1,
                "resistance": resistance,
                "touches": touches,
                "sweep_i": i,
                "break_i": j,
                "swing_low": swing_low,
            }
    
    return False, {}

def score_boof31_short(day, signal):
    """Score the confirmed setup"""
    i = signal["break_i"]
    sweep_i = signal["sweep_i"]
    resistance = signal["resistance"]
    touches = signal["touches"]
    
    score = 0
    
    # Volume
    avg_vol = day["volume"].iloc[max(0, i-20):i].mean()
    if day["volume"].iloc[sweep_i] > avg_vol:
        score += 1
    if day["volume"].iloc[i] > avg_vol:
        score += 1
    
    # Rejection strength
    sweep_bar = day.iloc[sweep_i]
    upper_wick = sweep_bar["high"] - max(sweep_bar["open"], sweep_bar["close"])
    body = abs(sweep_bar["close"] - sweep_bar["open"])
    
    if upper_wick > body * 1.5:
        score += 1
    if sweep_bar["close"] < sweep_bar["open"]:
        score += 1
    if sweep_bar["close"] < resistance:
        score += 1
    
    # Freshness
    if touches >= 3:
        score += 1
    if signal["break_i"] - sweep_i <= 5:
        score += 1
    
    return score

def measure_mfe_mae(day, entry_i, entry_price):
    """Measure MFE/MAE for the trade"""
    future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS]
    
    if len(future) == 0:
        return 0, 0, 0, 0, 0
    
    mfe = (entry_price - future["low"].min()) / entry_price
    mae = (future["high"].max() - entry_price) / entry_price
    
    # Check TP levels
    hit_025 = (future["low"] <= entry_price * 0.9975).any()  # 0.25%
    hit_050 = (future["low"] <= entry_price * 0.9950).any()  # 0.50%
    hit_075 = (future["low"] <= entry_price * 0.9925).any()  # 0.75%
    
    return mfe, mae, hit_025, hit_050, hit_075

def analyze_symbol(symbol, df):
    """Analyze single symbol for BOOF 31 v2 setups"""
    results = []
    
    df = df.copy().sort_values('timestamp')
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    
    for date, day in df.groupby('date'):
        if len(day) < 100:
            continue
        
        day = day.reset_index(drop=True)
        
        # Scan bar by bar for setups
        for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - MAX_CONFIRM_BARS):
            
            # Check for short setup
            is_signal, signal = boof31_short_signal(day, i)
            
            if not is_signal:
                continue
            
            # Score the setup
            score = score_boof31_short(day, signal)
            entry_i = signal["entry_i"]
            
            if entry_i >= len(day):
                continue
            
            entry_price = day.iloc[entry_i]["open"]
            
            # Measure MFE/MAE
            mfe, mae, hit_025, hit_050, hit_075 = measure_mfe_mae(day, entry_i, entry_price)
            
            results.append({
                "symbol": symbol,
                "date": date,
                "score": score,
                "mfe": mfe,
                "mae": mae,
                "hit_025": hit_025,
                "hit_050": hit_050,
                "hit_075": hit_075,
                "entry_price": entry_price,
                "resistance": signal["resistance"],
                "touches": signal["touches"],
                "swing_low": signal["swing_low"],
                "sweep_i": signal["sweep_i"],
                "break_i": signal["break_i"],
            })
    
    return results

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

def run_analysis():
    """Main analysis runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - RESISTANCE SWEEP SETUP ANALYSIS')
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
        "mae": ["mean"],
        "hit_025": ["mean"],
        "hit_050": ["mean"],
        "hit_075": ["mean"]
    }).round(4)
    
    print('\n' + '='*100)
    print('BOOF 31 v2 - SETUP PERFORMANCE BY SCORE')
    print('='*100)
    print(f"{'Score':<6} {'Trades':<8} {'Avg MFE':<10} {'Median MFE':<12} {'Avg MAE':<10} {'% Hit 0.25%':<12} {'% Hit 0.50%':<12} {'% Hit 0.75%':<12}")
    print('-'*100)
    
    for score in sorted(results['score'].unique()):
        score_data = results[results['score'] == score]
        trades = len(score_data)
        avg_mfe = score_data['mfe'].mean()
        median_mfe = score_data['mfe'].median()
        avg_mae = score_data['mae'].mean()
        hit_025 = score_data['hit_025'].mean() * 100
        hit_050 = score_data['hit_050'].mean() * 100
        hit_075 = score_data['hit_075'].mean() * 100
        
        print(f"{score:<6} {trades:<8} {avg_mfe:<10.3%} {median_mfe:<12.3%} {avg_mae:<10.3%} {hit_025:<12.1f} {hit_050:<12.1f} {hit_075:<12.1f}")
    
    # Symbol breakdown
    symbol_analysis = results.groupby('symbol').agg({
        'score': 'count',
        'mfe': 'mean',
        'mae': 'mean',
        'hit_025': 'mean',
        'hit_050': 'mean',
        'hit_075': 'mean'
    ).round(4)
    symbol_analysis.columns = ['setups', 'avg_mfe', 'avg_mae', 'hit_025', 'hit_050', 'hit_075']
    symbol_analysis = symbol_analysis.sort_values('avg_mfe', ascending=False)
    
    print('\n' + '='*80)
    print('BY SYMBOL')
    print('='*80)
    print(f"{'Symbol':<8} {'Setups':<8} {'Avg MFE':<10} {'Avg MAE':<10} {'% Hit 0.25%':<12} {'% Hit 0.50%':<12} {'% Hit 0.75%':<12}")
    print('-'*80)
    
    for symbol, row in symbol_analysis.iterrows():
        print(f"{symbol:<8} {row['setups']:<8} {row['avg_mfe']:<10.3%} {row['avg_mae']:<10.3%} {row['hit_025']*100:<12.1f} {row['hit_050']*100:<12.1f} {row['hit_075']*100:<12.1f}")
    
    # Overall stats
    print('\n' + '='*60)
    print('OVERALL STATISTICS')
    print('='*60)
    total_setups = len(results)
    avg_score = results['score'].mean()
    overall_mfe = results['mfe'].mean()
    overall_mae = results['mae'].mean()
    overall_hit_025 = results['hit_025'].mean() * 100
    overall_hit_050 = results['hit_050'].mean() * 100
    overall_hit_075 = results['hit_075'].mean() * 100
    
    print(f"Total setups: {total_setups:,}")
    print(f"Average score: {avg_score:.1f}")
    print(f"Overall MFE: {overall_mfe:.3%}")
    print(f"Overall MAE: {overall_mae:.3%}")
    print(f"MFE/MAE Ratio: {overall_mfe/overall_mae:.2f}")
    print(f"Hit 0.25%: {overall_hit_025:.1f}%")
    print(f"Hit 0.50%: {overall_hit_050:.1f}%")
    print(f"Hit 0.75%: {overall_hit_075:.1f}%")
    
    # Save results
    results.to_csv('boof31v2_resistance_sweep_results.csv', index=False)
    
    print('\nSaved: boof31v2_resistance_sweep_results.csv')

if __name__ == '__main__':
    run_analysis()
