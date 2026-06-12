#!/usr/bin/env python3
"""
BOOF 31 v2 - EXIT C HIGH SLIPPAGE TEST
Test Exit C with 0.10% slippage to verify runner capture effectiveness
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
HIGH_SLIPPAGE = 0.0010    # 0.10% slippage

def simulate_exit_c_high_slippage(entry_price, mfe, mae):
    """
    Simulate Exit C with 0.10% slippage:
    50% at 0.50% + trailing stop on remaining
    """
    entry_with_slippage = entry_price * (1 + HIGH_SLIPPAGE)
    tp1 = 0.0050  # 0.50%
    
    if mfe >= tp1:
        # First 50% at 0.50%
        exit1_price = entry_with_slippage * (1 - tp1) * (1 + HIGH_SLIPPAGE)
        pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.5
        
        # Remaining 50% with trailing stop (0.25% from peak or SL, whichever is worse)
        trailing_stop = max(SL_OPTIMIZED, mfe - 0.0025)  # 0.25% trailing or SL
        
        if mae >= trailing_stop:
            exit2_price = entry_with_slippage * (1 + trailing_stop) * (1 + HIGH_SLIPPAGE)
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
        else:
            # Use MFE for remaining (best case for trailing)
            exit2_price = entry_with_slippage * (1 - mfe) * (1 + HIGH_SLIPPAGE)
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
        
        total_pnl = pnl1 + pnl2
        return total_pnl, {'type': 'TP1_TRAIL', 'pnl': total_pnl, 'partial1': pnl1, 'partial2': pnl2}
    
    if mae >= SL_OPTIMIZED:
        exit_price = entry_with_slippage * (1 + SL_OPTIMIZED) * (1 + HIGH_SLIPPAGE)
        pnl = (entry_with_slippage - exit_price) / entry_with_slippage
        return pnl, {'type': 'SL', 'pnl': pnl}
    
    # Average outcome
    avg_pnl = (mfe - mae) / 2 - HIGH_SLIPPAGE * 2
    return avg_pnl, {'type': 'AVG', 'pnl': avg_pnl}

def calculate_metrics(pnl_series):
    """Calculate comprehensive metrics"""
    if len(pnl_series) == 0:
        return 0, 0, 0
    
    win_rate = (pnl_series > 0).mean()
    avg_pnl = pnl_series.mean()
    
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    profit_factor = wins / losses if losses > 0 else float('inf')
    
    return win_rate, profit_factor, avg_pnl

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

def test_exit_c_high_slippage(df):
    """Test Exit C with 0.10% slippage"""
    print('\n' + '='*80)
    print('EXIT C WITH 0.10% SLIPPAGE TEST')
    print('='*80)
    
    # Apply optimized filters
    optimized_data = apply_optimized_filters(df)
    filtered = optimized_data[optimized_data['score'] >= MIN_SCORE]
    filtered = filtered[filtered['mfe'] >= SWEEP_OPTIMIZED]
    
    print(f"Total optimized setups: {len(filtered)}")
    print(f"Testing Exit C: 50% at 0.50% + trailing stop")
    print(f"Slippage: 0.10% (high stress test)")
    
    # Simulate trades
    pnls = []
    exit_types = []
    partial1_pnls = []
    partial2_pnls = []
    
    for _, row in filtered.iterrows():
        pnl, exit_details = simulate_exit_c_high_slippage(row['entry_price'], row['mfe'], row['mae'])
        pnls.append(pnl)
        exit_types.append(exit_details['type'])
        
        if 'partial1' in exit_details:
            partial1_pnls.append(exit_details['partial1'])
        if 'partial2' in exit_details:
            partial2_pnls.append(exit_details['partial2'])
    
    # Calculate metrics
    pnl_series = pd.Series(pnls)
    wr, pf, ev = calculate_metrics(pnl_series)
    total_pnl = pnl_series.sum()
    
    print(f"\n{'Metric':<20} {'Value':<15}")
    print('-'*35)
    print(f"{'Trades':<20} {len(pnls):<15}")
    print(f"{'Win Rate':<20} {wr:.1%}")
    print(f"{'Profit Factor':<20} {pf:.2f}")
    print(f"{'EV':<20} {ev:.4%}")
    print(f"{'Total Return':<20} {total_pnl:.2%}")
    
    # Exit type analysis
    exit_type_counts = pd.Series(exit_types).value_counts()
    print(f"\nExit Type Distribution:")
    for exit_type, count in exit_type_counts.items():
        percentage = count / len(pnls) * 100
        print(f"  {exit_type}: {count} ({percentage:.1f}%)")
    
    # Partial exit analysis
    if partial1_pnls and partial2_pnls:
        avg_partial1 = np.mean(partial1_pnls)
        avg_partial2 = np.mean(partial2_pnls)
        
        print(f"\nPartial Exit Analysis (for TP1_TRAIL exits):")
        print(f"  Average 0.50% exit (50%): {avg_partial1:.4%}")
        print(f"  Average trailing exit (50%): {avg_partial2:.4%}")
        print(f"  Trailing contribution: {avg_partial2/(avg_partial1+avg_partial2)*100:.1f}% of total profit")
    
    # Runner capture analysis
    tp1_trail_trades = exit_type_counts.get('TP1_TRAIL', 0)
    runner_capture_rate = tp1_trail_trades / len(pnls) if len(pnls) > 0 else 0
    
    print(f"\nRunner Capture Analysis:")
    print(f"  Trades hitting 0.50%: {runner_capture_rate:.1%}")
    print(f"  These trades can capture runners with trailing stop")
    
    # High slippage impact assessment
    print(f"\nHigh Slippage Impact Assessment:")
    print(f"  Previous PF (0.05% slippage): 4.70")
    print(f"  Current PF (0.10% slippage): {pf:.2f}")
    
    pf_degradation = (4.70 - pf) / 4.70 * 100
    ev_degradation = (0.3020 - ev) / 0.3020 * 100 if ev > 0 else 0
    
    print(f"  PF degradation: {pf_degradation:.1f}%")
    print(f"  EV degradation: {ev_degradation:.1f}%")
    
    # Final assessment
    print(f"\nFINAL ASSESSMENT:")
    if pf >= 3.0:
        print(f"  ✅ Exit C survives high slippage (PF >= 3.0)")
        print(f"  ✅ Runner capture strategy remains effective")
    elif pf >= 2.0:
        print(f"  ⚠️  Exit C marginal with high slippage (PF >= 2.0)")
        print(f"  ⚠️  Consider reducing slippage or position size")
    else:
        print(f"  ❌ Exit C fails with high slippage (PF < 2.0)")
        print(f"  ❌  Runner capture strategy not viable at this slippage level")
    
    return {
        'trades': len(pnls),
        'win_rate': wr,
        'profit_factor': pf,
        'ev': ev,
        'total_pnl': total_pnl,
        'exit_types': exit_type_counts.to_dict(),
        'runner_capture_rate': runner_capture_rate,
        'pf_degradation': pf_degradation,
        'ev_degradation': ev_degradation
    }

def run_exit_c_high_slippage_test():
    """Main test runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - EXIT C HIGH SLIPPAGE TEST')
    logging.info('='*80)
    
    try:
        # Load existing resistance sweep results
        df = pd.read_csv('boof31v2_resistance_sweep_results.csv')
        logging.info(f'Loaded {len(df)} existing setups')
        
        # Run test
        results = test_exit_c_high_slippage(df)
        
        return results
        
    except FileNotFoundError:
        logging.error('Cached results file not found. Run BOOF31V2_RESISTANCE_SWEEP_FIXED.py first.')
    except Exception as e:
        logging.error(f'Error in Exit C high slippage test: {e}')

if __name__ == '__main__':
    run_exit_c_high_slippage_test()
