"""
6-Month Micro-Move Backtest
Full dataset: Boof 22/23 with micro-move filters
Tests: 0.3%/5min, 0.5%/10min, 0.5%/15min, 0.7%/20min
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

# Alpaca API
ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
DATA_URL = 'https://data.alpaca.markets'

SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']
SLACK_MAX = 0.8

# Micro-move configs
MICRO_CONFIGS = {
    'micro_3_5': {'move_pct': 0.30, 'max_bars': 5, 'name': '0.3% / 5 min'},
    'micro_5_10': {'move_pct': 0.50, 'max_bars': 10, 'name': '0.5% / 10 min'},
    'micro_5_15': {'move_pct': 0.50, 'max_bars': 15, 'name': '0.5% / 15 min'},
    'micro_7_20': {'move_pct': 0.70, 'max_bars': 20, 'name': '0.7% / 20 min'},
}

def fetch_data(symbol, start, end):
    """Fetch 1-min bars in chunks"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    chunks = 0
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=30), end_dt)
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
                    chunks += 1
            else:
                print(f"  [WARN] Status {resp.status_code}")
        except Exception as e:
            print(f"  [ERROR] {symbol}: {e}")
        
        current_start = chunk_end
        time.sleep(0.5)  # Rate limit
    
    if not all_bars:
        return None
    
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    return df.set_index('timestamp').sort_index()

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def get_boof_signals(df):
    """Boof 22/23 signals with Slack < 0.8"""
    signals = []
    atr = compute_atr(df)
    vol_sma = compute_vol_sma(df)
    
    for i in range(50, len(df) - 1):
        if atr.iloc[i] == 0 or vol_sma.iloc[i] == 0:
            continue
        
        current_vol = df.iloc[i]['volume']
        if current_vol < vol_sma.iloc[i]:
            continue
        
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        left_highs, right_highs = highs[:3], highs[4:]
        left_lows, right_lows = lows[:3], lows[4:]
        
        fractal_peak = (highs[3] > left_highs.max()) and (highs[3] > right_highs.max())
        fractal_trough = (lows[3] < left_lows.min()) and (lows[3] < right_lows.min())
        
        atr_rejected_peak = closes[3] < highs[3] - atr.iloc[i] * 0.6
        atr_bounced_trough = closes[3] > lows[3] + atr.iloc[i] * 0.6
        
        peak_slack = (highs[3] - closes[3]) / atr.iloc[i] if atr.iloc[i] > 0 else 1
        trough_slack = (closes[3] - lows[3]) / atr.iloc[i] if atr.iloc[i] > 0 else 1
        
        if fractal_peak and atr_rejected_peak and peak_slack < SLACK_MAX:
            signals.append({
                'bar': i + 1,
                'direction': 'short',
                'slack': peak_slack,
                'entry_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
        elif fractal_trough and atr_bounced_trough and trough_slack < SLACK_MAX:
            signals.append({
                'bar': i + 1,
                'direction': 'long',
                'slack': trough_slack,
                'entry_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
    
    return signals

def test_micro_move(df, signal, move_pct, max_bars):
    """Test if price hits ±move_pct within max_bars"""
    entry_bar = signal['bar']
    if entry_bar >= len(df):
        return None
    
    entry_price = signal['entry_price']
    direction = signal['direction']
    
    for i in range(entry_bar, min(entry_bar + max_bars, len(df))):
        high = df.iloc[i]['high']
        low = df.iloc[i]['low']
        
        up_move = (high - entry_price) / entry_price * 100
        down_move = (low - entry_price) / entry_price * 100
        
        if direction == 'long':
            if up_move >= move_pct:
                return {'hit': True, 'pnl': move_pct, 'win': True, 'bars': i - entry_bar}
            if down_move <= -move_pct:
                return {'hit': True, 'pnl': -move_pct, 'win': False, 'bars': i - entry_bar}
        else:
            if down_move <= -move_pct:
                return {'hit': True, 'pnl': move_pct, 'win': True, 'bars': i - entry_bar}
            if up_move >= move_pct:
                return {'hit': True, 'pnl': -move_pct, 'win': False, 'bars': i - entry_bar}
    
    # Time exit
    exit_price = df.iloc[min(entry_bar + max_bars - 1, len(df) - 1)]['close']
    actual_move = (exit_price - entry_price) / entry_price * 100
    return {'hit': False, 'pnl': actual_move if direction == 'long' else -actual_move, 'win': False, 'bars': max_bars}

def main():
    print("="*80)
    print("6-MONTH MICRO-MOVE BACKTEST")
    print("Boof 22/23 + Slack < 0.8")
    print("="*80)
    print(f"Symbols: {SYMBOLS}")
    print(f"Period: 6 months")
    print(f"Micro-Move Tests: {list(MICRO_CONFIGS.keys())}")
    print("="*80)
    
    # 6 months back from today
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)
    
    print(f"\nPeriod: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    all_results = []
    
    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"[{symbol}] Backtesting...")
        print(f"{'='*60}")
        
        df = fetch_data(symbol, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        if df is None:
            print(f"  [SKIP] No data fetched")
            continue
        
        if len(df) < 5000:
            print(f"  [SKIP] Only {len(df)} bars, need 6 months")
            continue
        
        print(f"  Data: {len(df)} bars ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
        
        signals = get_boof_signals(df)
        print(f"  Signals: {len(signals)}")
        
        if not signals:
            continue
        
        # Test each signal with each micro-move config
        for signal in signals:
            for config_key, config in MICRO_CONFIGS.items():
                result = test_micro_move(df, signal, config['move_pct'], config['max_bars'])
                
                all_results.append({
                    'symbol': symbol,
                    'direction': signal['direction'],
                    'slack': signal['slack'],
                    'timestamp': signal['timestamp'],
                    'config': config_key,
                    'config_name': config['name'],
                    'hit': result['hit'],
                    'pnl': result['pnl'],
                    'win': result['win'],
                    'bars': result['bars']
                })
        
        print(f"  Processed: {len(signals)} signals x {len(MICRO_CONFIGS)} configs = {len(signals) * len(MICRO_CONFIGS)} results")
    
    if not all_results:
        print("\n[ERROR] No results captured")
        return
    
    df_results = pd.DataFrame(all_results)
    
    # Analysis
    print("\n" + "="*80)
    print("6-MONTH RESULTS BY MICRO-MOVE CONFIG")
    print("="*80)
    
    summary_rows = []
    
    for config_key in MICRO_CONFIGS.keys():
        config_results = df_results[df_results['config'] == config_key]
        
        if len(config_results) == 0:
            continue
        
        total = len(config_results)
        hits = config_results['hit'].sum()
        wins = config_results['win'].sum()
        
        hit_rate = hits / total * 100 if total > 0 else 0
        win_rate = wins / hits * 100 if hits > 0 else 0
        
        # Calculate expectancy
        hit_pct = hit_rate / 100
        win_pct = win_rate / 100 if hits > 0 else 0
        avg_win = config_results[config_results['win'] == True]['pnl'].mean() if wins > 0 else 0
        avg_loss = abs(config_results[config_results['win'] == False]['pnl'].mean()) if (hits - wins) > 0 else 0
        
        # Expectancy formula: (Hit% * (Win% * Target - Loss% * Target)) + (NoHit% * AvgTimeExit)
        time_exits = config_results[config_results['hit'] == False]
        avg_time_pnl = time_exits['pnl'].mean() if len(time_exits) > 0 else 0
        
        expectancy = (hit_pct * ((win_pct * avg_win) - ((1 - win_pct) * avg_loss))) + ((1 - hit_pct) * avg_time_pnl)
        
        avg_hold = config_results['bars'].mean()
        avg_slack = config_results['slack'].mean()
        
        summary_rows.append({
            'config': MICRO_CONFIGS[config_key]['name'],
            'trades': total,
            'hit_rate': hit_rate,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_time_pnl': avg_time_pnl,
            'expectancy': expectancy,
            'avg_hold': avg_hold,
            'avg_slack': avg_slack
        })
        
        print(f"\n{MICRO_CONFIGS[config_key]['name']}")
        print(f"  Trades: {total}")
        print(f"  Hit Rate: {hit_rate:.1f}%")
        print(f"  Win Rate (of hits): {win_rate:.1f}%")
        print(f"  Avg Win: +{avg_win:.2f}% | Avg Loss: -{avg_loss:.2f}%")
        print(f"  Avg Time Exit P&L: {avg_time_pnl:+.3f}%")
        print(f"  Expectancy: {expectancy:+.4f}%")
        print(f"  Avg Hold: {avg_hold:.1f} bars")
        print(f"  Avg Slack: {avg_slack:.3f}")
    
    # Summary table
    print("\n" + "="*80)
    print("COMPARISON TABLE")
    print("="*80)
    print(f"{'Config':<20} {'Trades':>10} {'Hit%':>8} {'Win%':>8} {'Expect%':>12} {'Hold':>8}")
    print("-"*80)
    
    for row in summary_rows:
        print(f"{row['config']:<20} {row['trades']:>10} {row['hit_rate']:>7.1f}% {row['win_rate']:>7.1f}% {row['expectancy']:>+11.4f}% {row['avg_hold']:>7.1f}m")
    
    # Monthly breakdown
    print("\n" + "="*80)
    print("MONTHLY BREAKDOWN (Best Config)")
    print("="*80)
    
    # Find best config by expectancy
    best_config = max(summary_rows, key=lambda x: x['expectancy'])['config']
    print(f"Best Config: {best_config}")
    
    best_results = df_results[df_results['config_name'] == best_config].copy()
    best_results['month'] = pd.to_datetime(best_results['timestamp']).dt.to_period('M')
    
    for month in sorted(best_results['month'].unique()):
        month_data = best_results[best_results['month'] == month]
        month_hits = month_data['hit'].sum()
        month_wins = month_data['win'].sum()
        month_pnl = month_data['pnl'].sum()
        
        print(f"  {month}: {len(month_data)} trades, {month_hits} hits ({month_wins} wins), P&L: {month_pnl:+.2f}%")
    
    # Save results
    date_str = datetime.now().strftime('%Y%m%d')
    df_results.to_csv(f'6mo_micro_backtest_{date_str}.csv', index=False)
    print(f"\n[SAVED] 6mo_micro_backtest_{date_str}.csv ({len(df_results)} rows)")
    
    # Per-symbol breakdown
    print("\n" + "="*80)
    print("PER-SYMBOL SUMMARY")
    print("="*80)
    
    symbol_summary = df_results.groupby(['symbol', 'config']).agg({
        'hit': 'sum',
        'win': 'sum',
        'pnl': 'mean',
        'slack': 'mean'
    }).reset_index()
    
    for symbol in SYMBOLS[:5]:
        sym_data = symbol_summary[symbol_summary['symbol'] == symbol]
        if len(sym_data) == 0:
            continue
        
        print(f"\n{symbol}:")
        for _, row in sym_data.iterrows():
            total = len(df_results[(df_results['symbol'] == symbol) & (df_results['config'] == row['config'])])
            print(f"  {row['config']}: {total} trades, {row['hit']} hits, P&L: {row['pnl']:+.3f}%, Slack: {row['slack']:.3f}")

if __name__ == '__main__':
    main()
