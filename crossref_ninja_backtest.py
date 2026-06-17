"""
Futures Cross-Reference + Boof 23
Load from NinjaTrader .txt exports (no headers)
"""
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import glob

# Config
RETURN_BARS = 5
ATR_LEN = 14
MAX_HOLD_BARS = 20
TP_R = 2.0
SL_R = 1.0
THRESHOLDS = {'aligned': 0.05, 'div': 0.15, 'lead': 0.10, 'rs': 0.10}

def load_ninja_txt(filename):
    """Load NinjaTrader .txt export (no header, space-separated)"""
    filepath = glob.glob(filename)
    if not filepath:
        print(f'  File not found: {filename}')
        return None
    
    print(f'  Loading {filepath[0]}...')
    
    # Read without header, space-separated
    df = pd.read_csv(filepath[0], sep=' ', header=None, 
                     names=['date', 'time', 'open', 'high', 'low', 'close', 'volume'])
    
    # Combine date and time columns
    df['datetime'] = df['date'].astype(str) + ' ' + df['time'].astype(str)
    df['time'] = pd.to_datetime(df['datetime'], format='%Y%m%d %H%M%S')
    
    # Select and convert columns
    df = df[['time', 'open', 'high', 'low', 'close', 'volume']].copy()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.sort_values('time').reset_index(drop=True)
    print(f'  Loaded {len(df)} bars')
    return df

def compute_atr(df):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < 14 else atr[i-1]*13/14 + tr/14
    return atr

def detect_signal(es_ret, nq_ret, mes_ret, mnq_ret):
    signals = []
    if all(x > THRESHOLDS['aligned'] for x in [es_ret, nq_ret, mes_ret, mnq_ret]):
        signals.append({'dir': 'LONG', 'type': 'AllAligned', 'str': 3})
    if all(x < -THRESHOLDS['aligned'] for x in [es_ret, nq_ret, mes_ret, mnq_ret]):
        signals.append({'dir': 'SHORT', 'type': 'AllAligned', 'str': 3})
    if abs(es_ret-mes_ret) > THRESHOLDS['div']:
        signals.append({'dir': 'LONG' if es_ret>mes_ret else 'SHORT', 'type': 'MicroDiv', 'str': 2})
    if abs(nq_ret-mnq_ret) > THRESHOLDS['div']:
        signals.append({'dir': 'LONG' if nq_ret>mnq_ret else 'SHORT', 'type': 'NQMicroDiv', 'str': 2})
    if es_ret > THRESHOLDS['lead'] and nq_ret < es_ret - 0.05:
        signals.append({'dir': 'LONG', 'type': 'ESLeads', 'str': 2})
    if es_ret < -THRESHOLDS['lead'] and nq_ret > es_ret + 0.05:
        signals.append({'dir': 'SHORT', 'type': 'ESLeads', 'str': 2})
    return max(signals, key=lambda x: x['str']) if signals else None

def update_zigzag(close, high, low, atr, state):
    zz_h, zz_l, trend = state['zz_h'], state['zz_l'], state['trend']
    th = atr * 0.75
    if high > zz_h: zz_h = high
    if low < zz_l: zz_l = low
    if trend=='up' and close < zz_l - th: trend, zz_l = 'down', low
    elif trend=='down' and close > zz_h + th: trend, zz_h = 'up', high
    return {'zz_h': zz_h, 'zz_l': zz_l, 'trend': trend}

def simulate(df, i, direction, entry, sl, tp):
    for j in range(i+1, min(i+MAX_HOLD_BARS, len(df))):
        if direction=='LONG':
            if df['low'].iloc[j] <= sl: return (sl-entry)/entry*100, 'SL'
            if df['high'].iloc[j] >= tp: return (tp-entry)/entry*100, 'TP'
        else:
            if df['high'].iloc[j] >= sl: return (entry-sl)/entry*100, 'SL'
            if df['low'].iloc[j] <= tp: return (entry-tp)/entry*100, 'TP'
    j = min(i+MAX_HOLD_BARS-1, len(df)-1)
    ex = df['close'].iloc[j]
    return ((ex-entry)/entry*100 if direction=='LONG' else (entry-ex)/entry*100), 'TIME'

def run_crossref(es_df, nq_df, mes_df, mnq_df):
    trades = []
    atr = compute_atr(es_df)
    state = {'zz_h': es_df['high'].iloc[0], 'zz_l': es_df['low'].iloc[0], 'trend': ''}
    
    min_len = min(len(es_df), len(nq_df), len(mes_df), len(mnq_df))
    
    for i in range(50, min_len-20):
        if atr[i]==0: continue
        
        es_r = (es_df['close'].iloc[i] - es_df['close'].iloc[max(0,i-RETURN_BARS)]) / es_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        nq_r = (nq_df['close'].iloc[i] - nq_df['close'].iloc[max(0,i-RETURN_BARS)]) / nq_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        mes_r = (mes_df['close'].iloc[i] - mes_df['close'].iloc[max(0,i-RETURN_BARS)]) / mes_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        mnq_r = (mnq_df['close'].iloc[i] - mnq_df['close'].iloc[max(0,i-RETURN_BARS)]) / mnq_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        
        sig = detect_signal(es_r, nq_r, mes_r, mnq_r)
        if not sig or sig['str'] < 2: continue
        
        state = update_zigzag(es_df['close'].iloc[i], es_df['high'].iloc[i], es_df['low'].iloc[i], atr[i], state)
        if state['trend']=='': continue
        
        aligned = (sig['dir']=='LONG' and state['trend']=='up') or (sig['dir']=='SHORT' and state['trend']=='down')
        if not aligned: continue
        
        entry = es_df['close'].iloc[i]
        cur_atr = atr[i]
        if sig['dir']=='LONG':
            sl, tp = entry - cur_atr*SL_R, entry + cur_atr*TP_R
        else:
            sl, tp = entry + cur_atr*SL_R, entry - cur_atr*TP_R
        
        pnl, ex_type = simulate(es_df, i, sig['dir'], entry, sl, tp)
        trades.append({'pnl': pnl, 'ex': ex_type, 'sig': sig['type'], 'dir': sig['dir']})
    
    return trades

# MAIN
print('='*70)
print('FUTURES CROSS-REFERENCE + BOOF 23')
print('Loading from NinjaTrader .txt files')
print('='*70)

es_df = load_ninja_txt('ES 06-26.Last.txt')
nq_df = load_ninja_txt('NQ 06-26.Last.txt')
mes_df = load_ninja_txt('MES 06-26.Last.txt')
mnq_df = load_ninja_txt('MNQ 06-26.Last.txt')

if all([es_df, nq_df, mes_df, mnq_df]):
    print(f'\nRunning cross-reference backtest...')
    trades = run_crossref(es_df, nq_df, mes_df, mnq_df)
    
    print('\n' + '='*70)
    print('RESULTS')
    print('='*70)
    
    if trades:
        pnls = np.array([t['pnl'] for t in trades])
        n = len(pnls)
        wr = len(pnls[pnls>0])/n*100
        pf = pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()) if len(pnls[pnls<0])>0 else 999
        total = pnls.sum()
        
        print(f'Total trades: {n}')
        print(f'Win rate: {wr:.1f}%')
        print(f'Profit factor: {pf:.2f}')
        print(f'Total P&L: ${total*100:,.0f}')
        print()
        
        by_sig = defaultdict(list)
        for t in trades: by_sig[t['sig']].append(t['pnl'])
        print('By Signal Type:')
        for s, v in by_sig.items():
            arr = np.array(v)
            print(f'  {s:<12} {len(arr):>4} trades | ${arr.sum()*100:>10,.0f}')
        
        by_ex = defaultdict(list)
        for t in trades: by_ex[t['ex']].append(t['pnl'])
        print('\nBy Exit Type:')
        for e, v in by_ex.items():
            arr = np.array(v)
            print(f'  {e:<8} {len(arr):>4} | ${arr.sum()*100:>10,.0f}')
    else:
        print('No trades generated')
else:
    print('ERROR: Missing data files')

print('='*70)
