"""
Futures Cross-Reference Strategy + Boof 23 Filter
ES, NQ, MES, MNQ - DataBento 5m data
Strategies: All Aligned, Micro Divergence, ES Lead, Relative Strength
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict

# DataBento API key (replace with yours)
DATABENTO_KEY = 'db-HjUMrsa7gNvavTcwU8fUdywvQSfH7'

# Dec 2025 - May 2026
START_DATE = datetime(2025, 12, 1)
END_DATE = datetime(2026, 5, 31)

# Config
RETURN_BARS = 5
ATR_LEN = 14
MAX_HOLD_BARS = 20
TP_R = 2.0
SL_R = 1.0

# Thresholds
ALL_ALIGNED_THRESH = 0.05   # 0.05% move
DIVERGENCE_THRESH = 0.15    # 0.15% divergence
LEAD_THRESH = 0.10          # ES leads by 0.10%
RS_THRESH = 0.10            # 0.10% relative strength

def compute_atr(df, period=14):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < period else atr[i-1]*(period-1)/period + tr/period
    return atr

def detect_signal(es_ret, nq_ret, mes_ret, mnq_ret):
    """Detect cross-reference signals"""
    signals = []
    
    # 1. All 4 Aligned (high conviction)
    all_up = es_ret > ALL_ALIGNED_THRESH and nq_ret > ALL_ALIGNED_THRESH and mes_ret > ALL_ALIGNED_THRESH and mnq_ret > ALL_ALIGNED_THRESH
    all_down = es_ret < -ALL_ALIGNED_THRESH and nq_ret < -ALL_ALIGNED_THRESH and mes_ret < -ALL_ALIGNED_THRESH and mnq_ret < -ALL_ALIGNED_THRESH
    
    if all_up:
        signals.append({'dir': 'LONG', 'type': 'AllAligned', 'strength': 3})
    if all_down:
        signals.append({'dir': 'SHORT', 'type': 'AllAligned', 'strength': 3})
    
    # 2. Micro Divergence (arbitrage)
    es_mes_spread = abs(es_ret - mes_ret)
    nq_mnq_spread = abs(nq_ret - mnq_ret)
    
    if es_mes_spread > DIVERGENCE_THRESH:
        if es_ret > mes_ret:
            signals.append({'dir': 'LONG', 'type': 'MicroDiv', 'strength': 2})
        else:
            signals.append({'dir': 'SHORT', 'type': 'MicroDiv', 'strength': 2})
    
    if nq_mnq_spread > DIVERGENCE_THRESH:
        if nq_ret > mnq_ret:
            signals.append({'dir': 'LONG', 'type': 'NQMicroDiv', 'strength': 2})
        else:
            signals.append({'dir': 'SHORT', 'type': 'NQMicroDiv', 'strength': 2})
    
    # 3. ES Leads, NQ Follows
    es_leads_up = es_ret > LEAD_THRESH and nq_ret < es_ret - 0.05
    es_leads_down = es_ret < -LEAD_THRESH and nq_ret > es_ret + 0.05
    
    if es_leads_up:
        signals.append({'dir': 'LONG', 'type': 'ESLeads', 'strength': 2})
    if es_leads_down:
        signals.append({'dir': 'SHORT', 'type': 'ESLeads', 'strength': 2})
    
    # 4. Relative Strength
    es_stronger = es_ret > nq_ret + RS_THRESH
    nq_stronger = nq_ret > es_ret + RS_THRESH
    
    if es_stronger and es_ret > 0:
        signals.append({'dir': 'LONG', 'type': 'ESStrong', 'strength': 1})
    if nq_stronger and nq_ret > 0:
        signals.append({'dir': 'LONG', 'type': 'NQStrong', 'strength': 1})
    
    # Return highest strength signal
    if signals:
        return max(signals, key=lambda x: x['strength'])
    return None

def update_zigzag(close, high, low, atr, trend_state):
    """Boof 23 ZigZag trend detection"""
    zz_high = trend_state['zz_high']
    zz_low = trend_state['zz_low']
    trend = trend_state['trend']
    
    threshold = atr * 0.75
    
    if high > zz_high:
        zz_high = high
    if low < zz_low:
        zz_low = low
    
    if trend == 'up' or trend == '':
        if close < zz_low - threshold:
            trend = 'down'
            zz_low = low
    
    if trend == 'down' or trend == '':
        if close > zz_high + threshold:
            trend = 'up'
            zz_high = high
    
    return {'zz_high': zz_high, 'zz_low': zz_low, 'trend': trend}

def simulate_trade(df, i, direction, entry, sl, tp, max_bars=20):
    """Simulate trade with actual bar prices"""
    for j in range(i+1, min(i+max_bars, len(df))):
        if direction == 'LONG':
            if df['low'].iloc[j] <= sl:
                return (sl-entry)/entry*100, 'SL'
            if df['high'].iloc[j] >= tp:
                return (tp-entry)/entry*100, 'TP'
        else:
            if df['high'].iloc[j] >= sl:
                return (entry-sl)/entry*100, 'SL'
            if df['low'].iloc[j] <= tp:
                return (entry-tp)/entry*100, 'TP'
    
    j = min(i+max_bars-1, len(df)-1)
    exit_p = df['close'].iloc[j]
    return ((exit_p-entry)/entry*100 if direction=='LONG' else (entry-exit_p)/entry*100), 'TIME'

def run_crossref_backtest(es_df, nq_df, mes_df, mnq_df):
    """Run cross-reference strategy with Boof 23 filter"""
    trades = []
    
    # Compute ATR on ES for stops
    es_atr = compute_atr(es_df)
    
    # ZigZag state
    trend_state = {
        'zz_high': es_df['high'].iloc[0],
        'zz_low': es_df['low'].iloc[0],
        'trend': ''
    }
    
    for i in range(50, len(es_df)-20):
        if es_atr[i] == 0:
            continue
        
        # Get returns for all 4 futures
        es_ret = (es_df['close'].iloc[i] - es_df['close'].iloc[max(0,i-RETURN_BARS)]) / es_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        nq_ret = (nq_df['close'].iloc[i] - nq_df['close'].iloc[max(0,i-RETURN_BARS)]) / nq_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        mes_ret = (mes_df['close'].iloc[i] - mes_df['close'].iloc[max(0,i-RETURN_BARS)]) / mes_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        mnq_ret = (mnq_df['close'].iloc[i] - mnq_df['close'].iloc[max(0,i-RETURN_BARS)]) / mnq_df['close'].iloc[max(0,i-RETURN_BARS)] * 100
        
        # Detect cross-reference signal
        signal = detect_signal(es_ret, nq_ret, mes_ret, mnq_ret)
        if not signal or signal['strength'] < 2:
            continue
        
        # Update ZigZag (Boof 23 filter)
        trend_state = update_zigzag(
            es_df['close'].iloc[i],
            es_df['high'].iloc[i],
            es_df['low'].iloc[i],
            es_atr[i],
            trend_state
        )
        trend = trend_state['trend']
        
        if trend == '':
            continue
        
        # Check trend alignment
        trend_aligned = (signal['dir'] == 'LONG' and trend == 'up') or (signal['dir'] == 'SHORT' and trend == 'down')
        if not trend_aligned:
            continue
        
        # Entry on ES
        entry = es_df['close'].iloc[i]
        cur_atr = es_atr[i]
        
        if signal['dir'] == 'LONG':
            sl = entry - cur_atr * SL_R
            tp = entry + cur_atr * TP_R
        else:
            sl = entry + cur_atr * SL_R
            tp = entry - cur_atr * TP_R
        
        # Simulate trade
        pnl, exit_type = simulate_trade(es_df, i, signal['dir'], entry, sl, tp)
        
        trades.append({
            'pnl': pnl,
            'exit_type': exit_type,
            'signal_type': signal['type'],
            'direction': signal['dir'],
            'es_ret': es_ret,
            'nq_ret': nq_ret
        })
    
    return trades

# Main
print('='*70)
print('FUTURES CROSS-REFERENCE STRATEGY')
print('ES + NQ + MES + MNQ + Boof 23 Filter')
print('='*70)
print()
print('Fetching data from DataBento...')
print()

# Check if databento is available
try:
    import databento as db
    print('DataBento SDK found')
except ImportError:
    print('DataBento SDK not installed. Install with: pip install databento')
    print()
    print('To run this backtest:')
    print('1. Get DataBento API key from databento.com')
    print('2. pip install databento')
    print('3. Update DATABENTO_KEY in this script')
    print('4. Run again')
    exit()

# Fetch data
client = db.Historical(DATABENTO_KEY)

schema = 'ohlcv-1m'  # 1-minute bars, we'll resample to 5m

print('Fetching ES...')
es_data = client.timeseries.get_range(
    dataset='GLBX.MDP3',
    symbols=['ES'],
    schema=schema,
    stype_in='continuous',
    start=START_DATE,
    end=END_DATE
)

print('Fetching NQ...')
nq_data = client.timeseries.get_range(
    dataset='GLBX.MDP3',
    symbols=['NQ'],
    schema=schema,
    stype_in='continuous',
    start=START_DATE,
    end=END_DATE
)

print('Fetching MES...')
mes_data = client.timeseries.get_range(
    dataset='GLBX.MDP3',
    symbols=['MES'],
    schema=schema,
    stype_in='continuous',
    start=START_DATE,
    end=END_DATE
)

print('Fetching MNQ...')
mnq_data = client.timeseries.get_range(
    dataset='GLBX.MDP3',
    symbols=['MNQ'],
    schema=schema,
    stype_in='continuous',
    start=START_DATE,
    end=END_DATE
)

# Convert to DataFrames
es_df = es_data.to_df()
nq_df = nq_data.to_df()
mes_df = mes_data.to_df()
mnq_df = mnq_data.to_df()

print(f'ES: {len(es_df)} bars')
print(f'NQ: {len(nq_df)} bars')
print(f'MES: {len(mes_df)} bars')
print(f'MNQ: {len(mnq_df)} bars')

print()
print('Running cross-reference backtest...')
trades = run_crossref_backtest(es_df, nq_df, mes_df, mnq_df)

print()
print('='*70)
print('RESULTS')
print('='*70)

if trades:
    pnls = np.array([t['pnl'] for t in trades])
    n = len(pnls)
    wr = len(pnls[pnls>0]) / n * 100
    pf = pnls[pnls>0].sum() / abs(pnls[pnls<0].sum()) if len(pnls[pnls<0]) > 0 else 999
    total = pnls.sum()
    
    print(f'Total trades: {n}')
    print(f'Win rate: {wr:.1f}%')
    print(f'Profit factor: {pf:.2f}')
    print(f'Total P&L: ${total*100:,.0f}')
    print()
    
    # By signal type
    by_signal = defaultdict(list)
    for t in trades:
        by_signal[t['signal_type']].append(t['pnl'])
    
    print('By Signal Type:')
    for sig_type, vals in by_signal.items():
        arr = np.array(vals)
        print(f'  {sig_type:<15} | {len(arr):>4} trades | ${arr.sum()*100:>10,.0f}')
    
    # By exit type
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[t['exit_type']].append(t['pnl'])
    
    print()
    print('By Exit Type:')
    for exit_type, vals in by_exit.items():
        arr = np.array(vals)
        print(f'  {exit_type:<8} | {len(arr):>4} | ${arr.sum()*100:>10,.0f}')
else:
    print('No trades generated')

print('='*70)
