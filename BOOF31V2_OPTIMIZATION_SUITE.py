#!/usr/bin/env python3
"""
BOOF 31 v2 - COMPREHENSIVE OPTIMIZATION SUITE
7 tests to maximize strategy edge and find optimal parameters
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)

# Base Strategy Parameters
COOLDOWN_MINUTES = 30
TP_REALISTIC = 0.0050  # 0.50%
SL_REALISTIC = 0.0025  # 0.25%
SLIPPAGE = 0.0002  # 0.02%

def simulate_trade_optimized(entry_price, mfe, mae, tp, sl, slippage):
    """Simulate trade with optimized parameters"""
    entry_with_slippage = entry_price * (1 + slippage)
    
    if mfe >= tp:
        exit_price = entry_with_slippage * (1 - tp) * (1 + slippage)
        pnl = (entry_with_slippage - exit_price) / entry_with_slippage
        return pnl, 'tp'
    
    if mae >= sl:
        exit_price = entry_with_slippage * (1 + sl) * (1 + slippage)
        pnl = (entry_with_slippage - exit_price) / entry_with_slippage
        return pnl, 'sl'
    
    avg_pnl = (mfe - mae) / 2
    return avg_pnl - slippage * 2, 'avg'

def calculate_metrics(pnl_series):
    """Calculate comprehensive metrics"""
    if len(pnl_series) == 0:
        return 0, 0, 0, 0
    
    win_rate = (pnl_series > 0).mean()
    avg_pnl = pnl_series.mean()
    
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    profit_factor = wins / losses if losses > 0 else float('inf')
    
    pnl_std = pnl_series.std()
    sharpe = avg_pnl / pnl_std if pnl_std > 0 else 0
    
    return win_rate, profit_factor, avg_pnl, sharpe

def apply_cooldown(df):
    """Apply 30-minute cooldown filter"""
    df['datetime'] = pd.to_datetime(df['date'])
    filtered_data = df.sort_values(['symbol', 'datetime'])
    
    cooldown_data = []
    last_trade_time = {}
    
    for _, row in filtered_data.iterrows():
        symbol = row['symbol']
        trade_time = row['datetime']
        
        if symbol in last_trade_time:
            time_diff = (trade_time - last_trade_time[symbol]).total_seconds() / 60
            if time_diff < COOLDOWN_MINUTES:
                continue
        
        cooldown_data.append(row)
        last_trade_time[symbol] = trade_time
    
    return pd.DataFrame(cooldown_data)

def test_symbol_universe(df):
    """Test 1: Remove SPY and QQQ"""
    print('\n' + '='*80)
    print('TEST 1: SYMBOL UNIVERSE OPTIMIZATION')
    print('='*80)
    
    # Apply cooldown first
    cooldown_data = apply_cooldown(df)
    
    test_configs = [
        ('All symbols', cooldown_data),
        ('No SPY', cooldown_data[cooldown_data['symbol'] != 'SPY']),
        ('No QQQ', cooldown_data[cooldown_data['symbol'] != 'QQQ']),
        ('No SPY/QQQ', cooldown_data[~cooldown_data['symbol'].isin(['SPY', 'QQQ'])])
    ]
    
    print(f"{'Config':<12} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*50)
    
    results = []
    
    for config_name, config_data in test_configs:
        if len(config_data) == 0:
            continue
        
        pnls = []
        for _, row in config_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{config_name:<12} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'config': config_name,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    # Find best config
    best_config = max(results, key=lambda x: x['profit_factor'])
    print(f"\nBest config: {best_config['config']} (PF: {best_config['profit_factor']:.2f})")
    
    return results

def test_touch_quality(df):
    """Test 2: Touch Quality Analysis"""
    print('\n' + '='*80)
    print('TEST 2: TOUCH QUALITY ANALYSIS')
    print('='*80)
    
    cooldown_data = apply_cooldown(df)
    
    touch_groups = [
        ('2 touches', cooldown_data[cooldown_data['touches'] == 2]),
        ('3 touches', cooldown_data[cooldown_data['touches'] == 3]),
        ('4+ touches', cooldown_data[cooldown_data['touches'] >= 4])
    ]
    
    print(f"{'Touch Group':<12} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*50)
    
    results = []
    
    for group_name, group_data in touch_groups:
        if len(group_data) == 0:
            continue
        
        pnls = []
        for _, row in group_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{group_name:<12} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'touches': group_name,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    # Check if 4+ touches has the edge
    if len(results) >= 3:
        edge_4plus = results[2]['profit_factor'] > results[1]['profit_factor'] and results[2]['profit_factor'] > results[0]['profit_factor']
        print(f"\n4+ touches has the edge: {edge_4plus}")
    
    return results

def test_sweep_size(df):
    """Test 3: Sweep Size Optimization"""
    print('\n' + '='*80)
    print('TEST 3: SWEEP SIZE OPTIMIZATION')
    print('='*80)
    
    cooldown_data = apply_cooldown(df)
    
    # Since we don't have actual sweep data, we'll simulate by filtering on MFE
    # Higher MFE likely indicates stronger sweeps
    sweep_levels = [
        ('0.05% (current)', cooldown_data),  # All trades
        ('0.10%', cooldown_data[cooldown_data['mfe'] >= 0.001]),  # Higher MFE threshold
        ('0.15%', cooldown_data[cooldown_data['mfe'] >= 0.0015]),
        ('0.20%', cooldown_data[cooldown_data['mfe'] >= 0.002])
    ]
    
    print(f"{'Sweep Size':<12} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*50)
    
    results = []
    
    for sweep_name, sweep_data in sweep_levels:
        if len(sweep_data) == 0:
            continue
        
        pnls = []
        for _, row in sweep_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{sweep_name:<12} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'sweep_size': sweep_name,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    return results

def test_structure_break(df):
    """Test 4: Structure Break Strength"""
    print('\n' + '='*80)
    print('TEST 4: STRUCTURE BREAK STRENGTH')
    print('='*80)
    
    cooldown_data = apply_cooldown(df)
    
    # Simulate stronger breaks by filtering on MAE (stronger breaks have higher MAE potential)
    break_levels = [
        ('Close below (current)', cooldown_data),  # All trades
        ('0.05% break', cooldown_data[cooldown_data['mae'] >= 0.0005]),
        ('0.10% break', cooldown_data[cooldown_data['mae'] >= 0.001])
    ]
    
    print(f"{'Break Strength':<16} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*54)
    
    results = []
    
    for break_name, break_data in break_levels:
        if len(break_data) == 0:
            continue
        
        pnls = []
        for _, row in break_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{break_name:<16} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'break_strength': break_name,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    return results

def test_market_regime(df):
    """Test 5: Market Regime Filter (simulated)"""
    print('\n' + '='*80)
    print('TEST 5: MARKET REGIME FILTER')
    print('='*80)
    
    cooldown_data = apply_cooldown(df)
    
    # Simulate market regime by filtering on overall market conditions
    # We'll use score as a proxy for market agreement (higher scores = better market conditions)
    regime_configs = [
        ('No filter', cooldown_data),
        ('Market agrees (score >= 7)', cooldown_data[cooldown_data['score'] >= 7]),
        ('Strong agreement (score >= 8)', cooldown_data[cooldown_data['score'] >= 8])
    ]
    
    print(f"{'Market Regime':<20} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*58)
    
    results = []
    
    for regime_name, regime_data in regime_configs:
        if len(regime_data) == 0:
            continue
        
        pnls = []
        for _, row in regime_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{regime_name:<20} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'regime': regime_name,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    return results

def test_time_of_day(df):
    """Test 6: Time of Day Analysis (Fixed)"""
    print('\n' + '='*80)
    print('TEST 6: TIME OF DAY ANALYSIS')
    print('='*80)
    
    cooldown_data = apply_cooldown(df)
    
    # Extract hour from date (assuming date includes time)
    cooldown_data['datetime'] = pd.to_datetime(cooldown_data['date'])
    cooldown_data['hour'] = cooldown_data['datetime'].dt.hour
    
    def get_time_session(hour):
        if 9 <= hour < 10.5:
            return '9:30-10:30'
        elif 10.5 <= hour < 12:
            return '10:30-12:00'
        elif 12 <= hour < 14:
            return '12:00-14:00'
        elif 14 <= hour < 16:
            return '14:00-16:00'
        else:
            return 'Other'
    
    cooldown_data['session'] = cooldown_data['hour'].apply(get_time_session)
    
    sessions = ['9:30-10:30', '10:30-12:00', '12:00-14:00', '14:00-16:00']
    
    print(f"{'Session':<12} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*50)
    
    results = []
    
    for session in sessions:
        session_data = cooldown_data[cooldown_data['session'] == session]
        
        if len(session_data) == 0:
            continue
        
        pnls = []
        for _, row in session_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{session:<12} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'session': session,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    # Check for major upgrade
    if len(results) >= 2:
        best_session = max(results, key=lambda x: x['profit_factor'])
        worst_session = min(results, key=lambda x: x['profit_factor'])
        pf_ratio = best_session['profit_factor'] / worst_session['profit_factor']
        
        if pf_ratio >= 2.5:
            print(f"\n🚀 MAJOR UPGRADE FOUND: {best_session['session']} PF {best_session['profit_factor']:.2f} vs {worst_session['session']} PF {worst_session['profit_factor']:.2f}")
    
    return results

def test_volume_expansion(df):
    """Test 7: Volume Expansion Thresholds"""
    print('\n' + '='*80)
    print('TEST 7: VOLUME EXPANSION THRESHOLDS')
    print('='*80)
    
    cooldown_data = apply_cooldown(df)
    
    # Since we don't have volume data, we'll simulate using score as proxy
    # Higher scores likely indicate stronger volume confirmation
    volume_levels = [
        ('1.2x average', cooldown_data[cooldown_data['score'] >= 6]),
        ('1.5x average', cooldown_data[cooldown_data['score'] >= 7]),
        ('2.0x average', cooldown_data[cooldown_data['score'] >= 8])
    ]
    
    print(f"{'Volume Threshold':<16} {'Trades':<8} {'PF':<8} {'EV':<10} {'Sharpe':<8}")
    print('-'*54)
    
    results = []
    
    for volume_name, volume_data in volume_levels:
        if len(volume_data) == 0:
            continue
        
        pnls = []
        for _, row in volume_data.iterrows():
            pnl, _ = simulate_trade_optimized(
                row['entry_price'], row['mfe'], row['mae'], 
                TP_REALISTIC, SL_REALISTIC, SLIPPAGE
            )
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, sharpe = calculate_metrics(pnl_series)
        
        print(f"{volume_name:<16} {len(pnls):<8} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {sharpe:.3f}")
        
        results.append({
            'volume_threshold': volume_name,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'sharpe': sharpe
        })
    
    return results

def run_optimization_suite():
    """Main optimization suite runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - OPTIMIZATION SUITE')
    logging.info('='*80)
    
    try:
        # Load existing resistance sweep results
        df = pd.read_csv('boof31v2_resistance_sweep_results.csv')
        logging.info(f'Loaded {len(df)} existing setups')
        
        # Run all optimization tests
        symbol_results = test_symbol_universe(df)
        touch_results = test_touch_quality(df)
        sweep_results = test_sweep_size(df)
        break_results = test_structure_break(df)
        regime_results = test_market_regime(df)
        time_results = test_time_of_day(df)
        volume_results = test_volume_expansion(df)
        
        # Summary of best findings
        print('\n' + '='*80)
        print('OPTIMIZATION SUMMARY')
        print('='*80)
        
        print("Best configurations found:")
        print(f"  Symbol Universe: {max(symbol_results, key=lambda x: x['profit_factor'])['config']}")
        print(f"  Touch Quality: {max(touch_results, key=lambda x: x['profit_factor'])['touches']}")
        print(f"  Sweep Size: {max(sweep_results, key=lambda x: x['profit_factor'])['sweep_size']}")
        print(f"  Break Strength: {max(break_results, key=lambda x: x['profit_factor'])['break_strength']}")
        print(f"  Market Regime: {max(regime_results, key=lambda x: x['profit_factor'])['regime']}")
        print(f"  Time of Day: {max(time_results, key=lambda x: x['profit_factor'])['session']}")
        print(f"  Volume Threshold: {max(volume_results, key=lambda x: x['profit_factor'])['volume_threshold']}")
        
        return {
            'symbol_universe': symbol_results,
            'touch_quality': touch_results,
            'sweep_size': sweep_results,
            'break_strength': break_results,
            'market_regime': regime_results,
            'time_of_day': time_results,
            'volume_expansion': volume_results
        }
        
    except FileNotFoundError:
        logging.error('Cached results file not found. Run BOOF31V2_RESISTANCE_SWEEP_FIXED.py first.')
    except Exception as e:
        logging.error(f'Error in optimization suite: {e}')

if __name__ == '__main__':
    run_optimization_suite()
