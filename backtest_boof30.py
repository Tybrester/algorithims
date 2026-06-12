"""
BOOF 30 Backtest — Morning Spike Strategy
RVOL spike detection with 5-min confirmation | TP=+0.40% | SL=-0.20%

Usage:
  python backtest_boof30.py
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import glob

# ── CONFIG ────────────────────────────────────────────────────────────
TP_PCT       = 0.004    # +0.40%
SL_PCT       = 0.002    # -0.20%
MIN_RVOL     = 2.0      # volume spike requirement
MIN_MOVE     = 0.0015   # 0.15% candle move
CONFIRM_BARS = 5        # wait 5 min confirmation

# Morning scan window
SCAN_START   = datetime.strptime("09:35", "%H:%M").time()
SCAN_END     = datetime.strptime("11:00", "%H:%M").time()
FORCE_CLOSE  = datetime.strptime("15:55", "%H:%M").time()

# Sizing (fixed dollar amounts)
POSITION_SIZE = 1000    # $1000 per trade

# ── DATA SOURCE ───────────────────────────────────────────────────────
DATA_DIR = r"C:\Users\tybre\Desktop\aivibe"

# Available 1m data files
def get_available_symbols(n=20):
    """Get list of stocks with 1m data files."""
    files = glob.glob(os.path.join(DATA_DIR, "boof24_*_1Min_*.csv"))
    symbols = []
    for f in files:
        # Extract symbol from filename like boof24_AAPL_1Min_mild_20260606.csv
        basename = os.path.basename(f)
        parts = basename.split('_')
        if len(parts) >= 2:
            sym = parts[1]
            if sym not in symbols:
                symbols.append(sym)
    return sorted(symbols)[:n]

SYMBOLS = get_available_symbols(20)
print(f"Found {len(SYMBOLS)} symbols with data: {SYMBOLS}")
print(f"Backtesting on {len(SYMBOLS)} symbols: {SYMBOLS}")

# ── SIGNAL DETECTION ─────────────────────────────────────────────────
def detect_morning_spike(df, timestamp):
    """
    Detect morning spike signal.
    df: DataFrame with 1m bars (needs at least 60 bars)
    timestamp: current time to check
    """
    if len(df) < 60:
        return None

    # Get current bar and previous
    recent = df.iloc[-1]
    prev = df.iloc[-2]

    # Calculate RVOL (relative volume)
    avg_volume = df["volume"].iloc[-21:-1].mean()
    rvol = recent["volume"] / avg_volume if avg_volume > 0 else 0

    # Candle move
    candle_move = (recent["close"] - recent["open"]) / recent["open"]

    # Check thresholds
    if rvol < MIN_RVOL:
        return None

    if abs(candle_move) < MIN_MOVE:
        return None

    # Direction confirmation over last 5 bars
    confirm = df.tail(CONFIRM_BARS)
    start_price = confirm["open"].iloc[0]
    end_price = confirm["close"].iloc[-1]
    confirm_move = (end_price - start_price) / start_price

    if candle_move > 0 and confirm_move > 0:
        return "long"

    if candle_move < 0 and confirm_move < 0:
        return "short"

    return None


# ── BACKTEST LOGIC ───────────────────────────────────────────────────
def run_backtest():
    all_trades = []

    for symbol in SYMBOLS:
        # Find any 1Min file for this symbol
        pattern = os.path.join(DATA_DIR, f"boof24_{symbol}_1Min_*.csv")
        files = glob.glob(pattern)
        if not files:
            print(f"Skipping {symbol}: no data file")
            continue
        filepath = files[0]  # Use first matching file

        if not os.path.exists(filepath):
            print(f"Skipping {symbol}: no data file")
            continue

        print(f"Processing {symbol}...")

        try:
            df = pd.read_csv(filepath)
        except Exception as e:
            print(f"Error loading {symbol}: {e}")
            continue

        # Debug: print available columns
        print(f"  Columns: {list(df.columns)}")
        
        # Rename Alpaca columns if needed
        if 'o' in df.columns and 'open' not in df.columns:
            df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
            print(f"  Renamed Alpaca columns")

        # Parse timestamp
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif 't' in df.columns:
            df['timestamp'] = pd.to_datetime(df['t'])
        elif 'date' in df.columns:
            df['timestamp'] = pd.to_datetime(df['date'])
        else:
            df['timestamp'] = pd.to_datetime(df.index)

        df = df.sort_values('timestamp')

        # Get date range (use all available data if less than 6 months)
        end_date = df['timestamp'].max()
        start_date = end_date - timedelta(days=180)
        df = df[df['timestamp'] >= start_date]
        
        # Ensure we have required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            print(f"  Missing columns: {missing_cols} for {symbol}")
            continue

        if len(df) < 100:
            print(f"  Insufficient data for {symbol}")
            continue

        # Walk through each day
        current_date = None
        in_position = False
        entry_price = 0
        direction = None
        entry_time = None

        for i in range(60, len(df)):
            row = df.iloc[i]
            ts = row['timestamp']
            time_only = ts.time()
            date_only = ts.date()

            # New day reset
            if date_only != current_date:
                if in_position:
                    # Close at previous day's force close
                    exit_price = df.iloc[i-1]['close']
                    pnl = calculate_pnl(entry_price, exit_price, direction)
                    all_trades.append({
                        'symbol': symbol,
                        'date': current_date,
                        'direction': direction,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'entry_time': entry_time,
                        'exit_time': ts,
                        'pnl_pct': pnl,
                        'exit_type': 'eod_carry',
                        'shares': int(POSITION_SIZE / entry_price)
                    })
                    in_position = False

                current_date = date_only

            # Skip weekends
            if ts.weekday() >= 5:
                continue

            # Get window of data for signal detection
            window = df.iloc[max(0, i-60):i+1].copy()

            # Manage existing position
            if in_position:
                current_price = row['close']
                pnl_pct = calculate_pnl(entry_price, current_price, direction, return_pct=True)

                # Check TP/SL
                if pnl_pct >= TP_PCT:
                    all_trades.append({
                        'symbol': symbol,
                        'date': current_date,
                        'direction': direction,
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'entry_time': entry_time,
                        'exit_time': ts,
                        'pnl_pct': pnl_pct,
                        'exit_type': 'tp',
                        'shares': int(POSITION_SIZE / entry_price)
                    })
                    in_position = False
                    continue

                if pnl_pct <= -SL_PCT:
                    all_trades.append({
                        'symbol': symbol,
                        'date': current_date,
                        'direction': direction,
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'entry_time': entry_time,
                        'exit_time': ts,
                        'pnl_pct': pnl_pct,
                        'exit_type': 'sl',
                        'shares': int(POSITION_SIZE / entry_price)
                    })
                    in_position = False
                    continue

                # Force close at end of day
                if time_only >= FORCE_CLOSE:
                    all_trades.append({
                        'symbol': symbol,
                        'date': current_date,
                        'direction': direction,
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'entry_time': entry_time,
                        'exit_time': ts,
                        'pnl_pct': pnl_pct,
                        'exit_type': 'eod',
                        'shares': int(POSITION_SIZE / entry_price)
                    })
                    in_position = False
                    continue

            # Look for new entry (only during scan window)
            if not in_position and SCAN_START <= time_only <= SCAN_END:
                signal = detect_morning_spike(window, ts)

                if signal:
                    entry_price = row['close']
                    direction = signal
                    entry_time = ts
                    in_position = True

    return pd.DataFrame(all_trades)


def calculate_pnl(entry, exit, direction, return_pct=False):
    if direction == 'long':
        pnl = (exit - entry) / entry
    else:
        pnl = (entry - exit) / entry
    return pnl if return_pct else (exit - entry)


# ── ANALYSIS ─────────────────────────────────────────────────────────
def analyze_results(trades_df):
    if trades_df.empty:
        print("No trades generated")
        return

    print("\n" + "="*70)
    print("BOOF 30 BACKTEST RESULTS — Morning Spike Strategy")
    print("="*70)

    total_trades = len(trades_df)
    wins = len(trades_df[trades_df['pnl_pct'] > 0])
    losses = total_trades - wins
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    print(f"\nTotal Trades: {total_trades}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")

    avg_win = trades_df[trades_df['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = trades_df[trades_df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if losses > 0 else 0

    print(f"Avg Win: +{avg_win:.2f}% | Avg Loss: {avg_loss:.2f}%")

    # Calculate dollar P&L
    trades_df['dollar_pnl'] = trades_df.apply(
        lambda r: r['pnl_pct'] * POSITION_SIZE, axis=1
    )

    total_pnl = trades_df['dollar_pnl'].sum()
    avg_pnl = trades_df['dollar_pnl'].mean()

    print(f"\nTotal P&L: ${total_pnl:,.2f}")
    print(f"Avg P&L per trade: ${avg_pnl:.2f}")

    # Profit factor
    gross_profit = trades_df[trades_df['dollar_pnl'] > 0]['dollar_pnl'].sum()
    gross_loss = abs(trades_df[trades_df['dollar_pnl'] < 0]['dollar_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    print(f"Profit Factor: {profit_factor:.2f}")

    # Monthly breakdown
    trades_df['month'] = pd.to_datetime(trades_df['date']).dt.to_period('M')
    monthly = trades_df.groupby('month').agg({
        'dollar_pnl': 'sum',
        'symbol': 'count'
    }).rename(columns={'symbol': 'trades'})

    print("\n" + "-"*70)
    print("Monthly Breakdown:")
    print("-"*70)
    for month, row in monthly.iterrows():
        print(f"  {month}: {row['trades']:3d} trades | P&L: ${row['dollar_pnl']:+.2f}")

    # Exit type breakdown
    print("\n" + "-"*70)
    print("Exit Types:")
    print("-"*70)
    for exit_type, count in trades_df['exit_type'].value_counts().items():
        pct = count / total_trades * 100
        print(f"  {exit_type:12s}: {count:3d} ({pct:.1f}%)")

    # Top symbols
    print("\n" + "-"*70)
    print("Top Symbols by Trade Count:")
    print("-"*70)
    symbol_stats = trades_df.groupby('symbol').agg({
        'symbol': 'count',
        'dollar_pnl': 'sum'
    }).rename(columns={'symbol': 'trades'}).sort_values('trades', ascending=False)

    for sym, row in symbol_stats.head(10).iterrows():
        print(f"  {sym:6s}: {row['trades']:3d} trades | P&L: ${row['dollar_pnl']:+.2f}")

    print("\n" + "="*70)

    # Save results
    trades_df.to_csv('backtest_boof30_results.csv', index=False)
    print("\nResults saved to backtest_boof30_results.csv")


# ── MAIN ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting Boof 30 Backtest...")
    print(f"Scan Window: {SCAN_START} to {SCAN_END}")
    print(f"TP: {TP_PCT*100:.2f}% | SL: {SL_PCT*100:.2f}% | Min RVOL: {MIN_RVOL}")
    print("-"*70)

    trades = run_backtest()
    analyze_results(trades)
