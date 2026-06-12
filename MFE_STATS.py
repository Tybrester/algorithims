import pandas as pd
import numpy as np

print('='*60)
print('MFE STATISTICS COMPARISON')
print('='*60)

# Load the CSV files
try:
    am_df = pd.read_csv('boof30_runners_9_11am.csv')
    pm_df = pd.read_csv('boof30_runners_2_30_4pm.csv')
    
    # Morning stats
    am_mfe = am_df['mfe'].values
    am_avg = np.mean(am_mfe)
    am_p90 = np.percentile(am_mfe, 90)
    
    # Afternoon stats  
    pm_mfe = pm_df['mfe'].values
    pm_avg = np.mean(pm_mfe)
    pm_p90 = np.percentile(pm_mfe, 90)
    
    print()
    print(f"{'Window':<15} {'Avg MFE':<12} {'P90 MFE':<12} {'Count'}")
    print('-'*60)
    print(f"{'Morning':<15} {am_avg:>10.2f}% {am_p90:>10.2f}% {len(am_mfe):>5}")
    print(f"{'Afternoon':<15} {pm_avg:>10.2f}% {pm_p90:>10.2f}% {len(pm_mfe):>5}")
    print()
    
    # Additional stats
    print('Additional Stats:')
    print(f"  Morning MFE range: {am_mfe.min():.2f}% to {am_mfe.max():.2f}%")
    print(f"  Afternoon MFE range: {pm_mfe.min():.2f}% to {pm_mfe.max():.2f}%")
    print(f"  Morning median: {np.median(am_mfe):.2f}%")
    print(f"  Afternoon median: {np.median(pm_mfe):.2f}%")
    print()
    
    # Best runners
    print('Top 3 Morning Runners (by MFE):')
    top_am = am_df.nsmallest(3, 'mfe')
    for _, r in top_am.iterrows():
        print(f"  {r['symbol']} {r['date']} | MFE: {r['mfe']}%")
    
    print()
    print('Top 3 Afternoon Runners (by MFE):')
    top_pm = pm_df.nsmallest(3, 'mfe')
    for _, r in top_pm.iterrows():
        print(f"  {r['symbol']} {r['date']} | MFE: {r['mfe']}%")
    
except FileNotFoundError as e:
    print(f'Error: Could not find file - {e}')
except Exception as e:
    print(f'Error: {e}')

print('='*60)
