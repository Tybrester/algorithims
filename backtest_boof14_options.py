import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import sys

# Import Boof 14.0 logic (backup of original Boof 15.0)
sys.path.append('.')
from backtest_boof14 import (
    generate_entries, backtest, calculate_position_size,
    classify_regime, build_ev_lookup_table, run_system
)

# =========================================================
# ALPACA OPTIONS API
# =========================================================

ALPACA_API_KEY = "AK5QL43AEYXZSYCRSNSIDYO36D"
ALPACA_SECRET_KEY = "qwEfPQ2CWZYzDzJLn4QQNYcs9tdNprxP44C4dWT5md3"

def fetch_alpaca_bars(symbol, start_date, end_date, timeframe='1Min', api_key=None, secret_key=None):
    """Fetch historical bars from Alpaca API"""
    if not api_key or not secret_key:
        print(f"No Alpaca credentials provided for {symbol}")
        return None
    
    try:
        start = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        end = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
        params = {
            'timeframe': timeframe,
            'start': start,
            'end': end,
            'adjustment': 'raw',
            'feed': 'sip',
            'limit': 10000
        }
        
        headers = {
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
        
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'bars' in data and data['bars']:
            df = pd.DataFrame(data['bars'])
            df['t'] = pd.to_datetime(df['t'])
            df.set_index('t', inplace=True)
            df.rename(columns={
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'vw': 'vwap'
            }, inplace=True)
            return df
        return None
    except Exception as e:
        print(f"  Error fetching data: {e}")
        return None

# =========================================================
# OPTIONS BACKTEST ENGINE FOR BOOF 14.0
# =========================================================

def backtest_options_140(df_underlying: pd.DataFrame, symbol: str = "SPY",
                        trade_direction: str = "both",
                        tp_pct: float = 0.50,
                        sl_pct: float = -0.20) -> Dict:
    """Backtest Boof 14.0 with 0DTE options using custom TP/SL"""
    
    # Generate signals using Boof 14.0 (original Boof 15.0)
    ev_table = build_ev_lookup_table([])  # Empty for now
    entries, diagnostics = generate_entries(
        df_underlying, symbol, ev_table, 
        use_ev=False, use_continuous_ev=False, use_kelly=False
    )
    
    if not entries:
        return {
            'symbol': symbol,
            'total_trades': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'expectancy': 0,
            'profit_factor': 0,
            'trades': []
        }
    
    trades = []
    
    for entry in entries:
        entry_time = entry['time']
        entry_price = entry['price']
        signal = entry['side']
        score = entry.get('score', 0)
        ev = entry.get('ev', 0)
        
        if entry_time not in df_underlying.index:
            continue
        
        idx = df_underlying.index.get_loc(entry_time)
        future = df_underlying.iloc[idx + 1: idx + 80]
        
        if len(future) == 0:
            continue
        
        # Simulate options PnL with theta decay
        # Option-specific parameters for 0DTE
        theta_decay_per_hour = 0.001  # 0.1% per hour theta decay
        iv_crush_factor = 0.98  # 2% IV crush on exit
        
        # Calculate underlying PnL first
        if signal == "LONG":
            underlying_pnl = (future.iloc[-1]['close'] - entry_price) / entry_price
        else:
            underlying_pnl = (entry_price - future.iloc[-1]['close']) / entry_price
        
        # Apply options-specific adjustments
        # Delta: Option moves ~0.50x underlying (for delta ~0.50 on 0DTE)
        delta = 0.50
        options_pnl = underlying_pnl * delta
        
        # Check custom TP/SL on options premium
        if options_pnl >= tp_pct:
            options_pnl = tp_pct  # Cap at TP
        elif options_pnl <= sl_pct:
            options_pnl = sl_pct  # Cap at SL
        
        # Theta decay: ~1 hour average hold time
        hours_held = 1.0
        theta_loss = theta_decay_per_hour * hours_held
        options_pnl -= theta_loss
        
        # IV crush on exit (only on losing trades)
        if underlying_pnl < 0:
            options_pnl *= iv_crush_factor
        
        # Transaction cost
        options_pnl -= 0.001
        
        trades.append({
            'entry_time': entry_time,
            'exit_time': future.index[-1],
            'signal': signal,
            'entry_price': entry_price,
            'exit_price': future.iloc[-1]['close'],
            'underlying_pnl': underlying_pnl,
            'options_pnl': options_pnl,
            'score': score,
            'ev': ev
        })
    
    # Calculate statistics
    if trades:
        pnls = [t['options_pnl'] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_pnl = np.mean(pnls) if pnls else 0
        expectancy = avg_pnl
        profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')
    else:
        win_rate = 0
        avg_pnl = 0
        expectancy = 0
        profit_factor = 0
    
    return {
        'symbol': symbol,
        'total_trades': len(trades),
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'expectancy': expectancy,
        'profit_factor': profit_factor,
        'trades': trades,
        'diagnostics': diagnostics
    }

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    # Backtest last week (May 16 - May 23, 2026)
    end_date = datetime(2026, 5, 23)
    start_date = datetime(2026, 5, 16)
    
    print(f"\n{'='*60}")
    print(f"BOOF 14.0 OPTIONS BACKTEST: {start_date.date()} to {end_date.date()}")
    print(f"TP: 50% | SL: -20% | 0DTE Options")
    print(f"{'='*60}\n")
    
    print("Using provided Alpaca credentials...")
    
    # Boof List symbols
    boof_list = ["QQQ", "SPY", "TSLA", "NVDA", "AMD", "AAPL", "MSFT", "AMZN"]
    
    all_results = {}
    
    for ticker in boof_list:
        print(f"\n{'='*60}")
        print(f"BACKTEST: {ticker} | {start_date.date()} to {end_date.date()} | 0DTE Options")
        print(f"{'='*60}\n")
        
        # Download underlying data
        print(f"  Downloading {ticker} underlying data from Alpaca API...")
        df = fetch_alpaca_bars(ticker, start_date, end_date, '1Min', 
                              ALPACA_API_KEY, ALPACA_SECRET_KEY)
        
        if df is None or len(df) == 0:
            print(f"No data found for {ticker}")
            continue
        
        print(f"Downloaded {len(df)} candles\n")
        
        # Run Boof 14.0 options backtest
        print("Running Boof 14.0 with 50% TP / -20% SL...")
        result = backtest_options_140(df, ticker, trade_direction="both", 
                                      tp_pct=0.50, sl_pct=-0.20)
        
        # Print results
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}\n")
        
        print(f"Total Trades: {result['total_trades']}")
        print(f"Win Rate: {result['win_rate']*100:.1f}%")
        print(f"Avg PnL: {result['avg_pnl']*100:.2f}%")
        print(f"Expectancy: {result['expectancy']*100:.2f}%")
        print(f"Profit Factor: {result['profit_factor']:.2f}")
        
        all_results[ticker] = result
    
    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}\n")
    
    total_trades = sum(r['total_trades'] for r in all_results.values())
    
    if all_results:
        avg_win_rate = np.mean([r['win_rate'] for r in all_results.values()])
        avg_expectancy = np.mean([r['expectancy'] for r in all_results.values()])
    else:
        avg_win_rate = 0
        avg_expectancy = 0
    
    print(f"Total Trades: {total_trades}")
    print(f"Average Win Rate: {avg_win_rate*100:.1f}%")
    print(f"Average Expectancy: {avg_expectancy*100:.2f}%")
    print(f"\nNote: This is a simulation using underlying data with")
    print(f"      estimated theta decay, IV crush, and delta effects.")
    print(f"      Full implementation would use actual options data.")
    
    print(f"\n{'='*60}")
    print(f"BACKTEST COMPLETE")
    print(f"{'='*60}")
