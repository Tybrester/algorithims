import pandas as pd
import numpy as np

print('='*70)
print('SCORE 3 - FILTERED (NO GARBAGE NAMES)')
print('='*70)

# Load data
df = pd.read_csv('score3_mae_analysis.csv')

print(f'Original Score 3 signals: {len(df)}')

# Remove garbage names
garbage = ['AMC', 'BBBY', 'GOEV', 'SPCE', 'KOSS', 'WKHS']
df_filtered = df[~df['symbol'].isin(garbage)].copy()

print(f'Removed: {garbage}')
print(f'Filtered Score 3 signals: {len(df_filtered)}')
print(f'Removed: {len(df) - len(df_filtered)} signals')
print()

# Recalculate all stats
mfe_values = df_filtered['mfe'].values
mae_values = df_filtered['mae'].values

print('='*70)
print('MFE THRESHOLD HIT RATES (FILTERED)')
print('='*70)
print(f"{'MFE >=':<12} {'Count':<10} {'% of Total':<15} {'% of 20 Original'}")
print('-'*70)

for threshold in [2, 3, 5, 8, 10, 15, 20, 30, 50]:
    count = sum(mfe_values >= threshold)
    pct_filtered = count / len(df_filtered) * 100
    pct_original = count / len(df) * 100
    print(f"{threshold}%{'':<10} {count:<10} {pct_filtered:>10.1f}% {pct_original:>14.1f}%")

print()
print('='*70)
print('MAE STATISTICS (FILTERED)')
print('='*70)
print(f"  Avg MAE: {mae_values.mean():.2f}%")
print(f"  Median MAE: {np.median(mae_values):.2f}%")
print(f"  P10 MAE (worst 10%): {np.percentile(mae_values, 10):.2f}%")
print(f"  P90 MAE: {np.percentile(mae_values, 90):.2f}%")
print()

# MFE vs MAE
wins = sum(mfe_values > abs(mae_values))
print(f'  MFE > |MAE| Rate: {wins}/{len(df_filtered)} ({wins/len(df_filtered)*100:.1f}%)')
print(f'  Avg MFE: {mfe_values.mean():.2f}%')
rr = mfe_values.mean() / abs(mae_values.mean())
print(f'  Risk/Reward: 1:{rr:.2f}')

print()
print('='*70)
print('TOP 15 MFE RUNNERS (FILTERED)')
print('='*70)

top = df_filtered.nlargest(15, 'mfe')
for _, r in top.iterrows():
    mae_pct = abs(r['mae'])
    rr = r['mfe'] / mae_pct if mae_pct > 0 else 0
    print(f"{r['symbol']:6} {r['date']} | MFE: {r['mfe']:6.2f}% | MAE: {r['mae']:6.2f}% | RR: 1:{rr:.1f}")

print()
print('='*70)
print('SYMBOLS REMOVED:')
print('='*70)
for sym in garbage:
    removed = df[df['symbol'] == sym]
    if len(removed) > 0:
        avg_mfe = removed['mfe'].mean()
        max_mfe = removed['mfe'].max()
        print(f"  {sym}: {len(removed)} signals, avg MFE {avg_mfe:.2f}%, max MFE {max_mfe:.2f}%")
    else:
        print(f"  {sym}: 0 signals")

print()
print('='*70)
print('COMPARISON: BEFORE vs AFTER')
print('='*70)

original_stats = {
    'count': len(df),
    'mfe_mean': df['mfe'].mean(),
    'mfe_median': df['mfe'].median(),
    'mae_mean': df['mae'].mean(),
    'pct_2pct': sum(df['mfe'] >= 2) / len(df) * 100,
    'pct_5pct': sum(df['mfe'] >= 5) / len(df) * 100,
    'pct_10pct': sum(df['mfe'] >= 10) / len(df) * 100,
}

filtered_stats = {
    'count': len(df_filtered),
    'mfe_mean': df_filtered['mfe'].mean(),
    'mfe_median': df_filtered['mfe'].median(),
    'mae_mean': df_filtered['mae'].mean(),
    'pct_2pct': sum(df_filtered['mfe'] >= 2) / len(df_filtered) * 100,
    'pct_5pct': sum(df_filtered['mfe'] >= 5) / len(df_filtered) * 100,
    'pct_10pct': sum(df_filtered['mfe'] >= 10) / len(df_filtered) * 100,
}

print(f"{'Metric':<25} {'Original':<15} {'Filtered':<15} {'Change'}")
print('-'*70)
print(f"{'Count':<25} {original_stats['count']:<15} {filtered_stats['count']:<15} {filtered_stats['count'] - original_stats['count']:+d}")
print(f"{'Avg MFE':<25} {original_stats['mfe_mean']:<14.2f}% {filtered_stats['mfe_mean']:<14.2f}% {(filtered_stats['mfe_mean'] - original_stats['mfe_mean']):+.2f}%")
print(f"{'Median MFE':<25} {original_stats['mfe_median']:<14.2f}% {filtered_stats['mfe_median']:<14.2f}% {(filtered_stats['mfe_median'] - original_stats['mfe_median']):+.2f}%")
print(f"{'Avg MAE':<25} {original_stats['mae_mean']:<14.2f}% {filtered_stats['mae_mean']:<14.2f}% {(filtered_stats['mae_mean'] - original_stats['mae_mean']):+.2f}%")
print(f"{'% >= 2% MFE':<25} {original_stats['pct_2pct']:<14.1f}% {filtered_stats['pct_2pct']:<14.1f}% {(filtered_stats['pct_2pct'] - original_stats['pct_2pct']):+.1f}pp")
print(f"{'% >= 5% MFE':<25} {original_stats['pct_5pct']:<14.1f}% {filtered_stats['pct_5pct']:<14.1f}% {(filtered_stats['pct_5pct'] - original_stats['pct_5pct']):+.1f}pp")
print(f"{'% >= 10% MFE':<25} {original_stats['pct_10pct']:<14.1f}% {filtered_stats['pct_10pct']:<14.1f}% {(filtered_stats['pct_10pct'] - original_stats['pct_10pct']):+.1f}pp")

print()
print('='*70)
print('COMPLETE')
print('='*70)
