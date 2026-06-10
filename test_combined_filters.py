"""
Test combined filters - the critical tests
"""
import pandas as pd
import numpy as np
import os

print("="*80)
print("COMBINED FILTER TESTS - Critical Combinations")
print("="*80)

# Load the full backtest results
files = [f for f in os.listdir('.') if f.startswith('6mo_backtest_boof') and f.endswith('.csv')]
if not files:
    print("No backtest files found. Run backtest first.")
    exit()

dfs = []
for f in files:
    df = pd.read_csv(f)
    df['source_file'] = f
    dfs.append(df)

df = pd.concat(dfs, ignore_index=True)
df['result'] = df['exit_type'].apply(lambda x: 1 if x == 'tp' else 0)

print(f"\nTotal trades loaded: {len(df)}")
print(f"Symbols: {sorted(df['symbol'].unique())}")
print(f"Strategies: {sorted(df['strategy'].unique())}")

# Simulate RVOL
np.random.seed(42)
df['rvol_sim'] = 1.5 + (0.5 - df['slack']) * 0.5 + np.random.normal(0, 0.3, len(df))
df['rvol_sim'] = df['rvol_sim'].clip(0.5, 4.0)

def analyze(df, label):
    if len(df) == 0:
        return {'trades': 0, 'win_rate': 0, 'profit_factor': 0, 'max_dd': 0, 'net_pnl': 0}
    
    wins = df[df['pnl_pct'] > 0]
    losses = df[df['pnl_pct'] <= 0]
    
    gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0.0001
    
    # Calculate max drawdown
    cumulative = df['pnl_pct'].cumsum()
    running_max = cumulative.expanding().max()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()
    
    return {
        'trades': len(df),
        'win_rate': len(wins) / len(df) * 100 if len(df) > 0 else 0,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else 0,
        'max_dd': max_dd * 100,
        'net_pnl': df['pnl_pct'].sum() * 100
    }

def print_comparison(baseline, filtered, filter_name):
    print(f"\n{'='*80}")
    print(f"FILTER: {filter_name}")
    print(f"{'='*80}")
    print(f"{'Metric':<20} {'All Trades':<15} {'Filtered':<15} {'Change':<15}")
    print("-"*80)
    
    metrics = ['trades', 'win_rate', 'profit_factor', 'max_dd', 'net_pnl']
    for m in metrics:
        if m == 'trades':
            change = f"{(filtered[m] - baseline[m]):.0f}"
            pct_change = f"({(filtered[m] / baseline[m] - 1) * 100:+.1f}%)" if baseline[m] > 0 else ""
            print(f"{m.capitalize():<20} {baseline[m]:<15.0f} {filtered[m]:<15.0f} {change:<15} {pct_change}")
        elif m == 'win_rate':
            change = f"{(filtered[m] - baseline[m]):+.1f}%"
            print(f"{m.replace('_', ' ').title():<20} {baseline[m]:<15.1f}% {filtered[m]:<15.1f}% {change:<15}")
        elif m == 'max_dd':
            change = f"{(filtered[m] - baseline[m]):+.2f}%"
            print(f"{m.replace('_', ' ').upper():<20} {baseline[m]:<15.2f}% {filtered[m]:<15.2f}% {change:<15}")
        elif m == 'net_pnl':
            change = f"{(filtered[m] - baseline[m]):+.2f}%"
            print(f"{m.replace('_', ' ').upper():<20} {baseline[m]:<15.2f}% {filtered[m]:<15.2f}% {change:<15}")
        else:
            change = f"{(filtered[m] - baseline[m]):+.2f}"
            print(f"{m.replace('_', ' ').title():<20} {baseline[m]:<15.2f} {filtered[m]:<15.2f} {change:<15}")

# Baseline - all trades
baseline_stats = analyze(df, "All Trades")

print("\n" + "="*80)
print("BASELINE - ALL TRADES")
print("="*80)
print(f"Trades: {baseline_stats['trades']:.0f}")
print(f"Win Rate: {baseline_stats['win_rate']:.1f}%")
print(f"Profit Factor: {baseline_stats['profit_factor']:.2f}")
print(f"Max Drawdown: {baseline_stats['max_dd']:.2f}%")
print(f"Net P&L: {baseline_stats['net_pnl']:.2f}%")

# ========================================================================
# TEST A: Slack < 0.8 AND RVOL 1.2-3.0
# ========================================================================
test_a_filtered = df[(df['slack'] < 0.8) & (df['rvol_sim'] >= 1.2) & (df['rvol_sim'] <= 3.0)].copy()
test_a_stats = analyze(test_a_filtered, "Test A")
print_comparison(baseline_stats, test_a_stats, "TEST A: Slack < 0.8 AND RVOL 1.2-3.0")

# ========================================================================
# TEST B: Slack < 0.8 AND RVOL 1.2-3.0 AND Long Only
# ========================================================================
test_b_filtered = df[(df['slack'] < 0.8) & (df['rvol_sim'] >= 1.2) & (df['rvol_sim'] <= 3.0) & (df['direction'] == 'long')].copy()
test_b_stats = analyze(test_b_filtered, "Test B")
print_comparison(baseline_stats, test_b_stats, "TEST B: Slack < 0.8 AND RVOL 1.2-3.0 AND Long Only")

# ========================================================================
# COMPARISON TABLE
# ========================================================================
print("\n" + "="*80)
print("FINAL COMPARISON - ALL TESTS")
print("="*80)
print(f"{'Test':<40} {'Trades':<10} {'WR%':<10} {'PF':<8} {'Max DD%':<10} {'Net P&L%':<12}")
print("-"*80)
print(f"{'All Trades':<40} {baseline_stats['trades']:<10.0f} {baseline_stats['win_rate']:<10.1f} {baseline_stats['profit_factor']:<8.2f} {baseline_stats['max_dd']:<10.2f} {baseline_stats['net_pnl']:<12.2f}")
print(f"{'Test A (Slack+RVOL)':<40} {test_a_stats['trades']:<10.0f} {test_a_stats['win_rate']:<10.1f} {test_a_stats['profit_factor']:<8.2f} {test_a_stats['max_dd']:<10.2f} {test_a_stats['net_pnl']:<12.2f}")
print(f"{'Test B (Slack+RVOL+Long)':<40} {test_b_stats['trades']:<10.0f} {test_b_stats['win_rate']:<10.1f} {test_b_stats['profit_factor']:<8.2f} {test_b_stats['max_dd']:<10.2f} {test_b_stats['net_pnl']:<12.2f}")

# Calculate efficiency metrics
print("\n" + "="*80)
print("EFFICIENCY ANALYSIS")
print("="*80)

def print_efficiency(stats, name):
    if stats['trades'] == 0:
        print(f"{name}: No trades")
        return
    
    trades_ratio = stats['trades'] / baseline_stats['trades'] * 100
    pnl_per_trade = stats['net_pnl'] / stats['trades']
    
    print(f"\n{name}:")
    print(f"  Trade Retention: {trades_ratio:.1f}% of all trades")
    print(f"  P&L per Trade: {pnl_per_trade:.4f}%")
    print(f"  Quality Score: {(stats['win_rate'] * stats['profit_factor'] / 100):.2f}")

print_efficiency(baseline_stats, "All Trades")
print_efficiency(test_a_stats, "Test A")
print_efficiency(test_b_stats, "Test B")

# Recommendation
print("\n" + "="*80)
print("RECOMMENDATION")
print("="*80)

if test_a_stats['win_rate'] > test_b_stats['win_rate']:
    winner = "Test A"
    winner_stats = test_a_stats
else:
    winner = "Test B"
    winner_stats = test_b_stats

print(f"\nBest Combination: {winner}")
print(f"  Win Rate: {winner_stats['win_rate']:.1f}%")
print(f"  Profit Factor: {winner_stats['profit_factor']:.2f}")
print(f"  Trades: {winner_stats['trades']:.0f} ({winner_stats['trades']/baseline_stats['trades']*100:.1f}% of total)")
print(f"  Max DD: {winner_stats['max_dd']:.2f}%")
print(f"  Net P&L: {winner_stats['net_pnl']:.2f}%")

if winner == "Test A":
    print("\nInsight: Adding 'Long Only' filter reduces trade count further")
    print("but doesn't significantly improve quality.")
    print("Test A (Slack + RVOL) provides best balance.")
else:
    print("\nInsight: Long-only bias adds value when combined with Slack+RVOL.")
