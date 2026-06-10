"""
Boof 23 Filter Diagnostic - Find which filter is blocking trades
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

symbol = 'NVDA'
start = datetime(2026, 3, 10)
end = datetime(2026, 3, 11)

print(f"Fetching {symbol} data...")
df = fetch_alpaca_bars(symbol, start, end, '1Min', creds['api_key'], creds['secret_key'])

if df is None or len(df) == 0:
    print("No data")
    sys.exit(1)

print(f"Data: {len(df)} bars")

# Get params
params = bt.SYMBOL_PARAMS.get(symbol, bt.DEFAULT_PARAMS)
vol_mult = params['vol_mult']
atr_mult = params['atr_mult']
sr_dist_max = params['sr_dist']
use_engulf = params['use_engulf']
F = bt.FRACTAL_BARS

# Reset and calculate
df_reset = df.copy().reset_index(drop=True)
atr_series = bt.compute_atr(df_reset)
df_reset['atr'] = atr_series
df_reset['vol_sma'] = df_reset['volume'].rolling(bt.VOL_LEN).mean()
df_reset['rvol'] = (df_reset['volume'] / df_reset['vol_sma'] * 100).fillna(0)
df_reset['hi_vol'] = df_reset['volume'] > df_reset['vol_sma'] * vol_mult

# Build cluster
cluster_prices, _ = bt.build_cluster_array(df_reset, atr_series, vol_mult)

# ZigZag
opens = df_reset['open'].values
highs = df_reset['high'].values
lows = df_reset['low'].values
closes = df_reset['close'].values
atrs = df_reset['atr'].values
hi_vol_arr = df_reset['hi_vol'].values

trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = bt._build_zigzag(
    highs, lows, opens, closes
)

# Count filter passes
warmup = bt.VOL_LEN + bt.ATR_LEN + F

filters = {
    'total_bars_after_warmup': 0,
    'atr_valid': 0,
    'rvol_80_plus': 0,
    'hi_vol_true': 0,
    'trend_set': 0,
    'near_sr_cluster': 0,
    'fractal_peak_or_trough': 0,
    'slack_passes': 0,
    'zz_proximity_passes': 0,
    'engulf_passes': 0,
    'would_trade': 0,
}

for i in range(warmup, len(df_reset) - F - 3):
    filters['total_bars_after_warmup'] += 1
    
    row = df_reset.iloc[i]
    atr = atrs[i]
    trend = trend_arr[i]
    
    # ATR valid
    if np.isnan(atr) or atr == 0:
        continue
    filters['atr_valid'] += 1
    
    # RVOL >= 80
    if row['rvol'] < 80:
        continue
    filters['rvol_80_plus'] += 1
    
    # HI_VOL
    if not hi_vol_arr[i]:
        continue
    filters['hi_vol_true'] += 1
    
    # Trend set
    if trend == '':
        continue
    filters['trend_set'] += 1
    
    # SR cluster proximity
    if bt.nearest_sr_distance(row['close'], cluster_prices, atr) > sr_dist_max:
        continue
    filters['near_sr_cluster'] += 1
    
    # Fractal check
    lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
    ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
    
    fractal_peak = (highs[i] > lh.max()) and (highs[i] > rh.max())
    fractal_trough = (lows[i] < ll.min()) and (lows[i] < rl.min())
    
    if not (fractal_peak or fractal_trough):
        continue
    filters['fractal_peak_or_trough'] += 1
    
    peak_slack = (highs[i] - closes[i]) / atr
    trough_slack = (closes[i] - lows[i]) / atr
    
    direction = None
    slack = 0.0
    
    # Check short setup
    if fractal_peak and peak_slack >= atr_mult and trend == 'up':
        zz_h_bar = int(zz_high_bar[i])
        if zz_h_bar >= 0 and abs(i - zz_h_bar) <= 10:
            filters['slack_passes'] += 1
            filters['zz_proximity_passes'] += 1
            engulf_ok = (not use_engulf) or (closes[i] < opens[i])
            if engulf_ok:
                filters['engulf_passes'] += 1
                direction = 'short'
                slack = peak_slack
    
    # Check long setup
    elif fractal_trough and trough_slack >= atr_mult and trend == 'down':
        zz_l_bar = int(zz_low_bar[i])
        if zz_l_bar >= 0 and abs(i - zz_l_bar) <= 10:
            filters['slack_passes'] += 1
            filters['zz_proximity_passes'] += 1
            engulf_ok = (not use_engulf) or (closes[i] > opens[i])
            if engulf_ok:
                filters['engulf_passes'] += 1
                direction = 'long'
                slack = trough_slack
    
    if direction:
        filters['would_trade'] += 1

print("\n" + "="*60)
print("FILTER PASS COUNTS")
print("="*60)
for name, count in filters.items():
    pct = count / filters['total_bars_after_warmup'] * 100 if filters['total_bars_after_warmup'] > 0 else 0
    print(f"{name:30}: {count:5} ({pct:5.1f}%)")

print("\n" + "="*60)
print("BOTTLENECK ANALYSIS")
print("="*60)

# Find biggest drops
prev = filters['total_bars_after_warmup']
for name, count in list(filters.items())[1:]:
    drop = prev - count
    if drop > 0:
        print(f"{name:30}: -{drop:5} blocked ({drop/prev*100:5.1f}% of incoming)")
    prev = count

print(f"\nFINAL TRADES: {filters['would_trade']} on {symbol} for 1 day")
print(f"Extrapolated to 5 symbols: ~{filters['would_trade'] * 5} trades/day")
