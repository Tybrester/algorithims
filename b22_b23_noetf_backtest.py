"""
Boof 22 + 23 Backtest - No ETF List
No future-looking fractals, historical clusters only, proper time exits
Uses Alpaca 5m data
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
from collections import defaultdict
import numpy as np

# Alpaca credentials
creds = {
    'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU',
    'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
}

# Boof No ETF List from dropdown
SYMBOLS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']

# Period: Dec 2025 - May 2026 (6 months)
START_DATE = datetime(2025, 12, 1)
END_DATE = datetime(2026, 5, 31)

# Boof 22 Config
CFG = {
    'ATR_LEN': 14,
    'VOL_LEN': 50,
    'CLUSTER_MERGE': 0.5,
    'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0,
    'VOL_MULT': 1.3,
    'ATR_REV_MULT': 0.75,  # Boof 23 ZigZag
    'MAX_HOLD_BARS': 20,
    'TP_R': 2.0,
    'SL_R': 1.0,
}

def compute_atr(df, period=14):
    """Calculate ATR"""
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        atr[i] = tr if i < period else atr[i-1] * (period-1)/period + tr/period
    return atr

def build_clusters_historical(df, atr, vol_sma, up_to_idx):
    """Build volume clusters using ONLY historical bars up to up_to_idx"""
    if up_to_idx < CFG['VOL_LEN']:
        return []
    
    avg_atr = np.mean(atr[atr > 0]) if np.any(atr > 0) else 1
    merge_tol = avg_atr * CFG['CLUSTER_MERGE']
    
    buckets = []
    for i in range(CFG['VOL_LEN'], up_to_idx + 1):
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
    """Find nearest cluster distance"""
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

def run_strategy(df, symbol='SPY'):
    """Run Boof 22 + 23 hybrid - no future-looking logic"""
    if len(df) < 100:
        return []
    
    trades = []
    atr = compute_atr(df)
    vol_sma = df['volume'].rolling(window=CFG['VOL_LEN']).mean().values
    
    # ZigZag state
    last_zz_high = df['high'].iloc[0]
    last_zz_low = df['low'].iloc[0]
    trend = ''
    
    for i in range(CFG['VOL_LEN'] + 50, len(df) - 1):
        current_atr = atr[i]
        if current_atr == 0:
            continue
        
        close = df['close'].iloc[i]
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]
        
        # Build clusters using ONLY historical bars up to i (NO future-looking)
        clusters = build_clusters_historical(df, atr, vol_sma, i)
        
        # Boof 22: Check cluster proximity
        cluster_dist, nearest = nearest_cluster(close, clusters, current_atr)
        if cluster_dist > CFG['SR_DIST_MAX']:
            continue
        
        # Update ZigZag (Boof 23) - NO fractals, just swing detection
        threshold = current_atr * CFG['ATR_REV_MULT']
        
        if high > last_zz_high:
            last_zz_high = high
        if low < last_zz_low:
            last_zz_low = low
        
        # Check trend change
        if trend == 'up' or trend == '':
            if close < last_zz_low - threshold:
                trend = 'down'
                last_zz_low = low
        
        if trend == 'down' or trend == '':
            if close > last_zz_high + threshold:
                trend = 'up'
                last_zz_high = high
        
        if trend == '':
            continue
        
        # Determine direction based on cluster + trend
        direction = None
        if nearest and close > nearest['price'] and trend == 'up':
            direction = 'LONG'
        elif nearest and close < nearest['price'] and trend == 'down':
            direction = 'SHORT'
        
        if not direction:
            continue
        
        # Entry/SL/TP
        entry = close
        sl = entry - current_atr * CFG['SL_R'] if direction == 'LONG' else entry + current_atr * CFG['SL_R']
        tp = entry + current_atr * CFG['TP_R'] if direction == 'LONG' else entry - current_atr * CFG['TP_R']
        
        # Simulate trade with ACTUAL exit price
        exit_price = None
        exit_type = None
        exit_bar = None
        
        for j in range(i + 1, min(i + CFG['MAX_HOLD_BARS'], len(df))):
            bar_high = df['high'].iloc[j]
            bar_low = df['low'].iloc[j]
            
            if direction == 'LONG':
                if bar_low <= sl:
                    exit_price = max(bar_low, sl)  # Actual fill
                    exit_type = 'SL'
                    exit_bar = j
                    break
                if bar_high >= tp:
                    exit_price = min(bar_high, tp)  # Actual fill
                    exit_type = 'TP'
                    exit_bar = j
                    break
            else:
                if bar_high >= sl:
                    exit_price = min(bar_high, sl)  # Actual fill
                    exit_type = 'SL'
                    exit_bar = j
                    break
                if bar_low <= tp:
                    exit_price = max(bar_low, tp)  # Actual fill
                    exit_type = 'TP'
                    exit_bar = j
                    break
        
        # Time exit - use ACTUAL close price at exit bar
        if exit_price is None:
            j = min(i + CFG['MAX_HOLD_BARS'] - 1, len(df) - 1)
            exit_price = df['close'].iloc[j]  # ACTUAL price, not theoretical
            exit_type = 'TIME'
            exit_bar = j
        
        if exit_price:
            pnl_pct = (exit_price - entry) / entry * 100 if direction == 'LONG' else (entry - exit_price) / entry * 100
            
            trades.append({
                'entry_idx': i,
                'exit_idx': exit_bar,
                'entry': entry,
                'exit': exit_price,
                'exit_type': exit_type,
                'direction': direction,
                'pnl_pct': pnl_pct,
                'atr': current_atr,
                'cluster_dist': cluster_dist,
                'trend': trend,
            })
    
    return trades

# Run backtest
print('=' * 70)
print('BOOF 22 + 23 Hybrid Backtest - No ETF List')
print('Symbols:', SYMBOLS)
print(f'Period: {START_DATE.date()} to {END_DATE.date()}')
print('NO future-looking fractals, historical clusters only')
print('=' * 70)
print()

all_trades = []

for sym in SYMBOLS:
    print(f'Fetching {sym}...', end=' ')
    df = fetch_alpaca_bars(sym, START_DATE, END_DATE, '5Min', creds['api_key'], creds['secret_key'])
    
    if df is None or len(df) < 100:
        print('NO DATA')
        continue
    
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    
    print(f'{len(df)} bars')
    
    trades = run_strategy(df, sym)
    print(f'  {len(trades)} trades')
    
    for t in trades:
        t['symbol'] = sym
        all_trades.append(t)

# Results
print('\n' + '=' * 70)
print('RESULTS')
print('=' * 70)

if not all_trades:
    print('No trades generated')
else:
    pnls = np.array([t['pnl_pct'] for t in all_trades])
    pos = pnls[pnls > 0]
    neg = pnls[pnls < 0]
    
    n = len(pnls)
    wr = len(pos) / n * 100
    pf = pos.sum() / abs(neg.sum()) if len(neg) > 0 else 999
    ev = pnls.mean()
    total = pnls.sum()
    
    # Dollar PnL (assume $10k account, 10% risk = $1000 per trade, ~$10 per 0.1%)
    dollar_pnl = total * 100  # $100 per 1%
    
    print(f'  Total trades:     {n}')
    print(f'  Win rate:         {wr:.1f}%')
    print(f'  Profit factor:    {pf:.2f}')
    print(f'  EV/trade:         ${ev:.2f}')
    print(f'  Total P&L:        ${dollar_pnl:,.2f}')
    
    # Exit type breakdown
    by_exit = defaultdict(list)
    for t in all_trades:
        by_exit[t['exit_type']].append(t['pnl_pct'])
    
    print('\n  By Exit Type:')
    for exit_type, t_pnls in by_exit.items():
        arr = np.array(t_pnls)
        print(f'    {exit_type:<8} {len(arr):>4} trades  Avg: ${arr.mean():>6.2f}  Total: ${arr.sum():>10,.0f}')
    
    # By symbol
    print('\n  By Symbol:')
    for sym in SYMBOLS:
        s_pnls = [t['pnl_pct'] for t in all_trades if t['symbol'] == sym]
        if s_pnls:
            arr = np.array(s_pnls)
            print(f'    {sym:<6} {len(arr):>4} trades  ${arr.sum():>10,.0f}')

print('=' * 70)
