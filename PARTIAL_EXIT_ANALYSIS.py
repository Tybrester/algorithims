import pandas as pd
import numpy as np

print('='*80)
print('PARTIAL EXIT STRATEGY ANALYSIS')
print('='*80)
print()
print('Strategy: Score >= 3')
print('  - Enter full position')
print('  - Exit 50% at +1%')
print('  - Exit remaining 50% at +1.75%')  
print('  - Stop Loss: -1%')
print()

# Load data
df = pd.read_csv('new_watchlist_score3.csv')

CORE_UNIVERSE = {
    'UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT',
    'ARM', 'HIMS', 'TEM', 'ASTS', 'LUNR', 'CLSK',
    'APP', 'SMCI', 'RDW', 'IREN', 'MSTR'
}

# Filter to core trades (we need both MFE and MAE data)
# For this simplified analysis, we'll use the signal data and estimate
# based on prior MAE analysis (avg MAE ~ -2.36%, but we use -1% SL)

core_df = df[df['symbol'].isin(CORE_UNIVERSE)].copy()
mfe_values = core_df['mfe'].values
total = len(mfe_values)

print(f'Core Universe Score 3+ trades: {total}')
print()

# For partial exit, we need to know:
# 1. Does it hit -1% SL first? = Full loss
# 2. Does it hit +1% then SL? = 50% @ +1%, 50% @ -1% 
# 3. Does it hit +1% then +1.75%? = 50% @ +1%, 50% @ +1.75%
# 4. Does it hit +1% then neither? = 50% @ +1%, 50% @ final price

# From our MAE analysis:
# - ~33% hit -1% SL (from MAE distribution)
# - 77% of winners hit +1% before +2%

# Simplified model based on data:
# If MFE >= 1.75%: Hits both targets (50% @ 1%, 50% @ 1.75%)
# If 1% <= MFE < 1.75%: Hits 1%, misses 1.75% (50% @ 1%, 50% @ exit)
# If MFE < 1% and MAE <= -1%: Full SL hit
# If MFE < 1% and MAE > -1%: Scratch/loss smaller than -1%

# Estimate based on distributions:
hit_1_75 = sum(mfe_values >= 1.75)  # Both targets
hit_1_only = sum((mfe_values >= 1.0) & (mfe_values < 1.75))  # Only first target
miss_1 = sum(mfe_values < 1.0)  # Miss first target

print('Based on MFE distribution:')
print(f'  Hit +1.75% (both targets): {hit_1_75}/{total} ({hit_1_75/total*100:.1f}%)')
print(f'  Hit +1% only: {hit_1_only}/{total} ({hit_1_only/total*100:.1f}%)')
print(f'  Miss +1%: {miss_1}/{total} ({miss_1/total*100:.1f}%)')
print()

# Estimate SL hits
# From MAE analysis, ~50% hit -2% or worse, ~33% hit -1% or worse
# Assume ~30% of trades hit -1% SL
sl_rate = 0.30  # Estimated from MAE distribution

# Calculate scenarios:
# Scenario A: Both targets hit (50% @ 1%, 50% @ 1.75%)
p_a = hit_1_75 / total
result_a = 0.5 * 1.0 + 0.5 * 1.75  # +1.375% avg

# Scenario B: Only 1% hit, then SL (50% @ 1%, 50% @ -1%)
# Assume 30% of "hit 1% only" hit SL
p_b = (hit_1_only / total) * sl_rate
result_b = 0.5 * 1.0 + 0.5 * (-1.0)  # 0% scratch

# Scenario C: Only 1% hit, then trail/no SL (50% @ 1%, 50% @ some exit)
# Remaining 70% of "hit 1% only" - assume exit at avg MFE of this bucket
p_c = (hit_1_only / total) * (1 - sl_rate)
mfe_1_to_175 = mfe_values[(mfe_values >= 1.0) & (mfe_values < 1.75)]
avg_exit_c = np.mean(mfe_1_to_175) if len(mfe_1_to_175) > 0 else 1.25
result_c = 0.5 * 1.0 + 0.5 * avg_exit_c

# Scenario D: Full SL (never hit 1%, hit -1%)
p_d = (miss_1 / total) * sl_rate
result_d = -1.0  # Full -1% loss

# Scenario E: Miss 1%, small loss/no SL
p_e = (miss_1 / total) * (1 - sl_rate)
mfe_below_1 = mfe_values[mfe_values < 1.0]
avg_exit_e = np.mean(mfe_below_1) if len(mfe_below_1) > 0 else 0.5
result_e = avg_exit_e  # Exit at avg MFE (small gain/loss)

# Normalize probabilities
total_p = p_a + p_b + p_c + p_d + p_e
p_a, p_b, p_c, p_d, p_e = p_a/total_p, p_b/total_p, p_c/total_p, p_d/total_p, p_e/total_p

print('='*80)
print('SCENARIO BREAKDOWN')
print('='*80)
print(f'A. Both targets hit:      {p_a*100:.1f}% | Result: +{result_a:.2f}%')
print(f'B. 1% then SL:            {p_b*100:.1f}% | Result: {result_b:+.2f}% (scratch)')
print(f'C. 1% then trail:         {p_c*100:.1f}% | Result: +{result_c:.2f}%')
print(f'D. Full SL (-1%):         {p_d*100:.1f}% | Result: {result_d:+.2f}%')
print(f'E. Miss 1%, small exit:   {p_e*100:.1f}% | Result: +{result_e:.2f}%')
print()

# Calculate expected value
ev = (p_a * result_a) + (p_b * result_b) + (p_c * result_c) + (p_d * result_d) + (p_e * result_e)

print('='*80)
print('EXPECTED VALUE CALCULATION')
print('='*80)
print(f'Expected Value per Trade: {ev:+.2f}%')
print()

# Win rate (positive outcome)
win_rate = (p_a + p_c + (p_e if result_e > 0 else 0)) * 100
print(f'Win Rate (positive): {win_rate:.1f}%')
print(f'Scratch Rate: {p_b*100:.1f}%')
print(f'Loss Rate: {(p_d + (p_e if result_e < 0 else 0))*100:.1f}%')

print()
print('='*80)
print('COMPARISON TO SINGLE EXIT STRATEGIES')
print('='*80)
print()
print('Partial Exit (1% + 1.75%, -1% SL):')
print(f'  EV: {ev:+.2f}% per trade')
print(f'  Win rate: ~{win_rate:.0f}%')
print()
print('1.75% TP / 1% SL (single exit):')
print(f'  EV: +0.71% per trade')
print(f'  Win rate: 62.3%')
print()
print('2% TP / 2% SL (single exit):')
print(f'  EV: +0.23% per trade')
print(f'  Win rate: 55.6%')
print()

if ev > 0.71:
    print('✓ Partial exit OUTPERFORMS single exit')
else:
    print('→ Single exit at 1.75% / 1% SL may be simpler with similar EV')

print('='*80)
print()
print('NOTE: This is an estimate. For precise calculation,')
print('we need bar-by-bar data to track path (which hits first).')
print('='*80)
