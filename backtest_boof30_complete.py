"""
BOOF 30 Complete Backtest — 3 Versions + Parameter Sweep
Version A: RVOL only
Version B: RVOL + VWAP side
Version C: RVOL + VWAP side + score >= 3

Data format: datetime,symbol,open,high,low,close,volume
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

# Parameter sweep grid
CONFIRM_BARS_LIST = [3, 5, 10]
RVOL_MIN_LIST = [2, 3, 5]
TP_PCT_LIST = [0.0075, 0.010, 0.015]
SL_PCT_LIST = [0.003, 0.004, 0.005]

LOOKBACK_VOL = 20
MAX_HOLD_BARS = 60
START_TIME = time(9, 30)
END_TIME = time(10, 30)


def fetch_data():
    """Fetch all data in required format."""
    all_data = []
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    print("Fetching 6 months of data...")
    for symbol in SYMBOLS:
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start_date,
                end=end_date,
            )
            df = data_client.get_stock_bars(req).df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol)
            df = df.reset_index()
            
            # Rename columns to match required format
            if 't' in df.columns:
                df = df.rename(columns={'t': 'timestamp'})
            df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
            df['datetime'] = pd.to_datetime(df['timestamp'])
            df['symbol'] = symbol
            
            all_data.append(df[['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume']])
            print(f"  {symbol}: {len(df)} bars")
        except Exception as e:
            print(f"  {symbol}: ERROR - {e}")
    
    return pd.concat(all_data, ignore_index=True) if all_data else None


def add_vwap(df):
    """Add VWAP calculation."""
    df = df.copy()
    df['date'] = df['datetime'].dt.date
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = tp * df['volume']
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    return df


def calculate_score(row, confirm):
    """Calculate entry score (0-5 scale)."""
    score = 0
    
    # RVOL component (0-2 points)
    if row['rvol'] >= 5:
        score += 2
    elif row['rvol'] >= 3:
        score += 1
    
    # VWAP distance component (0-2 points)
    vwap_dist = abs(confirm['close'] - confirm['vwap']) / confirm['vwap']
    if vwap_dist > 0.005:  # > 0.5% from VWAP
        score += 2
    elif vwap_dist > 0.002:
        score += 1
    
    # Candle body component (0-1 point)
    body_pct = abs(row['close'] - row['open']) / row['open']
    if body_pct > 0.005:
        score += 1
    
    return score


def get_future_moves(day, entry_idx, entry_price):
    """Get price moves after entry."""
    moves = {}
    for minutes in [5, 10, 15, 30, 60]:
        future_idx = entry_idx + minutes
        if future_idx < len(day):
            future_price = day.iloc[future_idx]['close']
            moves[f'{minutes}m'] = (future_price - entry_price) / entry_price
        else:
            moves[f'{minutes}m'] = None
    
    # Max move (max favorable excursion)
    future_end = min(entry_idx + 60, len(day))
    if entry_idx + 1 < future_end:
        future = day.iloc[entry_idx + 1:future_end]
        max_up = (future['high'].max() - entry_price) / entry_price
        max_down = (entry_price - future['low'].min()) / entry_price
        moves['max'] = max(max_up, max_down)
    else:
        moves['max'] = None
    
    return moves


def backtest_version(df, confirm_bars, rvol_min, tp_pct, sl_pct, version='A'):
    """
    Run backtest for a specific version.
    
    Version A: RVOL only
    Version B: RVOL + VWAP side
    Version C: RVOL + VWAP side + score >= 3
    """
    trades = []
    
    df = add_vwap(df)
    df['date'] = df['datetime'].dt.date
    df['time'] = df['datetime'].dt.time
    
    # Calculate rolling volume
    df['avg_vol'] = df.groupby('date')['volume'].rolling(LOOKBACK_VOL).mean().reset_index(level=0, drop=True)
    df['rvol'] = df['volume'] / df['avg_vol']
    
    for date, day in df.groupby('date'):
        day = day.reset_index(drop=True)
        trade_taken = False
        
        for i in range(LOOKBACK_VOL, len(day) - confirm_bars - MAX_HOLD_BARS):
            if trade_taken:
                break
            
            row = day.iloc[i]
            
            # Time window check
            if not (START_TIME <= row['time'] <= END_TIME):
                continue
            
            # RVOL check (all versions)
            if pd.isna(row['rvol']) or row['rvol'] < rvol_min:
                continue
            
            spike_dir = 'long' if row['close'] > row['open'] else 'short'
            confirm = day.iloc[i + confirm_bars]
            
            # Version B & C: VWAP side check
            if version in ['B', 'C']:
                if spike_dir == 'long' and confirm['close'] <= confirm['vwap']:
                    continue
                if spike_dir == 'short' and confirm['close'] >= confirm['vwap']:
                    continue
            
            # Version C: Score check
            if version == 'C':
                score = calculate_score(row, confirm)
                if score < 3:
                    continue
            
            # Entry and exit levels
            entry = confirm['close']
            
            if spike_dir == 'long':
                tp = entry * (1 + tp_pct)
                sl = entry * (1 - sl_pct)
            else:
                tp = entry * (1 - tp_pct)
                sl = entry * (1 + sl_pct)
            
            # Simulate hold period
            future_start = i + confirm_bars + 1
            future_end = min(future_start + MAX_HOLD_BARS, len(day))
            future = day.iloc[future_start:future_end]
            
            exit_price = future['close'].iloc[-1] if len(future) > 0 else entry
            result = 'TIME'
            exit_time = future['datetime'].iloc[-1] if len(future) > 0 else confirm['datetime']
            
            for _, bar in future.iterrows():
                if spike_dir == 'long':
                    if bar['high'] >= tp:
                        exit_price = tp
                        result = 'TP'
                        exit_time = bar['datetime']
                        break
                    if bar['low'] <= sl:
                        exit_price = sl
                        result = 'SL'
                        exit_time = bar['datetime']
                        break
                else:
                    if bar['low'] <= tp:
                        exit_price = tp
                        result = 'TP'
                        exit_time = bar['datetime']
                        break
                    if bar['high'] >= sl:
                        exit_price = sl
                        result = 'SL'
                        exit_time = bar['datetime']
                        break
            
            # Calculate P&L
            pnl_pct = (exit_price - entry) / entry if spike_dir == 'long' else (entry - exit_price) / entry
            
            # Get future moves for analysis
            moves = get_future_moves(day, i + confirm_bars, entry)
            
            trades.append({
                'symbol': row['symbol'],
                'date': date,
                'entry_time': confirm['datetime'],
                'exit_time': exit_time,
                'direction': spike_dir,
                'entry': entry,
                'exit': exit_price,
                'pnl_pct': pnl_pct,
                'result': result,
                'rvol': row['rvol'],
                'version': version,
                'confirm_bars': confirm_bars,
                'tp_pct': tp_pct,
                'sl_pct': sl_pct,
                'move_5m': moves.get('5m'),
                'move_10m': moves.get('10m'),
                'move_15m': moves.get('15m'),
                'move_30m': moves.get('30m'),
                'move_60m': moves.get('60m'),
                'max_move': moves.get('max'),
                'vwap_dist': abs(confirm['close'] - confirm['vwap']) / confirm['vwap'] if version in ['B', 'C'] else None,
                'score': calculate_score(row, confirm) if version == 'C' else None
            })
            
            trade_taken = True  # One trade per symbol per day
    
    return trades


def analyze_trades(trades):
    """Calculate all metrics for trade results."""
    if not trades:
        return None
    
    df = pd.DataFrame(trades)
    
    total = len(df)
    wins = len(df[df['pnl_pct'] > 0])
    losses = total - wins
    win_rate = wins / total * 100 if total > 0 else 0
    
    avg_win = df[df['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = df[df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if losses > 0 else 0
    avg_trade = df['pnl_pct'].mean() * 100
    
    gross_profit = df[df['pnl_pct'] > 0]['pnl_pct'].sum()
    gross_loss = abs(df[df['pnl_pct'] < 0]['pnl_pct'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Future moves
    avg_moves = {}
    for col in ['move_5m', 'move_10m', 'move_15m', 'move_30m', 'move_60m', 'max_move']:
        if col in df.columns:
            avg_moves[col] = df[col].mean() * 100
    
    return {
        'trades': total,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_trade': avg_trade,
        'profit_factor': profit_factor,
        'tp_hits': (df['result'] == 'TP').sum(),
        'sl_hits': (df['result'] == 'SL').sum(),
        'time_exits': (df['result'] == 'TIME').sum(),
        'move_5m': avg_moves.get('move_5m', 0),
        'move_15m': avg_moves.get('move_15m', 0),
        'max_move': avg_moves.get('max_move', 0)
    }


def print_comparison(results_a, results_b, results_c, params):
    """Print comparison table for three versions."""
    cb, rv, tp, sl = params
    
    print(f"\n{'='*80}")
    print(f"PARAMS: Confirm={cb} bars | RVOL>{rv} | TP={tp*100:.2f}% | SL={sl*100:.2f}%")
    print(f"{'='*80}")
    
    print(f"{'Metric':<20} {'Version A':<15} {'Version B':<15} {'Version C':<15}")
    print("-"*70)
    
    metrics = [
        ('Trades', 'trades', 0),
        ('Win Rate %', 'win_rate', 1),
        ('Avg Win %', 'avg_win', 2),
        ('Avg Loss %', 'avg_loss', 2),
        ('Avg Trade %', 'avg_trade', 3),
        ('Profit Factor', 'profit_factor', 2),
        ('5m Move %', 'move_5m', 2),
        ('15m Move %', 'move_15m', 2),
        ('Max Move %', 'max_move', 2),
    ]
    
    for label, key, decimals in metrics:
        a_val = results_a.get(key, 0) if results_a else 0
        b_val = results_b.get(key, 0) if results_b else 0
        c_val = results_c.get(key, 0) if results_c else 0
        
        fmt = f"{{:.{decimals}f}}"
        print(f"{label:<20} {fmt.format(a_val):<15} {fmt.format(b_val):<15} {fmt.format(c_val):<15}")


def main():
    print("="*80)
    print("BOOF 30 COMPLETE BACKTEST — 3 Versions + Parameter Sweep")
    print("="*80)
    
    # Fetch data
    data = fetch_data()
    if data is None:
        print("Failed to fetch data!")
        return
    
    print(f"\nTotal data points: {len(data)}")
    
    # Store all results
    all_results = []
    
    # Parameter sweep
    total_combos = len(CONFIRM_BARS_LIST) * len(RVOL_MIN_LIST) * len(TP_PCT_LIST) * len(SL_PCT_LIST)
    combo_num = 0
    
    for confirm_bars in CONFIRM_BARS_LIST:
        for rvol_min in RVOL_MIN_LIST:
            for tp_pct in TP_PCT_LIST:
                for sl_pct in SL_PCT_LIST:
                    combo_num += 1
                    params = (confirm_bars, rvol_min, tp_pct, sl_pct)
                    
                    print(f"\n[{combo_num}/{total_combos}] Testing params: CB={confirm_bars}, RVOL>{rvol_min}, TP={tp_pct*100:.2f}%, SL={sl_pct*100:.2f}%")
                    
                    # Run all three versions
                    trades_a, trades_b, trades_c = [], [], []
                    
                    for symbol, sdf in data.groupby('symbol'):
                        trades_a.extend(backtest_version(sdf.copy(), confirm_bars, rvol_min, tp_pct, sl_pct, 'A'))
                        trades_b.extend(backtest_version(sdf.copy(), confirm_bars, rvol_min, tp_pct, sl_pct, 'B'))
                        trades_c.extend(backtest_version(sdf.copy(), confirm_bars, rvol_min, tp_pct, sl_pct, 'C'))
                    
                    results_a = analyze_trades(trades_a)
                    results_b = analyze_trades(trades_b)
                    results_c = analyze_trades(trades_c)
                    
                    # Print comparison
                    print_comparison(results_a, results_b, results_c, params)
                    
                    # Store for summary
                    for version, trades, results in [('A', trades_a, results_a), ('B', trades_b, results_b), ('C', trades_c, results_c)]:
                        if results:
                            all_results.append({
                                'version': version,
                                'confirm_bars': confirm_bars,
                                'rvol_min': rvol_min,
                                'tp_pct': tp_pct,
                                'sl_pct': sl_pct,
                                'trades': results['trades'],
                                'win_rate': results['win_rate'],
                                'avg_win': results['avg_win'],
                                'avg_loss': results['avg_loss'],
                                'avg_trade': results['avg_trade'],
                                'profit_factor': results['profit_factor'],
                                'move_5m': results['move_5m'],
                                'max_move': results['max_move']
                            })
    
    # Summary
    print("\n" + "="*80)
    print("TOP 10 CONFIGURATIONS BY PROFIT FACTOR")
    print("="*80)
    
    results_df = pd.DataFrame(all_results)
    results_df = results_df.sort_values('profit_factor', ascending=False).head(10)
    
    print(f"{'Ver':<4} {'CB':<3} {'RVOL':<5} {'TP%':<6} {'SL%':<6} {'Trades':<8} {'Win%':<7} {'PF':<6} {'AvgTrade':<9}")
    print("-"*80)
    
    for _, row in results_df.iterrows():
        print(f"{row['version']:<4} {int(row['confirm_bars']):<3} {row['rvol_min']:<5.1f} "
              f"{row['tp_pct']*100:<6.2f} {row['sl_pct']*100:<6.2f} "
              f"{int(row['trades']):<8} {row['win_rate']:<7.1f} {row['profit_factor']:<6.2f} "
              f"{row['avg_trade']:<9.3f}")
    
    # Save all results
    results_df = pd.DataFrame(all_results)
    results_df.to_csv('boof30_complete_sweep.csv', index=False)
    print(f"\nSaved {len(all_results)} results to boof30_complete_sweep.csv")


if __name__ == "__main__":
    main()
