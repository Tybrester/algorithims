import pandas as pd
import numpy as np

print('='*80)
print('DYNAMIC THRESHOLD ANALYSIS')
print('='*80)

# Load the data
df = pd.read_csv('new_watchlist_score3.csv')

# Define CORE_UNIVERSE (top performers from analysis)
CORE_UNIVERSE = {
    'UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT',  # Original Watchlist A
    'ARM', 'HIMS', 'TEM', 'ASTS', 'LUNR', 'CLSK',     # New high-performers
    'APP', 'SMCI', 'RDW', 'IREN', 'MSTR'              # Additional solid names
}

print(f'CORE_UNIVERSE: {sorted(CORE_UNIVERSE)}')
print(f'Total symbols in dataset: {df["symbol"].nunique()}')
print()

# Apply dynamic thresholds
def should_trade(row):
    if row['symbol'] in CORE_UNIVERSE:
        return row['LONG_SCORE'] >= 3
    else:
        return row['LONG_SCORE'] >= 6

df['should_trade'] = df.apply(should_trade, axis=1)
df['is_core'] = df['symbol'].isin(CORE_UNIVERSE)

# Split analysis
core_df = df[df['is_core']].copy()
ext_df = df[~df['is_core']].copy()

# Trades only
core_trades = core_df[core_df['should_trade']].copy()
ext_trades = ext_df[ext_df['should_trade']].copy() if 'LONG_SCORE' in ext_df.columns else pd.DataFrame()

print('='*80)
print('CORE_UNIVERSE (threshold = 3)')
print('='*80)
print(f'  Symbols: {len(CORE_UNIVERSE)}')
print(f'  Total signals (Score 3+): {len(core_df)}')
print(f'  Trades taken (Score >= 3): {len(core_trades)}')
print()

if len(core_trades) > 0:
    runners = sum(core_trades['mfe'] >= 2)
    print(f'  Runner rate (MFE >= 2%): {runners}/{len(core_trades)} ({runners/len(core_trades)*100:.1f}%)')
    print(f'  Avg MFE: {core_trades["mfe"].mean():.2f}%')
    print(f'  Median MFE: {core_trades["mfe"].median():.2f}%')
    print(f'  Max MFE: {core_trades["mfe"].max():.2f}%')

print()
print('='*80)
print('EXTENDED UNIVERSE (threshold = 6)')
print('='*80)
print(f'  Symbols: {df["symbol"].nunique() - len(CORE_UNIVERSE)}')

# Check if any extended symbols have score 6+
if len(ext_df) > 0 and 'LONG_SCORE' in ext_df.columns:
    ext_high = ext_df[ext_df['LONG_SCORE'] >= 6]
    print(f'  Signals with Score >= 6: {len(ext_high)}')
    
    if len(ext_high) > 0:
        print(f'  Symbols with Score 6+: {sorted(ext_high["symbol"].unique())}')
        print()
        runners = sum(ext_high['mfe'] >= 2)
        print(f'  Runner rate: {runners}/{len(ext_high)} ({runners/len(ext_high)*100:.1f}%)')
        print(f'  Avg MFE: {ext_high["mfe"].mean():.2f}%')
    else:
        print('  -> NO trades from extended universe (no Score 6+ signals)')
else:
    print('  -> NO extended universe data')

print()
print('='*80)
print('COMBINED RESULTS')
print('='*80)

total_trades = len(core_trades) + len(ext_trades)
if total_trades > 0:
    all_trades = pd.concat([core_trades, ext_trades]) if len(ext_trades) > 0 else core_trades
    runners = sum(all_trades['mfe'] >= 2)
    
    print(f'Total trades: {total_trades}')
    print(f'  - Core universe: {len(core_trades)} ({len(core_trades)/total_trades*100:.1f}%)')
    print(f'  - Extended universe: {len(ext_trades)} ({len(ext_trades)/total_trades*100:.1f}%)')
    print()
    print(f'Runner rate: {runners}/{total_trades} ({runners/total_trades*100:.1f}%)')
    print(f'Avg MFE: {all_trades["mfe"].mean():.2f}%')
    print(f'Median MFE: {all_trades["mfe"].median():.2f}%')

print()
print('='*80)
print('PER SYMBOL (Core Universe Trades Only)')
print('='*80)

if len(core_trades) > 0:
    core_stats = core_trades.groupby('symbol').agg({
        'mfe': ['count', 'mean', 'median', lambda x: sum(x >= 2)]
    }).round(2)
    core_stats.columns = ['Trades', 'Avg MFE', 'Median MFE', 'Runners']
    core_stats['Runner%'] = (core_stats['Runners'] / core_stats['Trades'] * 100).round(1)
    core_stats = core_stats.sort_values('Avg MFE', ascending=False)
    print(core_stats.to_string())

print()
print('='*80)
print('TRADING LOGIC SUMMARY')
print('='*80)
print('''if symbol in CORE_UNIVERSE:
    trade_threshold = 3
else:
    trade_threshold = 6  # Only extreme Score for outside symbols
trade = score >= trade_threshold''')
print()
print(f'Core universe captures {len(core_trades)}/{total_trades} trades ({len(core_trades)/total_trades*100:.1f}%)')
print('Extended universe only trades on extreme Score 6+ signals')
print('='*80)
