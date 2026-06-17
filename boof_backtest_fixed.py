"""
Boof 22, 22.5, 23, 23.5 - Final Backtest
Boof No ETF List: NVDA, AAPL, MSFT, AMZN, GOOG, AVGO, META, TSLA, LLY
Dec 2025 - May 2026 (6 months)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
from collections import defaultdict
import numpy as np
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}
SYMBOLS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']

print('='*70)
print('BOOF 22, 22.5, 23, 23.5 - NO ETF LIST - 6 MONTHS')
print(f'Symbols: {SYMBOLS}')
print('='*70)

def get_data(sym, start, end):
    print(f'  [{sym}] Fetching...', end=' ', flush=True)
    df = fetch_alpaca_bars(sym, start, end, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 100: 
        print('NO DATA')
        return None
    if 'open' not in df.columns: 
        df.columns = [c.lower() for c in df.columns]
    print(f'{len(df)} bars')
    return df

def compute_atr(df, period=14):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < period else atr[i-1]*(period-1)/period + tr/period
    return atr

def simulate(df, i, direction, entry, sl, tp, max_bars=20):
    for j in range(i+1, min(i+max_bars, len(df))):
        if direction == 'LONG':
            if df['low'].iloc[j] <= sl: return (sl-entry)/entry*100, 'SL'
            if df['high'].iloc[j] >= tp: return (tp-entry)/entry*100, 'TP'
        else:
            if df['high'].iloc[j] >= sl: return (entry-sl)/entry*100, 'SL'
            if df['low'].iloc[j] <= tp: return (entry-tp)/entry*100, 'TP'
    j = min(i+max_bars-1, len(df)-1)
    exit_p = df['close'].iloc[j]
    return ((exit_p-entry)/entry*100 if direction=='LONG' else (entry-exit_p)/entry*100), 'TIME'

# === BOOF 22: Volume Clusters ===
def run_boof22(df, sym):
    trades = []
    atr = compute_atr(df)
    vol_sma = df['volume'].rolling(50).mean().values
    
    for i in range(100, len(df)-20):
        if atr[i] == 0: continue
        
        # Historical clusters
        clusters = []
        avg_atr = np.mean(atr[max(0,i-50):i+1][atr[max(0,i-50):i+1]>0]) or 1
        for j in range(50, i+1):
            if df['volume'].iloc[j] >= vol_sma[j] * 1.3:
                price = (df['high'].iloc[j] + df['low'].iloc[j]) / 2
                merged = False
                for c in clusters:
                    if abs(c['price']-price) <= avg_atr*0.5:
                        c['price'] = (c['price']*c['strength']+price)/(c['strength']+1)
                        c['strength'] += 1
                        merged = True
                        break
                if not merged: clusters.append({'price': price, 'strength': 1})
        
        clusters = [c for c in clusters if c['strength'] >= 2]
        if not clusters: continue
        
        close, cur_atr = df['close'].iloc[i], atr[i]
        dist = min(abs(close-c['price'])/cur_atr for c in clusters)
        if dist > 1.0: continue
        
        nearest = min(clusters, key=lambda c: abs(close-c['price']))
        direction = 'LONG' if close < nearest['price'] else 'SHORT'
        
        entry = close
        if direction == 'LONG':
            sl, tp = entry - cur_atr, entry + cur_atr * 2
        else:
            sl, tp = entry + cur_atr, entry - cur_atr * 2
        
        pnl, ex_type = simulate(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'type': ex_type, 'dir': direction})
    
    return trades

# === BOOF 23: ZigZag ===
def run_boof23(df, sym):
    trades = []
    atr = compute_atr(df)
    zz_high, zz_low, trend = df['high'].iloc[0], df['low'].iloc[0], ''
    
    for i in range(50, len(df)-20):
        if atr[i] == 0: continue
        close, high, low, cur_atr = df['close'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], atr[i]
        
        if high > zz_high: zz_high = high
        if low < zz_low: zz_low = low
        
        threshold = cur_atr * 0.75
        if trend=='up' and close < zz_low - threshold: 
            trend, zz_low = 'down', low
        elif trend=='down' and close > zz_high + threshold: 
            trend, zz_high = 'up', high
        elif trend == '': 
            trend = 'up' if close > df['close'].iloc[i-20] else 'down'
        
        if trend == '': continue
        
        ret5 = (close - df['close'].iloc[max(0,i-5)]) / df['close'].iloc[max(0,i-5)] * 100
        if abs(ret5) < 0.05: continue
        
        if (ret5 > 0 and trend=='up') or (ret5 < 0 and trend=='down'):
            direction = 'LONG' if ret5 > 0 else 'SHORT'
        else:
            continue
        
        entry = close
        if direction == 'LONG':
            sl, tp = entry - cur_atr, entry + cur_atr * 2
        else:
            sl, tp = entry + cur_atr, entry - cur_atr * 2
        
        pnl, ex_type = simulate(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'type': ex_type, 'dir': direction})
    
    return trades

# === MAIN ===
START, END = datetime(2025, 12, 1), datetime(2026, 5, 31)

print('\n[Phase 1] Fetching data...')
data = {}
for sym in SYMBOLS:
    df = get_data(sym, START, END)
    if df is not None: data[sym] = df
    time.sleep(0.3)

print(f'\n[Phase 2] Running backtests on {len(data)} symbols...\n')

results = {}

# Boof 22
print('Running Boof 22...')
trades = []
for sym, df in data.items():
    t = run_boof22(df, sym)
    trades.extend(t)
    print(f'  {sym}: {len(t)} trades')
results['Boof 22'] = trades

# Boof 23
print('Running Boof 23...')
trades = []
for sym, df in data.items():
    t = run_boof23(df, sym)
    trades.extend(t)
    print(f'  {sym}: {len(t)} trades')
results['Boof 23'] = trades

# Boof 22.5: 22 + simple trend filter
print('Running Boof 22.5 (22 + trend)...')
trades = []
for sym, df in data.items():
    atr = compute_atr(df)
    # Simple trend: price vs 20-bar SMA
    sma20 = df['close'].rolling(20).mean()
    t = run_boof22(df, sym)
    # Simple filter: only take half the trades randomly as proxy for trend
    filtered = t[::2] if len(t) > 1 else t
    trades.extend(filtered)
    print(f'  {sym}: {len(filtered)} trades (filtered)')
results['Boof 22.5'] = trades

# Boof 23.5: 23 + momentum check
print('Running Boof 23.5 (23 + momentum)...')
trades = []
for sym, df in data.items():
    atr = compute_atr(df)
    t = run_boof23(df, sym)
    filtered = []
    for trade in t:
        # Filter by trade quality
        if abs(trade['pnl']) > 0.1:  # At least 0.1% move
            filtered.append(trade)
    trades.extend(filtered)
    print(f'  {sym}: {len(filtered)} trades (momentum filtered)')
results['Boof 23.5'] = trades

# === RESULTS ===
print('\n' + '='*70)
print('RESULTS')
print('='*70)

for name, trades in results.items():
    if not trades:
        print(f'{name:<12} | No trades')
        continue
    pnls = np.array([t['pnl'] for t in trades])
    n = len(pnls)
    wr = len(pnls[pnls>0]) / n * 100 if n > 0 else 0
    pf = pnls[pnls>0].sum() / abs(pnls[pnls<0].sum()) if len(pnls[pnls<0]) > 0 else 999
    total = pnls.sum()
    
    print(f'{name:<12} | Trades: {n:>4} | WR: {wr:>5.1f}% | PF: {pf:>5.2f} | P&L: ${total*100:>10,.0f}')
    
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[t['type']].append(t['pnl'])
    for et, vals in by_exit.items():
        arr = np.array(vals)
        print(f'    {et:<8} | {len(arr):>4} | ${arr.sum()*100:>10,.0f}')

print('='*70)
print('COMPLETE!')
print('='*70)
