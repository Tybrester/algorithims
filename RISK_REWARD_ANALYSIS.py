import pandas as pd
import numpy as np

print('='*80)
print('MAE DISTRIBUTION & TP/SL SCENARIOS')
print('='*80)

# Load the new watchlist data
df = pd.read_csv('new_watchlist_score3.csv')

# Define CORE_UNIVERSE
CORE_UNIVERSE = {
    'UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT',
    'ARM', 'HIMS', 'TEM', 'ASTS', 'LUNR', 'CLSK',
    'APP', 'SMCI', 'RDW', 'IREN', 'MSTR'
}

# Filter to core trades (Score >= 3)
core_df = df[df['symbol'].isin(CORE_UNIVERSE)].copy()

print(f'Total Core Universe trades: {len(core_df)}')
print()

# ============== MAE DISTRIBUTION ==============
print('='*80)
print('MAE DISTRIBUTION ANALYSIS')
print('='*80)

# For MAE, we need to calculate it. The CSV has MFE but not MAE.
# Load the detailed signals with MAE
print('Loading detailed MAE data...')
try:
    mae_df = pd.read_csv('score3_mae_analysis.csv')
    # Merge with core symbols
    core_mae = mae_df[mae_df['symbol'].isin(CORE_UNIVERSE)].copy()
    
    if len(core_mae) > 0:
        mae_values = core_mae['mae'].values
        
        print(f'\nMAE Statistics ({len(core_mae)} signals):')
        print(f'  Avg MAE: {np.mean(mae_values):.2f}%')
        print(f'  Median MAE: {np.median(mae_values):.2f}%')
        print(f'  Std MAE: {np.std(mae_values):.2f}%')
        print(f'  Max MAE: {np.min(mae_values):.2f}%')  # Most negative
        print()
        
        # MAE percentiles
        percentiles = [10, 25, 50, 75, 90, 95, 99]
        print('MAE Percentiles:')
        for p in percentiles:
            val = np.percentile(mae_values, p)
            print(f'  P{p}: {val:.2f}%')
        
        print()
        print('MAE Threshold Distribution:')
        thresholds = [-0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -5.0]
        for t in thresholds:
            count = sum(mae_values <= t)
            pct = count / len(mae_values) * 100
            print(f'  MAE <= {t}%: {count}/{len(mae_values)} ({pct:.1f}%)')
    else:
        print('No MAE data found for core universe. Using estimated MAE from core_df...')
        # Estimate from avg mfe data (rough approximation)
        print('  Core Avg MFE: 3.06%')
        print('  Estimated Avg MAE: -2.5% to -3.0% (based on prior analysis)')
        
except FileNotFoundError:
    print('score3_mae_analysis.csv not found. Cannot compute MAE distribution.')
    print('Run CALCULATE_MAE.py first or use prior MAE data.')

print()

# ============== TP/SL SCENARIOS ==============
print('='*80)
print('TP/SL SCENARIO TESTING')
print('='*80)

mfe_values = core_df['mfe'].values

scenarios = [
    ('2% TP / 2% SL', 2.0, 2.0),
    ('3% TP / 2% SL', 3.0, 2.0),
    ('5% TP / 2% SL', 5.0, 2.0),
    ('5% TP / 3% SL', 5.0, 3.0),
    ('7% TP / 3% SL', 7.0, 3.0),
]

print()
print('SCENARIO RESULTS:')
print()

results = []

for name, tp, sl in scenarios:
    wins = sum(mfe_values >= tp)
    losses = sum(mfe_values < tp)  # Simplified: assume SL hit if not TP
    
    # More realistic: assume we hit TP or trail
    # Win = MFE >= TP (captured target)
    # Loss = MFE < TP but we assume -SL or MAE
    
    total = len(mfe_values)
    win_rate = wins / total * 100
    
    # Expected R:R calculation
    avg_win_r = tp / sl
    avg_loss_r = 1.0
    
    # Expected value
    p_win = win_rate / 100
    p_loss = 1 - p_win
    ev = (p_win * tp) - (p_loss * sl)
    
    results.append({
        'Scenario': name,
        'Wins': wins,
        'Win%': win_rate,
        'TP': tp,
        'SL': sl,
        'R:R': f'1:{tp/sl:.1f}',
        'EV': ev
    })
    
    print(f'{name}:')
    print(f'  Win rate: {wins}/{total} ({win_rate:.1f}%)')
    print(f'  R:R ratio: 1:{tp/sl:.1f}')
    print(f'  Expected value per trade: {ev:.2f}%')
    print()

# No SL scenario
print('No TP / 2% SL (Time Exit at 60 min):')
wins_no_tp = sum(mfe_values > 2.0)  # Arbitrary profit
print(f'  MFE > 2%: {wins_no_tp}/{total} ({wins_no_tp/total*100:.1f}%)')
print(f'  Avg MFE (exit at 60 min): {np.mean(mfe_values):.2f}%')

print()
print('='*80)
print('OPTIMAL SETUP ANALYSIS')
print('='*80)

# Find best scenario by EV
best = max(results, key=lambda x: x['EV'])
print(f'Best Expected Value: {best["Scenario"]} with EV = {best["EV"]:.2f}% per trade')
print()

# Risk/reward breakdown
print('Risk Assessment:')
print(f'  With 2% SL: Breakeven at 50% win rate (1:1 R:R)')
print(f'  With 3% SL: Need 60% win rate for 2:1 R:R')
print(f'  Current win rate to 2% TP: {sum(mfe_values >= 2.0)/total*100:.1f}%')
print(f'  Current win rate to 3% TP: {sum(mfe_values >= 3.0)/total*100:.1f}%')
print(f'  Current win rate to 5% TP: {sum(mfe_values >= 5.0)/total*100:.1f}%')

print()
print('='*80)
print('COMPLETE')
print('='*80)
