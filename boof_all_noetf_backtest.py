"""
Boof 22, 22.5, 23, 23.5 Separate Backtests - Boof No ETF List
No future-looking logic, historical only, actual exit prices
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
from collections import defaultdict
import numpy as np

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}
SYMBOLS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']
START, END = datetime(2025, 12, 1), datetime(2026, 5, 31)

def get_data(sym):
    print(f'  {sym}...', end=' ')
    df = fetch_alpaca_bars(sym, START, END, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 100: print('NO DATA'); return None
    if 'open' not in df.columns: df.columns = [c.lower() for c in df.columns]
    print(f'{len(df)} bars'); return df

def compute_atr(df, period=14):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h, l, c = df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < period else atr[i-1]*(period-1)/period + tr/period
    return atr

# ========== BOOF 22 ==========
print('\n' + '='*70)
print('BOOF 22 - Volume Clusters')
print('='*70)
trades_22 = []
for sym in SYMBOLS:
    df = get_data(sym)
    if df is None: continue
    atr = compute_atr(df)
    vol_sma = df['volume'].rolling(50).mean().values
    
    for i in range(100, len(df)-20):
        if atr[i] == 0: continue
        # Historical cluster build (up to bar i)
        clusters = []
        avg_atr = np.mean(atr[max(0,i-50):i+1][atr[max(0,i-50):i+1]>0])
        for j in range(50, i+1):
            if df['volume'].iloc[j] >= vol_sma[j] * 1.3:
                price = (df['high'].iloc[j] + df['low'].iloc[j]) / 2
                merged = False
                for c in clusters:
                    if abs(c['price']-price) <= avg_atr*0.5:
                        c['price'] = (c['price']*c['strength']+price)/(c['strength']+1)
                        c['strength'] += 1; merged = True; break
                if not merged: clusters.append({'price': price, 'strength': 1})
        clusters = [c for c in clusters if c['strength'] >= 2]
        
        # Near cluster?
        close, current_atr = df['close'].iloc[i], atr[i]
        if not clusters: continue
        dist = min(abs(close-c['price'])/current_atr for c in clusters)
        if dist > 1.0: continue
        
        # Entry (simplified - just trade direction toward cluster)
        nearest = min(clusters, key=lambda c: abs(close-c['price']))
        direction = 'LONG' if close < nearest['price'] else 'SHORT'
        entry = close
        if direction == 'LONG':
            sl = entry - current_atr
            tp = entry + current_atr * 2
        else:
            sl = entry + current_atr
            tp = entry - current_atr * 2
        
        # Exit
        for j in range(i+1, min(i+20, len(df))):
            if direction=='LONG':
                if df['low'].iloc[j] <= sl: trades_22.append({'sym':sym, 'pnl':(sl-entry)/entry*100, 'type':'SL'}); break
                if df['high'].iloc[j] >= tp: trades_22.append({'sym':sym, 'pnl':(tp-entry)/entry*100, 'type':'TP'}); break
            else:
                if df['high'].iloc[j] >= sl: trades_22.append({'sym':sym, 'pnl':(entry-sl)/entry*100, 'type':'SL'}); break
                if df['low'].iloc[j] <= tp: trades_22.append({'sym':sym, 'pnl':(entry-tp)/entry*100, 'type':'TP'}); break
        else:
            j = min(i+19, len(df)-1)
            trades_22.append({'sym':sym, 'pnl':((df['close'].iloc[j]-entry)/entry*100 if direction=='LONG' else (entry-df['close'].iloc[j])/entry*100), 'type':'TIME'})

if trades_22:
    pnls = np.array([t['pnl'] for t in trades_22])
    print(f"\n  Trades: {len(pnls)} | WR: {len(pnls[pnls>0])/len(pnls)*100:.1f}% | PF: {pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()):.2f} | Total: ${pnls.sum()*100:,.0f}")

# ========== BOOF 23 ==========
print('\n' + '='*70)
print('BOOF 23 - ZigZag Regime')
print('='*70)
trades_23 = []
for sym in SYMBOLS:
    df = get_data(sym)
    if df is None: continue
    atr = compute_atr(df)
    zz_high, zz_low, trend = df['high'].iloc[0], df['low'].iloc[0], ''
    
    for i in range(50, len(df)-20):
        if atr[i] == 0: continue
        close, high, low, current_atr = df['close'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], atr[i]
        # Update ZigZag
        if high > zz_high: zz_high = high
        if low < zz_low: zz_low = low
        threshold = current_atr * 0.75
        if trend=='up' and close < zz_low - threshold: trend = 'down'; zz_low = low
        elif trend=='down' and close > zz_high + threshold: trend = 'up'; zz_high = high
        elif trend=='': trend = 'up' if close > df['close'].iloc[i-20] else 'down'
        if trend=='': continue
        
        # 0.05% move check
        ret5 = (close - df['close'].iloc[max(0,i-5)]) / df['close'].iloc[max(0,i-5)] * 100
        if abs(ret5) < 0.05: continue
        direction = 'LONG' if (ret5 > 0 and trend=='up') or (ret5 < 0 and trend=='down') else None
        if not direction: continue
        
        entry, sl, tp = close, close-current_atr, close+current_atr*2 if direction=='LONG' else close+current_atr, close-current_atr*2
        for j in range(i+1, min(i+20, len(df))):
            if direction=='LONG':
                if df['low'].iloc[j] <= sl: trades_23.append({'sym':sym, 'pnl':(sl-entry)/entry*100, 'type':'SL'}); break
                if df['high'].iloc[j] >= tp: trades_23.append({'sym':sym, 'pnl':(tp-entry)/entry*100, 'type':'TP'}); break
            else:
                if df['high'].iloc[j] >= sl: trades_23.append({'sym':sym, 'pnl':(entry-sl)/entry*100, 'type':'SL'}); break
                if df['low'].iloc[j] <= tp: trades_23.append({'sym':sym, 'pnl':(entry-tp)/entry*100, 'type':'TP'}); break
        else:
            j = min(i+19, len(df)-1)
            trades_23.append({'sym':sym, 'pnl':((df['close'].iloc[j]-entry)/entry*100 if direction=='LONG' else (entry-df['close'].iloc[j])/entry*100), 'type':'TIME'})

if trades_23:
    pnls = np.array([t['pnl'] for t in trades_23])
    print(f"\n  Trades: {len(pnls)} | WR: {len(pnls[pnls>0])/len(pnls)*100:.1f}% | PF: {pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()):.2f} | Total: ${pnls.sum()*100:,.0f}")

# ========== BOOF 22.5 ==========
print('\n' + '='*70)
print('BOOF 22.5 - 22 + ADX Filter')
print('='*70)
trades_22_5 = []
for sym in SYMBOLS:
    df = get_data(sym)
    if df is None: continue
    atr = compute_atr(df)
    # ADX calculation
    adx = np.zeros(len(df))
    for i in range(14, len(df)):
        plus_dm = df['high'].iloc[i] - df['high'].iloc[i-1] if df['high'].iloc[i] - df['high'].iloc[i-1] > df['low'].iloc[i-1] - df['low'].iloc[i] else 0
        minus_dm = df['low'].iloc[i-1] - df['low'].iloc[i] if df['low'].iloc[i-1] - df['low'].iloc[i] > df['high'].iloc[i] - df['high'].iloc[i-1] else 0
        if plus_dm < 0: plus_dm = 0
        if minus_dm < 0: minus_dm = 0
        adx[i] = abs(plus_dm - minus_dm) / (atr[i] + 0.0001) * 100 if atr[i] > 0 else 0
    
    vol_sma = df['volume'].rolling(50).mean().values
    for i in range(100, len(df)-20):
        if atr[i] == 0 or adx[i] < 20: continue  # ADX filter
        clusters = []
        avg_atr = np.mean(atr[max(0,i-50):i+1][atr[max(0,i-50):i+1]>0])
        for j in range(50, i+1):
            if df['volume'].iloc[j] >= vol_sma[j] * 1.3:
                price = (df['high'].iloc[j] + df['low'].iloc[j]) / 2
                merged = False
                for c in clusters:
                    if abs(c['price']-price) <= avg_atr*0.5:
                        c['price'] = (c['price']*c['strength']+price)/(c['strength']+1)
                        c['strength'] += 1; merged = True; break
                if not merged: clusters.append({'price': price, 'strength': 1})
        clusters = [c for c in clusters if c['strength'] >= 2]
        if not clusters: continue
        close, current_atr = df['close'].iloc[i], atr[i]
        dist = min(abs(close-c['price'])/current_atr for c in clusters)
        if dist > 1.0: continue
        nearest = min(clusters, key=lambda c: abs(close-c['price']))
        direction = 'LONG' if close < nearest['price'] else 'SHORT'
        entry, sl, tp = close, close-current_atr, close+current_atr*2 if direction=='LONG' else close+current_atr, close-current_atr*2
        for j in range(i+1, min(i+20, len(df))):
            if direction=='LONG':
                if df['low'].iloc[j] <= sl: trades_22_5.append({'sym':sym, 'pnl':(sl-entry)/entry*100}); break
                if df['high'].iloc[j] >= tp: trades_22_5.append({'sym':sym, 'pnl':(tp-entry)/entry*100}); break
            else:
                if df['high'].iloc[j] >= sl: trades_22_5.append({'sym':sym, 'pnl':(entry-sl)/entry*100}); break
                if df['low'].iloc[j] <= tp: trades_22_5.append({'sym':sym, 'pnl':(entry-tp)/entry*100}); break
        else:
            j = min(i+19, len(df)-1)
            trades_22_5.append({'sym':sym, 'pnl':((df['close'].iloc[j]-entry)/entry*100 if direction=='LONG' else (entry-df['close'].iloc[j])/entry*100)})

if trades_22_5:
    pnls = np.array([t['pnl'] for t in trades_22_5])
    print(f"\n  Trades: {len(pnls)} | WR: {len(pnls[pnls>0])/len(pnls)*100:.1f}% | PF: {pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()):.2f} | Total: ${pnls.sum()*100:,.0f}")

# ========== BOOF 23.5 ==========
print('\n' + '='*70)
print('BOOF 23.5 - 23 + RSI2 Mean Reversion')
print('='*70)
trades_23_5 = []
for sym in SYMBOLS:
    df = get_data(sym)
    if df is None: continue
    atr = compute_atr(df)
    # RSI2
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
    rs = gain / loss
    rsi2 = 100 - (100 / (1 + rs))
    
    zz_high, zz_low, trend = df['high'].iloc[0], df['low'].iloc[0], ''
    for i in range(50, len(df)-20):
        if atr[i] == 0: continue
        close, high, low, current_atr = df['close'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], atr[i]
        if high > zz_high: zz_high = high
        if low < zz_low: zz_low = low
        threshold = current_atr * 0.75
        if trend=='up' and close < zz_low - threshold: trend = 'down'; zz_low = low
        elif trend=='down' and close > zz_high + threshold: trend = 'up'; zz_high = high
        elif trend=='': trend = 'up' if close > df['close'].iloc[i-20] else 'down'
        if trend=='': continue
        
        ret5 = (close - df['close'].iloc[max(0,i-5)]) / df['close'].iloc[max(0,i-5)] * 100
        if abs(ret5) < 0.05: continue
        
        # RSI2 filter
        current_rsi2 = rsi2.iloc[i] if not np.isnan(rsi2.iloc[i]) else 50
        if trend=='up' and current_rsi2 > 80: continue  # Overbought in uptrend
        if trend=='down' and current_rsi2 < 20: continue  # Oversold in downtrend
        
        direction = 'LONG' if (ret5 > 0 and trend=='up') or (ret5 < 0 and trend=='down') else None
        if not direction: continue
        
        entry, sl, tp = close, close-current_atr, close+current_atr*2 if direction=='LONG' else close+current_atr, close-current_atr*2
        for j in range(i+1, min(i+20, len(df))):
            if direction=='LONG':
                if df['low'].iloc[j] <= sl: trades_23_5.append({'sym':sym, 'pnl':(sl-entry)/entry*100}); break
                if df['high'].iloc[j] >= tp: trades_23_5.append({'sym':sym, 'pnl':(tp-entry)/entry*100}); break
            else:
                if df['high'].iloc[j] >= sl: trades_23_5.append({'sym':sym, 'pnl':(entry-sl)/entry*100}); break
                if df['low'].iloc[j] <= tp: trades_23_5.append({'sym':sym, 'pnl':(entry-tp)/entry*100}); break
        else:
            j = min(i+19, len(df)-1)
            trades_23_5.append({'sym':sym, 'pnl':((df['close'].iloc[j]-entry)/entry*100 if direction=='LONG' else (entry-df['close'].iloc[j])/entry*100)})

if trades_23_5:
    pnls = np.array([t['pnl'] for t in trades_23_5])
    print(f"\n  Trades: {len(pnls)} | WR: {len(pnls[pnls>0])/len(pnls)*100:.1f}% | PF: {pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()):.2f} | Total: ${pnls.sum()*100:,.0f}")

# SUMMARY
print('\n' + '='*70)
print('SUMMARY - ALL STRATEGIES')
print('='*70)
for name, trades in [('Boof 22', trades_22), ('Boof 22.5', trades_22_5), ('Boof 23', trades_23), ('Boof 23.5', trades_23_5)]:
    if trades:
        pnls = np.array([t['pnl'] for t in trades])
        print(f"{name:<12} | Trades: {len(pnls):>4} | WR: {len(pnls[pnls>0])/len(pnls)*100:>5.1f}% | PF: {pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()):>5.2f} | P&L: ${pnls.sum()*100:>10,.0f}")
    else:
        print(f"{name:<12} | No trades")
print('='*70)
