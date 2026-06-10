import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import sys

# Import Boof 15.0/16.0 logic from backtest_signals.py
sys.path.append('.')
from backtest_signals import (
    generate_entries, backtest, calculate_position_size,
    classify_regime, build_ev_lookup_table, run_system
)

# =========================================================
# ALPACA OPTIONS API
# =========================================================

ALPACA_API_KEY = "AK5QL43AEYXZSYCRSNSIDYO36D"
ALPACA_SECRET_KEY = "qwEfPQ2CWZYzDzJLn4QQNYcs9tdNprxP44C4dWT5md3"

def fetch_option_chain(symbol: str, expiration_date: str, api_key: str = None, 
                       secret_key: str = None) -> Optional[Dict]:
    """Fetch option chain for a symbol on a specific expiration date"""
    if not api_key or not secret_key:
        return None
    
    url = f"https://data.alpaca.markets/v2/options/chain"
    params = {
        'underlying_symbol': symbol,
        'expiration_date': expiration_date,
        'feed': 'opra'
    }
    
    headers = {
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': secret_key
    }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"  Error fetching option chain: {e}")
        return None

def fetch_option_bars(option_symbols: List[str], start_date: datetime, 
                      end_date: datetime, timeframe: str = '1Min',
                      api_key: str = None, secret_key: str = None) -> Optional[pd.DataFrame]:
    """Fetch historical bars for option symbols"""
    if not api_key or not secret_key:
        return None
    
    url = f"https://data.alpaca.markets/v2/options/bars"
    params = {
        'symbols': ','.join(option_symbols),
        'timeframe': timeframe,
        'start': start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end': end_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'feed': 'opra',
        'limit': 10000
    }
    
    headers = {
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': secret_key
    }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'bars' in data and data['bars']:
            all_bars = []
            for symbol, bars in data['bars'].items():
                for bar in bars:
                    bar['symbol'] = symbol
                    all_bars.append(bar)
            
            df = pd.DataFrame(all_bars)
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
        print(f"  Error fetching option bars: {e}")
        return None

# =========================================================
# OPTIONS SELECTION LOGIC
# =========================================================

def select_0dte_option(option_chain: Dict, current_price: float, 
                       signal: str, delta_target: float = 0.35) -> Optional[str]:
    """Select the best 0DTE option based on delta target"""
    if not option_chain or 'option_chain' not in option_chain:
        return None
    
    contracts = option_chain['option_chain']
    
    # Filter by call/put based on signal
    option_type = 'call' if signal == 'LONG' else 'put'
    
    # Find contracts closest to delta target
    best_contract = None
    min_delta_diff = float('inf')
    
    for contract in contracts:
        if contract.get('type') != option_type:
            continue
        
        greeks = contract.get('greeks', {})
        delta = greeks.get('delta', 0)
        
        delta_diff = abs(delta - delta_target)
        if delta_diff < min_delta_diff:
            min_delta_diff = delta_diff
            best_contract = contract
    
    if best_contract:
        return best_contract.get('symbol')
    return None

# =========================================================
# OPTIONS BACKTEST ENGINE
# =========================================================

def backtest_options_150(df_underlying: pd.DataFrame, symbol: str = "SPY",
                        expiration_date: str = None, 
                        trade_direction: str = "both",
                        use_kelly: bool = False,
                        transaction_cost: float = 0.001,
                        is_1dte: bool = False,
                        is_weekly: bool = False,
                        use_auto_exits: bool = False) -> Dict:
    """Backtest Boof 15.0/16.0 with options (0DTE, 1DTE, or weekly)"""
    
    # Generate signals using Boof 15.0/16.0
    ev_table = build_ev_lookup_table([])  # Empty for now, would build from history
    entries, diagnostics = generate_entries(
        df_underlying, symbol, ev_table, 
        use_ev=False, use_continuous_ev=True, use_kelly=use_kelly
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
    
    # For now, simulate options trading using underlying data
    # In full implementation, would fetch actual options data
    
    trades = []
    
    # Adjust parameters based on option type
    if is_weekly:
        theta_decay_per_day = 0.0002  # 0.02% per day (very low)
        iv_crush_factor = 0.995  # 0.5% IV crush (minimal)
        delta = 0.75  # Higher delta for weekly
        tp_pct = 0.50  # 50% profit target
        sl_pct = -0.25  # 25% stop loss
        max_hold_days = 3.0  # Can hold 1-3 days
        bars_per_day = 390  # 6.5 hours * 60 minutes
    elif is_1dte:
        theta_decay_per_hour = 0.0005  # 0.05% per hour
        iv_crush_factor = 0.99  # 1% IV crush
        delta = 0.65  # Higher delta for 1DTE
        tp_pct = 0.30  # 30% profit target
        sl_pct = -0.20  # 20% stop loss
        max_hold_hours = 4.0  # Can hold longer
        bars_per_day = 60
    else:  # 0DTE
        theta_decay_per_hour = 0.001  # 0.1% per hour theta decay
        iv_crush_factor = 0.98  # 2% IV crush
        delta = 0.50  # Delta ~0.50 on 0DTE
        tp_pct = 0.30  # 30% profit target
        sl_pct = -0.20  # 20% stop loss
        max_hold_hours = 1.0  # Shorter hold time
        bars_per_day = 60
    
    # Calculate indicators for structure break detection
    df_underlying['vwap'] = df_underlying['close'].rolling(window=20).mean()  # Simplified VWAP
    df_underlying['ema9'] = df_underlying['close'].ewm(span=9).mean()
    df_underlying['ema20'] = df_underlying['close'].ewm(span=20).mean()
    
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
        
        # Simulate options PnL with automatic exit signals
        exit_reason = 'timeout'
        exit_idx = len(future) - 1
        
        for bar_idx, (_, row) in enumerate(future.iterrows()):
            current_price = row['close']
            
            # Calculate underlying PnL so far
            if signal == "LONG":
                underlying_pnl = (current_price - entry_price) / entry_price
            else:
                underlying_pnl = (entry_price - current_price) / entry_price
            
            # Apply delta
            options_pnl = underlying_pnl * delta
            
            # Time held (in hours or days, depending on option type)
            if is_weekly:
                time_held = bar_idx / bars_per_day  # In days
            else:
                time_held = bar_idx / 60.0  # In hours
            
            # EXIT 1: TP/SL on premium
            if options_pnl >= tp_pct:
                exit_reason = 'tp'
                exit_idx = bar_idx
                break
            elif options_pnl <= sl_pct:
                exit_reason = 'sl'
                exit_idx = bar_idx
                break
            
            # EXIT 2: Time-based exit (theta decay or max hold)
            if use_auto_exits:
                if is_weekly and time_held >= max_hold_days:
                    exit_reason = 'max_hold'
                    exit_idx = bar_idx
                    break
                elif not is_weekly and time_held >= max_hold_hours:
                    exit_reason = 'theta_decay'
                    exit_idx = bar_idx
                    break
            
            # EXIT 3: EOD exit (30 min before close = 3:30 PM = 930 minutes from midnight UTC)
            if use_auto_exits:
                bar_time = row.name
                if hasattr(bar_time, 'hour'):
                    hour = bar_time.hour
                    minute = bar_time.minute
                    time_minutes = hour * 60 + minute
                    if time_minutes >= 930:  # 3:30 PM UTC
                        exit_reason = 'eod_exit'
                        exit_idx = bar_idx
                        break
            
            # EXIT 4: Structure break (only if using auto exits)
            if use_auto_exits:
                cur_vwap = row.get('vwap', 0)
                cur_ema9 = row.get('ema9', 0)
                cur_ema20 = row.get('ema20', 0)
                
                if signal == "LONG":
                    if current_price < cur_vwap and cur_ema9 < cur_ema20:
                        exit_reason = 'structure_break'
                        exit_idx = bar_idx
                        break
                else:  # SHORT
                    if current_price > cur_vwap and cur_ema9 > cur_ema20:
                        exit_reason = 'structure_break'
                        exit_idx = bar_idx
                        break
        
        # Get final values at exit
        exit_row = future.iloc[exit_idx]
        exit_price = exit_row['close']
        
        if signal == "LONG":
            underlying_pnl = (exit_price - entry_price) / entry_price
        else:
            underlying_pnl = (entry_price - exit_price) / entry_price
        
        options_pnl = underlying_pnl * delta
        
        # Apply theta decay based on actual hold time
        if is_weekly:
            days_held = exit_idx / bars_per_day
            theta_loss = theta_decay_per_day * days_held
        else:
            hours_held = exit_idx / 60.0
            theta_loss = theta_decay_per_hour * hours_held
        options_pnl -= theta_loss
        
        # IV crush on exit (only on losing trades)
        if underlying_pnl < 0:
            options_pnl *= iv_crush_factor
        
        # Transaction cost
        options_pnl -= transaction_cost
        
        trades.append({
            'entry_time': entry_time,
            'exit_time': future.index[exit_idx],
            'signal': signal,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'underlying_pnl': underlying_pnl,
            'options_pnl': options_pnl,
            'score': score,
            'ev': ev,
            'exit_reason': exit_reason
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
    print(f"BOOF 15.0/16.0 OPTIONS BACKTEST: {start_date.date()} to {end_date.date()}")
    print(f"Sub-$10 Stocks: 0DTE Options (30% TP / -20% SL)")
    print(f"{'='*60}\n")
    
    print("Using provided Alpaca credentials...")
    
    # Sub-$10 stocks to test
    sub10_stocks = ["SOFI", "RIVN", "LCID", "AMC", "NIO", "XPEV"]
    
    # Import fetch function from backtest_signals
    from backtest_signals import fetch_alpaca_bars
    
    all_results = {}
    
    for ticker in sub10_stocks:
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
        
        # Run Boof 16.0 options backtest with 0DTE parameters
        print("Running Boof 16.0 with 0DTE options simulation...")
        result = backtest_options_150(df, ticker, use_kelly=True, transaction_cost=0.001, is_1dte=False, is_weekly=False, use_auto_exits=False)
        
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
