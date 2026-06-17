"""
Futures Cross-Reference + Boof 23
Load from NinjaTrader CSV exports
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

def load_csv(symbol):
    """Load NinjaTrader export (CSV or TXT)"""
    # Try exact match first, then patterns
    patterns = [
        f'{symbol}.txt',
        f'{symbol}.csv',
        f'{symbol}*.txt',
        f'{symbol}*.csv',
    ]
    
    for pattern in patterns:
        files = glob.glob(pattern)
        if files:
            print(f'  Found: {files[0]}')
            # Try different separators
            for sep in [',', '\t', ';', ' ']:
                try:
                    df = pd.read_csv(files[0], sep=sep, header=None)
                    if len(df.columns) >= 5:
                        break
                except:
                    continue
            
            # NinjaTrader format: datetime, open, high, low, close, volume
            if len(df.columns) == 6:
                df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
            elif len(df.columns) == 5:
                df.columns = ['datetime', 'open', 'high', 'low', 'close']
            else:
                print(f'  Unexpected columns: {len(df.columns)}')
                return None
            
            # Parse datetime
            df['time'] = pd.to_datetime(df['datetime'], format='%Y%m%d %H%M%S')
            df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
            print(f'  Loaded {len(df)} bars')
            return df
            
            # Map common NinjaTrader column names
            col_map = {
                'date': 'time', 'timestamp': 'time', 'time': 'time',
                'open': 'open', 'o': 'open',
                'high': 'high', 'h': 'high',
                'low': 'low', 'l': 'low',
                'close': 'close', 'c': 'close', 'last': 'close', 'last price': 'close',
                'volume': 'volume', 'vol': 'volume', 'v': 'volume'
            }
            
            new_cols = {}
            for c in df.columns:
                for key, val in col_map.items():
                    if key in c:
                        new_cols[c] = val
                        break
            
            df = df.rename(columns=new_cols)
            
            # Ensure required columns exist
            required = ['time', 'open', 'high', 'low', 'close']
            missing = [c for c in required if c not in df.columns]
            if missing:
                print(f'  Missing columns: {missing}')
                print(f'  Available: {list(df.columns)}')
                return None
            
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').reset_index(drop=True)
            print(f'  Loaded {len(df)} bars')
            return df
    
    print(f'  File not found: {symbol}')
    return None

def compute_atr(df):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < 14 else atr[i-1]*13/14 + tr/14
    return atr

def detect_signal(es_ret, nq_ret, mes_ret, mnq_ret):
    signals = []
    # All Aligned
    if all(x > THRESHOLDS['aligned'] for x in [es_ret, nq_ret, mes_ret, mnq_ret]):
        signals.append({'dir': 'LONG', 'type': 'AllAligned', 'str': 3})
    if all(x < -THRESHOLDS['aligned'] for x in [es_ret, nq_ret, mes_ret, mnq_ret]):
        signals.append({'dir': 'SHORT', 'type': 'AllAligned', 'str': 3})
    # Micro Divergence
    if abs(es_ret-mes_ret) > THRESHOLDS['div']:
        signals.append({'dir': 'LONG' if es_ret>mes_ret else 'SHORT', 'type': 'MicroDiv', 'str': 2})
    if abs(nq_ret-mnq_ret) > THRESHOLDS['div']:
        signals.append({'dir': 'LONG' if nq_ret>mnq_ret else 'SHORT', 'type': 'NQMicroDiv', 'str': 2})
    # ES Lead
    if es_ret > THRESHOLDS['lead'] and nq_ret < es_ret - 0.05:
        signals.append({'dir': 'LONG', 'type': 'ESLeads', 'str': 2})
    if es_ret < -THRESHOLDS['lead'] and nq_ret > es_ret + 0.05:
        signals.append({'dir': 'SHORT', 'type': 'ESLeads', 'str': 2})
    # Relative Strength
    if es_ret > nq_ret + THRESHOLDS['rs'] and es_ret > 0:
        signals.append({'dir': 'LONG', 'type': 'ESStrong', 'str': 1})
    if nq_ret > es_ret + THRESHOLDS['rs'] and nq_ret > 0:
        signals.append({'dir': 'LONG', 'type': 'NQStrong', 'str': 1})
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

def run_crossref_backtest(es_df, nq_df, mes_df, mnq_df):
    trades = []
    atr = compute_atr(es_df)
    state = {'zz_h': es_df['high'].iloc[0], 'zz_l': es_df['low'].iloc[0], 'trend': ''}
    
    # Align dataframes by time
    min_len = min(len(es_df), len(nq_df), len(mes_df), len(mnq_df))
    
    for i in range(50, min_len-20):
        if atr[i]==0: continue
        
        es_ret = (es_df['close'].iloc[i] - es_df['close'].iloc[max(0,i-RETURN_BARS)]) / es_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        nq_ret = (nq_df['close'].iloc[i] - nq_df['close'].iloc[max(0,i-RETURN_BARS)]) / nq_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        mes_ret = (mes_df['close'].iloc[i] - mes_df['close'].iloc[max(0,i-RETURN_BARS)]) / mes_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        mnq_ret = (mnq_df['close'].iloc[i] - mnq_df['close'].iloc[max(0,i-RETURN_BARS)]) / mnq_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        
        sig = detect_signal(es_ret, nq_ret, mes_ret, mnq_ret)
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
print('Loading from NinjaTrader CSV exports')
print('='*70)

print('\nLoading ES...')
es_df = load_csv('ES 06-26.Last')

print('Loading NQ...')
nq_df = load_csv('NQ 06-26.Last')

print('Loading MES...')
mes_df = load_csv('MES 06-26.Last')

print('Loading MNQ...')
mnq_df = load_csv('MNQ 06-26.Last')

if all([es_df, nq_df, mes_df, mnq_df]):
    print(f'\nRunning cross-reference backtest...')
    trades = run_crossref_backtest(es_df, nq_df, mes_df, mnq_df)
    
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
    print('\nERROR: Missing data files')
    print('Please export ES.csv, NQ.csv, MES.csv, MNQ.csv from NinjaTrader')
    print('Files should have columns: time, open, high, low, close, volume')

print('='*70)
