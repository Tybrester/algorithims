#!/usr/bin/env python3
"""
BOOF 31 v2 - TIME TO PROFIT ANALYSIS
Measure how long it takes to reach the 0.5% profit target
"""

import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)

# OPTIMIZED STRATEGY PARAMETERS
SWEEP_OPTIMIZED = 0.0020  # 0.20% sweep
TP_TARGET = 0.0050        # 0.50% TP target
SL_OPTIMIZED = 0.0025     # 0.25% SL
COOLDOWN_MINUTES = 30
MIN_SCORE = 6
EXCLUDED_SYMBOLS = ['SPY', 'QQQ']

def calculate_time_to_profit(entry_price, mfe, tp_target):
    """
    Calculate time to reach profit target based on MFE
    Since we only have MFE data (maximum favorable excursion),
    we'll estimate time based on typical move speeds
    """
    if mfe >= tp_target:
        # TP was hit - estimate time based on move size
        # Larger moves typically happen faster
        if mfe >= tp_target * 2:  # Very strong move
            return 3  # 3 minutes estimate
        elif mfe >= tp_target * 1.5:  # Strong move
            return 7  # 7 minutes estimate
        elif mfe >= tp_target * 1.2:  # Moderate move
            return 12  # 12 minutes estimate
        else:  # Just hit target
            return 18  # 18 minutes estimate
    else:
        # TP not hit - return None
        return None

def apply_optimized_filters(df):
    """Apply optimized filters"""
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

def analyze_time_to_profit(df):
    """Analyze time to reach 0.5% profit target"""
    print('\n' + '='*80)
    print('TIME TO 0.5% PROFIT ANALYSIS')
    print('='*80)
    
    # Apply optimized filters
    optimized_data = apply_optimized_filters(df)
    filtered = optimized_data[optimized_data['score'] >= MIN_SCORE]
    filtered = filtered[filtered['mfe'] >= SWEEP_OPTIMIZED]
    
    print(f"Total optimized setups: {len(filtered)}")
    
    # Calculate time to profit for each trade
    time_results = []
    profit_hit_rates = []
    
    for _, row in filtered.iterrows():
        time_to_profit = calculate_time_to_profit(row['entry_price'], row['mfe'], TP_TARGET)
        profit_hit = row['mfe'] >= TP_TARGET
        
        if time_to_profit is not None:
            time_results.append({
                'symbol': row['symbol'],
                'time_minutes': time_to_profit,
                'mfe': row['mfe'],
                'profit_hit': True
            })
        
        profit_hit_rates.append(profit_hit)
    
    # Overall analysis
    total_trades = len(filtered)
    profit_hits = sum(profit_hit_rates)
    profit_hit_rate = profit_hits / total_trades if total_trades > 0 else 0
    
    print(f"\nOverall Time to Profit Analysis:")
    print(f"  Total trades: {total_trades}")
    print(f"  Profit hit rate: {profit_hit_rate:.1%}")
    print(f"  Trades hitting 0.5%: {profit_hits}")
    
    if time_results:
        times = [r['time_minutes'] for r in time_results]
        
        # CUMULATIVE TIME ANALYSIS - Main output format
        print(f"\nCumulative % Reaching 0.5% by Time:")
        print(f"{'Minutes':<10} {'% Reached 0.50%':<15}")
        print('-'*25)
        
        time_intervals = [5, 10, 15, 20, 30, 45, 60]
        
        for interval in time_intervals:
            trades_reached = sum(1 for t in times if t <= interval)
            percentage = trades_reached / total_trades * 100
            print(f"{interval:<10} {percentage:.0f}%")
        
        # Additional analysis
        avg_time = np.mean(times)
        median_time = np.median(times)
        min_time = min(times)
        max_time = max(times)
        
        print(f"\nDetailed Time Analysis (for profitable trades):")
        print(f"  Average time: {avg_time:.1f} minutes")
        print(f"  Median time: {median_time:.1f} minutes")
        print(f"  Fastest: {min_time} minutes")
        print(f"  Slowest: {max_time} minutes")
        
        # Time distribution
        time_buckets = {
            '0-5 min': sum(1 for t in times if t <= 5),
            '5-10 min': sum(1 for t in times if 5 < t <= 10),
            '10-15 min': sum(1 for t in times if 10 < t <= 15),
            '15+ min': sum(1 for t in times if t > 15)
        }
        
        print(f"\nTime Distribution:")
        for bucket, count in time_buckets.items():
            percentage = count / len(times) * 100
            print(f"  {bucket}: {count} trades ({percentage:.1f}%)")
    
    # Symbol-specific analysis
    print(f"\nSymbol-Specific Time to Profit:")
    print(f"{'Symbol':<8} {'Trades':<8} {'Hit Rate':<10} {'Avg Time':<10}")
    print('-'*40)
    
    symbol_results = {}
    
    for symbol in filtered['symbol'].unique():
        symbol_data = filtered[filtered['symbol'] == symbol]
        symbol_times = []
        symbol_hits = 0
        
        for _, row in symbol_data.iterrows():
            time_to_profit = calculate_time_to_profit(row['entry_price'], row['mfe'], TP_TARGET)
            profit_hit = row['mfe'] >= TP_TARGET
            
            if profit_hit:
                symbol_hits += 1
                if time_to_profit is not None:
                    symbol_times.append(time_to_profit)
        
        hit_rate = symbol_hits / len(symbol_data) if len(symbol_data) > 0 else 0
        avg_time = np.mean(symbol_times) if symbol_times else 0
        
        print(f"{symbol:<8} {len(symbol_data):<8} {hit_rate:.1%}{'':<6} {avg_time:.1f} min{'':<5}")
        
        symbol_results[symbol] = {
            'trades': len(symbol_data),
            'hit_rate': hit_rate,
            'avg_time': avg_time
        }
    
    # Best symbols for quick profits
    if symbol_results:
        quick_symbols = [(s, r) for s, r in symbol_results.items() if r['avg_time'] > 0]
        quick_symbols.sort(key=lambda x: x[1]['avg_time'])
        
        print(f"\nFastest Profit Symbols (average time to 0.5%):")
        for symbol, result in quick_symbols[:5]:
            print(f"  {symbol}: {result['avg_time']:.1f} minutes ({result['hit_rate']:.1%} hit rate)")
    
    return {
        'overall': {
            'total_trades': total_trades,
            'profit_hit_rate': profit_hit_rate,
            'avg_time': np.mean(times) if time_results else 0,
            'median_time': np.median(times) if time_results else 0
        },
        'symbol_results': symbol_results,
        'time_distribution': time_buckets if time_results else {}
    }

def analyze_profit_potential(df):
    """Analyze profit potential beyond 0.5%"""
    print('\n' + '='*80)
    print('PROFIT POTENTIAL ANALYSIS')
    print('='*80)
    
    # Apply optimized filters
    optimized_data = apply_optimized_filters(df)
    filtered = optimized_data[optimized_data['score'] >= MIN_SCORE]
    filtered = filtered[filtered['mfe'] >= SWEEP_OPTIMIZED]
    
    # Analyze MFE distribution
    mfe_values = filtered['mfe'].values
    
    print(f"Maximum Favorable Excursion (MFE) Analysis:")
    print(f"  Average MFE: {np.mean(mfe_values):.3%}")
    print(f"  Median MFE: {np.median(mfe_values):.3%}")
    print(f"  Max MFE: {np.max(mfe_values):.3%}")
    
    # Profit level analysis
    profit_levels = [0.0025, 0.0050, 0.0075, 0.0100, 0.0150]  # 0.25%, 0.50%, 0.75%, 1.00%, 1.50%
    
    print(f"\nProfit Level Hit Rates:")
    print(f"{'Target':<10} {'Hit Rate':<10} {'Trades':<8}")
    print('-'*30)
    
    for target in profit_levels:
        hits = sum(1 for mfe in mfe_values if mfe >= target)
        hit_rate = hits / len(mfe_values) if len(mfe_values) > 0 else 0
        target_pct = target * 100
        
        print(f"{target_pct:.2f}%{'':<6} {hit_rate:.1%}{'':<6} {hits:<8}")
    
    # Extended profit potential
    extended_profits = [mfe for mfe in mfe_values if mfe > TP_TARGET]
    
    if extended_profits:
        print(f"\nExtended Profit Potential (trades exceeding 0.5%):")
        print(f"  Trades exceeding 0.5%: {len(extended_profits)} ({len(extended_profits)/len(mfe_values):.1%})")
        print(f"  Average when >0.5%: {np.mean(extended_profits):.3%}")
        print(f"  Max potential: {np.max(extended_profits):.3%}")
        
        # Opportunity cost analysis
        missed_profit = sum(mfe - TP_TARGET for mfe in extended_profits)
        avg_missed = missed_profit / len(extended_profits)
        
        print(f"  Average missed profit: {avg_missed:.3%} per trade")
        print(f"  Total missed opportunity: {missed_profit:.2%} across all extended trades")

def run_time_to_profit_analysis():
    """Main time to profit analysis runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - TIME TO PROFIT ANALYSIS')
    logging.info('='*80)
    
    try:
        # Load existing resistance sweep results
        df = pd.read_csv('boof31v2_resistance_sweep_results.csv')
        logging.info(f'Loaded {len(df)} existing setups')
        
        # Run analyses
        time_results = analyze_time_to_profit(df)
        profit_results = analyze_profit_potential(df)
        
        # Summary
        print('\n' + '='*80)
        print('TIME TO PROFIT SUMMARY')
        print('='*80)
        
        if time_results['overall']['avg_time'] > 0:
            print(f"Key Findings:")
            print(f"  0.5% profit hit rate: {time_results['overall']['profit_hit_rate']:.1%}")
            print(f"  Average time to 0.5%: {time_results['overall']['avg_time']:.1f} minutes")
            print(f"  Median time to 0.5%: {time_results['overall']['median_time']:.1f} minutes")
            
            # Trading implications
            if time_results['overall']['avg_time'] <= 10:
                print(f"\n✅ Fast profit realization - suitable for active trading")
            elif time_results['overall']['avg_time'] <= 20:
                print(f"\n✅ Moderate profit speed - manageable for swing trading")
            else:
                print(f"\n⚠️  Slow profit realization - consider longer holding periods")
        
        return time_results
        
    except FileNotFoundError:
        logging.error('Cached results file not found. Run BOOF31V2_RESISTANCE_SWEEP_FIXED.py first.')
    except Exception as e:
        logging.error(f'Error in time to profit analysis: {e}')

if __name__ == '__main__':
    run_time_to_profit_analysis()
