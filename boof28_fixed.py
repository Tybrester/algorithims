"""
BOOF 28 - Fixed Version
Opening Drive with proper RS, OR, and RVOL handling
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Top 50 stocks + SPY
STOCKS = ["SPY","AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","JPM",
          "V","XOM","MA","HD","PG","COST","JNJ","ABBV","WMT","KO",
          "PEP","BAC","UNH","LIN","MRK","TMO","ACN","ABT","MCD","ADBE",
          "CSCO","TXN","VZ","CRM","NEE","PM","NKE","CMCSA","RTX","BMY",
          "ORCL","AMGN","SPGI","HON","UPS","LOW","INTC","IBM","UNP","QCOM"]

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
    # 2 months: Dec 2025 - Jan 2026
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 31, tzinfo=timezone.utc)
    fetch_start = start_date - timedelta(days=25)  # For RVOL history
    fetch_end = end_date + timedelta(days=1)
    
    print('='*70)
    print('BOOF 28 - FIXED VERSION')
    print('5m data | First hour | 50 stocks | Dec-Jan')
    print('='*70)
    
    # Fetch data
    print(f'\nFetching data for {len(STOCKS)} symbols...')
    data = {}
    for sym in STOCKS:
        df = get_data(sym, fetch_start, fetch_end)
        if df is not None and len(df) >= 10:
            data[sym] = df
            print(f'  {sym}: OK')
        else:
            print(f'  {sym}: SKIP')
        time.sleep(0.15)
    
    print(f'\nLoaded {len(data)} symbols')
    
    spy_data = data.get('SPY')
    if spy_data is None:
        print('ERROR: SPY required')
        return []
    
    # Trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current.date())
        current += timedelta(days=1)
    
    print(f'\nBacktesting {len(trading_days)} days...')
    print('='*70)
    
    all_trades = []
    
    for date in trading_days:
        trades = scan_day(date, data, spy_data)
        all_trades.extend(trades)
        if trades:
            print(f'{date}: {len(trades)} trades, P&L: {sum(t["pnl"] for t in trades):.2f}%')
    
    return all_trades

def scan_day(date, data, spy_data):
    """Scan at 9:35 AM, enter long above VWAP + above OR"""
    trades = []
    target_time = datetime.combine(date, datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)
    
    # Get SPY data for the day
    spy_day = spy_data[spy_data['timestamp'].dt.date == date]
    if len(spy_day) < 2:
        return []
    
    spy_open = spy_day['open'].iloc[0]
    spy_935 = spy_day[spy_day['timestamp'] <= target_time]
    spy_price = spy_935['close'].iloc[-1] if len(spy_935) > 0 else spy_open
    spy_ret = (spy_price - spy_open) / spy_open * 100
    
    candidates = []
    
    for sym, df in data.items():
        if sym == 'SPY':
            continue
        
        # Get day data
        day_data = df[df['timestamp'].dt.date == date].reset_index(drop=True)
        if len(day_data) < 5:  # Need enough bars
            continue
        
        # Get 9:35 bar
        bars_935 = day_data[day_data['timestamp'] <= target_time]
        if len(bars_935) < 1:
            continue
        
        idx = len(bars_935) - 1
        current_price = bars_935['close'].iloc[-1]
        day_open = day_data['open'].iloc[0]
        
        # VWAP
        vwap = calculate_vwap(bars_935).iloc[-1]
        
        # RVOL - compare to avg of last 10 days at same time
        current_vol = bars_935['volume'].iloc[-1]
        hist_vols = []
        for days_back in range(1, 11):
            past_date = date - timedelta(days=days_back)
            if past_date.weekday() >= 5:
                continue
            past_day = df[df['timestamp'].dt.date == past_date]
            if len(past_day) >= len(bars_935):
                hist_vols.append(past_day['volume'].iloc[len(bars_935)-1])
        
        if len(hist_vols) < 3:
            continue
        rvol = current_vol / np.mean(hist_vols)
        
        # Skip if RVOL too low
        if rvol < 1:
            continue
        
        # Relative Strength vs SPY
        stock_ret = (current_price - day_open) / day_open * 100
        rel_strength = stock_ret - spy_ret
        
        # Opening Range - first 15 minutes (3 bars of 5m)
        or_high = day_data.iloc[:3]['high'].max() if len(day_data) >= 3 else day_data['high'].iloc[:2].max()
        
        # LONG ONLY: Above VWAP + Above OR High + Positive RS
        if current_price > vwap and current_price > or_high and rel_strength > 0.5:
            candidates.append({
                'sym': sym,
                'price': current_price,
                'score': rvol * 0.5 + rel_strength * 0.3,
                'rvol': rvol,
                'rs': rel_strength,
                'day_data': day_data,
                'entry_idx': idx
            })
    
    # Take top 3 by score
    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        for c in candidates[:3]:
            # Quick ATR
            dd = c['day_data']
            if c['entry_idx'] >= 3:
                recent = dd.iloc[c['entry_idx']-3:c['entry_idx']]
                atr = (recent['high'] - recent['low']).mean()
            else:
                atr = c['price'] * 0.002
            
            # Simulate trade (1R SL, 2R TP, 12 bar max)
            pnl, exit_type = simulate(dd, c['entry_idx'], c['price'], atr)
            if pnl is not None:
                trades.append({
                    'date': date,
                    'sym': c['sym'],
                    'score': c['score'],
                    'rvol': c['rvol'],
                    'rs': c['rs'],
                    'pnl': pnl,
                    'exit': exit_type
                })
    
    return trades

def simulate(df, entry_idx, entry_price, atr, sl_r=1.0, tp_r=2.0, max_bars=12):
    """Simulate with 1R SL, 2R TP, time exit"""
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
    
    exit_price = df.iloc[max_idx]['close']
    return (exit_price - entry_price) / entry_price * 100, 'TIME'

# MAIN
if __name__ == '__main__':
    trades = run_backtest()
    
    print('\n' + '='*70)
    print('FINAL RESULTS')
    print('='*70)
    
    if trades:
        df = pd.DataFrame(trades)
        
        print(f"\nTotal Trades: {len(df)}")
        print(f"Win Rate: {len(df[df['pnl'] > 0]) / len(df) * 100:.1f}%")
        print(f"Avg P&L: {df['pnl'].mean():.3f}%")
        print(f"Total Return: {df['pnl'].sum():.2f}%")
        
        wins = df[df['pnl'] > 0]['pnl'].sum()
        losses = abs(df[df['pnl'] < 0]['pnl'].sum())
        pf = wins / losses if losses > 0 else 999
        print(f"Profit Factor: {pf:.2f}")
        
        print("\nBy Exit:")
        for et, group in df.groupby('exit'):
            wr = len(group[group['pnl'] > 0]) / len(group) * 100
            print(f"  {et}: {len(group)} trades, {group['pnl'].sum():.2f}%, WR: {wr:.1f}%")
        
        print("\nTop 10 Symbols:")
        by_sym = df.groupby('sym').agg({'pnl': 'sum', 'sym': 'count'}).rename(columns={'sym': 'count'}).sort_values('pnl', ascending=False).head(10)
        for sym, row in by_sym.iterrows():
            print(f"  {sym}: {row['count']} trades, {row['pnl']:.2f}%")
    else:
        print("No trades generated")
    
    print('='*70)
