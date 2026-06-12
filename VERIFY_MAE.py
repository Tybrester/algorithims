import pandas as pd
import numpy as np

print('='*70)
print('VERIFY MAE CALCULATIONS')
print('='*70)

# Load the MAE data
df = pd.read_csv('score3_mae_analysis.csv')

print(f'Total signals: {len(df)}')
print()

# Basic stats
mae_values = df['mae'].values
mfe_values = df['mfe'].values

print('MAE Distribution:')
print(f'  Min: {mae_values.min():.2f}%')
print(f'  Max: {mae_values.max():.2f}%')
print(f'  Mean: {mae_values.mean():.2f}%')
print(f'  Median: {np.median(mae_values):.2f}%')
print()

# Percentiles - correct interpretation
print('MAE Percentiles:')
print(f'  P10 (10th percentile): {np.percentile(mae_values, 10):.2f}%')
print(f'  P25 (25th percentile): {np.percentile(mae_values, 25):.2f}%')
print(f'  P50 (50th percentile/median): {np.percentile(mae_values, 50):.2f}%')
print(f'  P75 (75th percentile): {np.percentile(mae_values, 75):.2f}%')
print(f'  P90 (90th percentile): {np.percentile(mae_values, 90):.2f}%')
print()

# For negative MAE, P90 should be the value where 90% are at or below it
# Since MAE is negative, P90 being closer to 0 means 90% have worse drawdown
print('Interpretation:')
print(f'  P90 = {np.percentile(mae_values, 90):.2f}% means 90% of trades have MAE <= this value')
print(f'  So 90% have drawdown of {np.percentile(mae_values, 90):.2f}% or worse')
print()

# MFE vs MAE comparison
wins = sum(mfe_values > abs(mae_values))
print(f'MFE > |MAE|: {wins}/{len(df)} ({wins/len(df)*100:.1f}%)')
print()

# Sample of worst MAE cases
print('Worst 10 MAE (most negative):')
worst = df.nsmallest(10, 'mae')
for _, r in worst.iterrows():
    print(f"  {r['symbol']} {r['date']} | MAE: {r['mae']:.2f}% | MFE: {r['mfe']:.2f}%")

print()
print('Best 10 MAE (least negative / closest to 0):')
best = df.nlargest(10, 'mae')
for _, r in best.iterrows():
    print(f"  {r['symbol']} {r['date']} | MAE: {r['mae']:.2f}% | MFE: {r['mfe']:.2f}%")

print()
print('='*70)
print('CHECKING IF P90 SHOULD BE P10 FOR RISK ANALYSIS:')
print('='*70)
print()
print('For risk management, we care about:')
print(f'  "What is the MAE for the worst 10% of trades?"')
print(f'  That would be P10: {np.percentile(mae_values, 10):.2f}%')
print()
print(f'  Or "What is the MAE exceeded by only 10% of trades?"')
print(f'  That would be P90: {np.percentile(mae_values, 90):.2f}%')
print()
print('Actually for drawdown (negative numbers):')
print(f'  P10 = {np.percentile(mae_values, 10):.2f}% (worst 10% have this or worse)')
print(f'  P90 = {np.percentile(mae_values, 90):.2f}% (best 10% have this or better)')
print()
print('='*70)
