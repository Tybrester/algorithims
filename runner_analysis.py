"""
Runner Analysis - Save results to file
"""
import pandas as pd
import sys

# Redirect output to file
sys.stdout = open('runner_results.txt', 'w')
sys.stderr = sys.stdout

print("="*100)
print("RUNNER ANALYSIS FROM EXISTING DATA")
print("="*100)

# Load the signals file
df = pd.read_csv('boof30_mfe_mae_signals.csv')
print(f"\nLoaded boof30_mfe_mae_signals.csv: {len(df)} rows")
print(f"Columns: {list(df.columns)}")

# Check for MFE column
mfe_cols = [c for c in df.columns if 'mfe' in c.lower()]
print(f"\nMFE columns found: {mfe_cols}")

if mfe_cols:
    mfe_col = mfe_cols[0]  # Use first MFE column
    runners = df[df[mfe_col] >= 0.02]
    print(f"\n{'='*100}")
    print(f"RUNNERS (MFE >= 2%): {len(runners)} signals")
    print(f"{'='*100}")
    
    if len(runners) > 0:
        # Print each runner
        for idx, row in runners.iterrows():
            print(f"\n--- Runner #{idx+1} ---")
            for col in df.columns:
                if col != 'Unnamed: 0' and pd.notna(row[col]):
                    val = row[col]
                    if isinstance(val, float) and ('mfe' in col or 'mae' in col):
                        print(f"  {col}: {val*100:.2f}%")
                    else:
                        print(f"  {col}: {val}")
        
        # Summary
        print(f"\n{'='*100}")
        print("SUMMARY STATISTICS")
        print(f"{'='*100}")
        for col in df.select_dtypes(include=['float64']).columns:
            if col != 'Unnamed: 0':
                avg = runners[col].mean()
                if 'mfe' in col or 'mae' in col:
                    print(f"  {col}: Avg={avg*100:.2f}%, Med={runners[col].median()*100:.2f}%")
                else:
                    print(f"  {col}: Avg={avg:.4f}, Med={runners[col].median():.4f}")
        
        # Save
        runners.to_csv('boof30_runners_detailed.csv', index=False)
        print(f"\n{'='*100}")
        print("SAVED: boof30_runners_detailed.csv")
        print(f"{'='*100}")
    else:
        print("No runners found with MFE >= 2%")
else:
    print("No MFE column found")

sys.stdout.close()
print("Results saved to runner_results.txt")
