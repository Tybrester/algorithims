#!/usr/bin/env python3
"""
BOOF 31 v2 - EXIT STRATEGY OPTIMIZATION
Test 4 different exit strategies to maximize profitability
"""

import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)

# OPTIMIZED STRATEGY PARAMETERS
SWEEP_OPTIMIZED = 0.0020  # 0.20% sweep
SL_OPTIMIZED = 0.0025     # 0.25% SL
COOLDOWN_MINUTES = 30
MIN_SCORE = 6
EXCLUDED_SYMBOLS = ['SPY', 'QQQ']
SLIPPAGE = 0.0005         # 0.05% slippage

def simulate_exit_strategy(entry_price, mfe, mae, strategy):
    """
    Simulate different exit strategies
    Returns: (total_pnl, exit_details)
    """
    entry_with_slippage = entry_price * (1 + SLIPPAGE)
    
    if strategy == 'A':  # 100% at 0.50%
        tp1 = 0.0050  # 0.50%
        
        if mfe >= tp1:
            exit_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            pnl = (entry_with_slippage - exit_price) / entry_with_slippage
            return pnl, {'type': 'TP1', 'pnl': pnl}
        
        if mae >= SL_OPTIMIZED:
            exit_price = entry_with_slippage * (1 + SL_OPTIMIZED) * (1 + SLIPPAGE)
            pnl = (entry_with_slippage - exit_price) / entry_with_slippage
            return pnl, {'type': 'SL', 'pnl': pnl}
        
        # Average outcome
        avg_pnl = (mfe - mae) / 2 - SLIPPAGE * 2
        return avg_pnl, {'type': 'AVG', 'pnl': avg_pnl}
    
    elif strategy == 'B':  # 50% at 0.50%, 50% at 1.00%
        tp1 = 0.0050  # 0.50%
        tp2 = 0.0100  # 1.00%
        
        if mfe >= tp2:
            # Both targets hit
            exit1_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            exit2_price = entry_with_slippage * (1 - tp2) * (1 + SLIPPAGE)
            pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.5
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
            total_pnl = pnl1 + pnl2
            return total_pnl, {'type': 'TP2', 'pnl': total_pnl, 'partial1': pnl1, 'partial2': pnl2}
        
        elif mfe >= tp1:
            # First target hit, second missed
            exit1_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.5
            # Second half at average outcome
            pnl2 = ((mfe - tp1) - mae) / 2 * 0.5 - SLIPPAGE
            total_pnl = pnl1 + pnl2
            return total_pnl, {'type': 'TP1_PARTIAL', 'pnl': total_pnl, 'partial1': pnl1, 'partial2': pnl2}
        
        if mae >= SL_OPTIMIZED:
            exit_price = entry_with_slippage * (1 + SL_OPTIMIZED) * (1 + SLIPPAGE)
            pnl = (entry_with_slippage - exit_price) / entry_with_slippage
            return pnl, {'type': 'SL', 'pnl': pnl}
        
        # Average outcome
        avg_pnl = (mfe - mae) / 2 - SLIPPAGE * 2
        return avg_pnl, {'type': 'AVG', 'pnl': avg_pnl}
    
    elif strategy == 'C':  # 50% at 0.50%, remaining trailing
        tp1 = 0.0050  # 0.50%
        
        if mfe >= tp1:
            # First 50% at 0.50%
            exit1_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.5
            
            # Remaining 50% with trailing stop (0.25% from peak or SL, whichever is worse)
            trailing_stop = max(SL_OPTIMIZED, mfe - 0.0025)  # 0.25% trailing or SL
            
            if mae >= trailing_stop:
                exit2_price = entry_with_slippage * (1 + trailing_stop) * (1 + SLIPPAGE)
                pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
            else:
                # Use MFE for remaining (best case for trailing)
                exit2_price = entry_with_slippage * (1 - mfe) * (1 + SLIPPAGE)
                pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
            
            total_pnl = pnl1 + pnl2
            return total_pnl, {'type': 'TP1_TRAIL', 'pnl': total_pnl, 'partial1': pnl1, 'partial2': pnl2}
        
        if mae >= SL_OPTIMIZED:
            exit_price = entry_with_slippage * (1 + SL_OPTIMIZED) * (1 + SLIPPAGE)
            pnl = (entry_with_slippage - exit_price) / entry_with_slippage
            return pnl, {'type': 'SL', 'pnl': pnl}
        
        # Average outcome
        avg_pnl = (mfe - mae) / 2 - SLIPPAGE * 2
        return avg_pnl, {'type': 'AVG', 'pnl': avg_pnl}
    
    elif strategy == 'D':  # 33% at 0.50%, 33% at 0.75%, 34% at 1.00%
        tp1 = 0.0050  # 0.50%
        tp2 = 0.0075  # 0.75%
        tp3 = 0.0100  # 1.00%
        
        if mfe >= tp3:
            # All targets hit
            exit1_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            exit2_price = entry_with_slippage * (1 - tp2) * (1 + SLIPPAGE)
            exit3_price = entry_with_slippage * (1 - tp3) * (1 + SLIPPAGE)
            pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.33
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.33
            pnl3 = (entry_with_slippage - exit3_price) / entry_with_slippage * 0.34
            total_pnl = pnl1 + pnl2 + pnl3
            return total_pnl, {'type': 'TP3', 'pnl': total_pnl, 'partial1': pnl1, 'partial2': pnl2, 'partial3': pnl3}
        
        elif mfe >= tp2:
            # First two targets hit
            exit1_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            exit2_price = entry_with_slippage * (1 - tp2) * (1 + SLIPPAGE)
            pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.33
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.33
            # Third at average
            pnl3 = ((mfe - tp2) - mae) / 2 * 0.34 - SLIPPAGE
            total_pnl = pnl1 + pnl2 + pnl3
            return total_pnl, {'type': 'TP2_PARTIAL', 'pnl': total_pnl, 'partial1': pnl1, 'partial2': pnl2, 'partial3': pnl3}
        
        elif mfe >= tp1:
            # First target hit only
            exit1_price = entry_with_slippage * (1 - tp1) * (1 + SLIPPAGE)
            pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.33
            # Remaining at average
            pnl_remaining = ((mfe - tp1) - mae) / 2 * 0.67 - SLIPPAGE
            total_pnl = pnl1 + pnl_remaining
            return total_pnl, {'type': 'TP1_PARTIAL', 'pnl': total_pnl, 'partial1': pnl1, 'partial_remaining': pnl_remaining}
        
        if mae >= SL_OPTIMIZED:
            exit_price = entry_with_slippage * (1 + SL_OPTIMIZED) * (1 + SLIPPAGE)
            pnl = (entry_with_slippage - exit_price) / entry_with_slippage
            return pnl, {'type': 'SL', 'pnl': pnl}
        
        # Average outcome
        avg_pnl = (mfe - mae) / 2 - SLIPPAGE * 2
        return avg_pnl, {'type': 'AVG', 'pnl': avg_pnl}

def calculate_metrics(pnl_series):
    """Calculate comprehensive metrics"""
    if len(pnl_series) == 0:
        return 0, 0, 0, 0
    
    win_rate = (pnl_series > 0).mean()
    avg_pnl = pnl_series.mean()
    
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    profit_factor = wins / losses if losses > 0 else float('inf')
    
    return win_rate, profit_factor, avg_pnl, len(pnl_series)

def apply_optimized_filters(df):
    """Apply optimized filters"""
    filtered = df[~df['symbol'].isin(EXCLUDED_SYMBOLS)].copy()
    filtered['datetime'] = pd.to_datetime(filtered['date'])
    filtered = filtered.sort_values(['symbol', 'datetime'])
    
    cooldown_data = []
    last_trade_time = {}
    
    for _, row in filtered.iterrows():
        symbol = row['symbol']
        trade_time = row['datetime']
        
        if symbol in last_trade_time:
            time_diff = (trade_time - last_trade_time[symbol]).total_seconds() / 60
            if time_diff < COOLDOWN_MINUTES:
                continue
        
        cooldown_data.append(row)
        last_trade_time[symbol] = trade_time
    
    return pd.DataFrame(cooldown_data)

def test_exit_strategies(df):
    """Test all 4 exit strategies"""
    print('\n' + '='*80)
    print('EXIT STRATEGY OPTIMIZATION')
    print('='*80)
    
    # Apply optimized filters
    optimized_data = apply_optimized_filters(df)
    filtered = optimized_data[optimized_data['score'] >= MIN_SCORE]
    filtered = filtered[filtered['mfe'] >= SWEEP_OPTIMIZED]
    
    print(f"Total optimized setups: {len(filtered)}")
    
    strategies = {
        'A': 'Exit A: 100% at 0.50%',
        'B': 'Exit B: 50% at 0.50%, 50% at 1.00%',
        'C': 'Exit C: 50% at 0.50% + trailing stop',
        'D': 'Exit D: 33% at 0.50%, 33% at 0.75%, 34% at 1.00%'
    }
    
    print(f"\n{'Strategy':<40} {'Trades':<8} {'Win Rate':<10} {'PF':<8} {'EV':<10} {'Total PnL':<12}")
    print('-'*100)
    
    results = {}
    
    for strategy_code, strategy_name in strategies.items():
        pnls = []
        exit_types = []
        
        for _, row in filtered.iterrows():
            pnl, exit_details = simulate_exit_strategy(row['entry_price'], row['mfe'], row['mae'], strategy_code)
            pnls.append(pnl)
            exit_types.append(exit_details['type'])
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev, trades = calculate_metrics(pnl_series)
        total_pnl = pnl_series.sum()
        
        print(f"{strategy_name:<40} {trades:<8} {wr:.1%}{'':<6} {pf:.2f}{'':<5} {ev:.4%}{'':<7} {total_pnl:.2%}")
        
        # Analyze exit types
        exit_type_counts = pd.Series(exit_types).value_counts()
        
        results[strategy_code] = {
            'name': strategy_name,
            'trades': trades,
            'win_rate': wr,
            'profit_factor': pf,
            'ev': ev,
            'total_pnl': total_pnl,
            'exit_types': exit_type_counts.to_dict()
        }
    
    # Detailed analysis
    print(f"\nDETAILED EXIT ANALYSIS:")
    print('='*80)
    
    for strategy_code, result in results.items():
        print(f"\n{result['name']}:")
        print(f"  Exit Type Distribution:")
        for exit_type, count in result['exit_types'].items():
            percentage = count / result['trades'] * 100
            print(f"    {exit_type}: {count} ({percentage:.1f}%)")
    
    # Find best strategy
    best_strategy = max(results.values(), key=lambda x: x['profit_factor'])
    
    print(f"\n{'='*80}")
    print(f"BEST EXIT STRATEGY: {best_strategy['name']}")
    print(f"  Profit Factor: {best_strategy['profit_factor']:.2f}")
    print(f"  EV: {best_strategy['ev']:.4%}")
    print(f"  Win Rate: {best_strategy['win_rate']:.1%}")
    print(f"  Total Return: {best_strategy['total_pnl']:.2%}")
    
    # Comparison to baseline (Exit A)
    baseline_pf = results['A']['profit_factor']
    baseline_ev = results['A']['ev']
    
    print(f"\nIMPROVEMENT OVER BASELINE (Exit A):")
    for strategy_code, result in results.items():
        if strategy_code != 'A':
            pf_improvement = (result['profit_factor'] - baseline_pf) / baseline_pf * 100
            ev_improvement = (result['ev'] - baseline_ev) / baseline_ev * 100 if baseline_ev > 0 else 0
            
            print(f"  {result['name']}:")
            print(f"    PF improvement: {pf_improvement:+.1f}%")
            print(f"    EV improvement: {ev_improvement:+.1f}%")
    
    return results

def run_exit_optimization():
    """Main exit optimization runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - EXIT STRATEGY OPTIMIZATION')
    logging.info('='*80)
    
    try:
        # Load existing resistance sweep results
        df = pd.read_csv('boof31v2_resistance_sweep_results.csv')
        logging.info(f'Loaded {len(df)} existing setups')
        
        # Run exit strategy tests
        results = test_exit_strategies(df)
        
        # Final recommendation
        print(f"\n{'='*80}")
        print('FINAL EXIT STRATEGY RECOMMENDATION')
        print('='*80)
        
        best_strategy = max(results.values(), key=lambda x: x['profit_factor'])
        
        print(f"RECOMMENDED EXIT STRATEGY:")
        print(f"  {best_strategy['name']}")
        print(f"  Expected Profit Factor: {best_strategy['profit_factor']:.2f}")
        print(f"  Expected EV: {best_strategy['ev']:.4%}")
        print(f"  Win Rate: {best_strategy['win_rate']:.1%}")
        
        # Implementation notes
        if best_strategy['name'].startswith('Exit B'):
            print(f"\nIMPLEMENTATION NOTES:")
            print(f"  - Use bracket orders for partial exits")
            print(f"  - First exit at 0.50% for 50% position")
            print(f"  - Second exit at 1.00% for remaining 50%")
        elif best_strategy['name'].startswith('Exit C'):
            print(f"\nIMPLEMENTATION NOTES:")
            print(f"  - First exit at 0.50% for 50% position")
            print(f"  - Implement 0.25% trailing stop on remaining")
            print(f"  - Or use 5-bar low trailing stop")
        elif best_strategy['name'].startswith('Exit D'):
            print(f"\nIMPLEMENTATION NOTES:")
            print(f"  - Use OCO orders for three-tier exits")
            print(f"  - 33% at 0.50%, 33% at 0.75%, 34% at 1.00%")
        
        return results
        
    except FileNotFoundError:
        logging.error('Cached results file not found. Run BOOF31V2_RESISTANCE_SWEEP_FIXED.py first.')
    except Exception as e:
        logging.error(f'Error in exit optimization: {e}')

if __name__ == '__main__':
    run_exit_optimization()
