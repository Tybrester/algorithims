import pandas as pd

print('='*70)
print('DUPLICATE SIGNAL INVESTIGATION')
print('='*70)

df = pd.read_csv('boof30_all_signals_detailed.csv')

# Find all duplicates (same stock, date, window, direction)
dupes = df.groupby(['symbol', 'date', 'window', 'direction']).size()
dupes = dupes[dupes > 1].sort_values(ascending=False)

print(f'Total duplicate cases: {len(dupes)}')
print(f'Max signals per case: {dupes.max()}')
print()

# Show worst offender
worst = dupes.index[0]
print(f'Worst case: {worst}')
print(f'Signals: {dupes.iloc[0]}')
print()

# Get actual signals for worst case
worst_signals = df[
    (df['symbol'] == worst[0]) & 
    (df['date'] == worst[1]) & 
    (df['window'] == worst[2]) & 
    (df['direction'] == worst[3])
]

print('Signals for worst case:')
print(worst_signals[['time', 'entry', 'mfe', 'bar1_rvol', 'is_runner']].to_string())
print()

# Check if times are different (different bars) or same (bug)
print('Time analysis for all duplicates:')
time_diffs = []
for idx in dupes.index[:10]:  # Top 10
    signals = df[
        (df['symbol'] == idx[0]) & 
        (df['date'] == idx[1]) & 
        (df['window'] == idx[2]) & 
        (df['direction'] == idx[3])
    ]
    times = pd.to_datetime(signals['time'])
    time_spread = (times.max() - times.min()).total_seconds() / 60  # minutes
    time_diffs.append(time_spread)
    print(f'{idx[0]} {idx[1]} {idx[2]}: {len(signals)} signals, {time_spread:.0f} min spread')

print()
print(f'Average time spread: {sum(time_diffs)/len(time_diffs):.1f} minutes')
print()

if sum(time_diffs)/len(time_diffs) > 5:
    print('VERDICT: Signals are at DIFFERENT times within the window (not a bug)')
    print('Multiple signals per day = multiple 2-bar patterns forming')
else:
    print('VERDICT: Signals are at SAME time (possible bug)')

print('='*70)
