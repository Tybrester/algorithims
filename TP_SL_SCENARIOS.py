import pandas as pd
import numpy as np

print('='*80)
print('TP/SL SCENARIO COMPARISON')
print('='*80)

# Load the data
df = pd.read_csv('new_watchlist_score3.csv')

# Define CORE_UNIVERSE
CORE_UNIVERSE = {
    'UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT',
    'ARM', 'HIMS', 'TEM', 'ASTS', 'LUNR', 'CLSK',
    'APP', 'SMCI', 'RDW', 'IREN', 'MSTR'
}

# Filter to core trades
core_df = df[df['symbol'].isin(CORE_UNIVERSE)].copy()
mfe_values = core_df['mfe'].values
total = len(mfe_values)

print(f'Core Universe trades: {total}')
print()

# Define scenarios: (name, TP%, SL%)
scenarios = [
    ('2% TP / 2% SL', 2.0, 2.0),
    ('2% TP / 1% SL', 2.0, 1.0),
    ('1.5% TP / 1% SL', 1.5, 1.0),
    ('1.75% TP / 1% SL', 1.75, 1.0),
    ('1% TP / 1% SL', 1.0, 1.0),
]

print('='*80)
print('SCENARIO RESULTS')
print('='*80)
print()

results = []

for name, tp, sl in scenarios:
    wins = sum(mfe_values >= tp)
    win_rate = wins / total * 100
    
    # Expected value calculation
    p_win = win_rate / 100
    p_loss = 1 - p_win
    ev = (p_win * tp) - (p_loss * sl)
    
    # R:R ratio
    rr_ratio = tp / sl
    
    # Breakeven win rate
    be_rate = sl / (tp + sl) * 100
    
    results.append({
        'Scenario': name,
        'Wins': wins,
        'Win%': win_rate,
        'TP': tp,
        'SL': sl,
        'R:R': f'1:{rr_ratio:.2f}',
        'EV': ev,
        'BE_Rate': be_rate
    })
    
    print(f'{name}:')
    print(f'  Win rate: {wins}/{total} ({win_rate:.1f}%)')
    print(f'  R:R ratio: 1:{rr_ratio:.2f}')
    print(f'  Breakeven needed: {be_rate:.1f}%')
    print(f'  Expected value: {ev:+.2f}% per trade')
    print()

# Sort by EV
results_df = pd.DataFrame(results)
results_df = results_df.sort_values('EV', ascending=False)

print('='*80)
print('RANKED BY EXPECTED VALUE')
print('='*80)
print()
print(results_df[['Scenario', 'Win%', 'R:R', 'EV']].to_string(index=False))

print()
print('='*80)
print('RECOMMENDATION')
print('='*80)

best = results_df.iloc[0]
print(f'Best setup: {best["Scenario"]}')
print(f'  Expected value: {best["EV"]:+.2f}% per trade')
print(f'  Win rate: {best["Win%"]:.1f}%')
print()

# Compare specifically requested scenarios
print('Comparison of requested setups:')
print()
for name, tp, sl in [('2% TP / 1% SL', 2.0, 1.0), ('1.5% TP / 1% SL', 1.5, 1.0), ('1.75% TP / 1% SL', 1.75, 1.0)]:
    row = results_df[results_df['Scenario'] == name].iloc[0]
    print(f'{name}: EV = {row["EV"]:+.2f}%, Win% = {row["Win%"]:.1f}%')

print()
print('Key insight: Tighter SL (1%) with 2% TP gives 2:1 R:R')
print('             but requires higher win rate to breakeven')
print('='*80)
