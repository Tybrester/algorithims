"""
Boof 24.0 - Ablation Test
Compare: Full Algorithm vs No Volume Confirmation

Symbols: NQ, ES, SPY, QQQ, NVDA, META
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Test symbols
SYMBOLS = {
    'NQ': '^IXIC',      # Nasdaq Composite as proxy for /NQ
    'ES': 'ES=F',       # E-mini S&P futures
    'SPY': 'SPY',
    'QQQ': 'QQQ', 
    'NVDA': 'NVDA',
    'META': 'META'
}

# Config
CFG = {
    'ATR_LEN': 14,
    'VOL_LEN': 50,
    'ATR_REV_MULT': 1.0,
    'VOL_MULT': 1.25,
    'ATR_PERCENTILE_MIN': 40,
    'RETEST_BARS': 5,
    'TP_R': 2.0,
    'SL_R': 1.0,
    'START_DATE': '2026-01-01',
    'END_DATE': '2026-05-31',
}

def fetch_data(symbol, start, end, interval='5m'):
    """Fetch 5m data for 6 months"""
    try:
        ticker = yf.Ticker(symbol)
        # For 6 months, we need to download in chunks
        df = ticker.history(start=start, end=end, interval=interval)
        if len(df) == 0:
            print(f"  No data for {symbol}")
            return None
        df = df.dropna()
        print(f"  {symbol}: {len(df)} 5m bars")
        return df
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return None

def compute_atr(df, period=14):
    """Compute ATR"""
    high, low, close = df['High'], df['Low'], df['Close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def compute_vwap(df):
    """Compute VWAP"""
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * df['Volume']).cumsum() / df['Volume'].cumsum()

def compute_atr_percentile(atr, lookback=50):
    """ATR percentile"""
    def pct_rank(x):
        if len(x) == 0 or pd.isna(x[-1]):
            return 0
        return (x < x[-1]).sum() / len(x) * 100
    return atr.rolling(window=lookback).apply(pct_rank, raw=False)

def find_swings(df, atr):
    """Step 1: ATR-based swing detection"""
    swings = []
    last_high = {'idx': 0, 'price': df['High'].iloc[0]}
    last_low = {'idx': 0, 'price': df['Low'].iloc[0]}
    direction = ''
    
    for i in range(1, len(df)):
        current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.01
        threshold = current_atr * CFG['ATR_REV_MULT']
        
        if df['High'].iloc[i] > last_high['price']:
            last_high = {'idx': i, 'price': df['High'].iloc[i]}
        if df['Low'].iloc[i] < last_low['price']:
            last_low = {'idx': i, 'price': df['Low'].iloc[i]}
        
        close = df['Close'].iloc[i]
        
        if direction == 'up' and last_high['price'] - close > threshold:
            swings.append({'idx': last_high['idx'], 'price': last_high['price'], 'type': 'high'})
            direction = 'down'
            last_low = {'idx': i, 'price': df['Low'].iloc[i]}
        elif direction == 'down' and close - last_low['price'] > threshold:
            swings.append({'idx': last_low['idx'], 'price': last_low['price'], 'type': 'low'})
            direction = 'up'
            last_high = {'idx': i, 'price': df['High'].iloc[i]}
        elif direction == '':
            if close > df['High'].iloc[0] + threshold:
                direction = 'up'
            elif close < df['Low'].iloc[0] - threshold:
                direction = 'down'
    
    return swings

def analyze_structure(df, swings):
    """Step 2 & 3: Market structure + MSB"""
    if len(swings) < 4:
        return None
    
    recent = swings[-4:]
    highs = [s for s in recent if s['type'] == 'high']
    lows = [s for s in recent if s['type'] == 'low']
    
    if len(highs) < 2 or len(lows) < 2:
        return None
    
    # Trend detection
    trend = 'neutral'
    hh = highs[-1]['price'] > highs[-2]['price']
    hl = lows[-1]['price'] > lows[-2]['price']
    lh = highs[-1]['price'] < highs[-2]['price']
    ll = lows[-1]['price'] < lows[-2]['price']
    
    if hh and hl:
        trend = 'bullish'
    elif lh and ll:
        trend = 'bearish'
    
    # MSB detection
    close = df['Close'].iloc[-1]
    msb_bull = False
    msb_bear = False
    msb_price = 0
    
    if trend == 'bearish' and highs:
        if close > highs[-1]['price']:
            msb_bull = True
            msb_price = highs[-1]['price']
    elif trend == 'bullish' and lows:
        if close < lows[-1]['price']:
            msb_bear = True
            msb_price = lows[-1]['price']
    
    return {
        'trend': trend,
        'msb_bull': msb_bull,
        'msb_bear': msb_bear,
        'msb_price': msb_price,
        'last_high': highs[-1]['price'] if highs else df['High'].iloc[-1],
        'last_low': lows[-1]['price'] if lows else df['Low'].iloc[-1]
    }

def check_volume(df, idx):
    """Step 4: Volume confirmation"""
    vol_sma = df['Volume'].rolling(window=CFG['VOL_LEN']).mean()
    return df['Volume'].iloc[idx] > vol_sma.iloc[idx] * CFG['VOL_MULT']

def check_retest(df, msb_price, direction):
    """Step 5: Retest check"""
    n = len(df)
    for i in range(max(0, n-CFG['RETEST_BARS']-5), n):
        if direction == 'LONG':
            if df['Low'].iloc[i] <= msb_price * 1.005 and df['Close'].iloc[i] > msb_price:
                return True
        else:
            if df['High'].iloc[i] >= msb_price * 0.995 and df['Close'].iloc[i] < msb_price:
                return True
    return False

def check_context(df, atr, vwap, direction, idx):
    """Step 6: Context filters"""
    # ATR percentile
    atr_pct = compute_atr_percentile(atr)
    if pd.isna(atr_pct.iloc[idx]) or atr_pct.iloc[idx] < CFG['ATR_PERCENTILE_MIN']:
        return False
    
    # VWAP filter
    close = df['Close'].iloc[idx]
    if direction == 'LONG' and close < vwap.iloc[idx]:
        return False
    if direction == 'SHORT' and close > vwap.iloc[idx]:
        return False
    
    return True

def simulate_trade(df, entry_idx, direction, entry_price, sl_price, tp_price):
    """Simulate a trade from entry to exit"""
    for i in range(entry_idx + 1, min(entry_idx + 100, len(df))):
        high = df['High'].iloc[i]
        low = df['Low'].iloc[i]
        
        if direction == 'LONG':
            # Check stop loss
            if low <= sl_price:
                return -1.0  # -1R
            # Check take profit
            if high >= tp_price:
                return 2.0  # +2R
        else:
            # Check stop loss
            if high >= sl_price:
                return -1.0  # -1R
            # Check take profit
            if low <= tp_price:
                return 2.0  # +2R
    
    # Timeout - close at market price
    exit_price = df['Close'].iloc[min(entry_idx + 99, len(df) - 1)]
    if direction == 'LONG':
        r_return = (exit_price - entry_price) / (entry_price - sl_price)
    else:
        r_return = (entry_price - exit_price) / (sl_price - entry_price)
    
    return max(-2.0, min(3.0, r_return))  # Cap at -2R to +3R

def backtest_symbol(df, use_volume=True):
    """Backtest a single symbol"""
    if df is None or len(df) < 200:
        return None
    
    trades = []
    atr = compute_atr(df)
    vwap = compute_vwap(df)
    
    for i in range(100, len(df) - 10):
        window = df.iloc[:i+1]
        window_atr = atr.iloc[:i+1]
        window_vwap = vwap.iloc[:i+1]
        
        # Step 1: Find swings
        swings = find_swings(window, window_atr)
        if len(swings) < 6:
            continue
        
        # Step 2 & 3: Structure + MSB
        ms = analyze_structure(window, swings)
        if not ms or (not ms['msb_bull'] and not ms['msb_bear']):
            continue
        
        # Step 4: Volume (ablation test)
        if use_volume and not check_volume(window, i):
            continue
        
        # Step 5: Retest
        direction = 'LONG' if ms['msb_bull'] else 'SHORT'
        if not check_retest(window, ms['msb_price'], direction):
            continue
        
        # Step 6: Context
        if not check_context(window, window_atr, window_vwap, direction, i):
            continue
        
        # Calculate position
        entry_price = df['Close'].iloc[i]
        current_atr = window_atr.iloc[i] if pd.notna(window_atr.iloc[i]) else 0.01
        
        if direction == 'LONG':
            sl_price = max(ms['last_low'], entry_price - current_atr * 1.5)
            risk = entry_price - sl_price
            tp_price = entry_price + risk * 2.0
        else:
            sl_price = min(ms['last_high'], entry_price + current_atr * 1.5)
            risk = sl_price - entry_price
            tp_price = entry_price - risk * 2.0
        
        if risk <= 0:
            continue
        
        # Simulate trade
        r_return = simulate_trade(df, i, direction, entry_price, sl_price, tp_price)
        
        trades.append({
            'timestamp': df.index[i],
            'symbol': df.name if hasattr(df, 'name') else 'unknown',
            'direction': direction,
            'entry': entry_price,
            'sl': sl_price,
            'tp': tp_price,
            'r_return': r_return,
            'pnl_pct': (r_return * risk / entry_price) * 100
        })
    
    return trades

def main():
    print("=" * 70)
    print("BOOF 24.0 - 6 MONTH ABLATION TEST")
    print("=" * 70)
    print(f"Period: {CFG['START_DATE']} to {CFG['END_DATE']}")
    print(f"Symbols: {', '.join(SYMBOLS.keys())}")
    print(f"Config: 2R/3R, ATR% > {CFG['ATR_PERCENTILE_MIN']}, VWAP filter")
    print("=" * 70)
    
    all_results = {}
    
    for name, ticker in SYMBOLS.items():
        print(f"\n{name} ({ticker}):")
        
        # Fetch data
        df = fetch_data(ticker, CFG['START_DATE'], CFG['END_DATE'], '5m')
        if df is None:
            continue
        
        # Test WITH volume
        print("  Testing WITH volume filter...")
        trades_with_vol = backtest_symbol(df.copy(), use_volume=True)
        
        # Test WITHOUT volume
        print("  Testing WITHOUT volume filter...")
        trades_no_vol = backtest_symbol(df.copy(), use_volume=False)
        
        all_results[name] = {
            'with_volume': trades_with_vol,
            'no_volume': trades_no_vol
        }
    
    # Print results
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    
    for name, results in all_results.items():
        print(f"\n{name}:")
        
        for test_name, trades in results.items():
            if trades is None or len(trades) == 0:
                print(f"  {test_name}: No trades")
                continue
            
            df_trades = pd.DataFrame(trades)
            wins = (df_trades['r_return'] > 0).sum()
            total = len(df_trades)
            wr = wins / total * 100
            avg_r = df_trades['r_return'].mean()
            total_r = df_trades['r_return'].sum()
            
            print(f"  {test_name}:")
            print(f"    Trades: {total}")
            print(f"    Win Rate: {wr:.1f}%")
            print(f"    Avg R: {avg_r:.2f}")
            print(f"    Total R: {total_r:.2f}")
            print(f"    Profit Factor: {abs(df_trades[df_trades['r_return'] > 0]['r_return'].sum() / df_trades[df_trades['r_return'] < 0]['r_return'].sum()):.2f}")
    
    # Overall comparison
    print("\n" + "=" * 70)
    print("ABLATION TEST: VOLUME IMPACT")
    print("=" * 70)
    
    all_with = []
    all_without = []
    
    for results in all_results.values():
        if results['with_volume']:
            all_with.extend(results['with_volume'])
        if results['no_volume']:
            all_without.extend(results['no_volume'])
    
    if all_with and all_without:
        df_with = pd.DataFrame(all_with)
        df_without = pd.DataFrame(all_without)
        
        print(f"\nWITH Volume Filter:")
        print(f"  Total Trades: {len(df_with)}")
        print(f"  Win Rate: {(df_with['r_return'] > 0).sum() / len(df_with) * 100:.1f}%")
        print(f"  Total R: {df_with['r_return'].sum():.2f}")
        print(f"  Avg R per Trade: {df_with['r_return'].mean():.3f}")
        
        print(f"\nWITHOUT Volume Filter:")
        print(f"  Total Trades: {len(df_without)}")
        print(f"  Win Rate: {(df_without['r_return'] > 0).sum() / len(df_without) * 100:.1f}%")
        print(f"  Total R: {df_without['r_return'].sum():.2f}")
        print(f"  Avg R per Trade: {df_without['r_return'].mean():.3f}")
        
        impact = df_with['r_return'].sum() - df_without['r_return'].sum()
        print(f"\nVolume Filter Impact: {impact:+.2f} R ({impact/df_without['r_return'].sum()*100:+.1f}%)")
        
        if impact > 0:
            print("✅ Volume filter ADDED edge")
        elif impact < 0:
            print("❌ Volume filter REMOVED edge")
        else:
            print("➖ Volume filter had no significant impact")

if __name__ == "__main__":
    main()
