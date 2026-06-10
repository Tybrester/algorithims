"""
BOOF 28 - Quick Test
5m data, first hour only (9:30-10:30), top 100 stocks, 2 months
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Top 100 liquid S&P 500 stocks
SP100 = [
    "SPY","AAPL","MSFT","NVDA","AMZN","META","GOOGL","BRK.B","LLY","AVGO",
    "TSLA","UNH","JPM","V","XOM","MA","HD","PG","COST","ABBV",
    "JNJ","WMT","KO","BAC","PEP","LIN","MRK","TMO","ACN","ABT",
    "MCD","ADBE","CSCO","WFC","TXN","VZ","CRM","NEE","PM","NKE",
    "CMCSA","RTX","BMY","ORCL","AMGN","SPGI","HON","UPS","LOW","INTC",
    "IBM","UNP","QCOM","SBUX","MDT","GE","GS","CAT","DE","ELV",
    "LMT","GILD","CVS","BLK","AXP","PLD","CI","AMAT","TJX","INTU",
    "ADP","ISRG","VRTX","ZTS","MDLZ","TMUS","CB","PYPL","REGN","SYK",
    "BKNG","C","BSX","ADI","SCHW","SO","MMC","HCA","ETN","DUK",
    "MU","PNC","AON","ITW","SHW","CSX","NOC","CL","EOG","APD"
]

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
    fetch_start = start_date - timedelta(days=30)  # For RVOL history
    fetch_end = end_date + timedelta(days=1)
    
    print('='*70)
    print('BOOF 28 - QUICK TEST')
    print('5m data | First hour (9:30-10:30) | 100 stocks | Dec-Jan')
    print('='*70)
    
    # Fetch data
    print(f'\nFetching data for {len(SP100)} symbols...')
    data_cache = {}
    for sym in SP100:
        df = get_data(sym, fetch_start, fetch_end)
        if df is not None and len(df) > 0:
            data_cache[sym] = df
            print(f'  {sym}: OK')
        else:
            print(f'  {sym}: NO DATA')
        time.sleep(0.15)
    
    print(f'\nLoaded {len(data_cache)} symbols')
    
    spy_data = data_cache.get('SPY')
    if spy_data is None or len(spy_data) == 0:
        print('ERROR: SPY not loaded')
        return []
    
    # Generate trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current.date())
        current += timedelta(days=1)
    
    print(f'\nScanning {len(trading_days)} trading days...')
    print('='*70)
    
    all_trades = []
    
    for date in trading_days:
        trades = run_scan_day(date, data_cache, spy_data)
        all_trades.extend(trades)
        if len(trades) > 0:
            print(f'{date}: {len(trades)} trades')
    
    return all_trades

def run_scan_day(date, data_cache, spy_data):
    """Scan at 9:35 AM for one day"""
    trades = []
    target_time = datetime.combine(date, datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)
    end_time = datetime.combine(date, datetime.strptime('10:30', '%H:%M').time(), tzinfo=timezone.utc)
    
    spy_day = spy_data[spy_data['timestamp'].dt.date == date]
    if len(spy_day) < 2:
        return []
    
    spy_open = spy_day['open'].iloc[0]
    
    candidates = []
    
    # Debug counters
    total_checked = 0
    has_history = 0
    has_935 = 0
    has_prev_day = 0
    has_rvol = 0
    passed_rvol = 0
    passed_rs = 0
    passed_vwap = 0
    passed_or = 0
    
    for sym, df in data_cache.items():
        if sym == 'SPY':
            continue
        
        total_checked += 1
        
        # Get day data
        day_data = df[df['timestamp'].dt.date == date].reset_index(drop=True)
        if len(day_data) < 2:
            continue
        has_history += 1
        
        # Get 9:35 bar
        bars_935 = day_data[day_data['timestamp'] <= target_time]
        if len(bars_935) < 1:
            continue
        has_935 += 1
        
        idx = len(bars_935) - 1
        current_price = bars_935['close'].iloc[-1]
        open_price = day_data['open'].iloc[0]
        
        # VWAP
        vwap = calculate_vwap(bars_935).iloc[-1]
        
        # Gap %
        prev_day = df[df['timestamp'].dt.date == date - timedelta(days=1)]
        if len(prev_day) == 0:
            continue
        has_prev_day += 1
        prev_close = prev_day['close'].iloc[-1]
        gap_pct = (open_price - prev_close) / prev_close * 100
        
        # Simple RVOL (current vs avg of last 10 days at same time)
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
        has_rvol += 1
        rvol = current_vol / np.mean(hist_vols) if hist_vols else 1.0
        
        # Relative Strength vs SPY
        spy_935 = spy_day[spy_day['timestamp'] <= target_time]
        if len(spy_935) > 0:
            spy_price = spy_935['close'].iloc[-1]
            spy_move = (spy_price - spy_open) / spy_open * 100
        else:
            spy_move = 0
        stock_move = (current_price - open_price) / open_price * 100
        rel_strength = stock_move - spy_move
        
        # Opening Range (first 2 bars = 10 min with 5m data)
        if len(day_data) < 2:
            continue
        or_high = day_data.iloc[:2]['high'].max()
        or_low = day_data.iloc[:2]['low'].min()
        
        # Count filter passes
        if rvol > 2:
            passed_rvol += 1
        if rel_strength > 1:
            passed_rs += 1
        if current_price > vwap:
            passed_vwap += 1
        if current_price > or_high:
            passed_or += 1
        
        # Debug first stock that gets here
        if total_checked == 1:
            print(f"\nDEBUG {sym} on {date}:")
            print(f"  Price: {current_price:.2f}, VWAP: {vwap:.2f}, OR High: {or_high:.2f}")
            print(f"  RVOL: {rvol:.2f}, RS: {rel_strength:.2f}%, Gap: {gap_pct:.2f}%")
            print(f"  RVOL>2: {rvol>2}, RS>1: {rel_strength>1}, >VWAP: {current_price>vwap}, >OR: {current_price>or_high}")
        
        # Filters and score
        vwap_bonus = 1 if current_price > vwap else 0
        above_or = current_price > or_high
        
        score = min(rvol, 10) * 0.4 + rel_strength * 0.3 + abs(gap_pct) * 0.2 + vwap_bonus * 0.1
        
        # Entry: RVOL > 2, RS > 1%, above VWAP, above OR
        if rvol > 2 and rel_strength > 1 and current_price > vwap and above_or:
            candidates.append({
                'sym': sym,
                'price': current_price,
                'score': score,
                'rvol': rvol,
                'gap': gap_pct,
                'rs': rel_strength,
                'day_data': day_data,
                'entry_idx': idx,
                'entry_time': bars_935['timestamp'].iloc[-1]
            })
    
    # Take top 5 by score, simulate trades
    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        for c in candidates[:5]:
            # Quick ATR calc
            dd = c['day_data']
            if c['entry_idx'] >= 5:
                recent = dd.iloc[max(0, c['entry_idx']-5):c['entry_idx']]
                atr = (recent['high'] - recent['low']).mean()
            else:
                atr = c['price'] * 0.002
            
            # Check time to complete
            if c['entry_time'] + timedelta(minutes=60) > end_time:
                continue
            
            # Simulate
            pnl, exit_type = simulate(c['day_data'], c['entry_idx'], c['price'], atr)
            if pnl is not None:
                trades.append({
                    'date': date,
                    'sym': c['sym'],
                    'score': c['score'],
                    'rvol': c['rvol'],
                    'pnl': pnl,
                    'exit': exit_type
                })
    
    # Print debug stats for first day only
    if len(trades) == 0 and total_checked > 0:
        print(f"\n  Filter stats for {date}:")
        print(f"    Total checked: {total_checked}")
        print(f"    Has history: {has_history}")
        print(f"    Has 9:35 bar: {has_935}")
        print(f"    Has prev day: {has_prev_day}")
        print(f"    Has RVOL calc: {has_rvol}")
        print(f"    Passed RVOL>2: {passed_rvol}")
        print(f"    Passed RS>1: {passed_rs}")
        print(f"    Passed VWAP: {passed_vwap}")
        print(f"    Passed OR: {passed_or}")
    
    return trades

def simulate(df, entry_idx, entry_price, atr, sl_r=1.0, tp_r=2.0, max_bars=12):
    """Simulate with 1R SL, 2R TP, time exit"""
    if entry_idx >= len(df) - 1:
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
    print('RESULTS')
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
            print(f"  {et}: {len(group)} trades, {group['pnl'].sum():.2f}%")
        
        print("\nBy Symbol (Top 10):")
        by_sym = df.groupby('sym')['pnl'].sum().sort_values(ascending=False).head(10)
        for sym, pnl in by_sym.items():
            count = len(df[df['sym'] == sym])
            print(f"  {sym}: {count} trades, {pnl:.2f}%")
    else:
        print("No trades generated")
    
    print('='*70)
