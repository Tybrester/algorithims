import pandas as pd

# Read the filtered backtest results
summary = pd.read_csv('boof31_filtered_summary.csv')
trades = pd.read_csv('boof31_filtered_trades.csv')

print('='*80)
print('BOOF 31 - FILTERED BACKTEST RESULTS')
print('='*80)
print(f"{'TP':<8} {'SL':<8} {'Trades':<10} {'Win%':<8} {'Avg PnL':<10} {'Median':<10} {'Total':<12} {'PF':<6}")
print('-'*80)

for _, row in summary.iterrows():
    print(f"{row['tp']:<8.2%} {row['sl']:<8.2%} {row['total_trades']:<10.0f} {row['win_rate']:<8.1%} {row['avg_pnl']:<10.2%} {row['median_pnl']:<10.2%} {row['total_return']:<12.2%} {row['pf']:<6.2f}")

# Symbol breakdown
symbol_summary = (
    trades.groupby('symbol')
    .agg(
        trades=('pnl', 'count'),
        win_rate=('pnl', lambda x: (x > 0).mean()),
        avg_pnl=('pnl', 'mean'),
        total=('pnl', 'sum')
    )
    .reset_index()
    .sort_values('avg_pnl', ascending=False)
)

print('\n' + '='*60)
print('BY SYMBOL')
print('='*60)
print(symbol_summary.to_string(index=False))

# Filter impact
total_trades = len(trades)
trades_per_day = total_trades / (6 * 21)  # 6 months, ~21 trading days/month

print('\n' + '='*60)
print('FILTER IMPACT')
print('='*60)
print(f'Total trades: {total_trades:,.0f}')
print(f'Trades per day: {trades_per_day:.1f}')
print(f'Original was ~270 trades/day')
print(f'Reduction: {(270 - trades_per_day)/270:.1%}')

print(f'\nBest combo: TP={summary.iloc[0]["tp"]:.1%}, SL={summary.iloc[0]["sl"]:.1%}')
print(f'Win rate: {summary.iloc[0]["win_rate"]:.1%}')
print(f'Profit Factor: {summary.iloc[0]["pf"]:.2f}')
