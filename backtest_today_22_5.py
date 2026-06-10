#!/usr/bin/env python3
"""
Quick Boof 22.5 backtest on today's 1-minute data
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
# Force reload to pick up modified constants
import importlib
import backtest_boof22_5
importlib.reload(backtest_boof22_5)
from backtest_boof22_5 import run_boof22_5

# 10 non-ETF symbols
SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AMD', 'NFLX', 'CRM']

def fetch_today_1m(symbol):
    """Fetch today's 1-minute data from yfinance."""
    ticker = yf.Ticker(symbol)
    # Get today's data with 1m interval
    today = datetime.now().strftime('%Y-%m-%d')
    df = ticker.history(period='1d', interval='1m', prepost=False)
    if df.empty:
        print(f"No data for {symbol} today")
        return None
    
    # Rename columns to lowercase for consistency
    df.columns = [c.lower().replace(' ', '_') for c in df.columns]
    df = df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})
    df = df.reset_index()
    df['timestamp'] = df['datetime'] if 'datetime' in df.columns else df.index
    
    print(f"Fetched {len(df)} 1m bars for {symbol} on {today}")
    print(f"Time range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    print(f"Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
    
    return df

def main():
    print("=" * 70)
    print(f"Boof 22.5 Backtest - Today's 1m Data - 10 Symbols")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print("=" * 70)
    
    all_trades = []
    symbol_results = {}
    
    for symbol in SYMBOLS:
        print(f"\n--- {symbol} ---")
        df = fetch_today_1m(symbol)
        if df is None or len(df) < 50:
            print(f"Skipping {symbol} - insufficient data")
            symbol_results[symbol] = {'trades': 0, 'pnl': 0}
            continue
        
        trades = run_boof22_5(df, symbol)
        symbol_results[symbol] = {
            'trades': len(trades),
            'pnl': sum(t.get('pnl_pct', 0) * 100 for t in trades),
            'wins': sum(1 for t in trades if t.get('pnl_pct', 0) > 0),
            'losses': sum(1 for t in trades if t.get('pnl_pct', 0) <= 0)
        }
        
        for t in trades:
            t['symbol'] = symbol
            all_trades.append(t)
        
        print(f"  Trades: {len(trades)} | P&L: {symbol_results[symbol]['pnl']:.1f}%")
    
    # Print summary
    print("\n" + "=" * 70)
    print("AGGREGATE BACKTEST RESULTS - ALL 10 SYMBOLS")
    print("=" * 70)
    
    if not all_trades:
        print("No trades generated across all symbols")
        return
    
    wins = sum(1 for t in all_trades if t.get('pnl_pct', 0) > 0)
    losses = sum(1 for t in all_trades if t.get('pnl_pct', 0) <= 0)
    total_pnl = sum(t.get('pnl_pct', 0) * 100 for t in all_trades)
    
    print(f"Total Trades: {len(all_trades)}")
    print(f"Wins: {wins} ({wins/len(all_trades)*100:.1f}%)")
    print(f"Losses: {losses} ({losses/len(all_trades)*100:.1f}%)")
    print(f"Total P&L: {total_pnl:.1f}%")
    
    # Per-symbol breakdown
    print("\nPer-Symbol Results:")
    print("-" * 50)
    for symbol in SYMBOLS:
        r = symbol_results.get(symbol, {})
        if r.get('trades', 0) > 0:
            win_rate = r.get('wins', 0) / r['trades'] * 100
            print(f"{symbol:5} | Trades: {r['trades']:2} | Wins: {r.get('wins', 0)} | P&L: {r.get('pnl', 0):6.1f}%")
        else:
            print(f"{symbol:5} | No trades")
    
    print("\nAll Trade Details:")
    print("-" * 80)
    for i, t in enumerate(all_trades, 1):
        mode = t.get('mode', 'unknown')
        pnl_pct = t.get('pnl_pct', 0)
        direction = t.get('direction', 'unknown')
        exit_type = t.get('exit_type', 'unknown')
        symbol = t.get('symbol', '?')
        bars = t.get('bars_held', 0)
        duration = f"{bars}m" if bars else "-"
        print(f"  {i:2}. {symbol:5} {direction.upper():5} | {duration:>4} | Mode: {mode:6} | Exit: {exit_type:8} | P&L: {pnl_pct*100:5.1f}%")

if __name__ == '__main__':
    main()
