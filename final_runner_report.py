"""
Final Runner Analysis Report
Uses all available existing data files
"""
import pandas as pd
import numpy as np
import glob

# Load signals
df = pd.read_csv('boof30_mfe_mae_signals.csv')
print(f"Loaded {len(df)} signals from boof30_mfe_mae_signals.csv")
print(f"Columns: {list(df.columns)}\n")

# Check for MFE 60m column
mfe_col = 'mfe_60m' if 'mfe_60m' in df.columns else None
if not mfe_col:
    mfe_cols = [c for c in df.columns if 'mfe' in c.lower() and '60' in c]
    if mfe_cols:
        mfe_col = mfe_cols[0]

if mfe_col:
    print(f"Using MFE column: {mfe_col}")
    runners = df[df[mfe_col] >= 0.02].copy()
    print(f"\n*** FOUND {len(runners)} RUNNERS (MFE >= 2%) ***\n")
    
    if len(runners) > 0:
        # Display all available fields for each runner
        print("="*100)
        print("RUNNER DETAILS (All Available Fields)")
        print("="*100)
        
        for idx, row in runners.iterrows():
            print(f"\n--- Runner #{idx+1} ---")
            for col in df.columns:
                if col not in ['Unnamed: 0'] and pd.notna(row[col]):
                    val = row[col]
                    if isinstance(val, (int, float)):
                        if any(x in col.lower() for x in ['mfe', 'mae', 'body', 'dist', 'vwap']):
                            print(f"  {col}: {val*100:.3f}%" if val < 1 else f"  {col}: {val:.4f}")
                        else:
                            print(f"  {col}: {val:.4f}")
                    else:
                        print(f"  {col}: {val}")
        
        # Summary statistics
        print(f"\n{'='*100}")
        print("SUMMARY STATISTICS FOR RUNNERS")
        print(f"{'='*100}")
        
        for col in df.select_dtypes(include=[np.number]).columns:
            if col not in ['Unnamed: 0']:
                avg = runners[col].mean()
                med = runners[col].median()
                if any(x in col.lower() for x in ['mfe', 'mae', 'body', 'dist']):
                    print(f"  {col:20s}: Avg={avg*100:6.2f}%  Med={med*100:6.2f}%")
                else:
                    print(f"  {col:20s}: Avg={avg:8.4f}  Med={med:8.4f}")
        
        # Symbol distribution
        if 'symbol' in runners.columns:
            print(f"\n{'='*100}")
            print("SYMBOL DISTRIBUTION")
            print(f"{'='*100}")
            print(runners['symbol'].value_counts())
        
        # Time distribution
        time_col = None
        for c in ['time', 'timestamp', 'entry_time', 'signal_time']:
            if c in runners.columns:
                time_col = c
                break
        
        if time_col:
            print(f"\n{'='*100}")
            print("TIME OF DAY DISTRIBUTION")
            print(f"{'='*100}")
            print(runners[time_col].value_counts().head(10))
        
        # Save results
        runners.to_csv('boof30_runners_final_report.csv', index=False)
        print(f"\n{'='*100}")
        print("SAVED: boof30_runners_final_report.csv")
        print(f"{'='*100}")
        
        # Check if we have 1m data files to merge more fields
        print(f"\n{'='*100}")
        print("CHECKING FOR ADDITIONAL 1M DATA FILES")
        print(f"{'='*100}")
        
        data_files = glob.glob('boof24_*_1Min_*.csv')
        symbols_in_runners = runners['symbol'].unique() if 'symbol' in runners.columns else []
        print(f"Found {len(data_files)} 1m data files")
        print(f"Runner symbols: {list(symbols_in_runners)}")
        
else:
    print("No MFE column found!")
