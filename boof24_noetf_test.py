"""
Boof 24 - ICT/MSB Strategy on Boof No ETF List
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}
SYMBOLS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']
START, END = datetime(2025, 12, 1), datetime(2026, 5, 31)

def get_data(sym):
    print(f'  [{sym}]...', end=' ', flush=True)
    df = fetch_alpaca_bars(sym, START, END, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 100:
        print('NO DATA')
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    print(f'{len(df)} bars')
    return df

def compute_atr(df):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < 14 else atr[i-1]*13/14 + tr/14
    return atr

def find_swings(df, atr, atr_mult=0.75):
    """Find swing highs and lows based on ATR reversal"""
    swings = []
    last_high, last_low = df['high'].iloc[0], df['low'].iloc[0]
    last_high_idx, last_low_idx = 0, 0
    direction = 'up'
    
    for i in range(1, len(df)):
        if direction == 'up':
            if df['high'].iloc[i] > last_high:
                last_high, last_high_idx = df['high'].iloc[i], i
            elif df['close'].iloc[i] < last_high - atr[i] * atr_mult:
                swings.append({'idx': last_high_idx, 'price': last_high, 'type': 'high'})
                direction, last_low, last_low_idx = 'down', df['low'].iloc[i], i
        else:
            if df['low'].iloc[i] < last_low:
                last_low, last_low_idx = df['low'].iloc[i], i
            elif df['close'].iloc[i] > last_low + atr[i] * atr_mult:
                swings.append({'idx': last_low_idx, 'price': last_low, 'type': 'low'})
                direction, last_high, last_high_idx = 'up', df['high'].iloc[i], i
    
    return swings

def detect_msb(df, i, swings, atr, vol_sma):
    """Detect Market Structure Break with volume confirmation"""
    if len(swings) < 3:
        return None
    
    close = df['close'].iloc[i]
    volume = df['volume'].iloc[i]
    
    # Check volume confirmation
    if volume < vol_sma[i] * 1.25:
        return None
    
    # Find recent swings
    recent_swings = [s for s in swings if s['idx'] < i and s['idx'] >= i-50]
    if len(recent_swings) < 2:
        return None
    
    # Check for MSB (break of structure)
    last_high = max([s['price'] for s in recent_swings if s['type'] == 'high'], default=0)
    last_low = min([s['price'] for s in recent_swings if s['type'] == 'low'], default=float('inf'))
    
    if last_high == 0 or last_low == float('inf'):
        return None
    
    # Bullish MSB: Close above last high with momentum
    if close > last_high and df['close'].iloc[i-1] <= last_high:
        return 'LONG'
    
    # Bearish MSB: Close below last low with momentum  
    if close < last_low and df['close'].iloc[i-1] >= last_low:
        return 'SHORT'
    
    return None

def check_retest(df, i, direction, swings, bars=5):
    """Check if price retests broken level"""
    if len(swings) < 2:
        return False
    
    recent = [s for s in swings if s['idx'] < i and s['idx'] >= i-20]
    if not recent:
        return False
    
    if direction == 'LONG':
        # Look for price to come back near a recent low (support)
        support = min([s['price'] for s in recent if s['type'] == 'low'], default=df['low'].iloc[i])
        return abs(df['close'].iloc[i] - support) / df['close'].iloc[i] < 0.002
    else:
        # Look for price to come back near a recent high (resistance)
        resistance = max([s['price'] for s in recent if s['type'] == 'high'], default=df['high'].iloc[i])
        return abs(df['close'].iloc[i] - resistance) / df['close'].iloc[i] < 0.002
    
    return False

def simulate(df, i, direction, entry, sl, tp, max_bars=20):
    for j in range(i+1, min(i+max_bars, len(df))):
        if direction == 'LONG':
            if df['low'].iloc[j] <= sl: return (sl-entry)/entry*100, 'SL'
            if df['high'].iloc[j] >= tp: return (tp-entry)/entry*100, 'TP'
        else:
            if df['high'].iloc[j] >= sl: return (entry-sl)/entry*100, 'SL'
            if df['low'].iloc[j] <= tp: return (entry-tp)/entry*100, 'TP'
    j = min(i+max_bars-1, len(df)-1)
    ex = df['close'].iloc[j]
    return ((ex-entry)/entry*100 if direction=='LONG' else (entry-ex)/entry*100), 'TIME'

def run_boof24(df, sym):
    trades = []
    atr = compute_atr(df)
    vol_sma = df['volume'].rolling(50).mean().values
    
    # Get ATR percentile
    atr_pct = pd.Series(atr).rolling(50).apply(lambda x: (x > x.iloc[-1]).sum() / len(x) * 100, raw=False).values
    
    # Find swings
    swings = find_swings(df, atr)
    
    for i in range(100, len(df)-20):
        if atr[i] == 0 or atr_pct[i] < 40:
            continue
        
        # Detect MSB
        direction = detect_msb(df, i, swings, atr, vol_sma)
        if not direction:
            continue
        
        # Check retest
        if not check_retest(df, i, direction, swings):
            continue
        
        entry = df['close'].iloc[i]
        cur_atr = atr[i]
        
        if direction == 'LONG':
            sl = entry - cur_atr
            tp = entry + cur_atr * 2
        else:
            sl = entry + cur_atr
            tp = entry - cur_atr * 2
        
        pnl, ex_type = simulate(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'type': ex_type, 'dir': direction})
    
    return trades

# MAIN
print('='*70)
print('BOOF 24 - NO ETF LIST - 6 MONTHS')
print(f'Symbols: {SYMBOLS}')
print('='*70)

print('\nFetching data...')
data = {}
for sym in SYMBOLS:
    df = get_data(sym)
    if df is not None:
        data[sym] = df
    time.sleep(0.3)

print(f'\nRunning Boof 24 on {len(data)} symbols...')
trades = []
for sym, df in data.items():
    t = run_boof24(df, sym)
    trades.extend(t)
    print(f'  {sym}: {len(t)} trades')

print('\n' + '='*70)
print('RESULTS')
print('='*70)

if trades:
    pnls = np.array([t['pnl'] for t in trades])
    n = len(pnls)
    wr = len(pnls[pnls>0]) / n * 100
    pf = pnls[pnls>0].sum() / abs(pnls[pnls<0].sum()) if len(pnls[pnls<0]) > 0 else 999
    total = pnls.sum()
    
    print(f'Boof 24      | Trades: {n:>4} | WR: {wr:>5.1f}% | PF: {pf:>5.2f} | P&L: ${total*100:>10,.0f}')
    
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[t['type']].append(t['pnl'])
    for et, vals in by_exit.items():
        arr = np.array(vals)
        print(f'    {et:<8} | {len(arr):>4} | ${arr.sum()*100:>10,.0f}')
else:
    print('No trades')

print('='*70)
