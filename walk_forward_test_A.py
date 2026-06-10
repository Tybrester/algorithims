"""
Walk-Forward Test: Test A Filter (Slack < 0.8 AND RVOL 1.2-3.0)
Rolling 2-month train / 1-month test
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Alpaca API
ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
BASE_URL = 'https://paper-api.alpaca.markets'
DATA_URL = 'https://data.alpaca.markets'

# Config - Test A Filter
TP_PCT = 0.0005  # +0.05%
SL_PCT = 0.0003  # -0.03%
SLACK_MAX = 0.8
RVOL_MIN = 1.2
RVOL_MAX = 3.0

SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']

# Walk-forward periods
PERIODS = [
    {'name': 'Q1 Period 1', 'train_start': '2026-01-01', 'train_end': '2026-02-28', 'test_start': '2026-03-01', 'test_end': '2026-03-31'},
    {'name': 'Q1 Period 2', 'train_start': '2026-02-01', 'train_end': '2026-03-31', 'test_start': '2026-04-01', 'test_end': '2026-04-30'},
    {'name': 'Q2 Period 1', 'train_start': '2026-03-01', 'train_end': '2026-04-30', 'test_start': '2026-05-01', 'test_end': '2026-05-31'},
]

# Boof 22 Config
BOOF22_CONFIG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'MAX_HOLD': 30,
    'CLUSTER_MERGE': 0.5, 'SR_DIST_MAX': 1.0,
    'SR_STRENGTH_MIN': 2, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6, 'RVOL_MIN': 0.8,
}

# Boof 23 Config  
BOOF23_CONFIG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'MAX_HOLD': 30,
    'CLUSTER_MERGE': 0.5, 'SR_DIST_MAX': 1.0,
    'SR_STRENGTH_MIN': 2, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.4, 'RVOL_MIN': 0.8,
    'ZZ_PROX_BARS': 30, 'USE_ENGULF': False,
}

SYMBOL_PARAMS = {
    'AAPL': {'atr_mult': 0.6, 'vol_mult': 1.2},
    'NVDA': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'META': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'GOOGL': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'AMD': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'TSLA': {'atr_mult': 0.8, 'vol_mult': 1.4},
    'AMZN': {'atr_mult': 0.6, 'vol_mult': 1.2},
    'MSFT': {'atr_mult': 0.6, 'vol_mult': 1.2},
    'NFLX': {'atr_mult': 0.7, 'vol_mult': 1.3},
    'CRM': {'atr_mult': 0.6, 'vol_mult': 1.2},
}

def fetch_alpaca_data(symbol, start, end):
    """Fetch 1-min bars from Alpaca"""
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
    df = df.set_index('timestamp').sort_index()
    return df

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def calc_rvol(df, idx, vol_sma):
    if idx < 20 or idx >= len(df): return 1.0
    return df.iloc[idx]['volume'] / vol_sma.iloc[idx] if vol_sma.iloc[idx] > 0 else 1.0

def backtest_with_filter(df, symbol, strategy='boof22'):
    """Backtest with Test A filter applied"""
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3})
    atr_mult = params['atr_mult']
    config = BOOF22_CONFIG if strategy == 'boof22' else BOOF23_CONFIG
    
    df['atr'] = compute_atr(df)
    df['vol_sma'] = compute_vol_sma(df)
    
    trades = []
    in_trade = False
    
    for i in range(50, len(df) - 1):
        if in_trade:
            exit_bar = min(i + config['MAX_HOLD'], len(df) - 1)
            for j in range(i, exit_bar + 1):
                if direction == 'long':
                    if df.iloc[j]['high'] >= tp_price: exit_type = 'tp'; exit_pnl = TP_PCT; break
                    if df.iloc[j]['low'] <= sl_price: exit_type = 'sl'; exit_pnl = -SL_PCT; break
                else:
                    if df.iloc[j]['low'] <= tp_price: exit_type = 'tp'; exit_pnl = TP_PCT; break
                    if df.iloc[j]['high'] >= sl_price: exit_type = 'sl'; exit_pnl = -SL_PCT; break
            else: 
                exit_type = 'time'
                exit_pnl = (df.iloc[exit_bar]['close'] - entry_price) / entry_price * (1 if direction == 'long' else -1)
            
            # Calculate slack and rvol at entry
            rvol = calc_rvol(df, entry_idx, df['vol_sma'])
            
            # Apply Test A filter
            if entry_slack < SLACK_MAX and RVOL_MIN <= rvol <= RVOL_MAX:
                trades.append({
                    'symbol': symbol, 'direction': direction, 'entry': entry_price,
                    'exit': df.iloc[exit_bar]['close'], 'exit_type': exit_type,
                    'pnl_pct': exit_pnl, 'slack': entry_slack, 'rvol': rvol,
                    'strategy': strategy
                })
            in_trade = False
            continue
        
        if df.iloc[i]['atr'] == 0: continue
        
        # Fractal detection
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        left_highs, right_highs = highs[:3], highs[4:]
        left_lows, right_lows = lows[:3], lows[4:]
        
        fractal_peak = (highs[3] > left_highs.max()) and (highs[3] > right_highs.max())
        fractal_trough = (lows[3] < left_lows.min()) and (lows[3] < right_lows.min())
        
        atr_rejected_peak = closes[3] < highs[3] - df.iloc[i]['atr'] * atr_mult
        atr_bounced_trough = closes[3] > lows[3] + df.iloc[i]['atr'] * atr_mult
        
        peak_slack = (highs[3] - closes[3]) / df.iloc[i]['atr'] if df.iloc[i]['atr'] > 0 else 0
        trough_slack = (closes[3] - lows[3]) / df.iloc[i]['atr'] if df.iloc[i]['atr'] > 0 else 0
        
        is_peak = fractal_peak and atr_rejected_peak
        is_trough = fractal_trough and atr_bounced_trough
        
        # Boof 23 trend filter
        if strategy == 'boof23':
            trend = 'up' if df.iloc[i]['close'] > df.iloc[i-20:i]['close'].mean() else 'down'
            is_peak = is_peak and trend == 'up'
            is_trough = is_trough and trend == 'down'
        
        if is_peak:
            entry_price = df.iloc[i + 1]['open']
            direction = 'short'
            tp_price = entry_price * (1 - TP_PCT)
            sl_price = entry_price * (1 + SL_PCT)
            entry_idx = i + 1
            entry_slack = peak_slack
            in_trade = True
        elif is_trough:
            entry_price = df.iloc[i + 1]['open']
            direction = 'long'
            tp_price = entry_price * (1 + TP_PCT)
            sl_price = entry_price * (1 - SL_PCT)
            entry_idx = i + 1
            entry_slack = trough_slack
            in_trade = True
    
    return trades

def analyze_trades(trades):
    if not trades: return {'trades': 0, 'win_rate': 0, 'profit_factor': 0, 'max_dd': 0, 'net_pnl': 0}
    df = pd.DataFrame(trades)
    wins = df[df['pnl_pct'] > 0]
    losses = df[df['pnl_pct'] <= 0]
    
    gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0.0001
    
    cumulative = df['pnl_pct'].cumsum()
    running_max = cumulative.expanding().max()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()
    
    return {
        'trades': len(df),
        'win_rate': len(wins) / len(df) * 100 if len(df) > 0 else 0,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else 0,
        'max_dd': max_dd * 100,
        'net_pnl': df['pnl_pct'].sum() * 100
    }

def run_walk_forward():
    print("\n" + "="*80)
    print("WALK-FORWARD TEST: Test A Filter (Slack < 0.8 AND RVOL 1.2-3.0)")
    print("="*80)
    print("Training: 2 months | Testing: 1 month | Rolling window")
    print("="*80 + "\n")
    
    all_results = []
    
    for period in PERIODS:
        print(f"\n{'='*80}")
        print(f"PERIOD: {period['name']}")
        print(f"Training: {period['train_start']} to {period['train_end']}")
        print(f"Testing:  {period['test_start']} to {period['test_end']}")
        print(f"{'='*80}\n")
        
        # Training phase
        train_trades_22 = []
        train_trades_23 = []
        
        print("[TRAINING PHASE]")
        for symbol in SYMBOLS:
            df = fetch_alpaca_data(symbol, period['train_start'], period['train_end'])
            if df is None or len(df) < 1000:
                print(f"[SKIP] {symbol} - insufficient training data")
                continue
            print(f"[Train] {symbol}: {len(df)} bars")
            
            trades22 = backtest_with_filter(df, symbol, 'boof22')
            trades23 = backtest_with_filter(df, symbol, 'boof23')
            
            train_trades_22.extend(trades22)
            train_trades_23.extend(trades23)
        
        train_stats_22 = analyze_trades(train_trades_22)
        train_stats_23 = analyze_trades(train_trades_23)
        
        print(f"\n[Training Results - Boof 22]")
        print(f"  Trades: {train_stats_22['trades']:.0f} | WR: {train_stats_22['win_rate']:.1f}% | PF: {train_stats_22['profit_factor']:.2f} | P&L: {train_stats_22['net_pnl']:.2f}%")
        print(f"\n[Training Results - Boof 23]")
        print(f"  Trades: {train_stats_23['trades']:.0f} | WR: {train_stats_23['win_rate']:.1f}% | PF: {train_stats_23['profit_factor']:.2f} | P&L: {train_stats_23['net_pnl']:.2f}%")
        
        # Testing phase
        test_trades_22 = []
        test_trades_23 = []
        
        print("\n[TESTING PHASE]")
        for symbol in SYMBOLS:
            df = fetch_alpaca_data(symbol, period['test_start'], period['test_end'])
            if df is None or len(df) < 500:
                print(f"[SKIP] {symbol} - insufficient test data")
                continue
            print(f"[Test] {symbol}: {len(df)} bars")
            
            trades22 = backtest_with_filter(df, symbol, 'boof22')
            trades23 = backtest_with_filter(df, symbol, 'boof23')
            
            test_trades_22.extend(trades22)
            test_trades_23.extend(trades23)
        
        test_stats_22 = analyze_trades(test_trades_22)
        test_stats_23 = analyze_trades(test_trades_23)
        
        print(f"\n[Out-of-Sample Results - Boof 22]")
        print(f"  Trades: {test_stats_22['trades']:.0f} | WR: {test_stats_22['win_rate']:.1f}% | PF: {test_stats_22['profit_factor']:.2f} | P&L: {test_stats_22['net_pnl']:.2f}%")
        print(f"\n[Out-of-Sample Results - Boof 23]")
        print(f"  Trades: {test_stats_23['trades']:.0f} | WR: {test_stats_23['win_rate']:.1f}% | PF: {test_stats_23['profit_factor']:.2f} | P&L: {test_stats_23['net_pnl']:.2f}%")
        
        # Calculate degradation
        print(f"\n[ROBUSTNESS CHECK - Performance Degradation]")
        
        if train_stats_22['win_rate'] > 0:
            wr_degradation_22 = (test_stats_22['win_rate'] - train_stats_22['win_rate']) / train_stats_22['win_rate'] * 100
            pf_degradation_22 = (test_stats_22['profit_factor'] - train_stats_22['profit_factor']) / train_stats_22['profit_factor'] * 100 if train_stats_22['profit_factor'] > 0 else 0
            print(f"Boof 22: WR change {wr_degradation_22:+.1f}% | PF change {pf_degradation_22:+.1f}%")
        
        if train_stats_23['win_rate'] > 0:
            wr_degradation_23 = (test_stats_23['win_rate'] - train_stats_23['win_rate']) / train_stats_23['win_rate'] * 100
            pf_degradation_23 = (test_stats_23['profit_factor'] - train_stats_23['profit_factor']) / train_stats_23['profit_factor'] * 100 if train_stats_23['profit_factor'] > 0 else 0
            print(f"Boof 23: WR change {wr_degradation_23:+.1f}% | PF change {pf_degradation_23:+.1f}%")
        
        all_results.append({
            'period': period['name'],
            'train_22': train_stats_22, 'test_22': test_stats_22,
            'train_23': train_stats_23, 'test_23': test_stats_23
        })
    
    # Final summary
    print("\n" + "="*80)
    print("WALK-FORWARD SUMMARY - ALL PERIODS")
    print("="*80)
    
    print(f"\n{'Period':<20} {'Strategy':<10} {'Phase':<10} {'Trades':<8} {'WR%':<8} {'PF':<8} {'P&L%':<10}")
    print("-"*80)
    
    for r in all_results:
        print(f"{r['period']:<20} {'Boof 22':<10} {'Train':<10} {r['train_22']['trades']:<8.0f} {r['train_22']['win_rate']:<8.1f} {r['train_22']['profit_factor']:<8.2f} {r['train_22']['net_pnl']:<10.2f}")
        print(f"{'':<20} {'Boof 22':<10} {'Test':<10} {r['test_22']['trades']:<8.0f} {r['test_22']['win_rate']:<8.1f} {r['test_22']['profit_factor']:<8.2f} {r['test_22']['net_pnl']:<10.2f}")
        print(f"{r['period']:<20} {'Boof 23':<10} {'Train':<10} {r['train_23']['trades']:<8.0f} {r['train_23']['win_rate']:<8.1f} {r['train_23']['profit_factor']:<8.2f} {r['train_23']['net_pnl']:<10.2f}")
        print(f"{'':<20} {'Boof 23':<10} {'Test':<10} {r['test_23']['trades']:<8.0f} {r['test_23']['win_rate']:<8.1f} {r['test_23']['profit_factor']:<8.2f} {r['test_23']['net_pnl']:<10.2f}")
        print("-"*80)
    
    print("\n" + "="*80)
    print("VALIDATION CRITERIA")
    print("="*80)
    print("✓ Pass: <30% degradation from train to test")
    print("✓ Pass: All test periods profitable")
    print("✓ Pass: Win rate >70% in out-of-sample")
    print("="*80)

if __name__ == '__main__':
    run_walk_forward()
