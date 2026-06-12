"""
Comprehensive Runner Analysis - Process ALL existing 1m data
"""
import pandas as pd
import numpy as np
import glob
from datetime import time, datetime
import warnings
warnings.filterwarnings('ignore')

print("="*100)
print("COMPREHENSIVE RUNNER ANALYSIS - Using ALL Existing 1m Data")
print("="*100)

# Get all 1m files
files_1m = glob.glob('boof24_*_1Min_*.csv')
print(f"\nFound {len(files_1m)} 1-minute data files")

# Extract symbols
symbols = []
for f in files_1m:
    parts = f.split('_')
    if len(parts) >= 3:
        symbols.append(parts[1])
symbols = list(set(symbols))
print(f"Symbols available: {sorted(symbols)}")

all_signals = []

for symbol in symbols:
    # Get files for this symbol
    sym_files = [f for f in files_1m if f'boof24_{symbol}_1Min_' in f]
    
    for file in sym_files:
        try:
            df = pd.read_csv(file)
            if len(df) == 0:
                continue
                
            # Ensure timestamp column
            if 'timestamp' not in df.columns and 'date' in df.columns:
                df['timestamp'] = pd.to_datetime(df['date'])
            elif 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            else:
                continue
                
            df = df.sort_values('timestamp')
            df['symbol'] = symbol
            
            # Calculate VWAP
            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['tpv'] = df['tp'] * df['volume']
            df['cum_tpv'] = df['tpv'].cumsum()
            df['cum_vol'] = df['volume'].cumsum()
            df['vwap'] = df['cum_tpv'] / df['cum_vol']
            
            # Calculate RVOL (20-bar lookback)
            df['avg_vol'] = df['volume'].rolling(20).mean()
            df['rvol'] = df['volume'] / df['avg_vol']
            
            # Calculate body %
            df['body'] = abs(df['close'] - df['open']) / df['open']
            df['body_pct'] = df['body'] * 100
            
            # Calculate VWAP distance
            df['vwap_dist'] = (df['close'] - df['vwap']) / df['vwap']
            df['vwap_dist_pct'] = df['vwap_dist'] * 100
            
            # VWAP slope (3-bar)
            df['vwap_slope'] = df['vwap'].diff(3)
            
            # Time filters
            df['time'] = df['timestamp'].dt.time
            df['date'] = df['timestamp'].dt.date
            df['hour'] = df['timestamp'].dt.hour
            df['minute'] = df['timestamp'].dt.minute
            df['minutes_from_open'] = (df['hour'] - 9) * 60 + df['minute'] - 30
            
            # Filter market hours only
            market_df = df[(df['hour'] >= 9) & (df['hour'] <= 16)].copy()
            
            # Detect 2-bar short ignition pattern
            for i in range(len(market_df) - 2):
                if market_df.iloc[i]['minutes_from_open'] < 0 or market_df.iloc[i]['minutes_from_open'] > 90:
                    continue
                    
                bar1 = market_df.iloc[i]
                bar2 = market_df.iloc[i+1]
                
                # Criteria
                bar1_body_ok = bar1['body'] >= 0.004  # 0.4%
                bar1_rvol_ok = bar1['rvol'] >= 2.0
                bar2_rvol_ok = bar2['rvol'] >= 1.5
                
                # Below VWAP (for short)
                below_vwap = bar1['close'] < bar1['vwap'] and bar2['close'] < bar2['vwap']
                
                # No reclaim (close below bar1 low)
                no_reclaim = bar2['close'] < bar1['low']
                
                if bar1_body_ok and bar1_rvol_ok and bar2_rvol_ok and below_vwap and no_reclaim:
                    entry_price = bar2['close']
                    entry_time = bar2['timestamp']
                    
                    # Calculate MFE 60m (look ahead 60 bars)
                    future_df = market_df.iloc[i+2:i+62]
                    if len(future_df) >= 30:  # At least 30 mins of data
                        mfe_60m = ((future_df['low'].min() - entry_price) / entry_price)
                        mae_60m = ((future_df['high'].max() - entry_price) / entry_price)
                        
                        signal = {
                            'symbol': symbol,
                            'date': bar1['date'],
                            'time': str(bar1['time']),
                            'entry_time': str(entry_time),
                            'entry_price': entry_price,
                            'bar1_open': bar1['open'],
                            'bar1_high': bar1['high'],
                            'bar1_low': bar1['low'],
                            'bar1_close': bar1['close'],
                            'bar1_volume': bar1['volume'],
                            'bar1_body': bar1['body'],
                            'bar1_body_pct': bar1['body_pct'],
                            'bar1_rvol': bar1['rvol'],
                            'bar2_open': bar2['open'],
                            'bar2_high': bar2['high'],
                            'bar2_low': bar2['low'],
                            'bar2_close': bar2['close'],
                            'bar2_volume': bar2['volume'],
                            'bar2_body': bar2['body'],
                            'bar2_body_pct': bar2['body_pct'],
                            'bar2_rvol': bar2['rvol'],
                            'vwap_distance': bar2['vwap_dist'],
                            'vwap_distance_pct': bar2['vwap_dist_pct'],
                            'vwap_slope': bar2['vwap_slope'],
                            'minutes_from_open': bar2['minutes_from_open'],
                            'mfe_60m': mfe_60m,
                            'mfe_60m_pct': mfe_60m * 100,
                            'mae_60m': mae_60m,
                            'mae_60m_pct': mae_60m * 100
                        }
                        all_signals.append(signal)
                        
        except Exception as e:
            print(f"Error processing {file}: {e}")
            continue

# Create DataFrame
if all_signals:
    results_df = pd.DataFrame(all_signals)
    
    print(f"\n{'='*100}")
    print(f"TOTAL SIGNALS FOUND: {len(results_df)}")
    print(f"{'='*100}")
    
    # Get runners (MFE >= 2%)
    runners = results_df[results_df['mfe_60m'] <= -0.02].copy()  # Negative for short
    
    print(f"\n*** RUNNERS (MFE 60m >= 2%): {len(runners)} signals ***\n")
    
    if len(runners) > 0:
        # Print all runner details
        print("="*100)
        print("RUNNER DETAILS")
        print("="*100)
        
        cols_to_show = ['symbol', 'time', 'bar1_rvol', 'bar2_rvol', 'bar1_body_pct', 
                       'bar2_body_pct', 'bar1_volume', 'bar2_volume', 
                       'vwap_distance_pct', 'vwap_slope', 'minutes_from_open', 
                       'mfe_60m_pct', 'mae_60m_pct']
        
        for idx, row in runners.iterrows():
            print(f"\n--- Runner #{idx+1} ---")
            for col in cols_to_show:
                if col in row:
                    val = row[col]
                    if isinstance(val, float):
                        print(f"  {col:20s}: {val:.4f}")
                    else:
                        print(f"  {col:20s}: {val}")
        
        # Summary statistics
        print(f"\n{'='*100}")
        print("RUNNER STATISTICS (Averages)")
        print(f"{'='*100}")
        
        metrics = [
            ('Bar 1 RVOL', 'bar1_rvol'),
            ('Bar 2 RVOL', 'bar2_rvol'),
            ('Bar 1 Body %', 'bar1_body_pct'),
            ('Bar 2 Body %', 'bar2_body_pct'),
            ('Bar 1 Volume', 'bar1_volume'),
            ('Bar 2 Volume', 'bar2_volume'),
            ('VWAP Distance %', 'vwap_distance_pct'),
            ('VWAP Slope', 'vwap_slope'),
            ('Minutes from Open', 'minutes_from_open'),
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
        runners.to_csv('boof30_runners_comprehensive.csv', index=False)
        print(f"\n{'='*100}")
        print("SAVED: boof30_runners_comprehensive.csv")
        print(f"{'='*100}")
        
    else:
        print("No runners found with MFE >= 2%")
        
    # Save all signals too
    results_df.to_csv('boof30_all_signals_comprehensive.csv', index=False)
    print(f"Also saved: boof30_all_signals_comprehensive.csv ({len(results_df)} signals)")
    
else:
    print("No signals found!")
