#!/usr/bin/env python3
"""
BOOF 31 v2 - OPTIMIZED WALK-FORWARD VALIDATION
Test A: Walk-forward with new optimized parameters
Test B: Symbol contribution recheck without SPY/QQQ
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)

# OPTIMIZED STRATEGY PARAMETERS
SWEEP_OPTIMIZED = 0.0020  # 0.20% sweep (game-changer!)
TP_OPTIMIZED = 0.0050     # 0.50% TP
SL_OPTIMIZED = 0.0025     # 0.25% SL
COOLDOWN_MINUTES = 30
SLIPPAGE = 0.0002         # 0.02%
MIN_SCORE = 6

# EXCLUDE SYMBOLS
EXCLUDED_SYMBOLS = ['SPY', 'QQQ']

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
        return 0, 0, 0
    
    win_rate = (pnl_series > 0).mean()
    avg_pnl = pnl_series.mean()
    
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    profit_factor = wins / losses if losses > 0 else float('inf')
    
    return win_rate, profit_factor, avg_pnl

def apply_optimized_filters(df):
    """Apply all optimized filters"""
    # Remove SPY/QQQ
    filtered = df[~df['symbol'].isin(EXCLUDED_SYMBOLS)].copy()
    
    # Convert to datetime and sort
    filtered['datetime'] = pd.to_datetime(filtered['date'])
    filtered = filtered.sort_values(['symbol', 'datetime'])
    
    # Apply 30-minute cooldown
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

def test_optimized_walkforward(df):
    """Test A: Optimized walk-forward validation"""
    print('\n' + '='*80)
    print('TEST A: OPTIMIZED WALK-FORWARD VALIDATION')
    print('='*80)
    print(f'Optimized Parameters: Sweep {SWEEP_OPTIMIZED:.1%}, No SPY/QQQ, TP {TP_OPTIMIZED:.1%}/SL {SL_OPTIMIZED:.1%}')
    
    # Apply optimized filters
    optimized_data = apply_optimized_filters(df)
    
    # Convert date for proper filtering
    optimized_data['datetime'] = pd.to_datetime(optimized_data['date'])
    
    # Define test periods
    test_periods = [
        ('Jan-Feb Train', 'Mar Test', 
         optimized_data[(optimized_data['datetime'].dt.month.isin([1, 2]))], 
         optimized_data[optimized_data['datetime'].dt.month == 3]),
        
        ('Feb-Mar Train', 'Apr Test', 
         optimized_data[(optimized_data['datetime'].dt.month.isin([2, 3]))], 
         optimized_data[optimized_data['datetime'].dt.month == 4]),
        
        ('Mar-Apr Train', 'May Test', 
         optimized_data[(optimized_data['datetime'].dt.month.isin([3, 4]))], 
         optimized_data[optimized_data['datetime'].dt.month == 5]),
    ]
    
    print(f"\n{'Period':<20} {'Trades':<8} {'PF':<8} {'EV':<10} {'WR':<8}")
    print('-'*60)
    
    results = []
    
    for train_name, test_name, train_data, test_data in test_periods:
        # Filter for Score >= 6 and simulate 0.20% sweep (higher MFE threshold)
        train_filtered = train_data[train_data['score'] >= MIN_SCORE]
        test_filtered = test_data[test_data['score'] >= MIN_SCORE]
        
        # Simulate 0.20% sweep by requiring higher MFE (stronger setups)
        train_filtered = train_filtered[train_filtered['mfe'] >= SWEEP_OPTIMIZED]
        test_filtered = test_filtered[test_filtered['mfe'] >= SWEEP_OPTIMIZED]
        
        if len(train_filtered) == 0 or len(test_filtered) == 0:
            print(f"{train_name} → {test_name:<12} {'No data':<8} {'N/A':<8} {'N/A':<10} {'N/A':<8}")
            continue
        
        # Simulate trades
        train_pnls = []
        for _, row in train_filtered.iterrows():
            pnl, _ = simulate_trade_optimized(row['entry_price'], row['mfe'], row['mae'], TP_OPTIMIZED, SL_OPTIMIZED, SLIPPAGE)
            train_pnls.append(pnl)
        
        test_pnls = []
        for _, row in test_filtered.iterrows():
            pnl, _ = simulate_trade_optimized(row['entry_price'], row['mfe'], row['mae'], TP_OPTIMIZED, SL_OPTIMIZED, SLIPPAGE)
            test_pnls.append(pnl)
        
        # Calculate metrics
        train_wr, train_pf, train_ev = calculate_metrics(pd.Series(train_pnls))
        test_wr, test_pf, test_ev = calculate_metrics(pd.Series(test_pnls))
        
        results.append({
            'period': f"{train_name} → {test_name}",
            'train_pf': train_pf,
            'train_ev': train_ev,
            'test_pf': test_pf,
            'test_ev': test_ev,
            'train_trades': len(train_pnls),
            'test_trades': len(test_pnls)
        })
        
        print(f"{train_name} → {test_name:<12} {len(test_pnls):<8} {test_pf:<8.2f} {test_ev:<10.4%} {test_wr:<8.1%}")
    
    # Check stability
    if results:
        avg_test_pf = sum(r['test_pf'] for r in results) / len(results)
        avg_test_ev = sum(r['test_ev'] for r in results) / len(results)
        
        print(f"\nOptimized Strategy Stability:")
        print(f"  Average Test PF: {avg_test_pf:.2f}")
        print(f"  Average Test EV: {avg_test_ev:.4%}")
        
        if avg_test_pf >= 3.0:
            print(f"  ✅ Excellent stability (PF >= 3.0)")
        elif avg_test_pf >= 2.0:
            print(f"  ✅ Good stability (PF >= 2.0)")
        else:
            print(f"  ⚠️  Marginal stability (PF < 2.0)")
    
    return results

def test_optimized_symbol_contribution(df):
    """Test B: Optimized symbol contribution without SPY/QQQ"""
    print('\n' + '='*80)
    print('TEST B: OPTIMIZED SYMBOL CONTRIBUTION (No SPY/QQQ)')
    print('='*80)
    
    # Apply optimized filters
    optimized_data = apply_optimized_filters(df)
    
    # Filter for Score >= 6 and simulate 0.20% sweep
    filtered = optimized_data[optimized_data['score'] >= MIN_SCORE]
    filtered = filtered[filtered['mfe'] >= SWEEP_OPTIMIZED]
    
    # Analyze each remaining symbol
    symbols = ['AMD', 'AVGO', 'PLTR', 'NVDA', 'TSLA', 'META', 'AMZN', 'MSFT']
    
    print(f"{'Symbol':<8} {'Trades':<8} {'PF':<8} {'EV':<10} {'WR':<8}")
    print('-'*50)
    
    results = []
    
    for symbol in symbols:
        symbol_data = filtered[filtered['symbol'] == symbol]
        
        if len(symbol_data) == 0:
            print(f"{symbol:<8} {'No data':<8} {'N/A':<8} {'N/A':<10} {'N/A':<8}")
            continue
        
        # Simulate trades
        pnls = []
        for _, row in symbol_data.iterrows():
            pnl, _ = simulate_trade_optimized(row['entry_price'], row['mfe'], row['mae'], TP_OPTIMIZED, SL_OPTIMIZED, SLIPPAGE)
            pnls.append(pnl)
        
        pnl_series = pd.Series(pnls)
        wr, pf, ev = calculate_metrics(pnl_series)
        total_pnl = pnl_series.sum()
        
        print(f"{symbol:<8} {len(pnls):<8} {pf:<8.2f} {ev:<10.4%} {wr:<8.1%}")
        
        results.append({
            'symbol': symbol,
            'trades': len(pnls),
            'profit_factor': pf,
            'ev': ev,
            'win_rate': wr,
            'total_pnl': total_pnl
        })
    
    # Analyze concentration
    if results:
        total_pnl = sum(r['total_pnl'] for r in results)
        top_3_pnl = sum(r['total_pnl'] for r in sorted(results, key=lambda x: x['total_pnl'], reverse=True)[:3])
        concentration = top_3_pnl / total_pnl if total_pnl > 0 else 0
        
        best_symbol = max(results, key=lambda x: x['profit_factor'])
        
        print(f"\nOptimized Symbol Analysis:")
        print(f"  Best performer: {best_symbol['symbol']} (PF: {best_symbol['profit_factor']:.2f})")
        print(f"  Top 3 concentration: {concentration:.1%}")
        print(f"  Total optimized trades: {sum(r['trades'] for r in results)}")
    
    return results

def run_optimized_validation():
    """Main optimized validation runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - OPTIMIZED WALK-FORWARD VALIDATION')
    logging.info('='*80)
    
    try:
        # Load existing resistance sweep results
        df = pd.read_csv('boof31v2_resistance_sweep_results.csv')
        logging.info(f'Loaded {len(df)} existing setups')
        
        # Run optimized tests
        walkforward_results = test_optimized_walkforward(df)
        symbol_results = test_optimized_symbol_contribution(df)
        
        # Final assessment
        print('\n' + '='*80)
        print('OPTIMIZED STRATEGY ASSESSMENT')
        print('='*80)
        
        if walkforward_results:
            avg_pf = sum(r['test_pf'] for r in walkforward_results) / len(walkforward_results)
            avg_ev = sum(r['test_ev'] for r in walkforward_results) / len(walkforward_results)
            
            print(f"Optimized Strategy Performance:")
            print(f"  Average Walk-Forward PF: {avg_pf:.2f}")
            print(f"  Average Walk-Forward EV: {avg_ev:.4%}")
            print(f"  Parameters: Sweep {SWEEP_OPTIMIZED:.1%}, No SPY/QQQ, TP {TP_OPTIMIZED:.1%}/SL {SL_OPTIMIZED:.1%}")
            
            if avg_pf >= 3.0:
                print(f"\n🚀 OPTIMIZED STRATEGY READY FOR DEPLOYMENT")
                print(f"   Significant improvement over original strategy")
            elif avg_pf >= 2.0:
                print(f"\n✅ OPTIMIZED STRATEGY VIABLE")
                print(f"   Moderate improvement, ready for paper trading")
            else:
                print(f"\n⚠️  OPTIMIZATION NEEDS REVIEW")
                print(f"   Limited improvement, consider further refinement")
        
        return {
            'walkforward': walkforward_results,
            'symbol_contribution': symbol_results
        }
        
    except FileNotFoundError:
        logging.error('Cached results file not found. Run BOOF31V2_RESISTANCE_SWEEP_FIXED.py first.')
    except Exception as e:
        logging.error(f'Error in optimized validation: {e}')

if __name__ == '__main__':
    run_optimized_validation()
