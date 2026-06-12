"""
Runner Analysis - 2:30-4:00 PM EST (Power Hour)
"""
import pandas as pd
import numpy as np
import glob
from datetime import time, datetime
import warnings
warnings.filterwarnings('ignore')

print("="*100)
print("RUNNER ANALYSIS - 2:30-4:00 PM EST (POWER HOUR)")
print("="*100)

# Get all 1m files
files_1m = glob.glob('boof24_*_1Min_*.csv')
print(f"Found {len(files_1m)} 1-minute data files")

# Extract symbols
symbols = []
for f in files_1m:
    parts = f.split('_')
    if len(parts) >= 3:
        symbols.append(parts[1])
symbols = list(set(symbols))
print(f"Processing {len(symbols)} symbols: {sorted(symbols)}")

all_signals = []

for symbol in symbols[:12]:
    # Get files for this symbol
    sym_files = [f for f in files_1m if f'boof24_{symbol}_1Min_' in f]
    
    for file in sym_files[:2]:
        try:
            df = pd.read_csv(file)
            if len(df) == 0:
                continue
                
            # Parse timestamp
            if 'timestamp' not in df.columns and 'date' in df.columns:
                df['timestamp'] = pd.to_datetime(df['date'])
            elif 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            else:
                continue
            
            # Filter to 2:30-4:00 PM EST only
            df['time'] = df['timestamp'].dt.time
            df['hour'] = df['timestamp'].dt.hour
            df['minute'] = df['timestamp'].dt.minute
            df['date'] = df['timestamp'].dt.date
            
            # 2:30-4:00 PM filter (14:30-16:00)
            mask = ((df['hour'] == 14) & (df['minute'] >= 30)) | (df['hour'] == 15) | ((df['hour'] == 16) & (df['minute'] == 0))
            df = df[mask].copy()
            
            if len(df) < 50:
                continue
            
            df = df.sort_values('timestamp')
            df['symbol'] = symbol
            
            # Calculate VWAP
            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['tpv'] = df['tp'] * df['volume']
            df['cum_tpv'] = df['tpv'].cumsum()
            df['cum_vol'] = df['volume'].cumsum()
            df['vwap'] = df['cum_tpv'] / df['cum_vol']
            
            # Calculate RVOL
            df['avg_vol'] = df['volume'].rolling(20).mean()
            df['rvol'] = df['volume'] / df['avg_vol']
            
            # Calculate body %
            df['body'] = abs(df['close'] - df['open']) / df['open']
            df['body_pct'] = df['body'] * 100
            
            # VWAP distance
            df['vwap_dist'] = (df['close'] - df['vwap']) / df['vwap']
            df['vwap_dist_pct'] = df['vwap_dist'] * 100
            
            # VWAP slope
            df['vwap_slope'] = df['vwap'].diff(3)
            
            # Minutes from 2:30 PM
            df['minutes_from_230'] = (df['hour'] - 14) * 60 + df['minute'] - 30
            
            # Detect 2-bar short ignition pattern
            for i in range(len(df) - 62):
                bar1 = df.iloc[i]
                bar2 = df.iloc[i+1]
                
                # Pattern criteria
                bar1_body_ok = bar1['body'] >= 0.004
                bar1_rvol_ok = bar1['rvol'] >= 2.0
                bar2_rvol_ok = bar2['rvol'] >= 1.5
                below_vwap = bar1['close'] < bar1['vwap'] and bar2['close'] < bar2['vwap']
                no_reclaim = bar2['close'] < bar1['low']
                
                if bar1_body_ok and bar1_rvol_ok and bar2_rvol_ok and below_vwap and no_reclaim:
                    entry_price = bar2['close']
                    
                    # Calculate MFE 60m
                    future_df = df.iloc[i+2:i+62]
                    if len(future_df) >= 30:
                        mfe_60m = ((future_df['low'].min() - entry_price) / entry_price)
                        mae_60m = ((future_df['high'].max() - entry_price) / entry_price)
                        
                        signal = {
                            'symbol': symbol,
                            'date': str(bar1['date']),
                            'time': str(bar1['time']),
                            'bar1_rvol': bar1['rvol'],
                            'bar2_rvol': bar2['rvol'],
                            'bar1_body_pct': bar1['body_pct'],
                            'bar2_body_pct': bar2['body_pct'],
                            'bar1_volume': bar1['volume'],
                            'bar2_volume': bar2['volume'],
                            'vwap_dist_pct': bar2['vwap_dist_pct'],
                            'vwap_slope': bar2['vwap_slope'],
                            'minutes_from_230': bar2['minutes_from_230'],
                            'mfe_60m_pct': mfe_60m * 100,
                            'mae_60m_pct': mae_60m * 100
                        }
                        all_signals.append(signal)
                        
        except Exception as e:
            continue

# Create DataFrame
if all_signals:
    results_df = pd.DataFrame(all_signals)
    
    print(f"\n{'='*100}")
    print(f"TOTAL SIGNALS FOUND (2:30-4 PM): {len(results_df)}")
    print(f"{'='*100}")
    
    # Get runners (MFE >= 2%)
    runners = results_df[results_df['mfe_60m_pct'] <= -2.0].copy()
    
    print(f"\n*** RUNNERS (MFE 60m >= 2%): {len(runners)} signals ***\n")
    
    if len(runners) > 0:
        print("="*100)
        print("RUNNER DETAILS")
        print("="*100)
        
        for idx, row in runners.iterrows():
            print(f"\n--- Runner #{idx+1} ---")
            print(f"  symbol:            {row['symbol']}")
            print(f"  date:              {row['date']}")
            print(f"  time:              {row['time']}")
            print(f"  bar1_rvol:         {row['bar1_rvol']:.2f}x")
            print(f"  bar2_rvol:         {row['bar2_rvol']:.2f}x")
            print(f"  bar1_body_pct:     {row['bar1_body_pct']:.2f}%")
            print(f"  bar2_body_pct:     {row['bar2_body_pct']:.2f}%")
            print(f"  bar1_volume:       {row['bar1_volume']:,.0f}")
            print(f"  bar2_volume:       {row['bar2_volume']:,.0f}")
            print(f"  vwap_dist_pct:     {row['vwap_dist_pct']:.2f}%")
            print(f"  vwap_slope:        {row['vwap_slope']:.4f}")
            print(f"  minutes_from_230:  {row['minutes_from_230']}")
            print(f"  mfe_60m_pct:       {row['mfe_60m_pct']:.2f}%")
            print(f"  mae_60m_pct:       {row['mae_60m_pct']:.2f}%")
        
        # Summary statistics
        print(f"\n{'='*100}")
        print("RUNNER STATISTICS (AVERAGES)")
        print(f"{'='*100}")
        
        metrics = [
            ('Bar 1 RVOL', 'bar1_rvol'),
            ('Bar 2 RVOL', 'bar2_rvol'),
            ('Bar 1 Body %', 'bar1_body_pct'),
            ('Bar 2 Body %', 'bar2_body_pct'),
            ('Bar 1 Volume', 'bar1_volume'),
            ('Bar 2 Volume', 'bar2_volume'),
            ('VWAP Distance %', 'vwap_dist_pct'),
            ('VWAP Slope', 'vwap_slope'),
            ('Minutes from 2:30', 'minutes_from_230'),
            ('MFE 60m %', 'mfe_60m_pct'),
            ('MAE 60m %', 'mae_60m_pct')
        ]
        
        for label, col in metrics:
            if col in runners.columns:
                avg = runners[col].mean()
                med = runners[col].median()
                print(f"  {label:20s}: Avg={avg:8.4f}  Med={med:8.4f}")
        
        # Symbol distribution
        print(f"\n{'='*100}")
        print("SYMBOL DISTRIBUTION")
        print(f"{'='*100}")
        print(runners['symbol'].value_counts())
        
        # Time distribution
        print(f"\n{'='*100}")
        print("TIME OF DAY DISTRIBUTION")
        print(f"{'='*100}")
        print(runners['time'].value_counts().head(10))
        
        # Save results
        runners.to_csv('boof30_runners_2_30_4pm.csv', index=False)
        print(f"\n{'='*100}")
        print("SAVED: boof30_runners_2_30_4pm.csv")
        print(f"{'='*100}")
    else:
        print("No runners found with MFE >= 2%")
        results_df.to_csv('boof30_all_signals_2_30_4pm.csv', index=False)
        print(f"Saved all signals: boof30_all_signals_2_30_4pm.csv ({len(results_df)} signals)")
else:
    print("No signals found!")

print("\n" + "="*100)
print("Analysis complete!")
print("="*100)
