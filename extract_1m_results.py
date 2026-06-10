"""
Extract 1m results from the 50 symbol test and save to CSV
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

def fetch_data(symbol, start, end):
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    chunk_size = 30
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=chunk_size), end_dt)
        params = {
            'timeframe': '1Min', 'start': current_start.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d'), 'limit': 10000, 'feed': 'iex'
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                bars = resp.json().get('bars', [])
                if bars:
                    all_bars.extend(bars)
        except:
            pass
        current_start = chunk_end
        time.sleep(0.15)
    
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
        
        if row['bull'] and row['close'] > row['vwap'] and row['vwap_slope'] > 0:
            if use_breakout and row['close'] <= row['prev_10_high']:
                continue
            signals.append({'direction': 'long', 'entry_price': entry_price, 'idx': i + 1})
        elif row['bear'] and row['close'] < row['vwap'] and row['vwap_slope'] < 0:
            if use_breakout and row['close'] >= row['prev_10_low']:
                continue
            signals.append({'direction': 'short', 'entry_price': entry_price, 'idx': i + 1})
    
    return signals

def backtest(df, signals, tp=0.8, sl=0.5, max_bars=20):
    if not signals:
        return None
    
    wins, losses, total_pnl = 0, 0, 0
    
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
            wins += 1
        else:
            losses += 1
    
    total = wins + losses
    return {'trades': total, 'win_rate': wins/total*100 if total else 0, 'avg_pnl': total_pnl/total if total else 0}

def main():
    print("Extracting 1m results for 50 symbols...")
    
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=180)
    
    results = []
    
    for i, symbol in enumerate(SYMBOLS, 1):
        print(f"[{i}/50] {symbol}")
        df = fetch_data(symbol, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is None or len(df) < 5000:
            print(f"  No data")
            continue
        
        sigs_base = generate_signals(df, use_breakout=False)
        res_base = backtest(df, sigs_base)
        
        sigs_break = generate_signals(df, use_breakout=True)
        res_break = backtest(df, sigs_break)
        
        if res_base and res_break:
            print(f"  Base {res_base['trades']}t {res_base['win_rate']:.1f}% {res_base['avg_pnl']:+.3f}% | Break {res_break['trades']}t {res_break['win_rate']:.1f}% {res_break['avg_pnl']:+.3f}%")
            results.append({
                'symbol': symbol,
                'baseline_trades': res_base['trades'],
                'baseline_wr': res_base['win_rate'],
                'baseline_avg': res_base['avg_pnl'],
                'breakout_trades': res_break['trades'],
                'breakout_wr': res_break['win_rate'],
                'breakout_avg': res_break['avg_pnl']
            })
    
    # Save
    df_out = pd.DataFrame(results)
    date_str = datetime.now().strftime('%Y%m%d')
    df_out.to_csv(f'boof24_50symbols_1m_{date_str}.csv', index=False)
    print(f"\n[SAVED] boof24_50symbols_1m_{date_str}.csv")
    
    # Quick summary
    print("\n" + "="*70)
    print("1MIN SUMMARY")
    print("="*70)
    print(f"{'Symbol':<8} {'Base#':>8} {'BaseWR':>8} {'BaseAvg':>10} {'Break#':>8} {'BreakWR':>8} {'BreakAvg':>10}")
    print("-"*70)
    
    for r in results:
        print(f"{r['symbol']:<8} {r['baseline_trades']:>8} {r['baseline_wr']:>7.1f}% {r['baseline_avg']:>+9.3f}% {r['breakout_trades']:>8} {r['breakout_wr']:>7.1f}% {r['breakout_avg']:>+9.3f}%")
    
    # Winners
    base_wins = sum(1 for r in results if r['baseline_avg'] > r['breakout_avg'])
    break_wins = len(results) - base_wins
    print(f"\nWinner count: Baseline={base_wins}, Breakout={break_wins}")

if __name__ == '__main__':
    main()
