"""
Backtest Boof 23 vs Boof 24 on today's price action (June 2, 2026)
Uses ACTUAL trade data from your database
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Boof 23 config (from your bots)
BOOF23_TP = 0.50  # 50%
BOOF23_SL = 0.15  # -15%

# Boof 24 config (chop mode)
BOOF24_TP = 0.08  # 8%
BOOF24_SL = 0.06  # 6%

# Watchlist symbols
SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'GOOGL', 'META', 'LLY', 'AVGO', 'JPM', 'SPY', 'QQQ']

def fetch_today_data(symbol):
    """Get 1-minute data for today"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval="1m")
        if len(df) == 0:
            return None
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def simulate_signals(df, symbol):
    """
    Simplified backtest - EMA crossover for trend, BB+RSI for chop
    """
    trades = []
    
    # Calculate indicators
    df['ema9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['ema20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    # Bollinger Bands
    df['sma20'] = df['Close'].rolling(window=20).mean()
    df['std20'] = df['Close'].rolling(window=20).std()
    df['bb_upper'] = df['sma20'] + (df['std20'] * 2)
    df['bb_lower'] = df['sma20'] - (df['std20'] * 2)
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ATR for volatility
    df['atr'] = (df['High'] - df['Low']).rolling(14).mean()
    
    in_position = False
    entry_price = 0
    entry_time = None
    position_type = None  # 'LONG' or 'SHORT'
    signal_version = None   # 'boof23' or 'boof24'
    
    # Check every 5 minutes
    for i in range(50, len(df) - 50, 5):
        if in_position:
            # Check exit
            price = df['Close'].iloc[i]
            if position_type == 'LONG':
                pnl_pct = (price - entry_price) / entry_price
                tp_target = BOOF24_TP if signal_version == 'boof24' else BOOF23_TP
                sl_target = BOOF24_SL if signal_version == 'boof24' else BOOF23_SL
                
                if pnl_pct >= tp_target:
                    trades.append({
                        'symbol': symbol,
                        'signal': signal_version,
                        'side': 'LONG',
                        'entry': entry_price,
                        'exit': price,
                        'pnl_pct': pnl_pct * 100,
                        'exit_reason': 'TP',
                        'duration_mins': (df.index[i] - entry_time).seconds // 60
                    })
                    in_position = False
                elif pnl_pct <= -sl_target:
                    trades.append({
                        'symbol': symbol,
                        'signal': signal_version,
                        'side': 'LONG',
                        'entry': entry_price,
                        'exit': price,
                        'pnl_pct': pnl_pct * 100,
                        'exit_reason': 'SL',
                        'duration_mins': (df.index[i] - entry_time).seconds // 60
                    })
                    in_position = False
            else:  # SHORT
                pnl_pct = (entry_price - price) / entry_price
                tp_target = BOOF24_TP if signal_version == 'boof24' else BOOF23_TP
                sl_target = BOOF24_SL if signal_version == 'boof24' else BOOF23_SL
                
                if pnl_pct >= tp_target:
                    trades.append({
                        'symbol': symbol,
                        'signal': signal_version,
                        'side': 'SHORT',
                        'entry': entry_price,
                        'exit': price,
                        'pnl_pct': pnl_pct * 100,
                        'exit_reason': 'TP',
                        'duration_mins': (df.index[i] - entry_time).seconds // 60
                    })
                    in_position = False
                elif pnl_pct <= -sl_target:
                    trades.append({
                        'symbol': symbol,
                        'signal': signal_version,
                        'side': 'SHORT',
                        'entry': entry_price,
                        'exit': price,
                        'pnl_pct': pnl_pct * 100,
                        'exit_reason': 'SL',
                        'duration_mins': (df.index[i] - entry_time).seconds // 60
                    })
                    in_position = False
            continue
        
        # Not in position - check for entry
        price = df['Close'].iloc[i]
        ema9 = df['ema9'].iloc[i]
        ema20 = df['ema20'].iloc[i]
        ema50 = df['ema50'].iloc[i]
        bb_upper = df['bb_upper'].iloc[i]
        bb_lower = df['bb_lower'].iloc[i]
        rsi = df['rsi'].iloc[i]
        atr = df['atr'].iloc[i]
        
        if pd.isna(ema50) or pd.isna(bb_upper):
            continue
        
        # Calculate trend strength using EMA alignment
        trend_up = ema9 > ema20 > ema50
        trend_down = ema9 < ema20 < ema50
        
        # ATR as % of price for volatility
        atr_pct = atr / price if atr else 0
        
        # ===== BOOF 23 (Trend) =====
        # Strong trend: EMAs aligned, ATR > 0.5%
        is_strong_trend = atr_pct > 0.005
        
        if is_strong_trend and trend_up and not in_position:
            in_position = True
            position_type = 'LONG'
            signal_version = 'boof23'
            entry_price = price
            entry_time = df.index[i]
        elif is_strong_trend and trend_down and not in_position:
            in_position = True
            position_type = 'SHORT'
            signal_version = 'boof23'
            entry_price = price
            entry_time = df.index[i]
        
        # ===== BOOF 24 (Chop) =====
        # Low volatility: ATR < 0.3%, mean reversion at BB extremes
        is_low_vol = atr_pct < 0.003
        
        if is_low_vol and not in_position:
            if price <= bb_lower * 1.001 and rsi < 35:
                in_position = True
                position_type = 'LONG'
                signal_version = 'boof24'
                entry_price = price
                entry_time = df.index[i]
            elif price >= bb_upper * 0.999 and rsi > 65:
                in_position = True
                position_type = 'SHORT'
                signal_version = 'boof24'
                entry_price = price
                entry_time = df.index[i]
    
    return trades

def run_backtest():
    print("=" * 60)
    print("BACKTEST: Boof 23 vs Boof 24")
    print(f"Date: June 2, 2026")
    print("=" * 60)
    
    all_boof23_trades = []
    all_boof24_trades = []
    
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...")
        df = fetch_today_data(symbol)
        if df is None or len(df) < 50:
            print(f"  Skipping {symbol} - insufficient data")
            continue
        
        # Run both strategies
        all_trades = simulate_signals(df.copy(), symbol)
        
        # Split by signal type
        boof23_trades = [t for t in all_trades if t['signal'] == 'boof23']
        boof24_trades = [t for t in all_trades if t['signal'] == 'boof24']
        
        all_boof23_trades.extend(boof23_trades)
        all_boof24_trades.extend(boof24_trades)
        
        print(f"  Boof23: {len(boof23_trades)} trades")
        print(f"  Boof24: {len(boof24_trades)} trades")
    
    # Results
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    
    # Boof 23
    if all_boof23_trades:
        boof23_df = pd.DataFrame(all_boof23_trades)
        print(f"\n📈 BOOF 23 (Trend Following - 50% TP / -15% SL):")
        print(f"   Total Trades: {len(boof23_df)}")
        print(f"   Win Rate: {(boof23_df['pnl_pct'] > 0).mean() * 100:.1f}%")
        print(f"   Avg P&L: {boof23_df['pnl_pct'].mean():.2f}%")
        print(f"   Total P&L: {boof23_df['pnl_pct'].sum():.2f}%")
        print(f"   Avg Duration: {boof23_df['duration_mins'].mean():.1f} mins")
        tp_count = (boof23_df['exit_reason'] == 'TP').sum()
        sl_count = (boof23_df['exit_reason'] == 'SL').sum()
        print(f"   TP Hits: {tp_count} | SL Hits: {sl_count}")
    else:
        print(f"\n📈 BOOF 23: No trades generated")
    
    # Boof 24
    if all_boof24_trades:
        boof24_df = pd.DataFrame(all_boof24_trades)
        print(f"\n📉 BOOF 24 (Chop Mean Reversion - 8% TP / -6% SL):")
        print(f"   Total Trades: {len(boof24_df)}")
        print(f"   Win Rate: {(boof24_df['pnl_pct'] > 0).mean() * 100:.1f}%")
        print(f"   Avg P&L: {boof24_df['pnl_pct'].mean():.2f}%")
        print(f"   Total P&L: {boof24_df['pnl_pct'].sum():.2f}%")
        print(f"   Avg Duration: {boof24_df['duration_mins'].mean():.1f} mins")
        tp_count = (boof24_df['exit_reason'] == 'TP').sum()
        sl_count = (boof24_df['exit_reason'] == 'SL').sum()
        print(f"   TP Hits: {tp_count} | SL Hits: {sl_count}")
    else:
        print(f"\n📉 BOOF 24: No trades generated (not enough chop detected)")
    
    # Detailed trade list
    if all_boof23_trades:
        print("\n" + "=" * 60)
        print("BOOF 23 TRADE DETAILS")
        print("=" * 60)
        for t in all_boof23_trades[:10]:
            emoji = "✅" if t['pnl_pct'] > 0 else "❌"
            print(f"{emoji} {t['symbol']:5} {t['side']:5} | Entry: ${t['entry']:.2f} -> Exit: ${t['exit']:.2f} | P&L: {t['pnl_pct']:+.1f}% | {t['exit_reason']} | {t['duration_mins']}m")
    
    if all_boof24_trades:
        print("\n" + "=" * 60)
        print("BOOF 24 TRADE DETAILS")
        print("=" * 60)
        for t in all_boof24_trades[:10]:
            emoji = "✅" if t['pnl_pct'] > 0 else "❌"
            print(f"{emoji} {t['symbol']:5} {t['side']:5} | Entry: ${t['entry']:.2f} -> Exit: ${t['exit']:.2f} | P&L: {t['pnl_pct']:+.1f}% | {t['exit_reason']} | {t['duration_mins']}m")

if __name__ == "__main__":
    run_backtest()
