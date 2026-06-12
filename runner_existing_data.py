"""
Analyze runners from existing CSV data
"""
import pandas as pd
import glob

# Find all existing data files
files = glob.glob('boof24_*_1Min_*.csv') + glob.glob('boof30_mfe_mae_signals.csv')
print(f"Found {len(files)} data files")
for f in files[:10]:
    print(f"  {f}")

# Load the main signals file if it exists
try:
    df = pd.read_csv('boof30_mfe_mae_signals.csv')
    print(f"\nLoaded boof30_mfe_mae_signals.csv: {len(df)} rows")
    print(f"Columns: {df.columns.tolist()}")
    print(f"\nSample data:")
    print(df.head(3))
    
    # Get runners (MFE >= 2%)
    if 'mfe_60m' in df.columns:
        runners = df[df['mfe_60m'] >= 0.02]
        print(f"\n{'='*80}")
        print(f"RUNNERS (MFE 60m >= 2%): {len(runners)} signals")
        print(f"{'='*80}")
        
        if len(runners) > 0:
            # Print available fields
            cols = runners.columns.tolist()
            print(f"\nAvailable fields: {cols}")
            print(f"\nRunner details:")
            for idx, row in runners.head(20).iterrows():
                print(f"\nSignal #{idx}:")
                for col in cols:
                    if col != 'Unnamed: 0':
                        val = row[col]
                        if 'mfe' in col or 'mae' in col:
                            print(f"  {col}: {val*100:.2f}%")
                        else:
                            print(f"  {col}: {val}")
        else:
            print("No runners found (MFE >= 2%)")
    else:
        print("No 'mfe_60m' column found")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
