"""
Boof 26.0 — Hybrid Strategy Backtest (Working Version)
Boof ETF List: NVDA, AAPL, MSFT, AMZN, GOOG, AVGO, META, TSLA, LLY, QQQ, SPY
3 Months: Mar-May 2026
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

# Boof ETF list
ETF_LIST = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY', 'QQQ', 'SPY']

# Hardcoded Alpaca credentials
creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Config
CFG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6, 'CLUSTER_MERGE': 0.5, 'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0, 'VOL_MULT': 1.3, 'ATR_REV_MULT': 0.75,
    'VOL_MULT_MS': 1.25, 'ATR_PERCENTILE_MIN': 40, 'RETEST_BARS': 5,
    'TP_R': 2.0, 'SL_R': 1.0,
}

def compute_atr(df):
    highs, lows, closes = df['high'].values, df['low'].values, df['close'].values
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        atr[i] = tr if i < CFG['ATR_LEN'] else atr[i-1]*(CFG['ATR_LEN']-1)/CFG['ATR_LEN'] + tr/CFG['ATR_LEN']
    return atr

def run_boof26(df):
    if len(df) < 100: return []
    trades, atr = [], compute_atr(df)
    vol_sma = df['volume'].rolling(window=CFG['VOL_LEN']).mean().values
    
    for i in range(100, len(df)-1):
        if atr[i] == 0: continue
        close = df['close'].iloc[i]
        
        # Check for fractal
        fb = CFG['FRACTAL_BARS']
        peak = trough = False
        for offset in range(fb+2, min(10, i-fb)):
            idx = i - offset
            if idx < fb: break
            is_peak = all(df['high'].iloc[idx] > df['high'].iloc[idx+j] for j in range(1,fb+1)) and all(df['high'].iloc[idx] > df['high'].iloc[idx-j] for j in range(1,fb+1))
            is_trough = all(df['low'].iloc[idx] < df['low'].iloc[idx+j] for j in range(1,fb+1)) and all(df['low'].iloc[idx] < df['low'].iloc[idx-j] for j in range(1,fb+1))
            if is_peak: peak = True
            if is_trough: trough = True
        
        if not peak and not trough: continue
        
        # Simple trend (simplified)
        direction = None
        if peak and close > df['close'].iloc[i-20]: direction = 'SHORT'
        if trough and close < df['close'].iloc[i-20]: direction = 'LONG'
        if not direction: continue
        
        # Volume check
        if df['volume'].iloc[i] < vol_sma[i] * CFG['VOL_MULT_MS']: continue
        
        # Entry/SL/TP
        entry, current_atr = close, atr[i]
        sl = entry - current_atr * CFG['SL_R'] if direction == 'LONG' else entry + current_atr * CFG['SL_R']
        tp = entry + current_atr * CFG['TP_R'] if direction == 'LONG' else entry - current_atr * CFG['TP_R']
        
        # Simulate
        for j in range(i+1, min(i+50, len(df))):
            high, low = df['high'].iloc[j], df['low'].iloc[j]
            if direction == 'LONG':
                if low <= sl: trades.append({'pnl_pct': (sl-entry)/entry*100}); break
                if high >= tp: trades.append({'pnl_pct': (tp-entry)/entry*100}); break
            else:
                if high >= sl: trades.append({'pnl_pct': (entry-sl)/entry*100}); break
                if low <= tp: trades.append({'pnl_pct': (entry-tp)/entry*100}); break
    return trades

months = [('Mar 26', datetime(2026,3,1), datetime(2026,3,31)), ('Apr 26', datetime(2026,4,1), datetime(2026,4,30)), ('May 26', datetime(2026,5,1), datetime(2026,5,31))]

print('='*60)
print('BOOF 26.0 — Hybrid Backtest')
print('Symbols:', ETF_LIST)
print('Period: Mar-May 2026')
print('='*60)

all_trades = []
for label, start, end in months:
    print(f'\n{label}...', end=' ')
    month_trades = 0
    for sym in ETF_LIST:
        df = fetch_alpaca_bars(sym, start, end, '5Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100: continue
        if 'open' not in df.columns: df.columns = [c.lower() for c in df.columns]
        trades = run_boof26(df)
        for t in trades:
            t['symbol'], t['month'] = sym, label
            all_trades.append(t)
            month_trades += 1
    print(f'{month_trades} trades')

print('\n' + '='*60)
print('RESULTS')
print('='*60)

if not all_trades:
    print('No trades')
else:
    pnls = np.array([t['pnl_pct'] for t in all_trades])
    pos = pnls[pnls > 0]
    wr = len(pos)/len(pnls)*100
    pf = pos.sum()/abs(pnls[pnls<0].sum()) if len(pnls[pnls<0]) > 0 else 999
    
    print(f'Total trades: {len(pnls)}')
    print(f'Win rate: {wr:.1f}%')
    print(f'Profit factor: {pf:.2f}')
    print(f'EV/trade: ${pnls.mean():.2f}')
    print(f'Total P&L: ${pnls.sum():,.2f}')
    
    # By symbol
    print('\nBy Symbol:')
    for sym in ETF_LIST:
        s_pnls = [t['pnl_pct'] for t in all_trades if t['symbol']==sym]
        if s_pnls:
            s_arr = np.array(s_pnls)
            s_wr = len(s_arr[s_arr>0])/len(s_arr)*100
            print(f'  {sym}: {len(s_pnls)} trades, {s_wr:.1f}% WR, ${s_arr.sum():,.0f}')

print('='*60)
