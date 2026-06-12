import pandas as pd

df = pd.read_csv('boof30_mfe_mae_signals.csv')

print("=" * 60)
print(f"2-BAR SHORT IGNITION — MFE/MAE ANALYSIS")
print(f"Signals: {len(df)}")
print("=" * 60)

for period in ['15m', '30m', '60m']:
    mfe = df[f'mfe_{period}'].dropna()
    mae = df[f'mae_{period}'].dropna()
    if len(mfe) == 0:
        continue
    
    print(f"\n{period}:")
    print(f"  MFE (favorable for short — price drops):")
    print(f"    Average:        {mfe.mean()*100:>6.2f}%")
    print(f"    Median:         {mfe.median()*100:>6.2f}%")
    print(f"    90th percentile: {mfe.quantile(0.90)*100:>6.2f}%")
    print(f"  MAE (adverse for short — price rises):")
    print(f"    Average:        {mae.mean()*100:>6.2f}%")
    print(f"    Median:         {mae.median()*100:>6.2f}%")
