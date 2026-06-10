"""
BOOF 28 - Simple Version
Based on working template
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Universe - start with 10, expand later
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "JPM", "V"]
LOOKBACK_DAYS = 20

START_TIME = "09:30"
END_TIME = "10:30"

def get_intraday(symbol, date):
    """Get 5m bars for a specific date"""
    start = date - timedelta(days=LOOKBACK_DAYS)
    end = date + timedelta(days=1)
    
    df = fetch_alpaca_bars(symbol, start, end, '5Min', creds['api_key'], creds['secret_key'])
    
    if df is None or len(df) < 30:
        return None
    
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    
    # Filter to target date and trading hours
    df = df[df['timestamp'].dt.date == date.date()]
    
    return df if len(df) > 0 else None

def calculate_vwap(df):
    """Calculate VWAP"""
    return (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

def get_avg_volume(symbol, date):
    """Get average daily volume over lookback period"""
    start = date - timedelta(days=LOOKBACK_DAYS + 5)
    end = date
    
    df = fetch_alpaca_bars(symbol, start, end, '1Day', creds['api_key'], creds['secret_key'])
    
    if df is None or len(df) < 5:
        return 0
    
    if 'volume' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    
    return df['volume'].mean() if len(df) > 0 else 0

def detect_volume_spike(df, avg_daily_vol):
    """Detect if current volume is spiking (RVOL)"""
    if avg_daily_vol == 0:
        return 0
    
    # Current volume in first hour
    current_vol = df['volume'].sum()
    
    # Expected volume in first hour (roughly 15% of daily)
    expected_vol = avg_daily_vol * 0.15
    
    return current_vol / expected_vol if expected_vol > 0 else 0

def scan_stock(symbol, date):
    """Scan a single stock for opening drive signal"""
    try:
        df = get_intraday(symbol, date)
        
        if df is None or len(df) < 3:
            return None
        
        # Calculate VWAP
        vwap = calculate_vwap(df)
        
        # Get current metrics (at end of available bars, simulating 9:35-10:00)
        price = df['close'].iloc[-1]
        vwap_val = vwap.iloc[-1]
        
        # Get average volume
        avg_vol = get_avg_volume(symbol, date)
        rvol = detect_volume_spike(df, avg_vol)
        
        # MOMENTUM CONFIRMATION
        # Check last 3 bars for trend
        if len(df) >= 3:
            last_3 = df['close'].iloc[-3:]
            trend_up = last_3.is_monotonic_increasing
            trend_down = last_3.is_monotonic_decreasing
        else:
            trend_up = trend_down = False
        
        # Determine direction with momentum confirmation
        direction = None
        if price > vwap_val and trend_up:
            direction = "LONG"
        elif price < vwap_val and trend_down:
            direction = "SHORT"
        
        # Filter: RVOL must be > 2 AND have direction
        if rvol < 2 or direction is None:
            return None
        
        return {
            "symbol": symbol,
            "price": price,
            "vwap": vwap_val,
            "rvol": rvol,
            "direction": direction,
            "date": date,
            "trend_up": trend_up,
            "trend_down": trend_down
        }
        
    except Exception as e:
        print(f"{symbol} error: {e}")
        return None

def simulate_trade(signal, df):
    """Simulate trade outcome"""
    try:
        entry_price = signal['price']
        direction = signal['direction']
        
        # Simple 1% target, 0.5% stop
        if direction == "LONG":
            target = entry_price * 1.01
            stop = entry_price * 0.995
        else:
            target = entry_price * 0.99
            stop = entry_price * 1.005
        
        # Check next bars for exit
        for i in range(len(df)):
            bar = df.iloc[i]
            
            if direction == "LONG":
                if bar['high'] >= target:
                    return 1.0, 'TP'
                if bar['low'] <= stop:
                    return -0.5, 'SL'
            else:
                if bar['low'] <= target:
                    return 1.0, 'TP'
                if bar['high'] >= stop:
                    return -0.5, 'SL'
        
        # Time exit
        exit_price = df['close'].iloc[-1]
        if direction == "LONG":
            return (exit_price - entry_price) / entry_price * 100, 'TIME'
        else:
            return (entry_price - exit_price) / entry_price * 100, 'TIME'
            
    except Exception as e:
        print(f"Sim error: {e}")
        return None, None

# -----------------------------
# MAIN BACKTEST
# -----------------------------
def run_backtest():
    # Test period: Dec 2025 - Jan 2026
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    
    print('='*70)
    print('BOOF 28 - SIMPLE VWAP + RVOL SYSTEM')
    print(f'Universe: {len(UNIVERSE)} stocks')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print('='*70)
    
    # Generate trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)
    
    print(f'\nScanning {len(trading_days)} trading days...\n')
    
    all_trades = []
    
    for date in trading_days:
        print(f'{date.date()}:', end=' ')
        
        signals = []
        for symbol in UNIVERSE:
            sig = scan_stock(symbol, date)
            if sig:
                signals.append(sig)
            time.sleep(0.1)
        
        if not signals:
            print('No signals')
            continue
        
        # Rank by RVOL
        signals.sort(key=lambda x: x['rvol'], reverse=True)
        
        # Take top 3
        day_pnl = 0
        for sig in signals[:3]:
            # Get intraday data for simulation
            df = get_intraday(sig['symbol'], date)
            if df is not None and len(df) > 0:
                pnl, exit_type = simulate_trade(sig, df)
                if pnl is not None:
                    all_trades.append({
                        'date': date,
                        'symbol': sig['symbol'],
                        'direction': sig['direction'],
                        'rvol': sig['rvol'],
                        'pnl': pnl,
                        'exit': exit_type
                    })
                    day_pnl += pnl
        
        print(f'{len(signals)} signals, {len([t for t in all_trades if t["date"] == date])} trades, P&L: {day_pnl:.2f}%')
    
    return all_trades

# -----------------------------
# RESULTS
# -----------------------------
if __name__ == "__main__":
    trades = run_backtest()
    
    print('\n' + '='*70)
    print('FINAL RESULTS')
    print('='*70)
    
    if trades:
        df = pd.DataFrame(trades)
        
        print(f"\nTotal Trades: {len(df)}")
        print(f"Win Rate: {len(df[df['pnl'] > 0]) / len(df) * 100:.1f}%")
        print(f"Avg P&L: {df['pnl'].mean():.3f}%")
        print(f"Total Return: {df['pnl'].sum():.2f}%")
        
        wins = df[df['pnl'] > 0]['pnl'].sum()
        losses = abs(df[df['pnl'] < 0]['pnl'].sum())
        pf = wins / losses if losses > 0 else 999
        print(f"Profit Factor: {pf:.2f}")
        
        print("\nBy Exit Type:")
        for et, group in df.groupby('exit'):
            print(f"  {et}: {len(group)} trades, {group['pnl'].sum():.2f}%")
        
        print("\nBy Symbol:")
        for sym, group in df.groupby('symbol'):
            print(f"  {sym}: {len(group)} trades, {group['pnl'].sum():.2f}%")
    else:
        print("No trades generated")
    
    print('='*70)
