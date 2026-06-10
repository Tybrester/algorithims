"""
Boof 22, 22.5, 23, 23.5 - Final Backtest
Boof No ETF List: NVDA, AAPL, MSFT, AMZN, GOOG, AVGO, META, TSLA, LLY
Dec 2025 - May 2026 (6 months)
Progress prints every symbol
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}
SYMBOLS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']
CFG = {'ATR_LEN': 14, 'VOL_LEN': 50, 'MAX_HOLD': 20, 'TP_R': 2.0, 'SL_R': 1.0}

def get_data(sym, start, end):
    print(f'  [{sym}] Fetching...', end=' ', flush=True)
    df = fetch_alpaca_bars(sym, start, end, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 100: 
        print('NO DATA')
        return None
    if 'open' not in df.columns: 
        df.columns = [c.lower() for c in df.columns]
    print(f'{len(df)} bars ✓')
    return df

def compute_atr(df):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < 14 else atr[i-1]*13/14 + tr/14
    return atr

def simulate_trade(df, entry_idx, direction, entry, sl, tp, max_bars=20):
    """Simulate trade with actual bar prices"""
    for j in range(entry_idx+1, min(entry_idx+max_bars, len(df))):
        if direction == 'LONG':
            if df['low'].iloc[j] <= sl:
                return (sl-entry)/entry*100, 'SL', j
            if df['high'].iloc[j] >= tp:
                return (tp-entry)/entry*100, 'TP', j
        else:
            if df['high'].iloc[j] >= sl:
                return (entry-sl)/entry*100, 'SL', j
            if df['low'].iloc[j] <= tp:
                return (entry-tp)/entry*100, 'TP', j
    # Time exit
    j = min(entry_idx+max_bars-1, len(df)-1)
    exit_p = df['close'].iloc[j]
    pnl = (exit_p-entry)/entry*100 if direction=='LONG' else (entry-exit_p)/entry*100
    return pnl, 'TIME', j

# === BOOF 22: Volume Clusters ===
def run_boof22(df, sym):
    trades = []
    atr = compute_atr(df)
    vol_sma = df['volume'].rolling(window=CFG['VOL_LEN']).mean().values
    
    for i in range(CFG['VOL_LEN']+50, len(df)-20):
        if atr[i] == 0: continue
        
        # Historical cluster build (NO future-looking)
        clusters = []
        avg_atr = np.mean(atr[max(0,i-50):i+1][atr[max(0,i-50):i+1]>0])
        for j in range(CFG['VOL_LEN'], i+1):
            if df['volume'].iloc[j] >= vol_sma[j] * 1.3:
                price = (df['high'].iloc[j] + df['low'].iloc[j]) / 2
                merged = False
                for c in clusters:
                    if abs(c['price']-price) <= avg_atr*0.5:
                        c['price'] = (c['price']*c['strength']+price)/(c['strength']+1)
                        c['strength'] += 1
                        merged = True
                        break
                if not merged: 
                    clusters.append({'price': price, 'strength': 1})
        clusters = [c for c in clusters if c['strength'] >= 2]
        if not clusters: continue
        
        close, current_atr = df['close'].iloc[i], atr[i]
        dist = min(abs(close-c['price'])/current_atr for c in clusters)
        if dist > 1.0: continue
        
        nearest = min(clusters, key=lambda c: abs(close-c['price']))
        direction = 'LONG' if close < nearest['price'] else 'SHORT'
        
        entry = close
        if direction == 'LONG':
            sl, tp = entry - current_atr, entry + current_atr * 2
        else:
            sl, tp = entry + current_atr, entry - current_atr * 2
        
        pnl, exit_type, exit_idx = simulate_trade(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'exit': exit_type, 'dir': direction})
    
    return trades

# === BOOF 23: ZigZag ===
def run_boof23(df, sym):
    trades = []
    atr = compute_atr(df)
    zz_high, zz_low, trend = df['high'].iloc[0], df['low'].iloc[0], ''
    
    for i in range(50, len(df)-20):
        if atr[i] == 0: continue
        close, high, low, current_atr = df['close'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], atr[i]
        
        # Update ZigZag
        if high > zz_high: zz_high = high
        if low < zz_low: zz_low = low
        threshold = current_atr * 0.75
        
        if trend=='up' and close < zz_low - threshold: 
            trend = 'down'; zz_low = low
        elif trend=='down' and close > zz_high + threshold: 
            trend = 'up'; zz_high = high
        elif trend=='': 
            trend = 'up' if close > df['close'].iloc[i-20] else 'down'
        
        if trend == '': continue
        
        # 0.05% move
        ret5 = (close - df['close'].iloc[max(0,i-5)]) / df['close'].iloc[max(0,i-5)] * 100
        if abs(ret5) < 0.05: continue
        
        if (ret5 > 0 and trend=='up') or (ret5 < 0 and trend=='down'):
            direction = 'LONG' if ret5 > 0 else 'SHORT'
        else:
            continue
        
        entry = close
        if direction == 'LONG':
            sl, tp = entry - current_atr, entry + current_atr * 2
        else:
            sl, tp = entry + current_atr, entry - current_atr * 2
        
        pnl, exit_type, exit_idx = simulate_trade(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'exit': exit_type, 'dir': direction})
    
    return trades

# === MAIN ===
START, END = datetime(2025, 12, 1), datetime(2026, 5, 31)

print('='*70)
print('BOOF 22, 22.5, 23, 23.5 - NO ETF LIST - 6 MONTHS')
print(f'Symbols: {SYMBOLS}')
print(f'Dates: {START.date()} to {END.date()}')
print('='*70)
print('\n[Phase 1] Fetching data...')

data = {}
for sym in SYMBOLS:
    df = get_data(sym, START, END)
    if df is not None:
        data[sym] = df
    time.sleep(0.5)  # Rate limit

print(f'\n[Phase 2] Running backtests on {len(data)} symbols...\n')

results = {}
for name, func in [('Boof 22', run_boof22), ('Boof 23', run_boof23)]:
    print(f'Running {name}...')
    trades = []
    for sym, df in data.items():
        t = func(df, sym)
        trades.extend(t)
        print(f'  {sym}: {len(t)} trades')
    results[name] = trades

# 22.5 = 22 + ADX filter
print('Running Boof 22.5 (22 + ADX filter)...')
trades = []
for sym, df in data.items():
    # Add ADX calc
    atr = compute_atr(df)
    adx = np.zeros(len(df))
    for i in range(14, len(df)):
        plus_dm = max(df['high'].iloc[i] - df['high'].iloc[i-1], 0)
        minus_dm = max(df['low'].iloc[i-1] - df['low'].iloc[i], 0)
        if minus_dm > plus_dm: plus_dm = 0
        if plus_dm > minus_dm: minus_dm = 0
        adx[i] = abs(plus_dm - minus_dm) / (atr[i] + 0.0001) * 100
    
    t = run_boof22(df, sym)
    # Filter by ADX
    t = [trade for trade in t if adx[df.index.get_loc(df[df['close']==trade.get('entry',df['close'].iloc[0])].index[0]) if len(df[df['close']==trade.get('entry',df['close'].iloc[0])]) > 0 else 0 > 20]
    trades.extend(t)
    print(f'  {sym}: {len(t)} trades (ADX filtered)')
results['Boof 22.5'] = trades

# 23.5 = 23 + RSI2
print('Running Boof 23.5 (23 + RSI2 filter)...')
trades = []
for sym, df in data.items():
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
    rsi2 = 100 - (100 / (1 + gain/loss.replace(0, 0.001)))
    
    t = run_boof23(df, sym)
    # Filter oversold/bought
    filtered = []
    for trade in t:
        idx = df[df['close'] == trade.get('entry', df['close'].iloc[0])].index
        if len(idx) > 0:
            r = rsi2.loc[idx[0]] if idx[0] in rsi2.index else 50
            if not (trade['dir']=='LONG' and r>80) and not (trade['dir']=='SHORT' and r<20):
                filtered.append(trade)
    trades.extend(filtered)
    print(f'  {sym}: {len(filtered)} trades (RSI2 filtered)')
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
    wr = len(pnls[pnls>0]) / n * 100
    pf = pnls[pnls>0].sum() / abs(pnls[pnls<0].sum()) if len(pnls[pnls<0]) > 0 else 999
    total = pnls.sum()
    
    print(f'{name:<12} | Trades: {n:>4} | WR: {wr:>5.1f}% | PF: {pf:>5.2f} | P&L: ${total*100:>10,.0f}')
    
    # By exit type
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[t['exit']].append(t['pnl'])
    for et, vals in by_exit.items():
        arr = np.array(vals)
        print(f'    {et:<8} | {len(arr):>4} trades | ${arr.sum()*100:>10,.0f}')

print('='*70)
print('COMPLETE!')
print('='*70)
