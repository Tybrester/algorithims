import pandas as pd

# Read the per-symbol results
df = pd.read_csv('boof31_per_symbol_trades.csv')

print('='*100)
print('BOOF 31 - DETAILED PER-SYMBOL ANALYSIS')
print('='*100)

# Overall stats
print(f"Total trades across all symbols: {len(df):,}")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
print(f"Symbols analyzed: {df['symbol'].nunique()}")
print()

# Symbol breakdown
symbol_stats = df.groupby('symbol').agg({
    'pnl': ['count', 'mean', 'sum', lambda x: (x > 0).mean()],
    'tp': lambda x: x.mode().iloc[0] if not x.mode().empty else 0,
    'sl': lambda x: x.mode().iloc[0] if not x.mode().empty else 0
}).round(6)

symbol_stats.columns = ['Trades', 'Avg PnL', 'Total PnL', 'Win Rate', 'Common TP', 'Common SL']
symbol_stats['Win Rate'] = symbol_stats['Win Rate'].apply(lambda x: f"{x:.1%}")
symbol_stats['Avg PnL'] = symbol_stats['Avg PnL'].apply(lambda x: f"{x:.3%}")
symbol_stats['Total PnL'] = symbol_stats['Total PnL'].apply(lambda x: f"{x:.2%}")
symbol_stats['Common TP'] = symbol_stats['Common TP'].apply(lambda x: f"{x:.2%}")
symbol_stats['Common SL'] = symbol_stats['Common SL'].apply(lambda x: f"{x:.2%}")

print("BY SYMBOL PERFORMANCE:")
print('-'*100)
print(symbol_stats.sort_values('Total PnL', ascending=False))

# TP/SL combo analysis
tp_sl_stats = df.groupby(['tp', 'sl']).agg({
    'pnl': ['count', 'mean', 'sum', lambda x: (x > 0).mean()]
}).round(6)

tp_sl_stats.columns = ['Trades', 'Avg PnL', 'Total PnL', 'Win Rate']
tp_sl_stats['Win Rate'] = tp_sl_stats['Win Rate'].apply(lambda x: f"{x:.1%}")
tp_sl_stats['Avg PnL'] = tp_sl_stats['Avg PnL'].apply(lambda x: f"{x:.3%}")
tp_sl_stats['Total PnL'] = tp_sl_stats['Total PnL'].apply(lambda x: f"{x:.2%}")

print('\n' + '='*80)
print("BEST TP/SL COMBINATIONS (Overall):")
print('-'*80)
print(tp_sl_stats.sort_values('Total PnL', ascending=False).head(10))

# Best combo per symbol
print('\n' + '='*80)
print("BEST TP/SL COMBO PER SYMBOL:")
print('-'*80)

for symbol in df['symbol'].unique():
    symbol_data = df[df['symbol'] == symbol]
    best_combo = symbol_data.groupby(['tp', 'sl'])['pnl'].sum().idxmax()
    best_pnl = symbol_data.groupby(['tp', 'sl'])['pnl'].sum().max()
    win_rate = (symbol_data[(symbol_data['tp'] == best_combo[0]) & (symbol_data['sl'] == best_combo[1])]['pnl'] > 0).mean()
    trades = len(symbol_data[(symbol_data['tp'] == best_combo[0]) & (symbol_data['sl'] == best_combo[1])])
    
    print(f"{symbol:<6}: TP={best_combo[0]:.2%}, SL={best_combo[1]:.2%} | PnL={best_pnl:.2%} | Win%={win_rate:.1%} | Trades={trades}")

# Direction analysis
direction_stats = df.groupby('symbol')['direction'].value_counts().unstack(fill_value=0)
direction_stats['Long%'] = direction_stats['long'] / (direction_stats['long'] + direction_stats['short']) * 100
direction_stats['Short%'] = direction_stats['short'] / (direction_stats['long'] + direction_stats['short']) * 100

print('\n' + '='*60)
print("LONG vs SHORT BREAKDOWN:")
print('-'*60)
print(direction_stats[['long', 'short', 'Long%', 'Short%']].sort_values('short', ascending=False))

# Daily analysis
daily_stats = df.groupby('date').agg({
    'pnl': ['count', 'sum', lambda x: (x > 0).mean()]
})
daily_stats.columns = ['Daily Trades', 'Daily PnL', 'Daily Win Rate']
avg_daily_trades = daily_stats['Daily Trades'].mean()
avg_daily_pnl = daily_stats['Daily PnL'].mean()
winning_days = (daily_stats['Daily PnL'] > 0).mean()

print('\n' + '='*60)
print("DAILY PERFORMANCE:")
print('-'*60)
print(f"Average trades per day: {avg_daily_trades:.1f}")
print(f"Average daily PnL: {avg_daily_pnl:.3%}")
print(f"Winning days: {winning_days:.1%}")
print(f"Best day: {daily_stats['Daily PnL'].max():.2%}")
print(f"Worst day: {daily_stats['Daily PnL'].min():.2%}")

# Profit Factor calculation
wins = df[df['pnl'] > 0]['pnl'].sum()
losses = abs(df[df['pnl'] < 0]['pnl'].sum())
profit_factor = wins / losses if losses > 0 else float('inf')

print('\n' + '='*60)
print("OVERALL METRICS:")
print('-'*60)
print(f"Total Win Rate: {(df['pnl'] > 0).mean():.1%}")
print(f"Average Trade PnL: {df['pnl'].mean():.3%}")
print(f"Median Trade PnL: {df['pnl'].median():.3%}")
print(f"Profit Factor: {profit_factor:.3f}")
print(f"Best Single Trade: {df['pnl'].max():.2%}")
print(f"Worst Single Trade: {df['pnl'].min():.2%}")

print('\n' + '='*60)
print("KEY INSIGHTS:")
print('-'*60)
if profit_factor < 1.0:
    print(f"❌ Strategy loses money overall (PF: {profit_factor:.3f})")
else:
    print(f"✅ Strategy profitable (PF: {profit_factor:.3f})")

if avg_daily_pnl < 0:
    print(f"❌ Average daily loss: {avg_daily_pnl:.3%}")
else:
    print(f"✅ Average daily profit: {avg_daily_pnl:.3%}")

best_symbol = symbol_stats.sort_values('Total PnL', ascending=False).index[0]
worst_symbol = symbol_stats.sort_values('Total PnL').index[0]
print(f"🏆 Best symbol: {best_symbol}")
print(f"⚠️  Worst symbol: {worst_symbol}")

print(f"\n📊 Data saved in: boof31_per_symbol_trades.csv")
