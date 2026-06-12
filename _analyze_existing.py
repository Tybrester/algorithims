import pandas as pd

# Load the existing signals
df = pd.read_csv('boof30_mfe_mae_signals.csv')

print("="*90)
print("MFE/MAE ANALYSIS BY FILTER COMBINATION")
print("="*90)
print(f"Total signals: {len(df)}")

# Since we don't have the detailed RVOL/VWAP data in the original CSV,
# let's just analyze the MFE/MAE relationship

print("\n" + "="*90)
print("OVERALL STATISTICS")
print("="*90)

for period in ['15m', '30m', '60m']:
    mfe = df[f'mfe_{period}'].dropna()
    mae = df[f'mae_{period}'].dropna()
    if len(mfe) == 0:
        continue
    
    mfe_gt_mae = (mfe > mae).mean() * 100
    perfect = ((mfe > 0.01) & (mae < 0.005)).mean() * 100
    
    print(f"\n{period}:")
    print(f"  MFE > MAE rate:       {mfe_gt_mae:.1f}%")
    print(f"  Perfect trade rate:   {perfect:.1f}% (MFE>1% & MAE<0.5%)")
    print(f"  MFE: Avg={mfe.mean()*100:.2f}% Med={mfe.median()*100:.2f}% P90={mfe.quantile(0.90)*100:.2f}%")
    print(f"  MAE: Avg={mae.mean()*100:.2f}% Med={mae.median()*100:.2f}%")

print("\n" + "="*90)
