"""
Boof 22/23 Backtest - Micro-Move Analysis
Tests: 0.3%/5min, 0.5%/10-15min, 0.7%/20min
Compare: Win rate, expectancy, trade frequency
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Alpaca API
ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
DATA_URL = 'https://data.alpaca.markets'

# Config
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']
SLACK_MAX = 0.8

# Micro-move filter configs
MICRO_CONFIGS = {
    'micro_3_5': {'move_pct': 0.30, 'max_bars': 5, 'name': '0.3% / 5 min'},
    'micro_5_10': {'move_pct': 0.50, 'max_bars': 10, 'name': '0.5% / 10 min'},
    'micro_5_15': {'move_pct': 0.50, 'max_bars': 15, 'name': '0.5% / 15 min'},
    'micro_7_20': {'move_pct': 0.70, 'max_bars': 20, 'name': '0.7% / 20 min'},
}

def fetch_data(symbol, start, end):
    """Fetch 1-min bars"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
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
                if bars: all_bars.extend(bars)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")
        current_start = chunk_end
    
    if not all_bars: return None
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
    """Boof 22/23 hybrid with Slack < 0.8"""
    signals = []
    atr = compute_atr(df)
    vol_sma = compute_vol_sma(df)
    
    for i in range(50, len(df) - 1):
        if atr.iloc[i] == 0 or vol_sma.iloc[i] == 0: continue
        
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

def analyze_micro_move(df, signal, move_pct, max_bars):
    """
    Check if price reached ±move_pct within max_bars.
    For LONG: check if price went UP by move_pct (profit) or DOWN by move_pct (loss)
    For SHORT: check if price went DOWN by move_pct (profit) or UP by move_pct (loss)
    
    Returns: success (bool), hold_bars, pnl_pct
    """
    entry_bar = signal['bar']
    if entry_bar >= len(df): return False, 0, 0
    
    entry_price = signal['entry_price']
    direction = signal['direction']
    
    # Track price over max_bars
    for i in range(entry_bar, min(entry_bar + max_bars, len(df))):
        high = df.iloc[i]['high']
        low = df.iloc[i]['low']
        
        # Calculate moves from entry
        up_move = (high - entry_price) / entry_price * 100
        down_move = (low - entry_price) / entry_price * 100
        
        if direction == 'long':
            # Win: price went UP by target
            if up_move >= move_pct:
                return True, i - entry_bar, move_pct
            # Loss: price went DOWN by target
            if down_move <= -move_pct:
                return True, i - entry_bar, -move_pct
        else:  # short
            # Win: price went DOWN by target
            if down_move <= -move_pct:
                return True, i - entry_bar, move_pct
            # Loss: price went UP by target
            if up_move >= move_pct:
                return True, i - entry_bar, -move_pct
    
    # Didn't hit target - calculate actual move at end of window
    exit_price = df.iloc[min(entry_bar + max_bars - 1, len(df) - 1)]['close']
    actual_move = (exit_price - entry_price) / entry_price * 100
    
    if direction == 'long':
        return False, max_bars, actual_move
    else:
        return False, max_bars, -actual_move

def run_backtest():
    print("="*80)
    print("BOOF 22/23 MICRO-MOVE BACKTEST")
    print("="*80)
    print(f"Symbols: {SYMBOLS}")
    print(f"Slack Filter: < {SLACK_MAX}")
    print("="*80)
    print("\nMicro-Move Configs:")
    for key, cfg in MICRO_CONFIGS.items():
        print(f"  {key}: {cfg['name']}")
    print("="*80)
    
    # 1 week of data
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    # Collect all trades
    all_trades = []
    
    for symbol in SYMBOLS:
        print(f"\n[{symbol}] Fetching...")
        df = fetch_data(symbol, start, end)
        if df is None or len(df) < 1000:
            print(f"  [SKIP] Insufficient data")
            continue
        
        signals = get_boof_signals(df)
        print(f"  Data: {len(df)} bars | Signals: {len(signals)}")
        
        if not signals:
            continue
        
        # Analyze each signal for each micro-move config
        for signal in signals:
            trade_data = {
                'symbol': symbol,
                'direction': signal['direction'],
                'slack': signal['slack'],
                'timestamp': signal['timestamp'],
                'entry_price': signal['entry_price']
            }
            
            # Test each micro-move config
            for config_key, config in MICRO_CONFIGS.items():
                success, hold_bars, pnl = analyze_micro_move(
                    df, signal, config['move_pct'], config['max_bars']
                )
                trade_data[f'{config_key}_hit'] = success
                trade_data[f'{config_key}_bars'] = hold_bars
                trade_data[f'{config_key}_pnl'] = pnl
                trade_data[f'{config_key}_win'] = pnl > 0
            
            all_trades.append(trade_data)
    
    if not all_trades:
        print("\n[ERROR] No trades captured")
        return
    
    df_all = pd.DataFrame(all_trades)
    
    # Step 3: Compare results
    print("\n" + "="*80)
    print("STEP 1: ALL TRADES (Baseline)")
    print("="*80)
    print(f"Total Signals: {len(df_all)}")
    print(f"Long: {len(df_all[df_all['direction'] == 'long'])}")
    print(f"Short: {len(df_all[df_all['direction'] == 'short'])}")
    print(f"Avg Slack: {df_all['slack'].mean():.3f}")
    
    print("\n" + "="*80)
    print("STEP 2 & 3: MICRO-MOVE COMPARISON")
    print("="*80)
    
    results = []
    for config_key, config in MICRO_CONFIGS.items():
        hit_col = f'{config_key}_hit'
        pnl_col = f'{config_key}_pnl'
        win_col = f'{config_key}_win'
        bars_col = f'{config_key}_bars'
        
        # Filter trades that hit the target
        hit_trades = df_all[df_all[hit_col] == True]
        total_trades = len(hit_trades)
        
        if total_trades == 0:
            continue
        
        wins = hit_trades[hit_trades[win_col] == True]
        losses = hit_trades[hit_trades[win_col] == False]
        
        win_rate = len(wins) / total_trades * 100
        
        # Expectancy = (Win% × Avg Win) + (Loss% × Avg Loss)
        avg_win = wins[pnl_col].mean() if len(wins) > 0 else 0
        avg_loss = losses[pnl_col].mean() if len(losses) > 0 else 0
        
        win_pct = len(wins) / total_trades
        loss_pct = len(losses) / total_trades
        
        expectancy = (win_pct * avg_win) + (loss_pct * avg_loss)
        
        # Frequency: % of all signals that hit this target
        frequency = total_trades / len(df_all) * 100
        
        avg_hold = hit_trades[bars_col].mean()
        
        results.append({
            'config': config['name'],
            'trades': total_trades,
            'frequency': frequency,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'expectancy': expectancy,
            'avg_hold': avg_hold
        })
        
        print(f"\n{config['name']}")
        print(f"  Trades: {total_trades} ({frequency:.1f}% of signals)")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg Win: +{avg_win:.2f}% | Avg Loss: {avg_loss:.2f}%")
        print(f"  Expectancy: {expectancy:.2f}%")
        print(f"  Avg Hold: {avg_hold:.1f} min")
    
    # Summary table
    print("\n" + "="*80)
    print("COMPARISON TABLE")
    print("="*80)
    print(f"{'Config':<20} {'Trades':>8} {'Freq%':>8} {'WR%':>8} {'Expect%':>10} {'Hold':>8}")
    print("-"*80)
    for r in results:
        print(f"{r['config']:<20} {r['trades']:>8} {r['frequency']:>7.1f}% {r['win_rate']:>7.1f}% {r['expectancy']:>9.2f}% {r['avg_hold']:>7.1f}m")
    
    # Save results
    date_str = datetime.now().strftime('%Y%m%d')
    df_all.to_csv(f'micro_move_trades_{date_str}.csv', index=False)
    print(f"\n[SAVED] micro_move_trades_{date_str}.csv")

if __name__ == '__main__':
    run_backtest()
