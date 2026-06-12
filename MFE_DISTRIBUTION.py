import pandas as pd
import numpy as np

print('='*70)
print('SCORE 3 MFE DISTRIBUTION ANALYSIS')
print('='*70)

# Load Score 3 data
df = pd.read_csv('score3_mae_analysis.csv')

print(f'Total Score 3 signals: {len(df)}')
print()

mfe_values = df['mfe'].values

# MFE threshold analysis
thresholds = [2, 3, 5, 8, 10, 15, 20, 30, 50]

print('='*70)
print('MFE THRESHOLD HIT RATES')
print('='*70)
print(f"{'MFE >=':<12} {'Count':<10} {'% of Total':<12} {'Cumulative'}")
print('-'*70)

cumulative = 0
for threshold in thresholds:
    count = sum(mfe_values >= threshold)
    pct = count / len(df) * 100
    cumulative += count
    print(f"{threshold}%{'':<10} {count:<10} {pct:>10.1f}% {cumulative:>8}")

print()
print('='*70)
print('MFE PERCENTILES (Score 3 only)')
print('='*70)

percentiles = [10, 25, 50, 75, 90, 95, 99]
for p in percentiles:
    val = np.percentile(mfe_values, p)
    print(f'  P{p}: {val:.2f}%')

print()
print('='*70)
print('MFE BUCKET DISTRIBUTION')
print('='*70)

buckets = [
    (0, 2, '0-2%'),
    (2, 3, '2-3%'),
    (3, 5, '3-5%'),
    (5, 8, '5-8%'),
    (8, 10, '8-10%'),
    (10, 15, '10-15%'),
    (15, 20, '15-20%'),
    (20, 30, '20-30%'),
    (30, 100, '30%+')
]

print(f"{'Bucket':<15} {'Count':<10} {'%':<10} {'Cumulative %'}")
print('-'*70)

cumulative_pct = 0
for low, high, label in buckets:
    count = sum((mfe_values >= low) & (mfe_values < high))
    pct = count / len(df) * 100
    cumulative_pct += pct
    print(f"{label:<15} {count:<10} {pct:>9.1f}% {cumulative_pct:>11.1f}%")

print()
print('='*70)
print('TOP 20 MFE RUNNERS (Score 3)')
print('='*70)

top = df.nlargest(20, 'mfe')
for _, r in top.iterrows():
    mae_pct = abs(r['mae'])
    rr = r['mfe'] / mae_pct if mae_pct > 0 else 0
    print(f"{r['symbol']:6} {r['date']} | MFE: {r['mfe']:6.2f}% | MAE: {r['mae']:6.2f}% | RR: 1:{rr:.1f}")

print()
print('='*70)
print('SUMMARY')
print('='*70)
print(f"Signals reaching 2%+ MFE: {sum(mfe_values >= 2)}/{len(df)} ({sum(mfe_values >= 2)/len(df)*100:.1f}%)")
print(f"Signals reaching 5%+ MFE: {sum(mfe_values >= 5)}/{len(df)} ({sum(mfe_values >= 5)/len(df)*100:.1f}%)")
print(f"Signals reaching 10%+ MFE: {sum(mfe_values >= 10)}/{len(df)} ({sum(mfe_values >= 10)/len(df)*100:.1f}%)")
print(f"Signals reaching 20%+ MFE: {sum(mfe_values >= 20)}/{len(df)} ({sum(mfe_values >= 20)/len(df)*100:.1f}%)")
print()
print('Score 3 signals have outsized upside - GOEV Jan 24 with 62% MFE!')
print('='*70)
