import pandas as pd
import numpy as np

print('='*70)
print('RUNNER vs NON-RUNNER COMPARISON')
print('='*70)

# Load the detailed signals
df = pd.read_csv('boof30_all_signals_detailed.csv')

print(f'Total signals: {len(df)}')
print(f'Runners (MFE >= 2%): {df["is_runner"].sum()}')
print(f'Non-runners: {len(df) - df["is_runner"].sum()}')
print()

# Separate runners and non-runners
runners = df[df['is_runner'] == 1]
non_runners = df[df['is_runner'] == 0]

# Calculate metrics
metrics = ['bar1_rvol', 'bar2_rvol', 'bar1_body_pct', 'bar2_body_pct', 'vwap_slope']

print('='*70)
print(f"{'Metric':<20} {'Runner Avg':<15} {'Non-Runner Avg':<15} {'Difference'}")
print('-'*70)

for metric in metrics:
    r_avg = runners[metric].mean()
    nr_avg = non_runners[metric].mean()
    diff = r_avg - nr_avg
    
    print(f"{metric:<20} {r_avg:>14.2f} {nr_avg:>14.2f} {diff:>+10.2f}")

print()
print('='*70)
print('BY DIRECTION & WINDOW:')
print('='*70)

for window in ['9:30-11AM', '2:30-4PM']:
    for direction in ['long', 'short']:
        subset = df[(df['window'] == window) & (df['direction'] == direction)]
        if len(subset) == 0:
            continue
            
        r = subset[subset['is_runner'] == 1]
        nr = subset[subset['is_runner'] == 0]
        
        print(f"\n{window} {direction.upper()}:")
        print(f"  Runners: {len(r)} | Non-runners: {len(nr)}")
        
        if len(r) > 0 and len(nr) > 0:
            for metric in ['bar1_rvol', 'bar2_rvol', 'bar1_body_pct', 'vwap_slope']:
                r_avg = r[metric].mean()
                nr_avg = nr[metric].mean()
                diff_pct = ((r_avg - nr_avg) / abs(nr_avg) * 100) if nr_avg != 0 else 0
                print(f"    {metric}: Runner={r_avg:.2f}, Non={nr_avg:.2f} ({diff_pct:+.1f}%)")

print()
print('='*70)
print('COMPLETE')
print('='*70)
