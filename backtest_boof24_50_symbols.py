"""
BOOF 24.1 — 50 Symbol Test: Baseline vs Breakout Filter
6 months | 1m & 5m | Tracking expectancy per symbol
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import time

ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
DATA_URL = 'https://data.alpaca.markets'

SYMBOLS = [
    'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'NFLX', 'TSLA', 'NVDA', 'AMD', 'CRM',
    'COIN', 'SHOP', 'PLTR', 'RIVN', 'SNOW', 'UBER', 'LYFT', 'DKNG', 'MAR', 'ABNB',
    'QQQ', 'IWM', 'XLF', 'XLK', 'XLE', 'BA', 'DIS', 'NKE', 'INTC', 'PYPL',
    'BABA', 'TGT', 'WMT', 'COST', 'GME', 'AMC', 'RIOT', 'MARA', 'F', 'GM',
    'PFE', 'KO', 'PEP', 'JPM', 'V', 'MA', 'HD', 'LOW', 'SBUX', 'NIO'
]

def fetch_data(symbol, timeframe, start, end):
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 30 if timeframe == '1Min' else 60
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_size), end_dt)
        params = {
            'timeframe': timeframe, 'start': current_start.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d'), 'limit': 10000, 'feed': 'iex'
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                bars = resp.json().get('bars', [])
                if bars:
                    all_bars.extend(bars)
        except Exception as e:
            pass
        
        current_start = chunk_end
        time.sleep(0.25)
    
    if not all_bars:
        return None
    
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    return df.set_index('timestamp').sort_index()

def add_indicators(df):
    df = df.copy()
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['vwap_slope'] = df['vwap'].diff(20)
    df['vol_mean'] = df['volume'].rolling(20, min_periods=1).mean()
    df['vol_std'] = df['volume'].rolling(20, min_periods=1).std().replace(0, np.nan)
    df['vol_z'] = (df['volume'] - df['vol_mean']) / df['vol_std']
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14, min_periods=1).mean()
    df['body_size'] = (df['close'] - df['open']).abs()
    df['prev_10_high'] = df['high'].rolling(10, min_periods=1).max().shift(1)
    df['prev_10_low'] = df['low'].rolling(10, min_periods=1).min().shift(1)
    df['bull'] = df['close'] > df['open']
    df['bear'] = df['close'] < df['open']
    return df

def generate_signals(df, use_breakout=False):
    df = add_indicators(df)
    signals = []
    
    for i in range(30, len(df) - 1):
        row = df.iloc[i]
        if pd.isna(row['atr']) or pd.isna(row['vol_z']) or row['vol_z'] < 1.8:
            continue
        if row['body_size'] < row['atr'] * 0.3:
            continue
        
        entry_price = df.iloc[i + 1]['open']
        
        # LONG: bull + above VWAP + VWAP rising
        if row['bull'] and row['close'] > row['vwap'] and row['vwap_slope'] > 0:
            if use_breakout and row['close'] <= row['prev_10_high']:
                continue
            signals.append({'direction': 'long', 'entry_price': entry_price, 'idx': i + 1, 'timestamp': df.index[i + 1]})
        
        # SHORT: bear + below VWAP + VWAP falling
        elif row['bear'] and row['close'] < row['vwap'] and row['vwap_slope'] < 0:
            if use_breakout and row['close'] >= row['prev_10_low']:
                continue
            signals.append({'direction': 'short', 'entry_price': entry_price, 'idx': i + 1, 'timestamp': df.index[i + 1]})
    
    return signals

def backtest(df, signals, tp=0.8, sl=0.5, max_bars=20):
    if not signals:
        return None
    
    wins, losses = 0, 0
    total_pnl = 0
    max_streak, curr = 0, 0
    
    for sig in signals:
        idx = sig['idx']
        if idx >= len(df) - 5:
            continue
        
        entry = sig['entry_price']
        direction = sig['direction']
        
        tp_price = entry * (1 + (tp if direction == 'long' else -tp) / 100)
        sl_price = entry * (1 - (sl if direction == 'long' else -sl) / 100)
        
        pnl, win = 0, False
        for j in range(idx + 1, min(idx + max_bars, len(df))):
            bar = df.iloc[j]
            if direction == 'long':
                if bar['low'] <= sl_price:
                    pnl, win = -sl, False
                    break
                if bar['high'] >= tp_price:
                    pnl, win = tp, True
                    break
            else:
                if bar['high'] >= sl_price:
                    pnl, win = -sl, False
                    break
                if bar['low'] <= tp_price:
                    pnl, win = tp, True
                    break
        
        if pnl == 0:
            exit_p = df.iloc[min(idx + max_bars - 1, len(df) - 1)]['close']
            pnl = (exit_p - entry) / entry * 100 if direction == 'long' else (entry - exit_p) / entry * 100
            win = pnl > 0
        
        total_pnl += pnl
        if win:
            wins, curr = wins + 1, 0
        else:
            losses, curr = losses + 1, curr + 1
            max_streak = max(max_streak, curr)
    
    total = wins + losses
    return {
        'trades': total, 'win_rate': wins/total*100 if total else 0,
        'avg_pnl': total_pnl/total if total else 0,
        'total_pnl': total_pnl, 'max_streak': max_streak
    }

def test_symbol(symbol, timeframe, start, end):
    df = fetch_data(symbol, timeframe, start, end)
    if df is None or len(df) < 1000:
        return None
    
    # Baseline (no breakout)
    sigs_base = generate_signals(df, use_breakout=False)
    res_base = backtest(df, sigs_base)
    
    # With breakout filter
    sigs_break = generate_signals(df, use_breakout=True)
    res_break = backtest(df, sigs_break)
    
    return {
        'symbol': symbol,
        'timeframe': timeframe,
        'baseline': res_base,
        'breakout': res_break,
        'baseline_signals': len(sigs_base),
        'breakout_signals': len(sigs_break)
    }

def main():
    print("="*80)
    print("BOOF 24.1 — 50 Symbol Test: Baseline vs Breakout Filter")
    print("6 months | 1m & 5m | TP 0.8% / SL 0.5%")
    print("="*80)
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=180)
    
    results_1m = []
    results_5m = []
    
    for i, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{i}/50] {symbol}")
        
        # 5m test (faster, do first)
        res_5m = test_symbol(symbol, '5Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if res_5m:
            results_5m.append(res_5m)
            b = res_5m['baseline']
            bo = res_5m['breakout']
            if b and bo:
                print(f"  5m: Base {b['trades']}t {b['win_rate']:.1f}% {b['avg_pnl']:+.3f}% | Break {bo['trades']}t {bo['win_rate']:.1f}% {bo['avg_pnl']:+.3f}%")
        
        # 1m test
        res_1m = test_symbol(symbol, '1Min', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if res_1m:
            results_1m.append(res_1m)
            b = res_1m['baseline']
            bo = res_1m['breakout']
            if b and bo:
                print(f"  1m: Base {b['trades']}t {b['win_rate']:.1f}% {b['avg_pnl']:+.3f}% | Break {bo['trades']}t {bo['win_rate']:.1f}% {bo['avg_pnl']:+.3f}%")
    
    # Summary tables
    print("\n" + "="*80)
    print("5MIN SUMMARY — Baseline vs Breakout Filter")
    print("="*80)
    print(f"{'Symbol':<8} {'Base#':>8} {'BaseWR':>8} {'BaseAvg':>10} {'Break#':>8} {'BreakWR':>8} {'BreakAvg':>10} {'Winner':>8}")
    print("-"*80)
    
    winners_base = 0
    winners_break = 0
    
    for r in results_5m:
        b = r['baseline']
        bo = r['breakout']
        if b and bo and b['trades'] > 5 and bo['trades'] > 5:
            winner = "BREAKOUT" if bo['avg_pnl'] > b['avg_pnl'] else "BASELINE"
            if winner == "BREAKOUT":
                winners_break += 1
            else:
                winners_base += 1
            print(f"{r['symbol']:<8} {b['trades']:>8} {b['win_rate']:>7.1f}% {b['avg_pnl']:>+9.3f}% {bo['trades']:>8} {bo['win_rate']:>7.1f}% {bo['avg_pnl']:>+9.3f}% {winner:>8}")
    
    print(f"\nWinner count: Baseline={winners_base}, Breakout={winners_break}")
    
    print("\n" + "="*80)
    print("1MIN SUMMARY — Baseline vs Breakout Filter")
    print("="*80)
    print(f"{'Symbol':<8} {'Base#':>8} {'BaseWR':>8} {'BaseAvg':>10} {'Break#':>8} {'BreakWR':>8} {'BreakAvg':>10} {'Winner':>8}")
    print("-"*80)
    
    winners_base_1m = 0
    winners_break_1m = 0
    
    for r in results_1m:
        b = r['baseline']
        bo = r['breakout']
        if b and bo and b['trades'] > 5 and bo['trades'] > 5:
            winner = "BREAKOUT" if bo['avg_pnl'] > b['avg_pnl'] else "BASELINE"
            if winner == "BREAKOUT":
                winners_break_1m += 1
            else:
                winners_base_1m += 1
            print(f"{r['symbol']:<8} {b['trades']:>8} {b['win_rate']:>7.1f}% {b['avg_pnl']:>+9.3f}% {bo['trades']:>8} {bo['win_rate']:>7.1f}% {bo['avg_pnl']:>+9.3f}% {winner:>8}")
    
    print(f"\nWinner count: Baseline={winners_base_1m}, Breakout={winners_break_1m}")
    
    # Top performers
    print("\n" + "="*80)
    print("TOP 5 PERFORMERS — Baseline 5m")
    print("="*80)
    valid_5m = [(r['symbol'], r['baseline']) for r in results_5m if r['baseline'] and r['baseline']['trades'] > 5]
    top_5m = sorted(valid_5m, key=lambda x: x[1]['avg_pnl'], reverse=True)[:5]
    for sym, res in top_5m:
        print(f"  {sym}: {res['avg_pnl']:+.3f}% avg, {res['win_rate']:.1f}% WR, {res['trades']} trades")
    
    print("\nTOP 5 PERFORMERS — Breakout 5m")
    print("="*80)
    valid_break = [(r['symbol'], r['breakout']) for r in results_5m if r['breakout'] and r['breakout']['trades'] > 5]
    top_break = sorted(valid_break, key=lambda x: x[1]['avg_pnl'], reverse=True)[:5]
    for sym, res in top_break:
        print(f"  {sym}: {res['avg_pnl']:+.3f}% avg, {res['win_rate']:.1f}% WR, {res['trades']} trades")
    
    # Save results
    date_str = datetime.now().strftime('%Y%m%d')
    df_5m = pd.DataFrame([{'symbol': r['symbol'], 'timeframe': '5m', 
                          'baseline_trades': r['baseline']['trades'] if r['baseline'] else 0,
                          'baseline_avg': r['baseline']['avg_pnl'] if r['baseline'] else 0,
                          'breakout_trades': r['breakout']['trades'] if r['breakout'] else 0,
                          'breakout_avg': r['breakout']['avg_pnl'] if r['breakout'] else 0} for r in results_5m])
    df_5m.to_csv(f'boof24_50symbols_5m_{date_str}.csv', index=False)
    print(f"\n[SAVED] boof24_50symbols_5m_{date_str}.csv")

if __name__ == '__main__':
    main()
