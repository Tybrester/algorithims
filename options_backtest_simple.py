"""
Simple Options Backtest - 1DTE P&L from Actual Stock Moves
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
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
SLACK_MAX = 0.8

# 1DTE ATM Option Model
# For 1DTE ATM options: option move ≈ 15-25x the stock move (gamma)
OPTION_LEVERAGE = 20  # 1% stock move = 20% option move
OPTION_PRICE = 2.00     # $2.00 typical 1DTE ATM price
SLIPPAGE = 0.02         # 2% entry/exit slippage

# Exit Models (TP/SL targets)
EXIT_MODELS = {
    'A': {'tp': 0.20, 'sl': -0.10, 'name': 'Tight (+20/-10%)'},
    'B': {'tp': 0.30, 'sl': -0.15, 'name': 'Balanced (+30/-15%)'},
    'C': {'tp': 0.40, 'sl': -0.20, 'name': 'Trend (+40/-20%)'},
}
MAX_HOLD_BARS = 120  # 2 hours max

def fetch_data(symbol, start, end):
    """Fetch 1-min bars"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    
    resp = requests.get(url, headers=headers, params={
        'timeframe': '1Min', 'start': start, 'end': end, 'limit': 10000, 'feed': 'iex'
    }, timeout=30)
    
    if resp.status_code == 200:
        bars = resp.json().get('bars', [])
        if bars:
            df = pd.DataFrame(bars)
            df['t'] = pd.to_datetime(df['t'])
            df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 't': 'timestamp'})
            return df.set_index('timestamp').sort_index()
    return None

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def get_signals(df):
    """Boof 22 signals with Slack < 0.8"""
    signals = []
    atr = compute_atr(df)
    
    for i in range(50, len(df) - 1):
        if atr.iloc[i] == 0: continue
        
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        # Fractal detection
        fractal_peak = (highs[3] > max(highs[:3])) and (highs[3] > max(highs[4:]))
        fractal_trough = (lows[3] < min(lows[:3])) and (lows[3] < min(lows[4:]))
        
        # ATR confirmation
        atr_rejected = closes[3] < highs[3] - atr.iloc[i] * 0.6
        atr_bounced = closes[3] > lows[3] + atr.iloc[i] * 0.6
        
        # Slack (distance from entry to peak/trough in ATR units)
        peak_slack = (highs[3] - closes[3]) / atr.iloc[i]
        trough_slack = (closes[3] - lows[3]) / atr.iloc[i]
        
        # SHORT signal: fractal peak + rejection + tight slack
        if fractal_peak and atr_rejected and peak_slack < SLACK_MAX:
            signals.append({
                'bar': i + 1,
                'direction': 'short',
                'slack': peak_slack,
                'entry_price': df.iloc[i + 1]['open'],  # Enter next bar open
                'timestamp': df.index[i + 1]
            })
        
        # LONG signal: fractal trough + bounce + tight slack
        elif fractal_trough and atr_bounced and trough_slack < SLACK_MAX:
            signals.append({
                'bar': i + 1,
                'direction': 'long',
                'slack': trough_slack,
                'entry_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
    
    return signals

def run_trade(df, signal, model):
    """
    Simulate 1DTE option trade based on ACTUAL stock price movement
    """
    entry_bar = signal['bar']
    if entry_bar >= len(df): return None
    
    stock_entry = signal['entry_price']
    
    # Option entry (ask + slippage)
    option_entry = OPTION_PRICE * (1 + SLIPPAGE)
    
    # TP/SL targets in option price terms
    tp_price = option_entry * (1 + model['tp'])
    sl_price = option_entry * (1 + model['sl'])
    
    exit_bar = entry_bar
    exit_type = 'time'
    
    # Track minute by minute
    for i in range(entry_bar, min(entry_bar + MAX_HOLD_BARS, len(df))):
        stock_current = df.iloc[i]['close']
        
        # Calculate actual stock move %
        stock_move_pct = (stock_current - stock_entry) / stock_entry
        
        # 1DTE option P&L = stock move × leverage
        # LONG: stock up = option up, stock down = option down
        # SHORT: stock down = put up, stock up = put down
        if signal['direction'] == 'long':
            option_pnl_pct = stock_move_pct * OPTION_LEVERAGE
        else:  # short - we buy puts, so stock down = profit
            option_pnl_pct = -stock_move_pct * OPTION_LEVERAGE
        
        current_option_price = option_entry * (1 + option_pnl_pct)
        
        # Check TP
        if current_option_price >= tp_price:
            exit_bar = i
            exit_type = 'tp'
            break
        
        # Check SL
        if current_option_price <= sl_price:
            exit_bar = i
            exit_type = 'sl'
            break
        
        exit_bar = i
    
    # Calculate final P&L
    stock_exit = df.iloc[exit_bar]['close']
    stock_move_pct = (stock_exit - stock_entry) / stock_entry
    
    if signal['direction'] == 'long':
        option_pnl_pct = stock_move_pct * OPTION_LEVERAGE
    else:
        option_pnl_pct = -stock_move_pct * OPTION_LEVERAGE
    
    # Apply exit slippage
    option_pnl_pct *= (1 - SLIPPAGE)
    
    return {
        'timestamp': signal['timestamp'],
        'direction': signal['direction'],
        'slack': signal['slack'],
        'stock_entry': stock_entry,
        'stock_exit': stock_exit,
        'stock_move': stock_move_pct * 100,  # as %
        'option_pnl': option_pnl_pct * 100,  # as %
        'option_dollar': option_pnl_pct * OPTION_PRICE,
        'exit_type': exit_type,
        'hold_bars': exit_bar - entry_bar,
        'model': model['name']
    }

def main():
    print("="*80)
    print("1DTE OPTIONS BACKTEST - Stock Move → Option P&L")
    print("="*80)
    print(f"Symbols: {SYMBOLS}")
    print(f"Slack Filter: < {SLACK_MAX}")
    print(f"1DTE Model: {OPTION_LEVERAGE}x leverage (1% stock = 20% option)")
    print(f"Base Option Price: ${OPTION_PRICE}")
    print("="*80)
    
    # 1 week of data
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    all_trades = {k: [] for k in EXIT_MODELS.keys()}
    
    for symbol in SYMBOLS:
        print(f"\n[{symbol}] Fetching...")
        df = fetch_data(symbol, start, end)
        if df is None or len(df) < 1000:
            print(f"  [SKIP] Insufficient data")
            continue
        
        signals = get_signals(df)
        print(f"  Data: {len(df)} bars | Signals: {len(signals)}")
        
        if not signals:
            continue
        
        # Run each signal through all 3 exit models
        for signal in signals[:30]:  # Limit for speed
            for model_key, model in EXIT_MODELS.items():
                trade = run_trade(df, signal, model)
                if trade:
                    trade['symbol'] = symbol
                    all_trades[model_key].append(trade)
    
    # Results
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    
    for model_key, trades in all_trades.items():
        if not trades:
            print(f"\n[{model_key}] No trades")
            continue
        
        df = pd.DataFrame(trades)
        wins = df[df['option_dollar'] > 0]
        losses = df[df['option_dollar'] <= 0]
        
        gross_profit = wins['option_dollar'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['option_dollar'].sum()) if len(losses) > 0 else 0.001
        
        print(f"\n{EXIT_MODELS[model_key]['name']}")
        print(f"  Trades: {len(df)}")
        print(f"  Win Rate: {len(wins)/len(df)*100:.1f}%")
        print(f"  Profit Factor: {gross_profit/gross_loss:.2f}")
        print(f"  Total P&L: ${df['option_dollar'].sum():.2f} per contract")
        print(f"  Avg Trade: ${df['option_dollar'].mean():.2f}")
        print(f"  Avg Hold: {df['hold_bars'].mean():.1f} min")
        
        # Exit breakdown
        tp = len(df[df['exit_type'] == 'tp'])
        sl = len(df[df['exit_type'] == 'sl'])
        time = len(df[df['exit_type'] == 'time'])
        print(f"  Exits: TP={tp} | SL={sl} | Time={time}")
        
        # Show sample trades
        print(f"\n  Sample Trades:")
        for _, t in df.head(3).iterrows():
            print(f"    {t['direction'].upper()} {t['symbol']}: Stock moved {t['stock_move']:+.2f}% -> Option ${t['option_dollar']:+.2f} ({t['exit_type']})")

if __name__ == '__main__':
    main()
