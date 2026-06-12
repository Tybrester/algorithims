"""
BOOF 30 Backtest — 6 Month Live Data Fetch
Morning Spike Strategy | TP=+0.40% | SL=-0.20%
Fetches data from Alpaca API for backtest
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# ── CONFIG ────────────────────────────────────────────────────────────
API_KEY    = os.getenv("ALPACA_API_KEY", "PKAJ7LELQVQMPJPEJTGZDRT3XP")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ")

TP_PCT       = 0.004    # +0.40%
SL_PCT       = 0.002    # -0.20%
MIN_RVOL     = 2.0      # volume spike requirement (relaxed from 3.0)
MIN_5MIN_RETURN = 0.003  # 0.3% 5-min return requirement (relaxed from 0.5%)

MAX_POSITIONS_PER_SCAN = 2  # take top 2 scored signals per scan

SCAN_START   = time(9, 35)
SCAN_END     = time(11, 0)
FORCE_CLOSE  = time(15, 55)

POSITION_SIZE = 1000    # $1000 per trade

SYMBOLS = [
    "NVDA", "TSLA", "META", "AVGO", "AMZN",
    "MSFT", "AAPL", "GOOGL", "AMD", "COIN"
]

ET = ZoneInfo("America/New_York")

# ── DATA FETCH ───────────────────────────────────────────────────────
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)


def fetch_bars(symbol, start, end, timeframe=TimeFrame.Minute):
    """Fetch bars from Alpaca."""
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
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


# ── SIGNAL DETECTION ─────────────────────────────────────────────────
def calculate_vwap(df):
    """Calculate Volume Weighted Average Price."""
    typical = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical * df['volume']).cumsum() / df['volume'].cumsum()
    return vwap


def calculate_vwap_slope(df, lookback=5):
    """Calculate VWAP slope (rising/falling)."""
    if len(df) < lookback + 1:
        return 0
    current_vwap = df['vwap'].iloc[-1]
    prev_vwap = df['vwap'].iloc[-(lookback+1)]
    return current_vwap - prev_vwap


def detect_signals(symbols_data, current_time):
    """
    Detect signals with new rules and scoring.
    
    LONG:
    - Price > VWAP
    - VWAP slope > 0
    - RVOL > 3
    - 5-min return > +0.5%
    - New high of day
    
    SHORT:
    - Price < VWAP
    - VWAP slope < 0
    - RVOL > 3
    - 5-min return < -0.5%
    - New low of day
    
    Score = rvol*2 + abs(5min_return) + distance_from_vwap
    """
    signals = []
    
    for symbol, df in symbols_data.items():
        if df is None or len(df) < 30:
            continue
        
        # Calculate indicators
        df['vwap'] = calculate_vwap(df)
        vwap_slope = calculate_vwap_slope(df)
        
        recent = df.iloc[-1]
        price = recent['close']
        vwap = recent['vwap']
        
        # RVOL calculation
        avg_volume = df["volume"].iloc[-21:-1].mean()
        rvol = recent["volume"] / avg_volume if avg_volume > 0 else 0
        
        if rvol < MIN_RVOL:
            continue
        
        # 5-min return
        if len(df) >= 6:
            price_5min_ago = df.iloc[-6]['close']
            return_5min = (price - price_5min_ago) / price_5min_ago
        else:
            continue
        
        # New high/low of session (last 60 bars = 1 hour for 1m, more achievable)
        session_bars = min(60, len(df))
        session_high = df.tail(session_bars)['high'].max()
        session_low = df.tail(session_bars)['low'].min()
        
        # Distance from VWAP (as percentage)
        dist_from_vwap = abs(price - vwap) / vwap
        
        # LONG conditions
        if price > vwap and vwap_slope > 0 and return_5min > MIN_5MIN_RETURN and price >= session_high:
            score = rvol * 2 + abs(return_5min) + dist_from_vwap
            signals.append({
                'symbol': symbol,
                'direction': 'long',
                'price': price,
                'score': score,
                'rvol': rvol,
                'return_5min': return_5min,
                'dist_vwap': dist_from_vwap
            })
        
        # SHORT conditions
        elif price < vwap and vwap_slope < 0 and return_5min < -MIN_5MIN_RETURN and price <= session_low:
            score = rvol * 2 + abs(return_5min) + dist_from_vwap
            signals.append({
                'symbol': symbol,
                'direction': 'short',
                'price': price,
                'score': score,
                'rvol': rvol,
                'return_5min': return_5min,
                'dist_vwap': dist_from_vwap
            })
    
    # Sort by score descending and return top signals
    signals.sort(key=lambda x: x['score'], reverse=True)
    return signals[:MAX_POSITIONS_PER_SCAN]


# ── BACKTEST ──────────────────────────────────────────────────────────
def run_backtest():
    all_trades = []
    open_positions = {}  # symbol -> {entry_price, direction, entry_time}

    # Date range: last 6 months
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)

    print(f"Fetching 6 months of data: {start_date.date()} to {end_date.date()}")
    print(f"Symbols: {SYMBOLS}")
    print("="*70)

    # Fetch all symbol data first
    symbols_data = {}
    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...")
        df = fetch_bars(symbol, start_date, end_date)
        if df is not None and len(df) >= 100:
            print(f"  Loaded {len(df)} bars")
            symbols_data[symbol] = df
        else:
            print(f"  Insufficient data for {symbol}")

    if not symbols_data:
        print("No data loaded!")
        return pd.DataFrame(all_trades)

    # Get all unique timestamps across all symbols
    all_timestamps = set()
    for df in symbols_data.values():
        all_timestamps.update(df['timestamp'].tolist())
    all_timestamps = sorted(all_timestamps)

    print(f"\nRunning backtest on {len(all_timestamps)} timestamps...")

    for ts in all_timestamps:
        ts = pd.to_datetime(ts)
        time_only = ts.time()
        date_only = ts.date()

        # Skip weekends
        if ts.weekday() >= 5:
            continue

        # Close positions at force close time
        if time_only >= FORCE_CLOSE:
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
                        'exit_type': 'eod', 'shares': int(POSITION_SIZE / pos['entry_price'])
                    })
                except:
                    pass
            open_positions.clear()
            continue

        # Manage exits for open positions
        for sym, pos in list(open_positions.items()):
            df = symbols_data[sym]
            try:
                current_row = df[df['timestamp'] <= ts].iloc[-1]
                current_price = current_row['close']
                pnl_pct = calculate_pnl(pos['entry_price'], current_price, pos['direction'])

                if pnl_pct >= TP_PCT or pnl_pct <= -SL_PCT:
                    exit_type = 'tp' if pnl_pct >= TP_PCT else 'sl'
                    all_trades.append({
                        'symbol': sym, 'date': date_only,
                        'direction': pos['direction'], 'entry_price': pos['entry_price'],
                        'exit_price': current_price, 'entry_time': pos['entry_time'],
                        'exit_time': ts, 'pnl_pct': pnl_pct,
                        'exit_type': exit_type, 'shares': int(POSITION_SIZE / pos['entry_price'])
                    })
                    del open_positions[sym]
            except:
                pass

        # Look for new entries during scan window
        if SCAN_START <= time_only <= SCAN_END and len(open_positions) < MAX_POSITIONS_PER_SCAN:
            # Build symbol windows for signal detection
            symbol_windows = {}
            for sym, df in symbols_data.items():
                if sym in open_positions:
                    continue  # Skip if already in position
                try:
                    window = df[df['timestamp'] <= ts].tail(60).copy()
                    if len(window) >= 30:
                        symbol_windows[sym] = window
                except:
                    pass

            # Detect signals
            signals = detect_signals(symbol_windows, ts)

            # Enter top signals up to max positions
            slots_available = MAX_POSITIONS_PER_SCAN - len(open_positions)
            for sig in signals[:slots_available]:
                sym = sig['symbol']
                open_positions[sym] = {
                    'entry_price': sig['price'],
                    'direction': sig['direction'],
                    'entry_time': ts
                }

    return pd.DataFrame(all_trades)


def calculate_pnl(entry, exit, direction):
    if direction == 'long':
        return (exit - entry) / entry
    return (entry - exit) / entry


# ── ANALYSIS ───────────────────────────────────────────────────────────
def analyze_results(trades_df):
    if trades_df.empty:
        print("\nNo trades generated")
        return

    print("\n" + "="*70)
    print("BOOF 30 BACKTEST RESULTS — 6 Month Morning Spike")
    print("="*70)

    total_trades = len(trades_df)
    wins = len(trades_df[trades_df['pnl_pct'] > 0])
    losses = total_trades - wins
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    print(f"\nTotal Trades: {total_trades}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")

    if wins > 0:
        avg_win = trades_df[trades_df['pnl_pct'] > 0]['pnl_pct'].mean() * 100
        print(f"Avg Win: +{avg_win:.2f}%")
    if losses > 0:
        avg_loss = trades_df[trades_df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100
        print(f"Avg Loss: {avg_loss:.2f}%")

    # Dollar P&L
    trades_df['dollar_pnl'] = trades_df['pnl_pct'] * POSITION_SIZE
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
        'dollar_pnl': 'sum', 'symbol': 'count'
    }).rename(columns={'symbol': 'trades'})

    print("\n" + "-"*70)
    print("Monthly Breakdown:")
    print("-"*70)
    for month, row in monthly.iterrows():
        print(f"  {month}: {int(row['trades']):3d} trades | P&L: ${row['dollar_pnl']:+.2f}")

    # Symbol performance
    print("\n" + "-"*70)
    print("By Symbol:")
    print("-"*70)
    sym_stats = trades_df.groupby('symbol').agg({
        'symbol': 'count', 'dollar_pnl': 'sum', 'pnl_pct': 'mean'
    }).rename(columns={'symbol': 'trades'}).sort_values('trades', ascending=False)

    for sym, row in sym_stats.iterrows():
        print(f"  {sym:6s}: {int(row['trades']):3d} trades | P&L: ${row['dollar_pnl']:+.2f} | Avg: {row['pnl_pct']*100:+.2f}%")

    # Exit types
    print("\n" + "-"*70)
    print("Exit Types:")
    print("-"*70)
    for exit_type, count in trades_df['exit_type'].value_counts().items():
        pct = count / total_trades * 100
        print(f"  {exit_type:12s}: {count:3d} ({pct:.1f}%)")

    print("\n" + "="*70)
    trades_df.to_csv('backtest_boof30_6mo_results.csv', index=False)
    print("Results saved to backtest_boof30_6mo_results.csv")


# ── MAIN ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting Boof 30 6-Month Backtest...")
    print(f"TP: {TP_PCT*100:.2f}% | SL: {SL_PCT*100:.2f}% | Min RVOL: {MIN_RVOL}")
    print(f"Scan: {SCAN_START} to {SCAN_END} ET")
    print("="*70)

    trades = run_backtest()
    analyze_results(trades)
