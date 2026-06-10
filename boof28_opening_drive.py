"""
BOOF 28 - Opening Drive Momentum Strategy
9:30-10:30 AM momentum scan with RVOL + Relative Strength
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Universe - S&P 500 core holdings
SYMBOLS = ['AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'BRK.B', 'UNH', 
           'JNJ', 'XOM', 'JPM', 'V', 'PG', 'HD', 'MA', 'CVX', 'LLY', 'ABBV', 'MRK',
           'PEP', 'KO', 'BAC', 'AVGO', 'PFE', 'TMO', 'COST', 'DIS', 'ABT', 'ACN',
           'WMT', 'MCD', 'ADBE', 'CSCO', 'VZ', 'NKE', 'CMCSA', 'TXN', 'PM', 'NFLX',
           'BMY', 'QCOM', 'HON', 'UNP', 'LOW', 'LIN', 'AMGN', 'RTX', 'IBM', 'GS',
           'SPY']  # 50 largest S&P 500 + SPY for relative strength

# Config
OPEN_START = 9*60 + 30  # 9:30 AM in minutes
OPEN_END = 10*60 + 30   # 10:30 AM in minutes
RVOL_THRESHOLD = 3.0
RVOL_LOOKBACK_DAYS = 20
GAP_THRESHOLD = 0.01    # 1%
REL_STR_THRESHOLD = 0.01  # 1% outperformance

def get_intraday_data(sym, date, timeframe='1Min'):
    """Fetch 1-minute data for a specific date plus lookback for RVOL"""
    start = date - timedelta(days=RVOL_LOOKBACK_DAYS + 5)  # Extra buffer
    end = date + timedelta(days=1)
    
    df = fetch_alpaca_bars(sym, start, end, timeframe, 
                          creds['api_key'], creds['secret_key'])
    
    if df is None or len(df) < 100:
        return None
    
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    
    # Parse timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    df = df.sort_values('timestamp')
    
    return df

def calculate_vwap(df):
    """Calculate VWAP"""
    typical = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (typical * df['volume']).cumsum() / df['volume'].cumsum()
    return df

def calculate_rvol(df, current_time, lookback_days=20):
    """
    Calculate Relative Volume:
    Current Volume / Average Volume For This Time Of Day (last 20 days)
    """
    # Get current bar's time (HH:MM)
    current_bar = df[df['timestamp'] <= current_time].iloc[-1] if len(df[df['timestamp'] <= current_time]) > 0 else None
    if current_bar is None:
        return None, None
    
    current_volume = current_bar['volume']
    current_time_of_day = current_bar['timestamp'].time()
    current_date = current_bar['timestamp'].date()
    
    # Get historical volumes at same time of day
    historical_volumes = []
    for days_back in range(1, lookback_days + 1):
        past_date = current_date - timedelta(days=days_back)
        # Skip weekends
        if past_date.weekday() >= 5:
            continue
        
        past_bars = df[
            (df['timestamp'].dt.date == past_date) & 
            (df['timestamp'].dt.time == current_time_of_day)
        ]
        if len(past_bars) > 0:
            historical_volumes.append(past_bars['volume'].iloc[0])
    
    if len(historical_volumes) < 10:  # Need at least 10 days of history
        return None, current_volume
    
    avg_volume = np.mean(historical_volumes)
    rvol = current_volume / avg_volume if avg_volume > 0 else 0
    
    return rvol, current_volume

def calculate_gap(df, current_time):
    """Calculate gap % from previous close"""
    current_bar = df[df['timestamp'] <= current_time].iloc[-1] if len(df[df['timestamp'] <= current_time]) > 0 else None
    if current_bar is None:
        return None
    
    current_date = current_bar['timestamp'].date()
    current_time_of_day = current_bar['timestamp'].time()
    
    # Get previous trading day's close
    prev_close = None
    for days_back in range(1, 10):  # Look back up to 10 days
        past_date = current_date - timedelta(days=days_back)
        if past_date.weekday() >= 5:
            continue
        
        past_day_data = df[df['timestamp'].dt.date == past_date]
        if len(past_day_data) > 0:
            prev_close = past_day_data['close'].iloc[-1]
            break
    
    if prev_close is None or prev_close == 0:
        return None
    
    gap_pct = (current_bar['open'] - prev_close) / prev_close
    return gap_pct

def calculate_relative_strength(df_stock, df_spy, current_time):
    """Calculate relative strength vs SPY"""
    stock_bar = df_stock[df_stock['timestamp'] <= current_time].iloc[-1] if len(df_stock[df_stock['timestamp'] <= current_time]) > 0 else None
    spy_bar = df_spy[df_spy['timestamp'] <= current_time].iloc[-1] if len(df_spy[df_spy['timestamp'] <= current_time]) > 0 else None
    
    if stock_bar is None or spy_bar is None:
        return None
    
    stock_return = (stock_bar['close'] - stock_bar['open']) / stock_bar['open']
    spy_return = (spy_bar['close'] - spy_bar['open']) / spy_bar['open']
    
    rel_strength = stock_return - spy_return
    return rel_strength

def get_opening_range(df, date):
    """Get opening range (first 5 minutes)"""
    day_data = df[df['timestamp'].dt.date == date.date()]
    if len(day_data) < 5:
        return None, None
    
    # First 5 bars = first ~5 minutes
    opening_bars = day_data.iloc[:5]
    or_high = opening_bars['high'].max()
    or_low = opening_bars['low'].min()
    
    return or_high, or_low

def calculate_score(rvol, gap, rel_strength):
    """Calculate composite score"""
    if rvol is None or gap is None or rel_strength is None:
        return None
    
    # RVOL * 0.5 + Gap% * 0.25 + Relative Strength * 0.25
    # Normalize gap and rel_strength to comparable scale (multiply by 100 for %)
    score = (rvol * 0.5) + (abs(gap) * 100 * 0.25) + (abs(rel_strength) * 100 * 0.25)
    return score

def simulate_trade(entry_price, direction, df, entry_idx, sl_r=1.0, tp_r=2.0):
    """Simulate trade with 1R SL, 2R TP"""
    if entry_idx >= len(df) - 1:
        return None, None
    
    # Calculate ATR for position sizing
    atr = 0
    if entry_idx >= 14:
        highs = df['high'].iloc[entry_idx-14:entry_idx].values
        lows = df['low'].iloc[entry_idx-14:entry_idx].values
        closes = df['close'].iloc[entry_idx-14:entry_idx].values
        trs = [max(h-l, abs(h-c), abs(l-c)) for h, l, c in zip(highs[1:], lows[1:], closes[:-1])]
        atr = np.mean(trs) if trs else 0
    
    if atr == 0:
        atr = entry_price * 0.001  # Default 0.1%
    
    if direction == 'LONG':
        sl = entry_price - atr * sl_r
        tp = entry_price + atr * tp_r
    else:
        sl = entry_price + atr * sl_r
        tp = entry_price - atr * tp_r
    
    # Check next bars (max hold until 11 AM or 20 bars)
    max_bars = min(20, len(df) - entry_idx - 1)
    
    for j in range(1, max_bars + 1):
        bar = df.iloc[entry_idx + j]
        
        if direction == 'LONG':
            if bar['low'] <= sl:
                return (sl - entry_price) / entry_price * 100, 'SL'
            if bar['high'] >= tp:
                return (tp - entry_price) / entry_price * 100, 'TP'
        else:
            if bar['high'] >= sl:
                return (entry_price - sl) / entry_price * 100, 'SL'
            if bar['low'] <= tp:
                return (entry_price - tp) / entry_price * 100, 'TP'
    
    # Time exit
    exit_price = df.iloc[entry_idx + max_bars]['close']
    if direction == 'LONG':
        return (exit_price - entry_price) / entry_price * 100, 'TIME'
    else:
        return (entry_price - exit_price) / entry_price * 100, 'TIME'

def run_boof28_backtest(test_date):
    """Run Boof 28 backtest for a single day"""
    print(f'\n=== Boof 28 Backtest: {test_date.date()} ===\n')
    
    # Fetch data for all symbols
    data = {}
    print('Fetching data...')
    for sym in SYMBOLS:
        df = get_intraday_data(sym, test_date)
        if df is not None:
            data[sym] = df
        else:
            print(f'  {sym}: No data')
    
    if len(data) < 5:
        print('Not enough data')
        return []
    
    # Get SPY for relative strength
    spy_df = data.get('SPY')
    if spy_df is None:
        print('SPY data required for relative strength')
        return []
    
    # Get opening ranges
    opening_ranges = {}
    for sym, df in data.items():
        or_high, or_low = get_opening_range(df, test_date)
        if or_high and or_low:
            opening_ranges[sym] = {'high': or_high, 'low': or_low}
    
    print(f'Opening ranges calculated for {len(opening_ranges)} symbols\n')
    
    # Scan 9:30-10:30
    trades = []
    
    # Generate scan times (every minute from 9:35 to 10:30)
    scan_times = []
    base_time = datetime.combine(test_date.date(), datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)
    for i in range(56):  # 9:35 to 10:30 = 55 minutes
        scan_times.append(base_time + timedelta(minutes=i))
    
    # Track which stocks we've already entered
    entered_stocks = set()
    
    print(f'\nScanning {len(scan_times)} time points from {scan_times[0]} to {scan_times[-1]}')
    print(f'Data available for: {list(data.keys())[:5]}...')
    
    for i, scan_time in enumerate(scan_times):
        candidates = []
        
        # Debug first scan
        if i == 0:
            print(f"\nFirst scan at {scan_time}")
            print(f"SPY data range: {spy_df['timestamp'].min()} to {spy_df['timestamp'].max()}")
        
        for sym, df in data.items():
            if sym == 'SPY' or sym not in opening_ranges:
                continue
            
            # Skip if already entered this stock today
            if sym in entered_stocks:
                continue
            
            # Get current bar
            current_bars = df[df['timestamp'] <= scan_time]
            if len(current_bars) == 0:
                continue
            
            current_bar = current_bars.iloc[-1]
            current_price = current_bar['close']
            
            # Calculate VWAP
            df_vwap = calculate_vwap(current_bars.copy())
            vwap = df_vwap['vwap'].iloc[-1]
            
            # Calculate metrics
            rvol, _ = calculate_rvol(df, scan_time)
            gap = calculate_gap(df, scan_time)
            rel_strength = calculate_relative_strength(df, spy_df, scan_time)
            
            if rvol is None or gap is None or rel_strength is None:
                continue
            
            or_high = opening_ranges[sym]['high']
            or_low = opening_ranges[sym]['low']
            
            # Debug first symbol at first scan time
            if scan_time == scan_times[0] and sym == list(opening_ranges.keys())[0]:
                print(f"\nDEBUG {sym} at {scan_time.strftime('%H:%M')}:")
                print(f"  Price: {current_price:.2f}, VWAP: {vwap:.2f}")
                print(f"  OR High: {or_high:.2f}, OR Low: {or_low:.2f}")
                print(f"  RVOL: {rvol}, Gap: {gap}, RelStr: {rel_strength}")
            
            # Check long setup
            long_setup = (
                rvol is not None and rvol > RVOL_THRESHOLD and
                gap is not None and gap > GAP_THRESHOLD and
                current_price > vwap and
                current_price > or_high  # Break above opening range
            )
            
            # Check short setup
            short_setup = (
                rvol is not None and rvol > RVOL_THRESHOLD and
                gap is not None and gap < -GAP_THRESHOLD and
                current_price < vwap and
                current_price < or_low  # Break below opening range
            )
            
            if long_setup or short_setup:
                score = calculate_score(rvol, gap, rel_strength)
                candidates.append({
                    'sym': sym,
                    'direction': 'LONG' if long_setup else 'SHORT',
                    'price': current_price,
                    'rvol': rvol,
                    'gap': gap,
                    'rel_str': rel_strength,
                    'vwap': vwap,
                    'score': score,
                    'entry_time': scan_time,
                    'entry_idx': current_bars.index[-1]
                })
        
        # Take top 5 by score
        if candidates:
            candidates.sort(key=lambda x: x['score'], reverse=True)
            top_candidates = candidates[:5]
            
            print(f"\n{scan_time.strftime('%H:%M')} - Top candidates:")
            for c in top_candidates[:3]:  # Show top 3
                print(f"  {c['sym']}: {c['direction']} @ {c['price']:.2f}, "
                      f"RVOL={c['rvol']:.1f}, Gap={c['gap']*100:.1f}%, "
                      f"Score={c['score']:.1f}")
            
            # Simulate trades for top candidates
            for candidate in top_candidates:
                sym = candidate['sym']
                if sym in entered_stocks:
                    continue
                
                df = data[sym]
                pnl, exit_type = simulate_trade(
                    candidate['price'],
                    candidate['direction'],
                    df,
                    candidate['entry_idx']
                )
                
                if pnl is not None:
                    trades.append({
                        'sym': sym,
                        'direction': candidate['direction'],
                        'entry_time': candidate['entry_time'],
                        'entry_price': candidate['price'],
                        'pnl': pnl,
                        'exit_type': exit_type,
                        'rvol': candidate['rvol'],
                        'score': candidate['score']
                    })
                    entered_stocks.add(sym)
                    print(f"    -> {exit_type}, P&L: {pnl:.2f}%")
    
    return trades

# MAIN
print('='*70)
print('BOOF 28 - OPENING DRIVE MOMENTUM STRATEGY')
print('9:30-10:30 AM Scan with RVOL + Relative Strength')
print('='*70)

# Test on available date
test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)  # Test single day first - Jan 2026
trades = run_boof28_backtest(test_date)

print('\n' + '='*70)
print('DAILY SUMMARY')
print('='*70)

if trades:
    pnls = [t['pnl'] for t in trades]
    wins = len([p for p in pnls if p > 0])
    
    print(f'Total trades: {len(trades)}')
    print(f'Win rate: {wins/len(trades)*100:.1f}%')
    print(f'Total P&L: {sum(pnls):.2f}%')
    print(f'Avg per trade: {np.mean(pnls):.2f}%')
    
    print('\nBy Symbol:')
    by_sym = {}
    for t in trades:
        if t['sym'] not in by_sym:
            by_sym[t['sym']] = []
        by_sym[t['sym']].append(t['pnl'])
    
    for sym, pnls in sorted(by_sym.items(), key=lambda x: sum(x[1]), reverse=True):
        print(f'  {sym}: {len(pnls)} trades, {sum(pnls):.2f}% total')
else:
    print('No trades generated')

print('='*70)
