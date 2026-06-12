import pandas as pd
import numpy as np

print('='*80)
print('WATCHLIST A - FOCUSED ANALYSIS')
print('='*80)

# Load data
df = pd.read_csv('score3_mae_analysis.csv')

# Watchlist A
watchlist_a = ['UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT']

print(f'Watchlist A: {watchlist_a}')
print()

# Filter
wl_df = df[df['symbol'].isin(watchlist_a)].copy()

print(f'Signals from Watchlist A: {len(wl_df)}')
print(f'Excluded (GOEV, BBBY, AMC): {len(df[df["symbol"].isin(["GOEV", "BBBY", "AMC"])])} signals')
print()

if len(wl_df) == 0:
    print('No signals found for Watchlist A')
    exit()

# Overall stats
mfe_values = wl_df['mfe'].values
mae_values = wl_df['mae'].values

print('='*80)
print('WATCHLIST A - OVERALL PERFORMANCE')
print('='*80)
print(f'  Signals: {len(wl_df)}')
print()

# Runner rate (MFE >= 2%)
runners = sum(mfe_values >= 2)
runner_rate = runners / len(wl_df) * 100
print(f'  Runners (MFE >= 2%): {runners}/{len(wl_df)} ({runner_rate:.1f}%)')
print()

print(f'  Avg MFE: {np.mean(mfe_values):.2f}%')
print(f'  Median MFE: {np.median(mfe_values):.2f}%')
print(f'  Max MFE: {np.max(mfe_values):.2f}%')
print()
print(f'  Avg MAE: {np.mean(mae_values):.2f}%')
print(f'  Median MAE: {np.median(mae_values):.2f}%')
print()

# Win rate (MFE > |MAE|)
wins = sum(mfe_values > abs(mae_values))
win_rate = wins / len(wl_df) * 100
rr_ratio = np.mean(mfe_values) / abs(np.mean(mae_values))

print(f'  Win Rate (MFE > |MAE|): {wins}/{len(wl_df)} ({win_rate:.1f}%)')
print(f'  Risk/Reward: 1:{rr_ratio:.2f}')
print()

# Per symbol breakdown
print('='*80)
print('PER SYMBOL BREAKDOWN')
print('='*80)

for symbol in watchlist_a:
    sym_df = wl_df[wl_df['symbol'] == symbol]
    if len(sym_df) == 0:
        print(f'{symbol:6}: No signals')
        continue
    
    mfe_vals = sym_df['mfe'].values
    mae_vals = sym_df['mae'].values
    
    signals = len(sym_df)
    runners = sum(mfe_vals >= 2)
    runner_rate = runners / signals * 100
    
    avg_mfe = np.mean(mfe_vals)
    avg_mae = np.mean(mae_vals)
    
    print(f'{symbol:6}: {signals:2} signals | {runners} runners ({runner_rate:.0f}%) | '
          f'Avg MFE: {avg_mfe:5.2f}% | Avg MAE: {avg_mae:6.2f}%')

print()

# Monthly distribution
wl_df['date'] = pd.to_datetime(wl_df['date'])
wl_df['month'] = wl_df['date'].dt.to_period('M')

print('='*80)
print('MONTHLY FLOW')
print('='*80)

monthly = wl_df.groupby('month').agg({
    'symbol': 'count',
    'mfe': ['mean', lambda x: sum(x >= 2)]
}).round(2)

monthly.columns = ['Signals', 'Avg MFE', 'Runners']
print(monthly.to_string())

print()
print(f'Monthly average: {len(wl_df) / wl_df["month"].nunique():.1f} signals')

print()
print('='*80)
print('TOP 10 PERFORMERS (Watchlist A)')
print('='*80)

top = wl_df.nlargest(10, 'mfe')
for _, r in top.iterrows():
    mae_pct = abs(r['mae'])
    rr = r['mfe'] / mae_pct if mae_pct > 0 else 0
    print(f"{r['symbol']:6} {str(r['date'])[:10]} | MFE: {r['mfe']:5.2f}% | MAE: {r['mae']:6.2f}% | RR: 1:{rr:.1f}")

print()
print('='*80)
print('SUMMARY')
print('='*80)
print(f'Watchlist A delivers {len(wl_df)} signals with {runner_rate:.1f}% runner rate')
print(f'Avg MFE: {np.mean(mfe_values):.2f}% | Avg MAE: {np.mean(mae_values):.2f}%')
print(f'Risk/Reward: 1:{rr_ratio:.2f}')
print()
print('Clean, tradeable set without meme stock volatility.')
print('='*80)
