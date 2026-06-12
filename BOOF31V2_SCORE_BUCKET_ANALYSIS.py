#!/usr/bin/env python3
"""
BOOF 31 v2 - SCORE BUCKET ANALYSIS + VOLUME EXPANSION TEST
Analyze performance by score buckets and test volume expansion scoring
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

def score_boof31_short_original(day, signal):
    """Original scoring system (0-7 points)"""
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

def score_boof31_short_volume_expansion(day, signal):
    """Enhanced scoring with volume expansion (0-9 points)"""
    i = signal["break_i"]
    sweep_i = signal["sweep_i"]
    resistance = signal["resistance"]
    touches = signal["touches"]
    
    score = 0
    
    # Enhanced Volume Scoring
    avg_vol = day["volume"].iloc[max(0, i-20):i].mean()
    sweep_vol = day["volume"].iloc[sweep_i]
    break_vol = day["volume"].iloc[i]
    
    # Basic volume > average
    if sweep_vol > avg_vol:
        score += 1
    if break_vol > avg_vol:
        score += 1
    
    # Volume expansion scoring
    if sweep_vol > avg_vol * 1.5:
        score += 1
    if sweep_vol > avg_vol * 2.0:
        score += 1
    if break_vol > avg_vol * 1.5:
        score += 1
    if break_vol > avg_vol * 2.0:
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
    """Analyze single symbol for BOOF 31 v2 setups with both scoring systems"""
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
            
            # Score with both systems
            original_score = score_boof31_short_original(day, signal)
            volume_score = score_boof31_short_volume_expansion(day, signal)
            
            entry_i = signal["entry_i"]
            
            if entry_i >= len(day):
                continue
            
            entry_price = day.iloc[entry_i]["open"]
            
            # Measure MFE/MAE
            mfe, mae, hit_025, hit_050, hit_075 = measure_mfe_mae(day, entry_i, entry_price)
            
            results.append({
                "symbol": symbol,
                "date": date,
                "original_score": original_score,
                "volume_score": volume_score,
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

def analyze_score_buckets(results, score_type):
    """Analyze performance by score buckets"""
    score_col = f"{score_type}_score"
    
    print(f'\n' + '='*80)
    print(f'SCORE BUCKET ANALYSIS - {score_type.upper()} SCORING')
    print('='*80)
    print(f"{'Score':<8} {'Trades':<8} {'MFE':<10} {'MAE':<10} {'Hit .25':<10} {'Hit .50':<10} {'Hit .75':<10}")
    print('-'*80)
    
    for score in sorted(results[score_col].unique()):
        score_data = results[results[score_col] == score]
        trades = len(score_data)
        avg_mfe = score_data['mfe'].mean()
        avg_mae = score_data['mae'].mean()
        hit_025 = score_data['hit_025'].mean() * 100
        hit_050 = score_data['hit_050'].mean() * 100
        hit_075 = score_data['hit_075'].mean() * 100
        
        print(f"{score:<8} {trades:<8} {avg_mfe:<10.3%} {avg_mae:<10.3%} {hit_025:<10.1f} {hit_050:<10.1f} {hit_075:<10.1f}")
    
    # Best score analysis
    best_score = results.groupby(score_col)['mfe'].mean().idxmax()
    best_mfe = results[results[score_col] == best_score]['mfe'].mean()
    best_trades = len(results[results[score_col] == best_score])
    
    print(f'\nBest score: {best_score} (Avg MFE: {best_mfe:.3%}, Trades: {best_trades})')
    
    return best_score, best_mfe, best_trades

def compare_scoring_systems(results):
    """Compare original vs volume expansion scoring"""
    print('\n' + '='*80)
    print('SCORING SYSTEM COMPARISON')
    print('='*80)
    
    # Original scoring
    orig_best_score, orig_best_mfe, orig_trades = analyze_score_buckets(results, 'original')
    
    # Volume expansion scoring
    vol_best_score, vol_best_mfe, vol_trades = analyze_score_buckets(results, 'volume')
    
    # Overall comparison
    print('\n' + '='*60)
    print('OVERALL COMPARISON')
    print('='*60)
    print(f"Original Scoring:")
    print(f"  Best score: {orig_best_score}")
    print(f"  Best MFE: {orig_best_mfe:.3%}")
    print(f"  Trades at best score: {orig_trades}")
    
    print(f"\nVolume Expansion Scoring:")
    print(f"  Best score: {vol_best_score}")
    print(f"  Best MFE: {vol_best_mfe:.3%}")
    print(f"  Trades at best score: {vol_trades}")
    
    improvement = (vol_best_mfe - orig_best_mfe) / orig_best_mfe * 100 if orig_best_mfe > 0 else 0
    print(f"\nMFE Improvement: {improvement:.1f}%")

def run_analysis():
    """Main analysis runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - SCORE BUCKET + VOLUME EXPANSION ANALYSIS')
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
    
    # Compare scoring systems
    compare_scoring_systems(results)
    
    # Volume expansion analysis
    print('\n' + '='*80)
    print('VOLUME EXPANSION IMPACT ANALYSIS')
    print('='*80)
    
    # Analyze volume expansion impact
    vol_expansion_setups = results[results['volume_score'] >= 7]  # High volume scores
    regular_setups = results[results['volume_score'] < 7]
    
    if len(vol_expansion_setups) > 0 and len(regular_setups) > 0:
        print(f"High Volume Expansion Setups (Score >= 7):")
        print(f"  Trades: {len(vol_expansion_setups)}")
        print(f"  Avg MFE: {vol_expansion_setups['mfe'].mean():.3%}")
        print(f"  Hit 0.25%: {vol_expansion_setups['hit_025'].mean()*100:.1f}%")
        print(f"  Hit 0.50%: {vol_expansion_setups['hit_050'].mean()*100:.1f}%")
        
        print(f"\nRegular Setups (Score < 7):")
        print(f"  Trades: {len(regular_setups)}")
        print(f"  Avg MFE: {regular_setups['mfe'].mean():.3%}")
        print(f"  Hit 0.25%: {regular_setups['hit_025'].mean()*100:.1f}%")
        print(f"  Hit 0.50%: {regular_setups['hit_050'].mean()*100:.1f}%")
    
    # Save results
    results.to_csv('boof31v2_score_bucket_analysis.csv', index=False)
    
    print('\nSaved: boof31v2_score_bucket_analysis.csv')

if __name__ == '__main__':
    run_analysis()
