"""
Debug Boof 23 - Diagnose why zero trades on Alpaca data
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as bt
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
import pandas as pd
import numpy as np

creds = {
    'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU',
    'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
}

# Test with NVDA for a single month
symbol = 'NVDA'
start = datetime(2026, 3, 1)
end = datetime(2026, 3, 31)

print(f"Fetching {symbol} data from {start.date()} to {end.date()}...")
df = fetch_alpaca_bars(symbol, start, end, '1Min', creds['api_key'], creds['secret_key'])

if df is None or len(df) == 0:
    print("ERROR: No data fetched")
    sys.exit(1)

print(f"\nData shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"Index type: {type(df.index)}")
print(f"Index[0]: {df.index[0]}")
print(f"\nFirst 5 rows:")
print(df.head())
print(f"\nLast 5 rows:")
print(df.tail())

# Check for required columns
required = ['open', 'high', 'low', 'close', 'volume']
missing = [c for c in required if c not in df.columns]
if missing:
    print(f"\nMISSING COLUMNS: {missing}")
else:
    print(f"\nAll required columns present ✓")

# Check data types
print(f"\nData types:")
print(df.dtypes)

# Check for NaN values
print(f"\nNaN counts:")
print(df.isna().sum())

# Check volume stats
print(f"\nVolume stats:")
print(f"  Min: {df['volume'].min()}")
print(f"  Max: {df['volume'].max()}")
print(f"  Mean: {df['volume'].mean():.0f}")
print(f"  Median: {df['volume'].median():.0f}")

# Manually calculate what Boof 23 calculates
print("\n" + "="*80)
print("MANUAL BOOF 23 PRE-CALCULATIONS")
print("="*80)

ATR_LEN = 14
VOL_LEN = 50
vol_mult = 1.3

# Reset index to get integer positions
df_reset = df.copy().reset_index(drop=True)

# Calculate ATR
atr_series = bt.compute_atr(df_reset)
df_reset['atr'] = atr_series

# Calculate volume SMA and RVOL
df_reset['vol_sma'] = df_reset['volume'].rolling(VOL_LEN).mean()
df_reset['rvol'] = (df_reset['volume'] / df_reset['vol_sma'] * 100).fillna(0)
df_reset['hi_vol'] = df_reset['volume'] > df_reset['vol_sma'] * vol_mult

print(f"\nATR stats:")
print(f"  Min: {df_reset['atr'].min():.4f}")
print(f"  Max: {df_reset['atr'].max():.4f}")
print(f"  Mean: {df_reset['atr'].mean():.4f}")

print(f"\nRVOL stats:")
print(f"  Min: {df_reset['rvol'].min():.2f}")
print(f"  Max: {df_reset['rvol'].max():.2f}")
print(f"  Mean: {df_reset['rvol'].mean():.2f}")
print(f"  Bars with RVOL >= 80: {(df_reset['rvol'] >= 80).sum()} / {len(df_reset)}")

print(f"\nHI_VOL stats:")
print(f"  Bars with hi_vol=True: {df_reset['hi_vol'].sum()} / {len(df_reset)}")
print(f"  Percentage: {df_reset['hi_vol'].mean()*100:.1f}%")

# Check ZigZag
print(f"\nZIGZAG CALCULATION:")
F = 3
warmup = VOL_LEN + ATR_LEN + F
print(f"Warmup bars: {warmup}")
print(f"Total bars: {len(df_reset)}")
print(f"Bars after warmup: {len(df_reset) - warmup}")

if len(df_reset) > warmup:
    opens = df_reset['open'].values
    highs = df_reset['high'].values
    lows = df_reset['low'].values
    closes = df_reset['close'].values
    
    trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = bt._build_zigzag(
        highs, lows, opens, closes
    )
    
    print(f"ZigZag trend values:")
    trend_after = trend_arr[warmup:]
    unique_trends = set(trend_after)
    print(f"  Unique trends after warmup: {unique_trends}")
    print(f"  'up' count: {sum(1 for t in trend_after if t == 'up')}")
    print(f"  'down' count: {sum(1 for t in trend_after if t == 'down')}")
    print(f"  Empty count: {sum(1 for t in trend_after if t == '')}")

# Now run the actual Boof 23
print("\n" + "="*80)
print("RUNNING BOOF 23")
print("="*80)

trades = bt.run_boof23(df, symbol=symbol)

print(f"\nTrades found: {len(trades)}")

if len(trades) == 0:
    print("\nDIAGNOSTIC: Why zero trades?")
    print("-"*80)
    
    # Check each filter step by step
    atr_series = bt.compute_atr(df_reset)
    df_reset['atr'] = atr_series
    df_reset['vol_sma'] = df_reset['volume'].rolling(VOL_LEN).mean()
    df_reset['rvol'] = (df_reset['volume'] / df_reset['vol_sma'] * 100).fillna(0)
    df_reset['hi_vol'] = df_reset['volume'] > df_reset['vol_sma'] * vol_mult
    
    # Re-calculate zigzag
    opens = df_reset['open'].values
    highs = df_reset['high'].values
    lows = df_reset['low'].values
    closes = df_reset['close'].values
    atrs = df_reset['atr'].values
    hi_vol = df_reset['hi_vol'].values
    
    trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = bt._build_zigzag(
        highs, lows, opens, closes
    )
    
    # Check cluster array
    cluster_prices, _ = bt.build_cluster_array(df_reset, atr_series, vol_mult)
    print(f"Cluster prices count: {len(cluster_prices)}")
    
    # Loop through bars and check each filter
    filter_counts = {
        'total_bars': 0,
        'after_warmup': 0,
        'atr_valid': 0,
        'rvol_80': 0,
        'hi_vol': 0,
        'trend_set': 0,
        'near_sr': 0,
        'fractal_peak': 0,
        'fractal_trough': 0,
        'slack_ok': 0,
        'zz_proximity': 0,
        'engulf_ok': 0,
    }
    
    F = 3
    warmup = VOL_LEN + ATR_LEN + F
    atr_mult = 0.4
    sr_dist_max = 1.0
    use_engulf = False
    
    for i in range(warmup, len(df_reset) - F - 3):
        filter_counts['total_bars'] += 1
        
        row = df_reset.iloc[i]
        atr = atrs[i]
        trend = trend_arr[i]
        
        # ATR valid
        if np.isnan(atr) or atr == 0:
            continue
        filter_counts['atr_valid'] += 1
        
        # RVOL >= 80
        if row['rvol'] < 80:
            continue
        filter_counts['rvol_80'] += 1
        
        # HI_VOL
        if not hi_vol[i]:
            continue
        filter_counts['hi_vol'] += 1
        
        # Trend set
        if trend == '':
            continue
        filter_counts['trend_set'] += 1
        
        # Near SR cluster
        if bt.nearest_sr_distance(row['close'], cluster_prices, atr) > sr_dist_max:
            continue
        filter_counts['near_sr'] += 1
        
        # Fractal check
        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
        
        fractal_peak = (highs[i] > lh.max()) and (highs[i] > rh.max())
        fractal_trough = (lows[i] < ll.min()) and (lows[i] < rl.min())
        
        if fractal_peak:
            filter_counts['fractal_peak'] += 1
        if fractal_trough:
            filter_counts['fractal_trough'] += 1
        
        peak_slack = (highs[i] - closes[i]) / atr
        trough_slack = (closes[i] - lows[i]) / atr
        
        # Check slack + trend + proximity
        if fractal_peak and peak_slack >= atr_mult and trend == 'up':
            zz_h_bar = int(zz_high_bar[i])
            if zz_h_bar >= 0 and abs(i - zz_h_bar) <= 10:
                filter_counts['slack_ok'] += 1
                filter_counts['zz_proximity'] += 1
                engulf_ok = (not use_engulf) or (closes[i] < opens[i])
                if engulf_ok:
                    filter_counts['engulf_ok'] += 1
        
        elif fractal_trough and trough_slack >= atr_mult and trend == 'down':
            zz_l_bar = int(zz_low_bar[i])
            if zz_l_bar >= 0 and abs(i - zz_l_bar) <= 10:
                filter_counts['slack_ok'] += 1
                filter_counts['zz_proximity'] += 1
                engulf_ok = (not use_engulf) or (closes[i] > opens[i])
                if engulf_ok:
                    filter_counts['engulf_ok'] += 1
    
    print("\nFilter pass counts:")
    for k, v in filter_counts.items():
        print(f"  {k:20}: {v:5}")

else:
    # Show trades
    for t in trades[:5]:
        print(f"  {t['direction']:5} | Entry: {t['entry']:.2f} | P&L: {t['pnl_pct']*100:.2f}% | Exit: {t['exit_type']}")
