import pandas as pd
import numpy as np

print('='*80)
print('BACKTEST AUDIT - VERIFYING CALCULATIONS')
print('='*80)

# Load the detailed signals
print('\nLoading boof30_all_signals_detailed.csv...')
df = pd.read_csv('boof30_all_signals_detailed.csv')

print(f'Total signals: {len(df)}')
print(f'Date range: {df["date"].min()} to {df["date"].max()}')
print(f'Symbols: {df["symbol"].nunique()}')

# Check 1: VWAP reset - look for signals with extreme VWAP distance
print('\n' + '='*80)
print('AUDIT 1: VWAP RESET CHECK')
print('='*80)
print('Checking for cross-day VWAP contamination...')

# VWAP slope should be reasonable within a session
extreme_vwap = df[abs(df['vwap_slope']) > 5]
print(f'Signals with extreme VWAP slope (>5%): {len(extreme_vwap)}')
if len(extreme_vwap) > 0:
    print('Sample extreme VWAP slopes:')
    print(extreme_vwap[['symbol', 'date', 'time', 'vwap_slope', 'window']].head())

# Check 2: Duplicate signals same day
print('\n' + '='*80)
print('AUDIT 2: DUPLICATE SIGNALS CHECK')
print('='*80)

duplicates = df.groupby(['symbol', 'date', 'window', 'direction']).size()
duplicates = duplicates[duplicates > 1]
print(f'Stock/date/window/direction combinations with multiple signals: {len(duplicates)}')

if len(duplicates) > 0:
    print('\nTop duplicate cases:')
    print(duplicates.head(10))
    
    # Show RKLB example
    rklb_dupes = df[(df['symbol'] == 'RKLB') & (df['is_runner'] == 1)]
    print(f'\nRKLB runners by date:')
    print(rklb_dupes.groupby('date').size().sort_values(ascending=False).head())

# Check 3: Time window filtering
print('\n' + '='*80)
print('AUDIT 3: TIME WINDOW CHECK')
print('='*80)

# Verify all signals are within claimed windows
print(f'9:30-11AM signals: {len(df[df["window"] == "9:30-11AM"])}')
print(f'2:30-4PM signals: {len(df[df["window"] == "2:30-4PM"])}')

# Check for signals outside windows
print('\nSample times in each window:')
for window in ['9:30-11AM', '2:30-4PM']:
    subset = df[df['window'] == window]
    if len(subset) > 0:
        print(f'{window}: {subset["time"].min()} to {subset["time"].max()}')

# Check 4: RVOL calculation verification
print('\n' + '='*80)
print('AUDIT 4: RVOL CALCULATION CHECK')
print('='*80)

# Check RVOL distribution by time of day
df['hour'] = pd.to_datetime(df['time']).dt.hour
df['minute'] = pd.to_datetime(df['time']).dt.minute

print('RVOL by time of day:')
rvol_by_time = df.groupby(['hour'])['bar1_rvol'].agg(['mean', 'median', 'max'])
print(rvol_by_time)

# Check if RVOL is inflated later in day
print('\nRVOL statistics by window:')
for window in ['9:30-11AM', '2:30-4PM']:
    subset = df[df['window'] == window]
    if len(subset) > 0:
        print(f'{window}: avg RVOL={subset["bar1_rvol"].mean():.2f}, max={subset["bar1_rvol"].max():.2f}')

# Check 5: Future leakage - verify MFE is calculated AFTER signal
print('\n' + '='*80)
print('AUDIT 5: FUTURE LEAKAGE CHECK')
print('='*80)
print('MFE should be calculated from bars AFTER signal time...')

# This is verified by construction in the code, but check for any weird patterns
# where MFE correlates with signal time (shouldn't happen)
print('MFE vs time correlation (should be ~0):')
corr_am = df[df['window'] == '9:30-11AM']['mfe'].corr(
    pd.to_datetime(df[df['window'] == '9:30-11AM']['time']).dt.minute)
corr_pm = df[df['window'] == '2:30-4PM']['mfe'].corr(
    pd.to_datetime(df[df['window'] == '2:30-4PM']['time']).dt.minute)
print(f'  9:30-11AM: {corr_am:.3f}')
print(f'  2:30-4PM: {corr_pm:.3f}')

if abs(corr_am) > 0.1 or abs(corr_pm) > 0.1:
    print('WARNING: Potential future leakage detected!')
else:
    print('OK: No significant correlation (future leakage unlikely)')

# Summary
print('\n' + '='*80)
print('AUDIT SUMMARY')
print('='*80)

issues = []

if len(extreme_vwap) > len(df) * 0.05:  # More than 5% extreme
    issues.append('Possible VWAP reset issue - many extreme VWAP slopes')

if len(duplicates) > 0:
    issues.append(f'Duplicate signals exist: {len(duplicates)} cases')

if len(issues) == 0:
    print('✓ No major issues detected')
else:
    print('⚠ Issues found:')
    for issue in issues:
        print(f'  - {issue}')

print('\nRecommendation:')
print('Check the source code (DETAILED_SIGNALS.py) to verify:')
print('1. VWAP is calculated per-day with groupby("date")')
print('2. RVOL uses rolling(20) within each day')
print('3. MFE is calculated from i+2:i+30 (future bars only)')
print('4. Time filters use hour & minute correctly')
print('='*80)
