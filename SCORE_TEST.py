import pandas as pd
import numpy as np

print('='*70)
print('BOOF 30 SCORING SYSTEM TEST')
print('='*70)

# Load data
df = pd.read_csv('boof30_all_signals_detailed.csv')

# Filter for longs only
longs = df[df['direction'] == 'long'].copy()

print(f'Total long signals: {len(longs)}')
print(f'2:30-4PM longs: {len(longs[longs["window"] == "2:30-4PM"])}')
print()

# Calculate LONG_SCORE
longs['LONG_SCORE'] = 0

# Score 1: bar1_rvol > 8
longs.loc[longs['bar1_rvol'] > 8, 'LONG_SCORE'] += 1

# Score 2: bar1_body_pct > 0.9
longs.loc[longs['bar1_body_pct'] > 0.9, 'LONG_SCORE'] += 1

# Score 3: vwap_slope > 0.25
longs.loc[longs['vwap_slope'] > 0.25, 'LONG_SCORE'] += 1

# Score 4: bar2_body_pct > 0.5
longs.loc[longs['bar2_body_pct'] > 0.5, 'LONG_SCORE'] += 1

# Filter for score >= 3
high_score = longs[longs['LONG_SCORE'] >= 3].copy()
low_score = longs[longs['LONG_SCORE'] < 3].copy()

print('='*70)
print('RESULTS')
print('='*70)
print(f'LONG_SCORE >= 3: {len(high_score)} signals')
print(f'LONG_SCORE < 3: {len(low_score)} signals')
print()

# Runner rates
hs_runners = high_score['is_runner'].sum()
hs_total = len(high_score)
hs_rate = hs_runners / hs_total * 100 if hs_total > 0 else 0

ls_runners = low_score['is_runner'].sum()
ls_total = len(low_score)
ls_rate = ls_runners / ls_total * 100 if ls_total > 0 else 0

print(f'Score >= 3: {hs_runners}/{hs_total} runners ({hs_rate:.1f}%)')
print(f'Score < 3: {ls_runners}/{ls_total} runners ({ls_rate:.1f}%)')
print()

if hs_total > 0 and ls_total > 0:
    improvement = hs_rate - ls_rate
    print(f'Improvement: +{improvement:.1f} percentage points')
    print(f'Lift: {hs_rate/ls_rate:.2f}x better' if ls_rate > 0 else 'N/A')

print()
print('='*70)
print('BY TIME WINDOW:')
print('='*70)

for window in ['9:30-11AM', '2:30-4PM']:
    window_data = longs[longs['window'] == window]
    if len(window_data) == 0:
        continue
    
    hs = window_data[window_data['LONG_SCORE'] >= 3]
    ls = window_data[window_data['LONG_SCORE'] < 3]
    
    hs_rate = hs['is_runner'].mean() * 100 if len(hs) > 0 else 0
    ls_rate = ls['is_runner'].mean() * 100 if len(ls) > 0 else 0
    
    print(f"\n{window}:")
    print(f"  Score >= 3: {len(hs)} signals, {hs['is_runner'].sum()} runners ({hs_rate:.1f}%)")
    print(f"  Score < 3: {len(ls)} signals, {ls['is_runner'].sum()} runners ({ls_rate:.1f}%)")
    if len(hs) > 0 and len(ls) > 0:
        print(f"  Lift: {hs_rate/ls_rate:.2f}x" if ls_rate > 0 else "  Lift: N/A")

print()
print('='*70)
print('SCORE BREAKDOWN:')
print('='*70)

for score in sorted(longs['LONG_SCORE'].unique(), reverse=True):
    subset = longs[longs['LONG_SCORE'] == score]
    runner_rate = subset['is_runner'].mean() * 100
    avg_mfe = subset['mfe'].mean()
    
    print(f'Score {score}: {len(subset)} signals, {subset["is_runner"].sum()} runners ({runner_rate:.1f}%), Avg MFE: {avg_mfe:.2f}%')

print()
print('='*70)
print('SAMPLE HIGH-SCORE RUNNERS:')
print('='*70)

high_score_runners = high_score[high_score['is_runner'] == 1]
if len(high_score_runners) > 0:
    for _, r in high_score_runners.head(10).iterrows():
        print(f"{r['symbol']} {r['date']} {r['window']} | Score: {r['LONG_SCORE']} | MFE: {r['mfe']}%")
        print(f"  RVOL1: {r['bar1_rvol']}x | Body1: {r['bar1_body_pct']}% | VWAP Slope: {r['vwap_slope']}")
else:
    print('No high-score runners found')

print()
print('='*70)
print('COMPLETE')
print('='*70)
