"""
Boof 26.0 — Hybrid Strategy Backtest (DataBento)
Futures: ES, NQ, MNQ, MES
6 Months: Dec 2025 - May 2026
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import requests

# DataBento API Key
DATABENTO_KEY = 'db-HjUMrsa7gNvavTcwU8fUdywvQSfH7'

# Futures config (DataBento symbols)
FUTURES = {
    'ES':  {'db_symbol': 'ES.c.0',  'tick_value': 12.50},
    'NQ':  {'db_symbol': 'NQ.c.0',  'tick_value': 5.00},
    'MES': {'db_symbol': 'MES.c.0', 'tick_value': 1.25},
    'MNQ': {'db_symbol': 'MNQ.c.0', 'tick_value': 0.50},
}

# Boof 26 Config
CFG = {
    'ATR_LEN': 14,
    'VOL_LEN': 50,
    'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6,
    'CLUSTER_MERGE': 0.5,
    'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0,
    'VOL_MULT': 1.3,
    'ATR_REV_MULT': 0.75,
    'VOL_MULT_MS': 1.25,
    'ATR_PERCENTILE_MIN': 40,
    'RETEST_BARS': 5,
    'TP_R': 2.0,
    'SL_R': 1.0,
}

def fetch_databento(symbol, start, end, schema='ohlcv-5m'):
    """Fetch futures data from DataBento"""
    url = 'https://hist.databento.com/v0/timeseries.get_range'
    headers = {'Authorization': DATABENTO_KEY}
    
    params = {
        'dataset': 'GLBX.MDP3',
        'symbols': FUTURES[symbol]['db_symbol'],
        'schema': schema,
        'start': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end': end.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stype_in': 'raw_symbol'
    }
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200:
            print(f"  DataBento error: {r.status_code}")
            return None
        
        data = r.json()
        bars = data.get('data', [])
        if not bars:
            return None
        
        # Convert to DataFrame-like structure
        import pandas as pd
        df = pd.DataFrame(bars)
        
        # DataBento columns: ts_event, open, high, low, close, volume
        if 'ts_event' in df.columns:
            df['time'] = pd.to_datetime(df['ts_event'], unit='ns')
        
        return df
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return None

def compute_atr(df, period=14):
    """Calculate ATR"""
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        atr[i] = tr if i < period else atr[i-1] * (period-1)/period + tr/period
    return atr

def build_clusters(df, atr, vol_sma):
    """Build volume-based SR clusters"""
    avg_atr = np.mean(atr[atr > 0]) if np.any(atr > 0) else 1
    merge_tol = avg_atr * CFG['CLUSTER_MERGE']
    
    buckets = []
    for i in range(CFG['VOL_LEN'], len(df)):
        if df['volume'].iloc[i] < vol_sma[i] * CFG['VOL_MULT']:
            continue
        price = (df['high'].iloc[i] + df['low'].iloc[i]) / 2
        merged = False
        for b in buckets:
            if abs(b['price'] - price) <= merge_tol:
                b['price'] = (b['price'] * b['strength'] + price) / (b['strength'] + 1)
                b['strength'] += 1
                merged = True
                break
        if not merged:
            buckets.append({'price': price, 'strength': 1})
    
    return [b for b in buckets if b['strength'] >= CFG['SR_STRENGTH_MIN']]

def nearest_cluster(price, clusters, atr):
    """Find nearest cluster"""
    if not clusters or atr == 0:
        return float('inf'), None
    best = clusters[0]
    best_dist = abs(price - best['price']) / atr
    for c in clusters:
        d = abs(price - c['price']) / atr
        if d < best_dist:
            best_dist = d
            best = c
    return best_dist, best

def update_zigzag(df, atr):
    """ZigZag state machine"""
    n = len(df)
    if n < 2:
        return {'trend': '', 'zz_high': df['high'].iloc[0], 'zz_low': df['low'].iloc[0]}
    
    last_high = {'idx': 0, 'price': df['high'].iloc[0]}
    last_low = {'idx': 0, 'price': df['low'].iloc[0]}
    trend = ''
    
    for i in range(1, n):
        threshold = atr[i] * CFG['ATR_REV_MULT']
        
        if df['high'].iloc[i] > last_high['price']:
            last_high = {'idx': i, 'price': df['high'].iloc[i]}
        if df['low'].iloc[i] < last_low['price']:
            last_low = {'idx': i, 'price': df['low'].iloc[i]}
        
        close = df['close'].iloc[i]
        
        if trend == 'up' and last_high['price'] - close > threshold:
            trend = 'down'
            last_low = {'idx': i, 'price': df['low'].iloc[i]}
        elif trend == 'down' and close - last_low['price'] > threshold:
            trend = 'up'
            last_high = {'idx': i, 'price': df['high'].iloc[i]}
        elif trend == '':
            if close > df['high'].iloc[0] + threshold:
                trend = 'up'
            elif close < df['low'].iloc[0] - threshold:
                trend = 'down'
    
    return {
        'trend': trend,
        'zz_high': last_high['price'],
        'zz_low': last_low['price']
    }

def check_fractal(df, lookback=10):
    """Check for recent fractals"""
    n = len(df)
    fb = CFG['FRACTAL_BARS']
    peak = trough = False
    
    for offset in range(fb + 2, min(lookback, n - fb - 1)):
        idx = n - 1 - offset
        if idx < fb:
            break
            
        is_peak = is_trough = True
        for j in range(1, fb + 1):
            if df['high'].iloc[idx] <= df['high'].iloc[idx + j]: is_peak = False
            if df['high'].iloc[idx] <= df['high'].iloc[idx - j]: is_peak = False
            if df['low'].iloc[idx] >= df['low'].iloc[idx + j]: is_trough = False
            if df['low'].iloc[idx] >= df['low'].iloc[idx - j]: is_trough = False
        
        if is_peak: peak = True
        if is_trough: trough = True
    
    return peak, trough

def check_msb(df, zz):
    """Market Structure Break"""
    close = df['close'].iloc[-1]
    bull = bear = False
    price = 0
    
    if zz['trend'] == 'down' and close > zz['zz_high']:
        bull = True
        price = zz['zz_high']
    elif zz['trend'] == 'up' and close < zz['zz_low']:
        bear = True
        price = zz['zz_low']
    
    return bull, bear, price

def check_retest(df, msb_price, direction, bars=5):
    """Check for retest"""
    n = len(df)
    start = max(0, n - bars - 5)
    
    for i in range(start, n):
        if direction == 'LONG':
            if df['low'].iloc[i] <= msb_price * 1.005 and df['close'].iloc[i] > msb_price:
                return True
        else:
            if df['high'].iloc[i] >= msb_price * 0.995 and df['close'].iloc[i] < msb_price:
                return True
    return False

def run_boof26(df, symbol='ES'):
    """Run Boof 26 hybrid strategy"""
    if len(df) < 100:
        return []
    
    import pandas as pd
    trades = []
    atr = compute_atr(df)
    
    # Volume SMA
    vol_sma = df['volume'].rolling(window=CFG['VOL_LEN']).mean().values
    
    # VWAP
    tp = (df['high'] + df['low'] + df['close']) / 3
    vwap = (tp * df['volume']).cumsum() / df['volume'].cumsum()
    
    # Build clusters once
    clusters = build_clusters(df, atr, vol_sma)
    
    for i in range(100, len(df) - 1):
        window = df.iloc[:i+1]
        current_atr = atr[i]
        
        if current_atr == 0:
            continue
        
        close = df['close'].iloc[i]
        
        # Layer 1: Cluster
        cluster_dist, nearest = nearest_cluster(close, clusters, current_atr)
        if cluster_dist > CFG['SR_DIST_MAX']:
            continue
        
        # Layer 2: Fractal + ZigZag
        peak, trough = check_fractal(window)
        zz = update_zigzag(window, atr[:i+1])
        
        if not zz['trend']:
            continue
        
        direction = None
        if peak and zz['trend'] == 'up':
            direction = 'SHORT'
        elif trough and zz['trend'] == 'down':
            direction = 'LONG'
        
        if not direction:
            continue
        
        # Layer 3: MSB
        msb_bull, msb_bear, msb_price = check_msb(window, zz)
        msb_aligned = (direction == 'LONG' and msb_bull) or (direction == 'SHORT' and msb_bear)
        
        if not msb_aligned:
            continue
        
        if not check_retest(window, msb_price, direction):
            continue
        
        # Layer 4: Context
        if df['volume'].iloc[i] < vol_sma[i] * CFG['VOL_MULT_MS']:
            continue
        
        # ATR percentile
        atr_slice = atr[max(0, i-50):i+1]
        atr_pct = (atr_slice < current_atr).sum() / len(atr_slice) * 100 if len(atr_slice) > 0 else 50
        if atr_pct < CFG['ATR_PERCENTILE_MIN']:
            continue
        
        # VWAP
        current_vwap = vwap.iloc[i]
        if direction == 'LONG' and close < current_vwap:
            continue
        if direction == 'SHORT' and close > current_vwap:
            continue
        
        # Entry
        entry = close
        sl = entry - current_atr * CFG['SL_R'] if direction == 'LONG' else entry + current_atr * CFG['SL_R']
        tp = entry + current_atr * CFG['TP_R'] if direction == 'LONG' else entry - current_atr * CFG['TP_R']
        
        # Simulate trade
        exit_price = None
        exit_type = None
        
        for j in range(i + 1, min(i + 50, len(df))):
            high = df['high'].iloc[j]
            low = df['low'].iloc[j]
            
            if direction == 'LONG':
                if low <= sl:
                    exit_price = sl
                    exit_type = 'sl'
                    break
                if high >= tp:
                    exit_price = tp
                    exit_type = 'tp'
                    break
            else:
                if high >= sl:
                    exit_price = sl
                    exit_type = 'sl'
                    break
                if low <= tp:
                    exit_price = tp
                    exit_type = 'tp'
                    break
        
        if exit_price and exit_type:
            actual_r = abs(exit_price - entry) / current_atr
            
            if direction == 'LONG':
                pnl_r = actual_r if exit_type == 'tp' else -1.0
            else:
                pnl_r = actual_r if exit_type == 'tp' else -1.0
            
            trades.append({
                'entry_idx': i,
                'entry': entry,
                'sl': sl,
                'tp': tp,
                'exit': exit_price,
                'exit_type': exit_type,
                'direction': direction,
                'pnl_r': pnl_r,
                'atr': current_atr,
                'cluster_dist': cluster_dist,
                'layers': 4
            })
    
    return trades

# Main backtest
months = [
    ('Dec 25', datetime(2025, 12, 1), datetime(2025, 12, 31)),
    ('Jan 26', datetime(2026, 1, 1), datetime(2026, 1, 31)),
    ('Feb 26', datetime(2026, 2, 1), datetime(2026, 2, 28)),
    ('Mar 26', datetime(2026, 3, 1), datetime(2026, 3, 31)),
    ('Apr 26', datetime(2026, 4, 1), datetime(2026, 4, 30)),
    ('May 26', datetime(2026, 5, 1), datetime(2026, 5, 31)),
]

print('=' * 70)
print('BOOF 26.0 — Hybrid Strategy Backtest (DataBento)')
print('Futures: ES, NQ, MES, MNQ')
print('Period: Dec 2025 - May 2026 (6 months)')
print('=' * 70)
print()

all_trades = []

for label, start, end in months:
    print(f'  {label}...', end=' ', flush=True)
    month_trades = 0
    
    for sym in FUTURES.keys():
        df = fetch_databento(sym, start, end, 'ohlcv-5m')
        
        if df is None or len(df) < 100:
            continue
        
        trades = run_boof26(df, sym)
        
        # Calculate dollar PnL
        tick_value = FUTURES[sym]['tick_value']
        for t in trades:
            # Convert R to ticks to dollars
            # R = 1.0 = SL distance in ATR units
            # Approximate: 1 ATR ≈ 40 ticks for ES/MES, 80 for NQ/MNQ
            ticks_per_r = 40 if sym in ['ES', 'MES'] else 80
            dollar_per_r = ticks_per_r * tick_value
            t['pnl_dollar'] = t['pnl_r'] * dollar_per_r
            t['symbol'] = sym
            t['month'] = label
            all_trades.append(t)
            month_trades += 1
    
    print(f'{month_trades} trades')

print()
print('=' * 70)
print('RESULTS')
print('=' * 70)

if not all_trades:
    print('No trades generated')
else:
    pnls = np.array([t['pnl_dollar'] for t in all_trades])
    pos = pnls[pnls > 0]
    neg = pnls[pnls < 0]
    
    n = len(pnls)
    wr = len(pos) / n * 100
    pf = pos.sum() / abs(neg.sum()) if len(neg) > 0 else 999
    ev = pnls.mean()
    total = pnls.sum()
    tdays = 23 + 23 + 20 + 21 + 22 + 21  # Trading days
    
    print(f'  Total trades:  {n}')
    print(f'  Trades/day:    {n/tdays:.2f}')
    print(f'  Win rate:      {wr:.1f}%')
    print(f'  Profit factor: {pf:.2f}')
    print(f'  EV/trade:      ${ev:.2f}')
    print(f'  Total P&L:     ${total:,.2f}')
    print(f'  Per month:     ${total/6:,.2f}')
    print()
    
    # By symbol
    by_sym = defaultdict(list)
    for t in all_trades:
        by_sym[t['symbol']].append(t['pnl_dollar'])
    
    print('By Symbol:')
    print(f'  {"Symbol":<8} {"Trades":>8} {"WR":>8} {"P&L":>12} {"EV/trade":>10}')
    print('  ' + '-' * 55)
    for sym in FUTURES.keys():
        if sym in by_sym:
            s_pnls = np.array(by_sym[sym])
            s_pos = s_pnls[s_pnls > 0]
            s_wr = len(s_pos) / len(s_pnls) * 100
            s_tot = s_pnls.sum()
            s_ev = s_pnls.mean()
            print(f'  {sym:<8} {len(s_pnls):>8} {s_wr:>7.1f}% ${s_tot:>10,.0f} ${s_ev:>9.2f}')
    
    print()
    
    # Monthly breakdown
    by_month = defaultdict(list)
    for t in all_trades:
        by_month[t['month']].append(t['pnl_dollar'])
    
    print('Monthly:')
    print(f'  {"Month":<10} {"Trades":>8} {"WR":>8} {"P&L":>12}')
    print('  ' + '-' * 42)
    for label, _, _ in months:
        if label in by_month:
            m_pnls = np.array(by_month[label])
            m_pos = m_pnls[m_pnls > 0]
            m_wr = len(m_pos) / len(m_pnls) * 100
            m_tot = m_pnls.sum()
            print(f'  {label:<10} {len(m_pnls):>8} {m_wr:>7.1f}% ${m_tot:>10,.0f}')

print('=' * 70)
