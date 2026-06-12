import pandas as pd
import numpy as np

print('='*80)
print('SCORE 3 - PER SYMBOL PERFORMANCE')
print('='*80)

# Load data
df = pd.read_csv('score3_mae_analysis.csv')

print(f'Total Score 3 signals: {len(df)}')
print(f'Symbols: {df["symbol"].nunique()}')
print()

# Group by symbol
grouped = df.groupby('symbol').agg({
    'mfe': ['count', 'mean', 'median', 'max'],
    'mae': ['mean', 'median']
})

# Flatten column names
grouped.columns = ['signals', 'avg_mfe', 'median_mfe', 'max_mfe', 'avg_mae', 'median_mae']

# Sort by avg MFE descending
grouped = grouped.sort_values('avg_mfe', ascending=False)

print('='*80)
print('ALL SYMBOLS (sorted by avg MFE)')
print('='*80)
print(grouped.round(2).to_string())

print()
print('='*80)
print('TOP PERFORMERS (signals >= 3)')
print('='*80)

# Filter for symbols with at least 3 signals
top_symbols = grouped[grouped['signals'] >= 3].copy()

print(f"Symbols with 3+ signals: {len(top_symbols)}")
print()

# Format nicely
for symbol, row in top_symbols.iterrows():
    print(f"{symbol:6} | {int(row['signals']):2} signals | "
          f"Avg MFE: {row['avg_mfe']:5.2f}% | "
          f"Median: {row['median_mfe']:5.2f}% | "
          f"Max: {row['max_mfe']:6.2f}% | "
          f"Avg MAE: {row['avg_mae']:6.2f}%")

print()
print('='*80)
print('TIER CLASSIFICATION')
print('='*80)

# Classify tiers based on avg MFE and signal count
tier1 = []
tier2 = []
tier3 = []

for symbol, row in grouped.iterrows():
    if row['signals'] >= 5 and row['avg_mfe'] >= 3.5:
        tier1.append((symbol, row['signals'], row['avg_mfe']))
    elif row['signals'] >= 3 and row['avg_mfe'] >= 2.0:
        tier2.append((symbol, row['signals'], row['avg_mfe']))
    elif row['signals'] >= 1:
        tier3.append((symbol, row['signals'], row['avg_mfe']))

print(f'\nTIER 1 (5+ signals, 3.5%+ avg MFE) - {len(tier1)} symbols:')
for sym, sig, mfe in tier1:
    print(f'  {sym}: {int(sig)} signals, {mfe:.2f}% avg')

print(f'\nTIER 2 (3+ signals, 2.0%+ avg MFE) - {len(tier2)} symbols:')
for sym, sig, mfe in tier2:
    print(f'  {sym}: {int(sig)} signals, {mfe:.2f}% avg')

print(f'\nTIER 3 (others) - {len(tier3)} symbols')

print()
print('='*80)
print('COMPLETE')
print('='*80)
