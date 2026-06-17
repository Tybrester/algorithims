"""
Futures Cross-Reference + Boof 23 - DataBento Version 3
ES, NQ, MES, MNQ - 5m data
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict

try:
    import databento as db
except ImportError:
    print('pip install databento')
    exit()

DATABENTO_KEY = 'db-HjUMrsa7gNvavTcwU8fUdywvQSfH7'
START, END = datetime(2025, 12, 1), datetime(2026, 1, 31)  # Shorter period for test

# Config
RETURN_BARS, ATR_LEN, MAX_HOLD = 5, 14, 20
TP_R, SL_R = 2.0, 1.0
THRESHOLDS = {'aligned': 0.05, 'div': 0.15, 'lead': 0.10, 'rs': 0.10}

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
    for j in range(i+1, min(i+MAX_HOLD, len(df))):
        if direction=='LONG':
            if df['low'].iloc[j] <= sl: return (sl-entry)/entry*100, 'SL'
            if df['high'].iloc[j] >= tp: return (tp-entry)/entry*100, 'TP'
        else:
            if df['high'].iloc[j] >= sl: return (entry-sl)/entry*100, 'SL'
            if df['low'].iloc[j] <= tp: return (entry-tp)/entry*100, 'TP'
    j = min(i+MAX_HOLD-1, len(df)-1)
    ex = df['close'].iloc[j]
    return ((ex-entry)/entry*100 if direction=='LONG' else (entry-ex)/entry*100), 'TIME'

def run_backtest(es_df, nq_df, mes_df, mnq_df):
    trades = []
    atr = compute_atr(es_df)
    state = {'zz_h': es_df['high'].iloc[0], 'zz_l': es_df['low'].iloc[0], 'trend': ''}
    
    for i in range(50, len(es_df)-20):
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
print(f'Dec 2025 - Jan 2026 (2 months test)')
print('='*70)

client = db.Historical(DATABENTO_KEY)

# Try with raw symbol mapping
print('\nFetching futures data...')

try:
    es = client.timeseries.get_range(
        dataset='GLBX.MDP3', 
        symbols=['ES'], 
        schema='ohlcv-5m',
        stype_in='raw_symbol',
        start=START, 
        end=END
    )
    print(f'ES: {len(es.to_df())} bars')
except Exception as e:
    print(f'ES error: {e}')
    es = None

try:
    nq = client.timeseries.get_range(
        dataset='GLBX.MDP3', 
        symbols=['NQ'], 
        schema='ohlcv-5m',
        stype_in='raw_symbol',
        start=START, 
        end=END
    )
    print(f'NQ: {len(nq.to_df())} bars')
except Exception as e:
    print(f'NQ error: {e}')
    nq = None

if es and nq:
    es_df, nq_df = es.to_df(), nq.to_df()
    print(f'\nRunning backtest on ES+NQ...')
    # Simplified - just ES vs NQ for now
    # For full version, need MES and MNQ data
else:
    print('Need data for backtest')
    print('\nAlternative: Use your NinjaTrader CSV export')
    print('Export ES, NQ, MES, MNQ 5m data and load from CSV')

print('='*70)
