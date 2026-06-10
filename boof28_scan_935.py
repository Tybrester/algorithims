"""
BOOF 28 - 9:35 AM Opening Drive Scanner
Single scan, rank S&P 500 stocks, output Top 10
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# S&P 500 Core (top 50 by market cap) + SPY for relative strength
SP500 = [
    "SPY",  # Load SPY first for relative strength
    "AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","BRK.B","UNH","JNJ",
    "XOM","JPM","V","PG","HD","MA","CVX","LLY","ABBV","MRK",
    "PEP","KO","BAC","AVGO","PFE","TMO","COST","DIS","ABT","ACN",
    "WMT","MCD","ADBE","CSCO","VZ","NKE","CMCSA","TXN","PM","NFLX",
    "BMY","QCOM","HON","UNP","LOW","LIN","AMGN","RTX","IBM","GS"
]

def get_data(sym, start, end, tf='1Min'):
    df = fetch_alpaca_bars(sym, start, end, tf, creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df.sort_values('timestamp').reset_index(drop=True)

def calculate_vwap(df):
    """Calculate VWAP from market open"""
    typical = (df['high'] + df['low'] + df['close']) / 3
    pv = (typical * df['volume']).cumsum()
    vol = df['volume'].cumsum()
    return pv / vol

def calculate_rvol(df, lookback_days=20):
    """Calculate RVOL at current bar vs historical average at same time"""
    if len(df) < 2:
        return None
    
    current_volume = df['volume'].iloc[-1]
    current_time = df['timestamp'].iloc[-1]
    current_date = current_time.date()
    current_time_str = current_time.strftime('%H:%M')
    
    # Get historical volumes at same time of day
    historical = []
    for days_back in range(1, lookback_days + 1):
        past_date = current_date - timedelta(days=days_back)
        if past_date.weekday() >= 5:  # Skip weekends
            continue
        past_rows = df[df['timestamp'].dt.date == past_date]
        if len(past_rows) > 0:
            # Find bar closest to current time
            past_rows['time_diff'] = abs(past_rows['timestamp'].dt.hour - current_time.hour) * 60 + \
                                      abs(past_rows['timestamp'].dt.minute - current_time.minute)
            closest = past_rows.loc[past_rows['time_diff'].idxmin()]
            if closest['time_diff'] <= 5:  # Within 5 minutes
                historical.append(closest['volume'])
    
    if len(historical) < 5:
        return None
    
    avg_volume = np.mean(historical)
    rvol = current_volume / avg_volume if avg_volume > 0 else 0
    return rvol

def calculate_gap(df):
    """Calculate gap % from previous close"""
    if len(df) < 1:
        return None
    
    today_open = df['open'].iloc[0]
    current_date = df['timestamp'].iloc[0].date()
    
    # Find yesterday's close
    yesterday_close = None
    for days_back in range(1, 10):
        past_date = current_date - timedelta(days=days_back)
        if past_date.weekday() >= 5:
            continue
        past_day = df[df['timestamp'].dt.date == past_date]
        if len(past_day) > 0:
            yesterday_close = past_day['close'].iloc[-1]
            break
    
    if yesterday_close is None or yesterday_close == 0:
        return None
    
    gap_pct = (today_open - yesterday_close) / yesterday_close * 100
    return gap_pct

def calculate_rel_strength(stock_df, spy_df):
    """Calculate relative strength vs SPY"""
    if len(stock_df) < 2 or len(spy_df) < 2:
        return None
    
    # From open to current
    stock_move = (stock_df['close'].iloc[-1] - stock_df['open'].iloc[0]) / stock_df['open'].iloc[0] * 100
    spy_move = (spy_df['close'].iloc[-1] - spy_df['open'].iloc[0]) / spy_df['open'].iloc[0] * 100
    
    return stock_move - spy_move

def get_opening_range(df, minutes=5):
    """Get opening range (first N minutes)"""
    if len(df) < minutes:
        return None, None
    opening = df.iloc[:minutes]
    return opening['high'].max(), opening['low'].min()

# MAIN
print('='*70)
print('BOOF 28 - 9:35 AM OPENING DRIVE SCANNER')
print('='*70)

# Test date
test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
start = test_date - timedelta(days=30)  # Get enough history for RVOL
end = test_date + timedelta(days=1)

print(f'\nScan Date: {test_date.date()}')
print(f'Fetching data for {len(SP500)} symbols...')

# Fetch all data
data = {}
spy_loaded = False
for sym in SP500:
    df = get_data(sym, start, end, '1Min')
    if df is not None and len(df) > 0:
        # Filter to scan date only
        day_data = df[df['timestamp'].dt.date == test_date.date()].copy()
        if sym == 'SPY':
            print(f'  SPY raw: {len(df)} total, {len(day_data)} on scan date')
            spy_loaded = True
        if len(day_data) >= 10:  # Need at least 10 minutes of data
            data[sym] = day_data
            if sym != 'SPY':
                print(f'  {sym}: {len(day_data)} bars')
    elif sym == 'SPY':
        print(f'  SPY: FAILED to load')

print(f'\nLoaded {len(data)} symbols for scan date')

# Get SPY for relative strength (optional)
spy_data = data.get('SPY')
if spy_data is None:
    print('WARNING: SPY not loaded, relative strength will be 0')
    # Create dummy spy_data with same timestamps
    first_sym = [k for k in data.keys() if k != 'SPY'][0]
    spy_data = data[first_sym].copy()
    spy_data['open'] = spy_data['close'] = spy_data['high'] = spy_data['low'] = 100
    spy_data['volume'] = 1000000

# Get 9:35 bar for each stock
target_time = datetime.combine(test_date.date(), datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)

print(f'\nScanning at {target_time.strftime("%H:%M")}...')
print('='*70)

results = []

print(f'\nProcessing {len([s for s in data.keys() if s != "SPY"])} symbols...')
first_debug = True

for sym, df in data.items():
    if sym == 'SPY':
        continue
    
    # Get bar at or before 9:35
    bars_at_time = df[df['timestamp'] <= target_time]
    if len(bars_at_time) < 5:  # Need at least opening range
        if first_debug:
            print(f'  DEBUG {sym}: only {len(bars_at_time)} bars at {target_time}')
            print(f'    Data range: {df["timestamp"].min()} to {df["timestamp"].max()}')
            first_debug = False
        continue
    
    # Calculate metrics
    current_price = bars_at_time['close'].iloc[-1]
    
    # VWAP
    vwap_series = calculate_vwap(bars_at_time)
    current_vwap = vwap_series.iloc[-1]
    
    # RVOL (need full history)
    rvol = calculate_rvol(df)
    
    # Gap
    gap_pct = calculate_gap(df)
    
    # Relative Strength
    rel_strength = calculate_rel_strength(bars_at_time, spy_data)
    
    # Opening Range
    or_high, or_low = get_opening_range(bars_at_time, 5)
    
    # Skip if any metric missing
    if rvol is None or gap_pct is None or rel_strength is None or or_high is None:
        continue
    
    # VWAP bonus
    vwap_bonus = 1.0 if current_price > current_vwap else 0.0
    
    # Calculate score
    score = (
        min(rvol, 10) * 0.4 +           # RVOL capped at 10
        rel_strength * 30 +              # Scale up (0.03 -> 0.9)
        abs(gap_pct) * 0.2 +            # Gap %
        vwap_bonus * 0.1                # VWAP alignment
    )
    
    # Opening range breakout check
    above_or = current_price > or_high
    below_or = current_price < or_low
    
    results.append({
        'sym': sym,
        'price': current_price,
        'rvol': rvol,
        'gap_pct': gap_pct,
        'rel_strength': rel_strength,
        'vwap': current_vwap,
        'above_vwap': current_price > current_vwap,
        'or_high': or_high,
        'or_low': or_low,
        'above_or': above_or,
        'below_or': below_or,
        'score': score
    })

print(f'\nScored {len(results)} symbols')
print('='*70)

# Sort by score
results.sort(key=lambda x: x['score'], reverse=True)

print('\n' + '='*70)
print('TOP 10 OPENING DRIVE CANDIDATES')
print('='*70)
print(f'{"#":<3} {"Symbol":<6} {"Score":>8} {"RVOL":>6} {"Gap%":>8} {"RelStr":>8} {"VWAP":>6} {"OR Brk":>8}')
print('-'*70)

for i, r in enumerate(results[:10], 1):
    or_status = "ABOVE" if r['above_or'] else ("BELOW" if r['below_or'] else "INSIDE")
    vwap_status = "ABOVE" if r['above_vwap'] else "BELOW"
    
    print(f"{i:<3} {r['sym']:<6} {r['score']:>8.2f} {r['rvol']:>6.1f} {r['gap_pct']:>8.2f} {r['rel_strength']:>8.2f} {vwap_status:>6} {or_status:>8}")

print('\n' + '='*70)
print('STRONGEST SETUPS (Filtered)')
print('='*70)
print('RVOL > 2, RelStr > 1%, Above VWAP, Above Opening Range')
print('-'*70)

filtered = [r for r in results if r['rvol'] > 2 and r['rel_strength'] > 1 and r['above_vwap'] and r['above_or']]

if filtered:
    for i, r in enumerate(filtered[:5], 1):
        print(f"{i}. {r['sym']} @ ${r['price']:.2f} | Score: {r['score']:.1f} | "
              f"RVOL: {r['rvol']:.1f}x | RS: +{r['rel_strength']:.2f}%")
else:
    print('No stocks meet all criteria')
    print('\nRelaxing filters (RVOL > 1.5, any RS, above VWAP):')
    relaxed = [r for r in results if r['rvol'] > 1.5 and r['above_vwap']]
    for i, r in enumerate(relaxed[:5], 1):
        print(f"{i}. {r['sym']} @ ${r['price']:.2f} | Score: {r['score']:.1f} | "
              f"RVOL: {r['rvol']:.1f}x | Gap: {r['gap_pct']:+.2f}% | RS: {r['rel_strength']:+.2f}%")

print('='*70)
