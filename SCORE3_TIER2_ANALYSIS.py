import pandas as pd
import numpy as np

print('='*80)
print('SCORE 3 + TIER 2 ONLY - DETAILED ANALYSIS')
print('='*80)

# Load data
df = pd.read_csv('score3_mae_analysis.csv')

# Tier 2 symbols
tier2_symbols = ['AMD', 'META', 'AVGO', 'MRNA', 'RBLX', 'AFRM', 'UPST']

# Filter
tier2_df = df[df['symbol'].isin(tier2_symbols)].copy()

print(f'Tier 2 symbols: {tier2_symbols}')
print(f'Total Score 3 + Tier 2 signals: {len(tier2_df)}')
print()

# Parse dates
tier2_df['date'] = pd.to_datetime(tier2_df['date'])
tier2_df['month'] = tier2_df['date'].dt.to_period('M')

# Monthly breakdown
print('='*80)
print('SIGNALS PER MONTH')
print('='*80)

monthly = tier2_df.groupby('month').agg({
    'symbol': 'count',
    'mfe': ['mean', 'median'],
    'mae': ['mean', 'median']
}).round(2)

monthly.columns = ['Signals', 'Avg MFE', 'Median MFE', 'Avg MAE', 'Median MAE']
print(monthly.to_string())

print()
print(f'Monthly average: {len(tier2_df) / tier2_df["month"].nunique():.1f} signals/month')
print()

# Overall stats
mfe_values = tier2_df['mfe'].values
mae_values = tier2_df['mae'].values

print('='*80)
print('OVERALL STATISTICS')
print('='*80)
print(f'  Avg MFE: {np.mean(mfe_values):.2f}%')
print(f'  Median MFE: {np.median(mfe_values):.2f}%')
print(f'  Avg MAE: {np.mean(mae_values):.2f}%')
print(f'  Median MAE: {np.median(mae_values):.2f}%')
print()

# MFE Distribution
print('='*80)
print('MFE THRESHOLD DISTRIBUTION')
print('='*80)
print(f"{'Threshold':<15} {'Count':<10} {'% of Total'}")
print('-'*40)

for threshold in [3, 5, 7, 10]:
    count = sum(mfe_values >= threshold)
    pct = count / len(tier2_df) * 100
    print(f"MFE >= {threshold}%{'':<6} {count:<10} {pct:>8.1f}%")

print()

# Bucket distribution
print('='*80)
print('MFE BUCKET DISTRIBUTION')
print('='*80)
print(f"{'Bucket':<20} {'Count':<10} {'%':<10}")
print('-'*40)

buckets = [
    (0, 2, '< 2%'),
    (2, 3, '2-3%'),
    (3, 5, '3-5%'),
    (5, 7, '5-7%'),
    (7, 10, '7-10%'),
    (10, 100, '10%+')
]

for low, high, label in buckets:
    count = sum((mfe_values >= low) & (mfe_values < high))
    pct = count / len(tier2_df) * 100
    print(f"{label:<20} {count:<10} {pct:>8.1f}%")

# Winners with good risk/reward
print()
print('='*80)
print('TOP 10 PERFORMERS (MFE >= 3%, sorted by Risk/Reward)')
print('='*80)

tier2_df['rr'] = tier2_df['mfe'] / abs(tier2_df['mae'])
top = tier2_df[tier2_df['mfe'] >= 3].nlargest(10, 'rr')

for _, r in top.iterrows():
    print(f"{r['symbol']:6} {str(r['date'])[:10]} | MFE: {r['mfe']:5.2f}% | MAE: {r['mae']:6.2f}% | RR: 1:{r['rr']:.1f}")

print()
print('='*80)
print('COMPLETE')
print('='*80)
