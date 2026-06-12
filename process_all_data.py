"""
Comprehensive runner analysis using all existing data
"""
import pandas as pd
import numpy as np
import glob
from datetime import datetime, time
import warnings
warnings.filterwarnings('ignore')

print("="*100)
print("COMPREHENSIVE RUNNER ANALYSIS - Using All Available Data")
print("="*100)

# Get all available 1m data files
all_1m_files = glob.glob('boof24_*_1Min_*.csv')
print(f"\nFound {len(all_1m_files)} 1-minute data files:")
for f in sorted(all_1m_files)[:20]:
    print(f"  {f}")

# Get symbols from filenames
symbols = set()
for f in all_1m_files:
    parts = f.split('_')
    if len(parts) >= 2:
        symbols.add(parts[1])
print(f"\nTotal unique symbols: {len(symbols)}")
print(f"Symbols: {sorted(symbols)}")

# Also check the existing signals file
try:
    signals_df = pd.read_csv('boof30_mfe_mae_signals.csv')
    print(f"\n{'='*100}")
    print(f"EXISTING SIGNALS FILE: boof30_mfe_mae_signals.csv")
    print(f"{'='*100}")
    print(f"Total rows: {len(signals_df)}")
    print(f"Columns: {list(signals_df.columns)}")
    
    # Check for MFE column
    mfe_col = None
    for col in signals_df.columns:
        if 'mfe' in col.lower() and '60' in col:
            mfe_col = col
            break
    
    if mfe_col:
        print(f"\nUsing MFE column: {mfe_col}")
        runners = signals_df[signals_df[mfe_col] >= 0.02]
        print(f"\n*** RUNNERS (MFE >= 2%): {len(runners)} signals ***")
        
        if len(runners) > 0:
            # Print runner details
            print(f"\n{'='*100}")
            print("RUNNER DETAILS")
            print(f"{'='*100}")
            
            for idx, row in runners.iterrows():
                print(f"\n--- Runner #{idx+1} ---")
                for col in signals_df.columns:
                    if col not in ['Unnamed: 0', ''] and not pd.isna(row[col]):
                        val = row[col]
                        if isinstance(val, float):
                            if 'mfe' in col or 'mae' in col or 'body' in col or 'dist' in col:
                                print(f"  {col}: {val*100:.2f}%" if val < 1 else f"  {col}: {val:.4f}")
                            else:
                                print(f"  {col}: {val:.4f}")
                        else:
                            print(f"  {col}: {val}")
            
            # Summary statistics
            print(f"\n{'='*100}")
            print("RUNNER SUMMARY STATISTICS")
            print(f"{'='*100}")
            
            numeric_cols = runners.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                if col != 'Unnamed: 0':
                    mean_val = runners[col].mean()
                    if 'mfe' in col or 'mae' in col or 'body' in col or 'dist' in col or 'vwap' in col:
                        print(f"  {col}: Avg={mean_val*100:.2f}%, Med={runners[col].median()*100:.2f}%")
                    else:
                        print(f"  {col}: Avg={mean_val:.4f}, Med={runners[col].median():.4f}")
            
            # Symbol distribution
            if 'symbol' in runners.columns:
                print(f"\n{'='*100}")
                print("SYMBOL DISTRIBUTION")
                print(f"{'='*100}")
                print(runners['symbol'].value_counts())
            
            # Time distribution
            if 'time' in runners.columns or 'timestamp' in runners.columns:
                time_col = 'time' if 'time' in runners.columns else 'timestamp'
                print(f"\n{'='*100}")
                print("TIME OF DAY DISTRIBUTION")
                print(f"{'='*100}")
                print(runners[time_col].value_counts().head(10))
            
            # Save runners
            runners.to_csv('boof30_runners_all_data.csv', index=False)
            print(f"\n{'='*100}")
            print("SAVED: boof30_runners_all_data.csv")
            print(f"{'='*100}")
    else:
        print("No MFE 60m column found in signals file")
        
except Exception as e:
    print(f"Error processing signals file: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*100)
print("Analysis complete!")
print("="*100)
