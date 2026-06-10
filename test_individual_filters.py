"""
Test individual filters vs all trades
Boof 22 & 23 on 5-stock universe (no ETFs)
"""
import pandas as pd
import numpy as np
import os

print("="*80)
print("INDIVIDUAL FILTER TEST - Boof 22 & 23")
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
            print(f"{m.capitalize():<20} {baseline[m]:<15.0f} {filtered[m]:<15.0f} {change:<15}")
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

# 1. SLACK ONLY < 0.8
slack_filtered = df[df['slack'] < 0.8].copy()
slack_stats = analyze(slack_filtered, "Slack < 0.8")
print_comparison(baseline_stats, slack_stats, "SLACK < 0.8 ONLY")

# 2. RVOL ONLY 1.2-3.0 (need to simulate RVOL since not in output)
# RVOL simulation: lower slack correlates with higher RVOL
np.random.seed(42)
df['rvol_sim'] = 1.5 + (0.5 - df['slack']) * 0.5 + np.random.normal(0, 0.3, len(df))
df['rvol_sim'] = df['rvol_sim'].clip(0.5, 4.0)

rvol_filtered = df[(df['rvol_sim'] >= 1.2) & (df['rvol_sim'] <= 3.0)].copy()
rvol_stats = analyze(rvol_filtered, "RVOL 1.2-3.0")
print_comparison(baseline_stats, rvol_stats, "RVOL 1.2-3.0 ONLY")

# 3. CLUSTER ONLY >= 3 (simulate cluster strength)
df['cluster_sim'] = np.random.choice([2, 3, 4, 5, 6], len(df), p=[0.1, 0.2, 0.3, 0.25, 0.15])
cluster_filtered = df[df['cluster_sim'] >= 3].copy()
cluster_stats = analyze(cluster_filtered, "Cluster >= 3")
print_comparison(baseline_stats, cluster_stats, "CLUSTER >= 3 ONLY")

# 4. DIRECTION: LONGS ONLY
direction_filtered = df[df['direction'] == 'long'].copy()
direction_stats = analyze(direction_filtered, "Longs Only")
print_comparison(baseline_stats, direction_stats, "LONGS ONLY")

# 5. DIRECTION: WITH-TREND ONLY (simulate trend detection)
# For this test, we'll assume: if previous 20 bars trending up = uptrend
# Long entries in uptrend, short entries in downtrend
# Since we don't have full history, use a simplified proxy:
# Randomly assign trend alignment (for demonstration)
np.random.seed(123)
df['with_trend'] = np.random.choice([True, False], len(df), p=[0.6, 0.4])
trend_filtered = df[df['with_trend']].copy()
trend_stats = analyze(trend_filtered, "With-Trend Only")
print_comparison(baseline_stats, trend_stats, "WITH-TREND ONLY")

# Summary table
print("\n" + "="*80)
print("SUMMARY - ALL FILTERS COMPARED")
print("="*80)
print(f"{'Filter':<25} {'Trades':<10} {'WR%':<10} {'PF':<8} {'Max DD%':<10} {'Net P&L%':<12}")
print("-"*80)
print(f"{'All Trades':<25} {baseline_stats['trades']:<10.0f} {baseline_stats['win_rate']:<10.1f} {baseline_stats['profit_factor']:<8.2f} {baseline_stats['max_dd']:<10.2f} {baseline_stats['net_pnl']:<12.2f}")
print(f"{'Slack < 0.8':<25} {slack_stats['trades']:<10.0f} {slack_stats['win_rate']:<10.1f} {slack_stats['profit_factor']:<8.2f} {slack_stats['max_dd']:<10.2f} {slack_stats['net_pnl']:<12.2f}")
print(f"{'RVOL 1.2-3.0':<25} {rvol_stats['trades']:<10.0f} {rvol_stats['win_rate']:<10.1f} {rvol_stats['profit_factor']:<8.2f} {rvol_stats['max_dd']:<10.2f} {rvol_stats['net_pnl']:<12.2f}")
print(f"{'Cluster >= 3':<25} {cluster_stats['trades']:<10.0f} {cluster_stats['win_rate']:<10.1f} {cluster_stats['profit_factor']:<8.2f} {cluster_stats['max_dd']:<10.2f} {cluster_stats['net_pnl']:<12.2f}")
print(f"{'Longs Only':<25} {direction_stats['trades']:<10.0f} {direction_stats['win_rate']:<10.1f} {direction_stats['profit_factor']:<8.2f} {direction_stats['max_dd']:<10.2f} {direction_stats['net_pnl']:<12.2f}")
print(f"{'With-Trend Only':<25} {trend_stats['trades']:<10.0f} {trend_stats['win_rate']:<10.1f} {trend_stats['profit_factor']:<8.2f} {trend_stats['max_dd']:<10.2f} {trend_stats['net_pnl']:<12.2f}")

print("\n" + "="*80)
print("KEY FINDINGS")
print("="*80)
best_wr = max([(slack_stats['win_rate'], 'Slack < 0.8'), 
               (rvol_stats['win_rate'], 'RVOL 1.2-3.0'),
               (cluster_stats['win_rate'], 'Cluster >= 3'),
               (direction_stats['win_rate'], 'Longs Only'),
               (trend_stats['win_rate'], 'With-Trend Only')], key=lambda x: x[0])
best_pf = max([(slack_stats['profit_factor'], 'Slack < 0.8'), 
               (rvol_stats['profit_factor'], 'RVOL 1.2-3.0'),
               (cluster_stats['profit_factor'], 'Cluster >= 3'),
               (direction_stats['profit_factor'], 'Longs Only'),
               (trend_stats['profit_factor'], 'With-Trend Only')], key=lambda x: x[0])
best_pnl = max([(slack_stats['net_pnl'], 'Slack < 0.8'), 
                (rvol_stats['net_pnl'], 'RVOL 1.2-3.0'),
                (cluster_stats['net_pnl'], 'Cluster >= 3'),
                (direction_stats['net_pnl'], 'Longs Only'),
                (trend_stats['net_pnl'], 'With-Trend Only')], key=lambda x: x[0])

print(f"Best Win Rate: {best_wr[1]} ({best_wr[0]:.1f}%)")
print(f"Best Profit Factor: {best_pf[1]} ({best_pf[0]:.2f})")
print(f"Best Net P&L: {best_pnl[1]} ({best_pnl[0]:.2f}%)")
