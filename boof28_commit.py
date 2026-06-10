"""
BOOF 28 - Wait-for-Commit Model
Detect spike → Wait 3-6 bars → Enter on secondary move
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "JPM", "V",
            "UNH", "XOM", "MA", "HD", "PG", "COST", "JNJ", "WMT", "KO", "PEP"]

LOOKBACK_DAYS = 20

def get_intraday(symbol, date):
    """Get 5m bars"""
    start = date - timedelta(days=LOOKBACK_DAYS)
    end = date + timedelta(days=1)
    
    df = fetch_alpaca_bars(symbol, start, end, '5Min', creds['api_key'], creds['secret_key'])
    
    if df is None or len(df) < 30:
        return None
    
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    df = df[df['timestamp'].dt.date == date.date()]
    
    return df if len(df) >= 10 else None

def get_avg_volume(symbol, date):
    """Average daily volume"""
    start = date - timedelta(days=LOOKBACK_DAYS + 5)
    end = date
    df = fetch_alpaca_bars(symbol, start, end, '1Day', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 5:
        return 0
    if 'volume' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    return df['volume'].mean()

def calculate_vwap(df):
    return (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

def calculate_vwap_slope(vwap_series, lookback=3):
    """Calculate VWAP slope (positive = rising)"""
    if len(vwap_series) < lookback:
        return 0
    recent = vwap_series.iloc[-lookback:]
    return (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0] * 100

def detect_spike_and_commit(df, symbol, spy_df=None):
    """
    STEP 1: Detect RVOL spike
    STEP 2: Wait 3-6 bars for commit
    STEP 3: Enter on secondary move
    QUALITY FILTERS: RVOL>2.5, beat SPY, VWAP slope agrees
    """
    if len(df) < 10:
        return None
    
    vwap = calculate_vwap(df)
    
    # Calculate RVOL for each bar
    avg_vol = df['volume'].mean() * len(df)
    
    # Get SPY returns for comparison (if available)
    spy_returns = {}
    if spy_df is not None and len(spy_df) > 0:
        spy_open = spy_df['open'].iloc[0]
        for idx in range(len(spy_df)):
            spy_returns[idx] = (spy_df['close'].iloc[idx] - spy_open) / spy_open * 100
    
    for i in range(3, len(df) - 6):
        current_price = df['close'].iloc[i]
        current_vwap = vwap.iloc[i]
        
        # RVOL
        current_vol = df['volume'].iloc[i]
        rvol = current_vol / (avg_vol * 0.15 / len(df)) if avg_vol > 0 else 0
        
        # QUALITY FILTER 1: Strong RVOL only (>2.5)
        if rvol < 2.5:
            continue
        
        # QUALITY FILTER 2: VWAP slope must agree with direction
        vwap_slope = calculate_vwap_slope(vwap.iloc[:i+1])
        
        spike_low = df['low'].iloc[i]
        spike_high = df['high'].iloc[i]
        
        # Long case: above VWAP with positive slope
        if current_price > current_vwap and vwap_slope > 0:
            # QUALITY FILTER 3: Must beat SPY
            if spy_df is not None and i in spy_returns:
                stock_ret = (current_price - df['open'].iloc[0]) / df['open'].iloc[0] * 100
                if stock_ret <= spy_returns[i]:
                    continue  # Not beating SPY
            
            commit_window = df.iloc[i+1:min(i+7, len(df))]
            if len(commit_window) < 3:
                continue
            
            holds_vwap = all(commit_window['close'] > vwap.iloc[i+1:min(i+7, len(df))])
            no_reversal = all(commit_window['low'] > spike_low * 0.995)
            
            if not (holds_vwap and no_reversal):
                continue
            
            local_high = commit_window['high'].max()
            entry_bar = None
            for j in range(i+3, min(i+7, len(df))):
                if df['high'].iloc[j] > local_high * 0.998:
                    entry_bar = j
                    break
            
            if entry_bar:
                return {
                    'symbol': symbol,
                    'entry_idx': entry_bar,
                    'entry_price': df['close'].iloc[entry_bar],
                    'direction': 'LONG',
                    'rvol': rvol,
                    'vwap_slope': vwap_slope,
                    'quality_score': rvol * 0.5 + vwap_slope * 0.3
                }
        
        # Short case: below VWAP with negative slope
        elif current_price < current_vwap and vwap_slope < 0:
            # QUALITY FILTER 3: Must underperform SPY (for shorts)
            if spy_df is not None and i in spy_returns:
                stock_ret = (current_price - df['open'].iloc[0]) / df['open'].iloc[0] * 100
                if stock_ret >= spy_returns[i]:
                    continue  # Not underperforming SPY
            
            commit_window = df.iloc[i+1:min(i+7, len(df))]
            if len(commit_window) < 3:
                continue
            
            holds_vwap = all(commit_window['close'] < vwap.iloc[i+1:min(i+7, len(df))])
            no_reversal = all(commit_window['high'] < spike_high * 1.005)
            
            if not (holds_vwap and no_reversal):
                continue
            
            local_low = commit_window['low'].min()
            entry_bar = None
            for j in range(i+3, min(i+7, len(df))):
                if df['low'].iloc[j] < local_low * 1.002:
                    entry_bar = j
                    break
            
            if entry_bar:
                return {
                    'symbol': symbol,
                    'entry_idx': entry_bar,
                    'entry_price': df['close'].iloc[entry_bar],
                    'direction': 'SHORT',
                    'rvol': rvol,
                    'vwap_slope': vwap_slope,
                    'quality_score': rvol * 0.5 + abs(vwap_slope) * 0.3
                }
    
    return None

def simulate(df, entry_idx, entry_price, direction, max_bars=12):
    """Simulate with 1% TP, 0.5% SL"""
    if direction == 'LONG':
        tp = entry_price * 1.01
        sl = entry_price * 0.995
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['high'].iloc[i] >= tp:
                return 1.0, 'TP'
            if df['low'].iloc[i] <= sl:
                return -0.5, 'SL'
    else:
        tp = entry_price * 0.99
        sl = entry_price * 1.005
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['low'].iloc[i] <= tp:
                return 1.0, 'TP'
            if df['high'].iloc[i] >= sl:
                return -0.5, 'SL'
    
    exit_price = df['close'].iloc[min(entry_idx + max_bars - 1, len(df) - 1)]
    if direction == 'LONG':
        return (exit_price - entry_price) / entry_price * 100, 'TIME'
    else:
        return (entry_price - exit_price) / entry_price * 100, 'TIME'

def run_backtest():
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 31, tzinfo=timezone.utc)
    
    print('='*70)
    print('BOOF 28 - WAIT-FOR-COMMIT MODEL')
    print('Detect spike → Wait 3-6 bars → Enter on secondary move')
    print('='*70)
    
    # Trading days
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    
    print(f'\nBacktesting {len(days)} days, {len(UNIVERSE)} symbols...\n')
    
    all_trades = []
    
    for date in days:
        day_signals = []
        
        # Get SPY data first for comparison
        spy_df = get_intraday('SPY', date)
        
        for sym in UNIVERSE:
            df = get_intraday(sym, date)
            if df is None:
                continue
            
            signal = detect_spike_and_commit(df, sym, spy_df)
            if signal:
                day_signals.append({
                    'signal': signal,
                    'df': df,
                    'date': date
                })
            
            time.sleep(0.05)
        
        # RANKING: Sort by quality score, take top 3-5
        if day_signals:
            day_signals.sort(key=lambda x: x['signal']['quality_score'], reverse=True)
            top_signals = day_signals[:5]  # Take top 5 max
            
            day_trades = []
            for sig_data in top_signals:
                sig = sig_data['signal']
                df = sig_data['df']
                
                pnl, exit_type = simulate(df, sig['entry_idx'], 
                                         sig['entry_price'], sig['direction'])
                if pnl is not None:
                    day_trades.append({
                        'date': date,
                        'symbol': sig['symbol'],
                        'direction': sig['direction'],
                        'rvol': sig['rvol'],
                        'quality_score': sig['quality_score'],
                        'pnl': pnl,
                        'exit': exit_type
                    })
            
            all_trades.extend(day_trades)
            if day_trades:
                day_pnl = sum(t['pnl'] for t in day_trades)
                print(f"{date.date()}: {len(day_signals)} candidates, top {len(day_trades)} trades, P&L: {day_pnl:+.2f}%")
    
    return all_trades

if __name__ == "__main__":
    trades = run_backtest()
    
    print('\n' + '='*70)
    print('FINAL RESULTS')
    print('='*70)
    
    if trades:
        df = pd.DataFrame(trades)
        wins = len(df[df['pnl'] > 0])
        
        print(f"\nTotal Trades: {len(df)}")
        print(f"Win Rate: {wins / len(df) * 100:.1f}%")
        print(f"Avg P&L: {df['pnl'].mean():.3f}%")
        print(f"Total Return: {df['pnl'].sum():.2f}%")
        
        win_sum = df[df['pnl'] > 0]['pnl'].sum()
        loss_sum = abs(df[df['pnl'] < 0]['pnl'].sum())
        pf = win_sum / loss_sum if loss_sum > 0 else 999
        print(f"Profit Factor: {pf:.2f}")
        
        print("\nBy Direction:")
        for d, g in df.groupby('direction'):
            wr = len(g[g['pnl'] > 0]) / len(g) * 100
            print(f"  {d}: {len(g)} trades, {g['pnl'].sum():.2f}%, WR: {wr:.1f}%")
        
        print("\nTop Symbols:")
        for sym, pnl in df.groupby('symbol')['pnl'].sum().sort_values(ascending=False).head(10).items():
            cnt = len(df[df['symbol'] == sym])
            print(f"  {sym}: {cnt} trades, {pnl:+.2f}%")
    else:
        print("No trades generated")
    
    print('='*70)
