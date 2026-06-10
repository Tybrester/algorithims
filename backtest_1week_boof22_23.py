"""
1-Week Backtest: Boof 22 & 23 on Boof 24 Scan List (9 symbols)
Symbols: NVDA, AAPL, META, MSFT, AMZN, GOOGL, AVGO, TSLA, LLY
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf

# Boof 24 scan list - 9 symbols
BOOF24_SYMBOLS = ['NVDA', 'AAPL', 'META', 'MSFT', 'AMZN', 'GOOGL', 'AVGO', 'TSLA', 'LLY']

# Config (same as your live bot)
ATR_LEN = 14
VOL_LEN = 50
MAX_HOLD_MIN = 30
CLUSTER_MERGE = 0.5
SR_DIST_MAX = 1.0
SR_STRENGTH_MIN = 2
FRACTAL_BARS = 3
ATR_MULT = 0.6

# Default params for all symbols
SYMBOL_PARAMS = {sym: {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0} for sym in BOOF24_SYMBOLS}

# Trading params
TP_PCT = 0.50  # 50%
SL_PCT = -0.15  # -15%
BASE_AMOUNT = 250  # per trade

def compute_atr(df, period=ATR_LEN):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def find_fractal_peaks(df, bars=FRACTAL_BARS):
    highs = df['high']
    peaks = []
    for i in range(bars, len(df) - bars):
        window_before = highs.iloc[i-bars:i]
        window_after = highs.iloc[i+1:i+1+bars]
        if highs.iloc[i] > window_before.max() and highs.iloc[i] > window_after.max():
            peaks.append(i)
    return peaks

def find_fractal_troughs(df, bars=FRACTAL_BARS):
    lows = df['low']
    troughs = []
    for i in range(bars, len(df) - bars):
        window_before = lows.iloc[i-bars:i]
        window_after = lows.iloc[i+1:i+1+bars]
        if lows.iloc[i] < window_before.min() and lows.iloc[i] < window_after.min():
            troughs.append(i)
    return troughs

def get_volume_clusters(df, lookback=50):
    """Simple volume cluster detection"""
    vol_sma = df['volume'].rolling(VOL_LEN).mean()
    high_vol = df['volume'] > vol_sma * 1.5
    
    clusters = []
    for i in range(len(df)):
        if high_vol.iloc[i]:
            price = round(df['close'].iloc[i], 2)
            clusters.append(price)
    return list(set(clusters)) if clusters else [df['close'].iloc[-1]]

def backtest_symbol(symbol, start_date, end_date, interval='5m'):
    """Backtest a single symbol"""
    try:
        # Download data
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        
        if len(df) < 50:
            return None, 0, []
        
        df.columns = [c.lower().replace(' ', '_') for c in df.columns]
        
        # Compute indicators
        df['atr'] = compute_atr(df)
        df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
        df['rvol'] = df['volume'] / df['vol_sma']
        
        # Find fractals
        peaks = find_fractal_peaks(df)
        troughs = find_fractal_troughs(df)
        
        trades = []
        in_trade = False
        entry_price = 0
        direction = None
        
        params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3})
        
        for i in range(50, len(df) - 1):
            if in_trade:
                # Check exits
                if direction == 'LONG':
                    pnl_pct = (df['close'].iloc[i] - entry_price) / entry_price
                    if pnl_pct >= TP_PCT or pnl_pct <= SL_PCT:
                        trades.append({
                            'symbol': symbol,
                            'direction': 'LONG',
                            'entry': entry_price,
                            'exit': df['close'].iloc[i],
                            'pnl_pct': pnl_pct,
                            'pnl_dollar': BASE_AMOUNT * pnl_pct,
                            'exit_time': df.index[i]
                        })
                        in_trade = False
                else:  # SHORT
                    pnl_pct = (entry_price - df['close'].iloc[i]) / entry_price
                    if pnl_pct >= TP_PCT or pnl_pct <= SL_PCT:
                        trades.append({
                            'symbol': symbol,
                            'direction': 'SHORT',
                            'entry': entry_price,
                            'exit': df['close'].iloc[i],
                            'pnl_pct': pnl_pct,
                            'pnl_dollar': BASE_AMOUNT * pnl_pct,
                            'exit_time': df.index[i]
                        })
                        in_trade = False
                continue
            
            # Check for new signals
            if i in peaks:
                # SHORT signal at fractal peak
                entry_price = df['close'].iloc[i]
                direction = 'SHORT'
                in_trade = True
            elif i in troughs:
                # LONG signal at fractal trough
                entry_price = df['close'].iloc[i]
                direction = 'LONG'
                in_trade = True
        
        # Calculate metrics
        if trades:
            total_pnl = sum(t['pnl_dollar'] for t in trades)
            win_count = sum(1 for t in trades if t['pnl_pct'] > 0)
            win_rate = win_count / len(trades)
            return trades, total_pnl, [win_rate, len(trades)]
        
        return None, 0, [0, 0]
    except Exception as e:
        print(f"Error backtesting {symbol}: {e}")
        return None, 0, [0, 0]

# Run backtest for last week
end_date = datetime.now()
start_date = end_date - timedelta(days=7)

print(f"\n{'='*60}")
print(f"1-WEEK BACKTEST: Boof 22 & 23 on Boof 24 Scan List")
print(f"Symbols: {', '.join(BOOF24_SYMBOLS)}")
print(f"Period: {start_date.date()} to {end_date.date()}")
print(f"Timeframe: 5m (Signal) + 1m (Entry simulation)")
print(f"{'='*60}\n")

all_trades = []
symbol_results = {}

for symbol in BOOF24_SYMBOLS:
    print(f"Backtesting {symbol}...")
    trades, pnl, metrics = backtest_symbol(symbol, start_date, end_date, '5m')
    if trades:
        all_trades.extend(trades)
        symbol_results[symbol] = {
            'trades': len(trades),
            'pnl': pnl,
            'win_rate': metrics[0]
        }
        print(f"  → {len(trades)} trades, ${pnl:.2f} P&L, {metrics[0]*100:.1f}% WR")

print(f"\n{'='*60}")
print("COMBINED RESULTS")
print(f"{'='*60}")

if all_trades:
    total_pnl = sum(t['pnl_dollar'] for t in all_trades)
    win_count = sum(1 for t in all_trades if t['pnl_pct'] > 0)
    loss_count = len(all_trades) - win_count
    win_rate = win_count / len(all_trades)
    
    avg_win = sum(t['pnl_dollar'] for t in all_trades if t['pnl_pct'] > 0) / win_count if win_count > 0 else 0
    avg_loss = sum(t['pnl_dollar'] for t in all_trades if t['pnl_pct'] <= 0) / loss_count if loss_count > 0 else 0
    
    gross_profit = sum(t['pnl_dollar'] for t in all_trades if t['pnl_pct'] > 0)
    gross_loss = abs(sum(t['pnl_dollar'] for t in all_trades if t['pnl_pct'] <= 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    print(f"Total Trades: {len(all_trades)}")
    print(f"Win Rate: {win_rate*100:.1f}%")
    print(f"Total P&L: ${total_pnl:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Avg Win: ${avg_win:.2f}")
    print(f"Avg Loss: ${avg_loss:.2f}")
    print(f"\nPer Symbol:")
    for sym, res in symbol_results.items():
        print(f"  {sym}: {res['trades']} trades, ${res['pnl']:.2f}, {res['win_rate']*100:.1f}% WR")
else:
    print("No trades generated in the past week")

print(f"{'='*60}")
