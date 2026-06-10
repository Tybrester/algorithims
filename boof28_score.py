"""
BOOF 28 - Score-Based Version
Relaxed filters, score >= 3 to enter
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Top 30 stocks + SPY
STOCKS = ["SPY","AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","JPM",
          "V","XOM","MA","HD","PG","COST","JNJ","ABBV","WMT","KO",
          "PEP","BAC","UNH","LIN","MRK","TMO","ACN","ABT","MCD","ADBE"]

def get_data(sym, start, end):
    df = fetch_alpaca_bars(sym, start, end, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df.sort_values('timestamp')

def calculate_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    pv = (typical * df['volume']).cumsum()
    vol = df['volume'].cumsum()
    return pv / vol

def run_backtest():
    # 2 months
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 31, tzinfo=timezone.utc)
    fetch_start = start_date - timedelta(days=20)
    fetch_end = end_date + timedelta(days=1)
    
    print('='*70)
    print('BOOF 28 - SCORE-BASED')
    print('Score >= 3 to enter | RVOL>1.5, RS>0.25, >VWAP, >OR')
    print('='*70)
    
    print(f'\nFetching {len(STOCKS)} symbols...')
    data = {}
    for sym in STOCKS:
        df = get_data(sym, fetch_start, fetch_end)
        if df is not None and len(df) >= 10:
            data[sym] = df
        time.sleep(0.1)
    
    print(f'Loaded {len(data)} symbols')
    
    spy_data = data.get('SPY')
    if spy_data is None or len(spy_data) == 0:
        print('ERROR: No SPY')
        return []
    
    # Trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current.date())
        current += timedelta(days=1)
    
    print(f'\nBacktesting {len(trading_days)} days...')
    all_trades = []
    
    for date in trading_days:
        trades = scan_day(date, data, spy_data)
        all_trades.extend(trades)
        if trades:
            pnl = sum(t['pnl'] for t in trades)
            print(f'{date}: {len(trades)} trades, P&L: {pnl:.2f}%')
    
    return all_trades

def scan_day(date, data, spy_data):
    trades = []
    
    # Build OR from first 3 bars (9:30-9:45 with 5m data)
    or_built = False
    or_high = None
    or_low = None
    
    # Get SPY data
    spy_day = spy_data[spy_data['timestamp'].dt.date == date]
    if len(spy_day) < 3:
        return []
    spy_open = spy_day['open'].iloc[0]
    
    # Scan from 9:35 to 10:30
    scan_start = datetime.combine(date, datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)
    scan_end = datetime.combine(date, datetime.strptime('10:30', '%H:%M').time(), tzinfo=timezone.utc)
    
    candidates = []
    
    for sym, df in data.items():
        if sym == 'SPY':
            continue
        
        day_data = df[df['timestamp'].dt.date == date].reset_index(drop=True)
        if len(day_data) < 5:
            continue
        
        # Build OR from first 3 bars
        or_high = day_data.iloc[:3]['high'].max()
        or_low = day_data.iloc[:3]['low'].min()
        
        # Get bar at scan time (9:35)
        bars_now = day_data[day_data['timestamp'] <= scan_start]
        if len(bars_now) < 1:
            continue
        
        idx = len(bars_now) - 1
        price = bars_now['close'].iloc[-1]
        day_open = day_data['open'].iloc[0]
        
        # VWAP
        vwap = calculate_vwap(bars_now).iloc[-1]
        
        # RVOL
        current_vol = bars_now['volume'].iloc[-1]
        hist_vols = []
        for days_back in range(1, 8):
            past_date = date - timedelta(days=days_back)
            if past_date.weekday() >= 5:
                continue
            past_day = df[df['timestamp'].dt.date == past_date]
            if len(past_day) >= len(bars_now):
                hist_vols.append(past_day['volume'].iloc[len(bars_now)-1])
        
        if len(hist_vols) < 2:
            continue
        rvol = current_vol / np.mean(hist_vols)
        
        # RS vs SPY
        spy_now = spy_day[spy_day['timestamp'] <= scan_start]
        spy_price = spy_now['close'].iloc[-1] if len(spy_now) > 0 else spy_open
        spy_ret = (spy_price - spy_open) / spy_open * 100
        stock_ret = (price - day_open) / day_open * 100
        rel_strength = stock_ret - spy_ret
        
        # SCORING (relaxed)
        score = 0
        if rvol > 1.5:
            score += 1
        if rel_strength > 0.25:
            score += 1
        if price > vwap:
            score += 1
        if price > or_high:
            score += 2  # OR breakout worth more
        
        if score >= 3:
            candidates.append({
                'sym': sym,
                'price': price,
                'score': score,
                'rvol': rvol,
                'rs': rel_strength,
                'vwap': vwap,
                'or_high': or_high,
                'day_data': day_data,
                'entry_idx': idx
            })
    
    # Take top 5 by score
    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        for c in candidates[:5]:
            # ATR
            dd = c['day_data']
            if c['entry_idx'] >= 3:
                atr = (dd.iloc[c['entry_idx']-3:c['entry_idx']]['high'] - 
                       dd.iloc[c['entry_idx']-3:c['entry_idx']]['low']).mean()
            else:
                atr = c['price'] * 0.002
            
            # Simulate
            pnl, exit = simulate(dd, c['entry_idx'], c['price'], atr)
            if pnl is not None:
                trades.append({
                    'date': date, 'sym': c['sym'], 'score': c['score'],
                    'rvol': c['rvol'], 'rs': c['rs'], 'pnl': pnl, 'exit': exit
                })
    
    return trades

def simulate(df, entry_idx, entry_price, atr, sl_r=1.0, tp_r=2.0, max_bars=12):
    if entry_idx >= len(df) - 1 or atr <= 0:
        return None, None
    
    sl = entry_price - atr * sl_r
    tp = entry_price + atr * tp_r
    max_idx = min(entry_idx + max_bars, len(df) - 1)
    
    for j in range(entry_idx + 1, max_idx + 1):
        bar = df.iloc[j]
        if bar['low'] <= sl:
            return (sl - entry_price) / entry_price * 100, 'SL'
        if bar['high'] >= tp:
            return (tp - entry_price) / entry_price * 100, 'TP'
    
    return (df.iloc[max_idx]['close'] - entry_price) / entry_price * 100, 'TIME'

if __name__ == '__main__':
    trades = run_backtest()
    
    print('\n' + '='*70)
    print('RESULTS')
    print('='*70)
    
    if trades:
        df = pd.DataFrame(trades)
        print(f"\nTotal: {len(df)} trades")
        print(f"Win Rate: {len(df[df['pnl'] > 0]) / len(df) * 100:.1f}%")
        print(f"Avg: {df['pnl'].mean():.3f}%")
        print(f"Total: {df['pnl'].sum():.2f}%")
        
        wins = df[df['pnl'] > 0]['pnl'].sum()
        losses = abs(df[df['pnl'] < 0]['pnl'].sum())
        print(f"PF: {wins/losses:.2f}" if losses > 0 else "PF: inf")
        
        print("\nBy Exit:")
        for et, g in df.groupby('exit'):
            print(f"  {et}: {len(g)} ({g['pnl'].sum():.2f}%)")
        
        print("\nTop Symbols:")
        for sym, pnl in df.groupby('sym')['pnl'].sum().sort_values(ascending=False).head(10).items():
            cnt = len(df[df['sym'] == sym])
            print(f"  {sym}: {cnt} trades, {pnl:.2f}%")
    else:
        print("No trades")
    
    print('='*70)
