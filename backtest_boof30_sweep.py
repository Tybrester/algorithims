"""
BOOF 30 Parameter Sweep — RVOL, TP, SL Grid Search
9:30-10:30 window, enter immediately on spike
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY    = os.getenv("ALPACA_API_KEY", "PKAJ7LELQVQMPJPEJTGZDRT3XP")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ")

ET = ZoneInfo("America/New_York")

data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

SYMBOLS = ["NVDA", "TSLA", "META", "AVGO", "AMZN", "MSFT", "AAPL", "GOOGL", "AMD", "COIN"]

# Parameter grid
RVOL_LEVELS = [2.0, 3.0, 4.0, 5.0]
TP_LEVELS = [0.0075, 0.01, 0.015]  # 0.75%, 1.0%, 1.5%
SL_LEVELS = [0.003, 0.005]  # 0.3%, 0.5%

POSITION_SIZE = 1000


def fetch_bars(symbol, start, end):
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
        )
        df = data_client.get_stock_bars(req).df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol)
        df = df.reset_index()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


def run_single_test(rvol_min, tp_pct, sl_pct, symbols_data):
    """Run backtest with specific parameters."""
    all_trades = []
    open_positions = {}
    
    # Get all timestamps
    all_timestamps = set()
    for df in symbols_data.values():
        all_timestamps.update(df['timestamp'].tolist())
    all_timestamps = sorted(all_timestamps)
    
    for ts in all_timestamps:
        ts = pd.to_datetime(ts)
        time_only = ts.time()
        date_only = ts.date()
        
        if ts.weekday() >= 5:
            continue
        
        # Window: 9:30 - 10:30 ET
        if not (time(9, 30) <= time_only <= time(10, 30)):
            # Close any open positions after 10:30
            if time_only > time(10, 30) and open_positions:
                for sym, pos in list(open_positions.items()):
                    df = symbols_data[sym]
                    try:
                        current_price = df[df['timestamp'] <= ts].iloc[-1]['close']
                        pnl_pct = calculate_pnl(pos['entry_price'], current_price, pos['direction'])
                        all_trades.append({
                            'symbol': sym, 'date': date_only,
                            'direction': pos['direction'], 'entry_price': pos['entry_price'],
                            'exit_price': current_price, 'entry_time': pos['entry_time'],
                            'exit_time': ts, 'pnl_pct': pnl_pct,
                            'exit_type': 'time_exit', 'rvol_at_entry': pos['rvol']
                        })
                    except:
                        pass
                open_positions.clear()
            continue
        
        # Manage exits
        for sym, pos in list(open_positions.items()):
            df = symbols_data[sym]
            try:
                current_row = df[df['timestamp'] <= ts].iloc[-1]
                current_price = current_row['close']
                pnl_pct = calculate_pnl(pos['entry_price'], current_price, pos['direction'])
                
                if pnl_pct >= tp_pct or pnl_pct <= -sl_pct:
                    exit_type = 'tp' if pnl_pct >= tp_pct else 'sl'
                    all_trades.append({
                        'symbol': sym, 'date': date_only,
                        'direction': pos['direction'], 'entry_price': pos['entry_price'],
                        'exit_price': current_price, 'entry_time': pos['entry_time'],
                        'exit_time': ts, 'pnl_pct': pnl_pct,
                        'exit_type': exit_type, 'rvol_at_entry': pos['rvol']
                    })
                    del open_positions[sym]
            except:
                pass
        
        # Look for entries - immediate entry on RVOL spike
        for sym, df in symbols_data.items():
            if sym in open_positions:
                continue
            try:
                window = df[df['timestamp'] <= ts].tail(60).copy()
                if len(window) < 30:
                    continue
                
                recent = window.iloc[-1]
                avg_volume = window["volume"].iloc[-21:-1].mean()
                rvol = recent["volume"] / avg_volume if avg_volume > 0 else 0
                
                if rvol < rvol_min:
                    continue
                
                # Calculate move info
                price = recent['close']
                move_pct = (recent['close'] - recent['open']) / recent['open']
                
                # Get future moves for analysis
                future_5m = get_future_move(df, ts, 5)
                future_10m = get_future_move(df, ts, 10)
                future_15m = get_future_move(df, ts, 15)
                future_30m = get_future_move(df, ts, 30)
                future_60m = get_future_move(df, ts, 60)
                max_future_move = get_max_future_move(df, ts, 60)
                
                direction = 'long' if move_pct > 0 else 'short'
                
                open_positions[sym] = {
                    'entry_price': price,
                    'direction': direction,
                    'entry_time': ts,
                    'rvol': rvol,
                    'move_at_spike': move_pct,
                    'future_5m': future_5m,
                    'future_10m': future_10m,
                    'future_15m': future_15m,
                    'future_30m': future_30m,
                    'future_60m': future_60m,
                    'max_future_move': max_future_move
                }
            except:
                pass
    
    return pd.DataFrame(all_trades)


def get_future_move(df, timestamp, minutes):
    """Get price move N minutes after timestamp."""
    try:
        future_ts = timestamp + timedelta(minutes=minutes)
        future_data = df[df['timestamp'] <= future_ts]
        if len(future_data) == 0:
            return None
        entry_price = df[df['timestamp'] <= timestamp].iloc[-1]['close']
        future_price = future_data.iloc[-1]['close']
        return (future_price - entry_price) / entry_price
    except:
        return None


def get_max_future_move(df, timestamp, minutes):
    """Get max favorable move in next N minutes."""
    try:
        future_ts = timestamp + timedelta(minutes=minutes)
        future_data = df[(df['timestamp'] > timestamp) & (df['timestamp'] <= future_ts)]
        if len(future_data) == 0:
            return None
        entry_price = df[df['timestamp'] <= timestamp].iloc[-1]['close']
        max_price = future_data['high'].max()
        min_price = future_data['low'].min()
        max_up = (max_price - entry_price) / entry_price
        max_down = (entry_price - min_price) / entry_price
        return max(max_up, max_down)
    except:
        return None


def calculate_pnl(entry, exit, direction):
    if direction == 'long':
        return (exit - entry) / entry
    return (entry - exit) / entry


def analyze_results(df, rvol, tp, sl):
    """Calculate all metrics for a test run."""
    if df.empty:
        return None
    
    total = len(df)
    wins = len(df[df['pnl_pct'] > 0])
    losses = total - wins
    win_rate = wins / total * 100 if total > 0 else 0
    
    avg_win = df[df['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = df[df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if losses > 0 else 0
    
    df['dollar_pnl'] = df['pnl_pct'] * POSITION_SIZE
    total_pnl = df['dollar_pnl'].sum()
    
    gross_profit = df[df['dollar_pnl'] > 0]['dollar_pnl'].sum()
    gross_loss = abs(df[df['dollar_pnl'] < 0]['dollar_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
    expectancy = (win_rate/100 * avg_win/100) - ((100-win_rate)/100 * abs(avg_loss/100))
    expectancy_dollar = expectancy * POSITION_SIZE
    
    # Best/worst symbol
    sym_pnl = df.groupby('symbol')['dollar_pnl'].sum().sort_values(ascending=False)
    best_sym = sym_pnl.index[0] if len(sym_pnl) > 0 else 'N/A'
    worst_sym = sym_pnl.index[-1] if len(sym_pnl) > 0 else 'N/A'
    
    # Average future moves
    avg_move_5m = df['future_5m'].mean() * 100 if 'future_5m' in df.columns else 0
    avg_move_15m = df['future_15m'].mean() * 100 if 'future_15m' in df.columns else 0
    avg_max_move = df['max_future_move'].mean() * 100 if 'max_future_move' in df.columns else 0
    
    return {
        'rvol': rvol,
        'tp_pct': tp * 100,
        'sl_pct': sl * 100,
        'trades': total,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'expectancy_pct': expectancy * 100,
        'expectancy_dollar': expectancy_dollar,
        'total_pnl': total_pnl,
        'best_sym': best_sym,
        'worst_sym': worst_sym,
        'avg_move_5m': avg_move_5m,
        'avg_move_15m': avg_move_15m,
        'avg_max_move': avg_max_move
    }


def main():
    print("="*80)
    print("BOOF 30 PARAMETER SWEEP")
    print("Testing RVOL x TP x SL combinations")
    print("="*80)
    
    # Fetch all data once
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    print(f"\nFetching 6 months of data...")
    symbols_data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end="")
        df = fetch_bars(sym, start_date, end_date)
        if df is not None and len(df) > 100:
            symbols_data[sym] = df
            print(f" {len(df)} bars")
        else:
            print(" SKIP")
    
    print(f"\nLoaded {len(symbols_data)} symbols")
    
    # Run all combinations
    results = []
    total_combos = len(RVOL_LEVELS) * len(TP_LEVELS) * len(SL_LEVELS)
    combo_num = 0
    
    for rvol in RVOL_LEVELS:
        for tp in TP_LEVELS:
            for sl in SL_LEVELS:
                combo_num += 1
                print(f"\n[{combo_num}/{total_combos}] RVOL>{rvol} TP={tp*100:.2f}% SL={sl*100:.2f}%")
                
                trades = run_single_test(rvol, tp, sl, symbols_data)
                metrics = analyze_results(trades, rvol, tp, sl)
                
                if metrics:
                    results.append(metrics)
                    print(f"  Trades: {metrics['trades']} | WinRate: {metrics['win_rate']:.1f}% | "
                          f"PF: {metrics['profit_factor']:.2f} | EV: ${metrics['expectancy_dollar']:.2f}")
                else:
                    print(f"  No trades generated")
    
    # Output results table
    results_df = pd.DataFrame(results)
    
    print("\n" + "="*80)
    print("RESULTS SUMMARY (sorted by Expectancy)")
    print("="*80)
    
    results_df = results_df.sort_values('expectancy_dollar', ascending=False)
    
    print(f"{'RVOL':>5} {'TP%':>5} {'SL%':>5} {'Trades':>7} {'Win%':>6} {'AvgWin':>7} {'AvgLoss':>8} "
          f"{'PF':>5} {'EV$':>7} {'Total$':>8} {'Best':>6} {'5mMove':>7} {'MaxMove':>8}")
    print("-"*100)
    
    for _, row in results_df.iterrows():
        print(f"{row['rvol']:>5.1f} {row['tp_pct']:>5.2f} {row['sl_pct']:>5.2f} "
              f"{int(row['trades']):>7} {row['win_rate']:>6.1f} {row['avg_win']:>7.2f} "
              f"{row['avg_loss']:>8.2f} {row['profit_factor']:>5.2f} "
              f"{row['expectancy_dollar']:>7.2f} {row['total_pnl']:>8.2f} "
              f"{row['best_sym']:>6} {row['avg_move_5m']:>7.2f} {row['avg_max_move']:>8.2f}")
    
    # Save to CSV
    results_df.to_csv('boof30_sweep_results.csv', index=False)
    print("\nResults saved to boof30_sweep_results.csv")
    
    # Best config
    best = results_df.iloc[0]
    print("\n" + "="*80)
    print("BEST CONFIGURATION:")
    print("="*80)
    print(f"RVOL > {best['rvol']}, TP = {best['tp_pct']:.2f}%, SL = {best['sl_pct']:.2f}%")
    print(f"Trades: {int(best['trades'])} | Win Rate: {best['win_rate']:.1f}% | Profit Factor: {best['profit_factor']:.2f}")
    print(f"Expectancy: ${best['expectancy_dollar']:.2f} per trade | Total P&L: ${best['total_pnl']:.2f}")


if __name__ == "__main__":
    main()
