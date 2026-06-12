import pandas as pd
import numpy as np

print('='*70)
print('MFE STATISTICS BY SCORE BUCKET')
print('='*70)

# Load the data
df = pd.read_csv('boof30_top100_signals.csv')

print(f'Total signals: {len(df)}')
print()

print('='*70)
print(f"{'Score':<8} {'Count':<8} {'Avg MFE':<12} {'Median MFE':<12} {'P90 MFE'}")
print('-'*70)

for score in sorted(df['LONG_SCORE'].unique()):
    subset = df[df['LONG_SCORE'] == score]
    mfe_values = subset['mfe'].values
    
    count = len(subset)
    avg_mfe = np.mean(mfe_values)
    median_mfe = np.median(mfe_values)
    p90_mfe = np.percentile(mfe_values, 90)
    
    print(f"{score:<8} {count:<8} {avg_mfe:>11.2f}% {median_mfe:>11.2f}% {p90_mfe:>10.2f}%")

print()
print('='*70)
print('RUNNERS ONLY (MFE >= 2%):')
print('='*70)
print(f"{'Score':<8} {'Count':<8} {'Avg MFE':<12} {'Median MFE':<12} {'P90 MFE'}")
print('-'*70)

runners_df = df[df['is_runner'] == 1]

for score in sorted(df['LONG_SCORE'].unique()):
    subset = runners_df[runners_df['LONG_SCORE'] == score]
    if len(subset) == 0:
        print(f"{score:<8} {0:<8} {'N/A':<12} {'N/A':<12} {'N/A'}")
        continue
    
    mfe_values = subset['mfe'].values
    count = len(subset)
    avg_mfe = np.mean(mfe_values)
    median_mfe = np.median(mfe_values)
    p90_mfe = np.percentile(mfe_values, 90)
    
    print(f"{score:<8} {count:<8} {avg_mfe:>11.2f}% {median_mfe:>11.2f}% {p90_mfe:>10.2f}%")

print()
print('='*70)
print('KEY INSIGHTS:')
print('='*70)

# Calculate improvement from score 0 to score 3
score_0 = df[df['LONG_SCORE'] == 0]
score_3 = df[df['LONG_SCORE'] == 3]

if len(score_0) > 0 and len(score_3) > 0:
    print(f'Score 0 avg MFE: {score_0["mfe"].mean():.2f}%')
    print(f'Score 3 avg MFE: {score_3["mfe"].mean():.2f}%')
    print(f'Improvement: +{score_3["mfe"].mean() - score_0["mfe"].mean():.2f} percentage points')
    print()

# Best performing score for runners
print('Best P90 MFE by score (all signals):')
for score in sorted(df['LONG_SCORE'].unique()):
    subset = df[df['LONG_SCORE'] == score]
    p90 = np.percentile(subset['mfe'].values, 90)
    print(f'  Score {score}: P90 = {p90:.2f}%')

print()
print('='*70)
print('COMPLETE')
print('='*70)
