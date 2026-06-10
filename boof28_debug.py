"""
BOOF 28 - DEBUG VERSION
Simple filters, print everything
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Just top 20 for fast testing
STOCKS = ["SPY","AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","JPM",
          "V","XOM","MA","HD","PG","COST","JNJ","ABBV","WMT","KO"]

def get_data(sym, start, end):
    df = fetch_alpaca_bars(sym, start, end, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df.sort_values('timestamp')

def calculate_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    pv = (typical * df['volume']).cumsum()
    vol = df['volume'].cumsum()
    return pv / vol

# Test single day
test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
fetch_start = test_date - timedelta(days=20)
fetch_end = test_date + timedelta(days=1)

print('='*70)
print('BOOF 28 - DEBUG MODE')
print(f'Testing: {test_date.date()}')
print('='*70)

# Fetch data
print('\nFetching data...')
data = {}
for sym in STOCKS:
    df = get_data(sym, fetch_start, fetch_end)
    if df is not None:
        data[sym] = df
        print(f'  {sym}: {len(df)} total bars')
    time.sleep(0.1)

print(f'\nLoaded {len(data)} symbols')

spy_data = data.get('SPY')
spy_day = None
spy_open = None
if spy_data is not None:
    spy_day = spy_data[spy_data['timestamp'].dt.date == test_date.date()]
    if len(spy_day) > 0:
        spy_open = spy_day['open'].iloc[0]
        print(f'\nSPY Open: {spy_open:.2f}')
    else:
        print('\nWARNING: SPY data not available for test date')
else:
    print('\nWARNING: No SPY data loaded')

# Target time 9:35 AM
target_time = datetime.combine(test_date.date(), datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)

print(f'\nScanning at {target_time.strftime("%H:%M")}...')
print('='*70)
print(f'{"Symbol":<8} {"Price":>8} {"VWAP":>8} {"OR High":>8} {"RVOL":>6} {"RS %":>8} {"Status":<20}')
print('-'*70)

count = 0
for sym, df in data.items():
    if sym == 'SPY':
        continue
    
    # Get day data
    day_data = df[df['timestamp'].dt.date == test_date.date()].reset_index(drop=True)
    if len(day_data) < 2:
        print(f'{sym:<8} {"NO DATA":<50}')
        continue
    
    # Get 9:35 bar
    bars_935 = day_data[day_data['timestamp'] <= target_time]
    if len(bars_935) < 1:
        print(f'{sym:<8} {"NO 9:35 BAR":<50}')
        continue
    
    idx = len(bars_935) - 1
    current_price = bars_935['close'].iloc[-1]
    open_price = day_data['open'].iloc[0]
    
    # VWAP
    vwap = calculate_vwap(bars_935).iloc[-1]
    
    # RVOL - compare current volume to avg of same time over last 10 days
    current_vol = bars_935['volume'].iloc[-1]
    hist_vols = []
    for days_back in range(1, 11):
        past_date = test_date.date() - timedelta(days=days_back)
        if past_date.weekday() >= 5:
            continue
        past_day = df[df['timestamp'].dt.date == past_date]
        if len(past_day) >= len(bars_935):
            hist_vols.append(past_day['volume'].iloc[len(bars_935)-1])
    
    if len(hist_vols) < 3:
        rvol = None
    else:
        rvol = current_vol / np.mean(hist_vols)
    
    # Relative Strength vs SPY (as %)
    if spy_open is not None:
        spy_935 = spy_day[spy_day['timestamp'] <= target_time]
        if len(spy_935) > 0:
            spy_price = spy_935['close'].iloc[-1]
            spy_move = (spy_price - spy_open) / spy_open * 100
        else:
            spy_move = 0
        stock_move = (current_price - open_price) / open_price * 100
        rel_strength = stock_move - spy_move
    else:
        rel_strength = 0  # Skip RS filter if no SPY
    
    # Opening Range - first 15 minutes (3 bars of 5m)
    if len(day_data) < 3:
        or_high = day_data['high'].iloc[:2].max()
    else:
        or_high = day_data.iloc[:3]['high'].max()
    
    # Status
    status = []
    if rvol and rvol > 1.5:
        status.append('RVOL_OK')
    if spy_open is not None and rel_strength > 0.25:
        status.append('RS_OK')
    if current_price > vwap:
        status.append('VWAP_OK')
    if current_price > or_high:
        status.append('OR_BREAK')
    
    status_str = ' | '.join(status) if status else 'NO SIGNAL'
    
    rvol_str = f'{rvol:.1f}' if rvol else 'N/A'
    print(f'{sym:<8} {current_price:>8.2f} {vwap:>8.2f} {or_high:>8.2f} {rvol_str:>6} {rel_strength:>+7.2f}% {status_str:<20}')
    
    # Count if passes ALL relaxed filters (skip RS if no SPY)
    rs_ok = (spy_open is None) or (rel_strength > 0.25)
    if rvol and rvol > 1.5 and rs_ok and current_price > vwap and current_price > or_high:
        count += 1

print('='*70)
print(f'Signals found: {count}')
print('='*70)

if count == 0:
    print('\nDIAGNOSIS:')
    print('Try these relaxed filters:')
    print('  RVOL > 1.0 (not 2.0)')
    print('  RS > 0.1% (not 1.0%)')
    print('  OR breakout OR VWAP pullback')
    print('\nOr check if timestamps are wrong (9:35 vs 14:35 UTC?)')
