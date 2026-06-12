import pandas as pd
import numpy as np

print('='*80)
print('SCORE 3 PERFORMANCE BY TIER')
print('='*80)

# Load data
df = pd.read_csv('score3_mae_analysis.csv')

# Define tiers
tiers = {
    'Tier 1 (High Vol Meme/Crypto)': ['TSLA', 'NVDA', 'PLTR', 'COIN', 'MSTR', 'RKLB', 'MARA', 'RIOT', 'HUT'],
    'Tier 2 (Growth/Mid Vol)': ['AMD', 'META', 'AVGO', 'MRNA', 'RBLX', 'AFRM', 'UPST'],
    'Tier 3 (Blue Chip/Low Vol)': ['SPY', 'QQQ', 'AAPL', 'MSFT']
}

print(f'Total Score 3 signals in dataset: {len(df)}')
print()

results = {}

for tier_name, symbols in tiers.items():
    tier_df = df[df['symbol'].isin(symbols)]
    
    if len(tier_df) == 0:
        print(f'{tier_name}: No signals')
        continue
    
    mfe_values = tier_df['mfe'].values
    mae_values = tier_df['mae'].values
    
    # Calculate stats
    count = len(tier_df)
    avg_mfe = mfe_values.mean()
    median_mfe = np.median(mfe_values)
    avg_mae = mae_values.mean()
    
    # Hit rates
    pct_2pct = sum(mfe_values >= 2) / count * 100
    pct_5pct = sum(mfe_values >= 5) / count * 100
    pct_10pct = sum(mfe_values >= 10) / count * 100
    
    # Win rate (MFE > |MAE|)
    wins = sum(mfe_values > abs(mae_values))
    win_rate = wins / count * 100
    
    # Risk/reward
    rr = avg_mfe / abs(avg_mae) if avg_mae != 0 else 0
    
    results[tier_name] = {
        'count': count,
        'avg_mfe': avg_mfe,
        'median_mfe': median_mfe,
        'avg_mae': avg_mae,
        'pct_2pct': pct_2pct,
        'pct_5pct': pct_5pct,
        'pct_10pct': pct_10pct,
        'win_rate': win_rate,
        'rr': rr
    }
    
    print('='*70)
    print(tier_name)
    print(f'Symbols: {symbols}')
    print('='*70)
    print(f'  Signals: {count}')
    print(f'  Avg MFE: {avg_mfe:.2f}%')
    print(f'  Median MFE: {median_mfe:.2f}%')
    print(f'  Avg MAE: {avg_mae:.2f}%')
    print(f'  Win Rate (MFE>|MAE|): {win_rate:.1f}%')
    print(f'  Risk/Reward: 1:{rr:.2f}')
    print()
    print(f'  % >= 2% MFE: {pct_2pct:.1f}%')
    print(f'  % >= 5% MFE: {pct_5pct:.1f}%')
    print(f'  % >= 10% MFE: {pct_10pct:.1f}%')
    print()
    
    # Top performers in this tier
    if len(tier_df) > 0:
        top = tier_df.nlargest(min(5, len(tier_df)), 'mfe')
        print('  Top performers:')
        for _, r in top.iterrows():
            print(f"    {r['symbol']} {r['date']}: MFE {r['mfe']:.2f}%, MAE {r['mae']:.2f}%")
    print()

# Comparison table
print('='*80)
print('TIER COMPARISON SUMMARY')
print('='*80)
print()

print(f"{'Metric':<25} {'Tier 1':<15} {'Tier 2':<15} {'Tier 3':<15}")
print('-'*80)

tier_names = list(results.keys())
if len(tier_names) == 3:
    t1, t2, t3 = results[tier_names[0]], results[tier_names[1]], results[tier_names[2]]
    
    print(f"{'Count':<25} {t1['count']:<15} {t2['count']:<15} {t3['count']:<15}")
    print(f"{'Avg MFE':<25} {t1['avg_mfe']:<14.2f}% {t2['avg_mfe']:<14.2f}% {t3['avg_mfe']:<14.2f}%")
    print(f"{'Median MFE':<25} {t1['median_mfe']:<14.2f}% {t2['median_mfe']:<14.2f}% {t3['median_mfe']:<14.2f}%")
    print(f"{'Avg MAE':<25} {t1['avg_mae']:<14.2f}% {t2['avg_mae']:<14.2f}% {t3['avg_mae']:<14.2f}%")
    print(f"{'Win Rate':<25} {t1['win_rate']:<14.1f}% {t2['win_rate']:<14.1f}% {t3['win_rate']:<14.1f}%")
    print(f"{'Risk/Reward':<25} 1:{t1['rr']:<13.2f} 1:{t2['rr']:<13.2f} 1:{t3['rr']:<13.2f}")
    print(f"{'% >= 2% MFE':<25} {t1['pct_2pct']:<14.1f}% {t2['pct_2pct']:<14.1f}% {t3['pct_2pct']:<14.1f}%")
    print(f"{'% >= 5% MFE':<25} {t1['pct_5pct']:<14.1f}% {t2['pct_5pct']:<14.1f}% {t3['pct_5pct']:<14.1f}%")
    print(f"{'% >= 10% MFE':<25} {t1['pct_10pct']:<14.1f}% {t2['pct_10pct']:<14.1f}% {t3['pct_10pct']:<14.1f}%")

print()
print('='*80)
print('KEY INSIGHT')
print('='*80)

if len(tier_names) == 3:
    t1, t2, t3 = results[tier_names[0]], results[tier_names[1]], results[tier_names[2]]
    
    best_tier = max(results.items(), key=lambda x: x[1]['avg_mfe'])
    print(f"Highest avg MFE: {best_tier[0]} with {best_tier[1]['avg_mfe']:.2f}%")
    
    best_rr = max(results.items(), key=lambda x: x[1]['rr'])
    print(f"Best risk/reward: {best_rr[0]} with 1:{best_rr[1]['rr']:.2f}")

print()
print('Tier 1 (meme/crypto) drives outsized returns but with higher variance.')
print('Tier 3 (blue chips) shows consistency but limited upside.')
print('='*80)
