"""
Boof 22.5 Backtest with 5m scan interval and 1m entry
- 5m timeframe for signal generation (chop detection, zigzag)
- 1m timeframe for precise entries and exits
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

# 10 non-ETF symbols
SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AMD', 'NFLX', 'CRM']

# Import backtest logic
from backtest_boof22_5 import (
    compute_adx, compute_rsi2, compute_vwap, detect_chop,
    zigzag_touches, in_prox_window
)


def fetch_today_5m(symbol):
    """Fetch today's 5-minute data for signals."""
    ticker = yf.Ticker(symbol)
    today = datetime.now().strftime('%Y-%m-%d')
    df = ticker.history(period='5d', interval='5m', prepost=False)
    if df.empty:
        return None
    
    df.columns = [c.lower().replace(' ', '_') for c in df.columns]
    df = df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})
    df = df.reset_index()
    df['timestamp'] = df['datetime'] if 'datetime' in df.columns else df.index
    
    # Filter to today only
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    today_date = datetime.now().date()
    df = df[df['date'] == today_date]
    
    if len(df) == 0:
        return None
    
    print(f"Fetched {len(df)} 5m bars for {symbol} on {today}")
    return df


def fetch_today_1m(symbol):
    """Fetch today's 1-minute data for entries."""
    ticker = yf.Ticker(symbol)
    today = datetime.now().strftime('%Y-%m-%d')
    df = ticker.history(period='1d', interval='1m', prepost=False)
    if df.empty:
        return None
    
    df.columns = [c.lower().replace(' ', '_') for c in df.columns]
    df = df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})
    df = df.reset_index()
    df['timestamp'] = df['datetime'] if 'datetime' in df.columns else df.index
    
    print(f"Fetched {len(df)} 1m bars for {symbol} on {today}")
    return df


def run_5m_scan_1m_entry(df_5m, df_1m, symbol):
    """Run backtest with 5m signals and 1m entries."""
    import backtest_boof22_5 as b22
    
    trades = []
    if df_5m is None or df_1m is None or len(df_5m) < 20:
        return trades
    
    # Compute indicators on 5m data
    df_5m = compute_adx(df_5m)
    df_5m['rsi2'] = compute_rsi2(df_5m)
    df_5m['vwap'] = compute_vwap(df_5m)
    df_5m['chop'] = detect_chop(df_5m)
    
    # Get zigzag touches on 5m
    highs = df_5m['high'].values
    lows = df_5m['low'].values
    closes = df_5m['close'].values
    touches = zigzag_touches(highs, lows, closes)
    prox_cache = {}
    
    position = None
    entry_price = None
    entry_mode = None
    direction = None
    entry_bar_1m = None
    
    # Align 1m data with 5m timestamps
    df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
    df_5m['timestamp'] = pd.to_datetime(df_5m['timestamp'])
    
    # Iterate through 1m bars for entries/exits
    for i in range(len(df_1m)):
        bar_1m = df_1m.iloc[i]
        ts_1m = bar_1m['timestamp']
        
        # Find corresponding 5m bar for signals
        # Get the 5m bar that contains this 1m timestamp
        mask_5m = df_5m['timestamp'] <= ts_1m
        if not mask_5m.any():
            continue
        idx_5m = mask_5m.idxmax()
        
        # Get current 5m indicators
        adx = df_5m.loc[idx_5m, 'adx'] if 'adx' in df_5m.columns else 50
        chop = df_5m.loc[idx_5m, 'chop'] if 'chop' in df_5m.columns else False
        rsi2 = df_5m.loc[idx_5m, 'rsi2'] if 'rsi2' in df_5m.columns else 50
        vwap = df_5m.loc[idx_5m, 'vwap'] if 'vwap' in df_5m.columns else bar_1m['close']
        
        # Check if we're in position
        if position is None:
            # ENTRY LOGIC - check 5m signals, execute on 1m
            # Need fresh 5m data (every 5th 1m bar approximately)
            if idx_5m < 10:
                continue
                
            prox = in_prox_window(idx_5m, touches, prox_cache, window=5)
            if not prox:
                continue
            
            # Check chop mode on 5m
            is_chop = chop or (adx < b22.ADX_CHOP_THRESHOLD)
            
            if is_chop:
                # Chop mode: VWAP mean reversion
                close_5m = df_5m.loc[idx_5m, 'close']
                if close_5m < vwap and rsi2 < b22.RSI2_OVERSOLD:
                    direction = 'call'
                elif close_5m > vwap and rsi2 > b22.RSI2_OVERBOUGHT:
                    direction = 'put'
                else:
                    continue
                entry_mode = 'chop'
            else:
                # Trend mode: Original Boof 22 logic
                # Simplified: just check proximity and direction
                close_5m = df_5m.loc[idx_5m, 'close']
                prev_close_5m = df_5m.loc[idx_5m-1, 'close'] if idx_5m > 0 else close_5m
                if close_5m > prev_close_5m:
                    direction = 'call'
                else:
                    direction = 'put'
                entry_mode = 'trend'
            
            # Execute entry on 1m bar
            position = True
            entry_price = bar_1m['close']
            entry_bar_1m = i
            
        else:
            # EXIT LOGIC - use 1m bars for precise exits
            bars_held = i - entry_bar_1m
            current_price = bar_1m['close']
            
            # Calculate P&L
            if direction == 'call':
                pnl_pct = (current_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_price) / entry_price
            
            # Set TP/SL based on mode
            if entry_mode == 'chop':
                tp_pct = b22.CHOP_TP_PCT
                sl_pct = -b22.CHOP_SL_PCT
                max_hold = b22.CHOP_MAX_HOLD_MIN
            else:
                tp_pct = b22.DEFAULT_TP_PCT
                sl_pct = -b22.DEFAULT_SL_PCT
                max_hold = b22.MAX_HOLD_MIN
            
            # Check exits
            exit_triggered = False
            exit_type = None
            exit_price = current_price
            
            if pnl_pct >= tp_pct:
                exit_triggered = True
                exit_type = 'tp'
            elif pnl_pct <= sl_pct:
                exit_triggered = True
                exit_type = 'sl'
            elif bars_held >= max_hold:
                exit_triggered = True
                exit_type = 'time'
            
            if exit_triggered:
                trades.append({
                    'symbol': symbol,
                    'direction': direction,
                    'entry': entry_price,
                    'exit': exit_price,
                    'exit_type': exit_type,
                    'pnl_pct': pnl_pct,
                    'mode': entry_mode,
                    'bars_held': bars_held,
                })
                position = None
                entry_price = None
                direction = None
                entry_mode = None
                entry_bar_1m = None
    
    return trades


def main():
    print("=" * 70)
    print("Boof 22.5 - 5m Scan / 1m Entry Backtest")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 70)
    
    all_trades = []
    
    for symbol in SYMBOLS:
        print(f"\n--- {symbol} ---")
        df_5m = fetch_today_5m(symbol)
        df_1m = fetch_today_1m(symbol)
        
        if df_5m is None or df_1m is None:
            print(f"Skipping {symbol} - no data")
            continue
        
        trades = run_5m_scan_1m_entry(df_5m, df_1m, symbol)
        all_trades.extend(trades)
        
        wins = sum(1 for t in trades if t.get('pnl_pct', 0) > 0)
        losses = len(trades) - wins
        total_pnl = sum(t.get('pnl_pct', 0) * 100 for t in trades)
        
        print(f"  Trades: {len(trades)} | Wins: {wins} | Losses: {losses} | P&L: {total_pnl:.1f}%")
    
    # Summary
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)
    
    if not all_trades:
        print("No trades executed")
        return
    
    total_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t.get('pnl_pct', 0) > 0)
    losses = total_trades - wins
    total_pnl = sum(t.get('pnl_pct', 0) * 100 for t in all_trades)
    
    win_rate = wins / total_trades * 100 if total_trades else 0
    avg_pnl = total_pnl / total_trades if total_trades else 0
    
    print(f"Total Trades: {total_trades}")
    print(f"Wins: {wins} ({win_rate:.1f}%)")
    print(f"Losses: {losses} ({100-win_rate:.1f}%)")
    print(f"Total P&L: {total_pnl:.1f}%")
    print(f"Avg per trade: {avg_pnl:.1f}%")
    print(f"P&L ($250/trade): ${total_pnl * 2.5:.0f}")
    
    # By mode
    trend_trades = [t for t in all_trades if t.get('mode') == 'trend']
    chop_trades = [t for t in all_trades if t.get('mode') == 'chop']
    
    if trend_trades:
        trend_pnl = sum(t.get('pnl_pct', 0) * 100 for t in trend_trades)
        print(f"\nTrend mode: {len(trend_trades)} trades, P&L: {trend_pnl:.1f}%")
    
    if chop_trades:
        chop_pnl = sum(t.get('pnl_pct', 0) * 100 for t in chop_trades)
        print(f"Chop mode: {len(chop_trades)} trades, P&L: {chop_pnl:.1f}%")


if __name__ == '__main__':
    main()
