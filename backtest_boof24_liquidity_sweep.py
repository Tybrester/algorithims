"""BOOF 24 - Liquidity Sweep + Reversal (Institutional Structure)"""
import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# Config
ORB_MINUTES = 15  # 9:30-9:45 ET establishes range
SWEEP_LOOKBACK_BARS = 8  # How many bars after ORB to look for sweep
RECLAIM_BARS = 3  # Must reclaim back inside within this many bars
TP_PCT = 0.008  # 0.8% TP
SL_PCT = 0.004  # 0.4% SL (2:1 RR)

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA', 'AMZN', 'GOOGL', 'NFLX', 'AMD', 'MSFT', 'CRM']

def compute_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    cumtpv = (typical * df['volume']).cumsum()
    cumvol = df['volume'].cumsum()
    return cumtpv / cumvol

def calc_rel_volume(df, idx, lookback=20):
    if idx < lookback:
        return 1.0
    avg_vol = df['volume'].iloc[idx-lookback:idx].mean()
    if avg_vol == 0:
        return 1.0
    return df['volume'].iloc[idx] / avg_vol

def is_market_hours(timestamp):
    et_hour = timestamp.hour - 4
    et_minute = timestamp.minute
    if et_hour < 0:
        et_hour += 24
    minutes_since_open = (et_hour - 9) * 60 + et_minute
    return 0 <= minutes_since_open < 390

def backtest_liquidity_sweep(symbol, start_date, end_date, vol_threshold=1.5, use_volume=True):
    """Liquidity Sweep + Reversal Strategy"""
    trades = []
    stats = {'sweeps': 0, 'reclaims': 0, 'entered': 0}
    
    try:
        df = api.get_bars(
            symbol, '5Min',
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            limit=10000,
            feed='iex'
        ).df
        
        if len(df) < 50:
            return trades, stats
            
        df = df.reset_index()
        if 'timestamp' in df.columns:
            df['time'] = pd.to_datetime(df['timestamp'])
        elif 'index' in df.columns:
            df['time'] = pd.to_datetime(df['index'])
        
        df['vwap'] = compute_vwap(df)
        df['date'] = df['time'].dt.date
        
        for date, day_df in df.groupby('date'):
            if len(day_df) < ORB_MINUTES + SWEEP_LOOKBACK_BARS + 5:
                continue
            
            first_time = day_df['time'].iloc[0]
            if not is_market_hours(first_time):
                continue
            
            # ORB range
            orb_bars = day_df.iloc[:ORB_MINUTES]
            orb_high = orb_bars['high'].max()
            orb_low = orb_bars['low'].min()
            orb_mid = (orb_high + orb_low) / 2
            orb_range = orb_high - orb_low
            
            # Skip tiny range days (< 0.3%)
            if orb_range / orb_mid < 0.003:
                continue
            
            # Look for liquidity sweep in bars after ORB
            post_orb = day_df.iloc[ORB_MINUTES:].reset_index(drop=True)
            
            if len(post_orb) < SWEEP_LOOKBACK_BARS + 5:
                continue
            
            sweep_window = post_orb.iloc[:SWEEP_LOOKBACK_BARS]
            
            # Check for sweep above ORB high
            sweep_up_idx = None
            for i, (_, row) in enumerate(sweep_window.iterrows()):
                if row['high'] > orb_high:
                    # Check if close is back inside (failed breakout = sweep)
                    if row['close'] < orb_high:
                        sweep_up_idx = i
                        stats['sweeps'] += 1
                        break
            
            # Check for sweep below ORB low
            sweep_down_idx = None
            for i, (_, row) in enumerate(sweep_window.iterrows()):
                if row['low'] < orb_low:
                    # Check if close is back inside (failed breakout = sweep)
                    if row['close'] > orb_low:
                        sweep_down_idx = i
                        stats['sweeps'] += 1
                        break
            
            # Enter on reclaim of ORB midpoint after sweep up (enter SHORT)
            if sweep_up_idx is not None:
                entry_idx = None
                # Look for entry in next few bars - reclaim ORB midpoint
                reclaim_start = sweep_up_idx + 1
                reclaim_end = min(reclaim_start + RECLAIM_BARS, len(post_orb))
                
                for j in range(reclaim_start, reclaim_end):
                    if j >= len(post_orb):
                        break
                    row = post_orb.iloc[j]
                    
                    # Entry: Price below ORB midpoint after sweep (trap complete)
                    if row['close'] < orb_mid:
                        # Volume check
                        if use_volume:
                            df_idx = ORB_MINUTES + j
                            rel_vol = calc_rel_volume(day_df, df_idx, 20)
                            if rel_vol < vol_threshold:
                                continue
                        
                        entry = row['close']
                        entry_idx = j
                        stats['reclaims'] += 1
                        stats['entered'] += 1
                        
                        # Simulate SHORT
                        tp = entry * (1 - TP_PCT)
                        sl = entry * (1 + SL_PCT)
                        
                        remaining = post_orb.iloc[j+1:]
                        for _, exit_row in remaining.iterrows():
                            if exit_row['low'] <= tp:
                                trades.append({
                                    'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': tp,
                                    'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win',
                                    'setup': 'sweep_up',
                                    'orb_range': orb_range / orb_mid * 100
                                })
                                break
                            elif exit_row['high'] >= sl:
                                trades.append({
                                    'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': sl,
                                    'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss',
                                    'setup': 'sweep_up',
                                    'orb_range': orb_range / orb_mid * 100
                                })
                                break
                        break
            
            # Enter on reclaim of ORB midpoint after sweep down (enter LONG)
            if sweep_down_idx is not None:
                entry_idx = None
                reclaim_start = sweep_down_idx + 1
                reclaim_end = min(reclaim_start + RECLAIM_BARS, len(post_orb))
                
                for j in range(reclaim_start, reclaim_end):
                    if j >= len(post_orb):
                        break
                    row = post_orb.iloc[j]
                    
                    # Entry: Price above ORB midpoint after sweep down
                    if row['close'] > orb_mid:
                        # Volume check
                        if use_volume:
                            df_idx = ORB_MINUTES + j
                            rel_vol = calc_rel_volume(day_df, df_idx, 20)
                            if rel_vol < vol_threshold:
                                continue
                        
                        entry = row['close']
                        entry_idx = j
                        stats['reclaims'] += 1
                        stats['entered'] += 1
                        
                        # Simulate LONG
                        tp = entry * (1 + TP_PCT)
                        sl = entry * (1 - SL_PCT)
                        
                        remaining = post_orb.iloc[j+1:]
                        for _, exit_row in remaining.iterrows():
                            if exit_row['high'] >= tp:
                                trades.append({
                                    'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': tp,
                                    'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win',
                                    'setup': 'sweep_down',
                                    'orb_range': orb_range / orb_mid * 100
                                })
                                break
                            elif exit_row['low'] <= sl:
                                trades.append({
                                    'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': sl,
                                    'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss',
                                    'setup': 'sweep_down',
                                    'orb_range': orb_range / orb_mid * 100
                                })
                                break
                        break
                
    except Exception as e:
        print(f"  {symbol} error: {e}")
        
    return trades, stats

def calculate_metrics(trades):
    if not trades:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
            'profit_factor': 0, 'total_r': 0, 'avg_r': 0
        }
    
    df = pd.DataFrame(trades)
    total = len(df)
    wins = len(df[df['r'] > 0])
    losses = len(df[df['r'] < 0])
    win_rate = (wins / total * 100) if total > 0 else 0
    
    gross_wins = df[df['r'] > 0]['r'].sum() if wins > 0 else 0
    gross_losses = abs(df[df['r'] < 0]['r'].sum()) if losses > 0 else 0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0
    
    total_r = df['r'].sum()
    avg_r = total_r / total if total > 0 else 0
    
    return {
        'trades': total, 'wins': wins, 'losses': losses, 'win_rate': win_rate,
        'profit_factor': profit_factor, 'total_r': total_r, 'avg_r': avg_r
    }

# Quick 6-month test first
print("="*80)
print("BOOF 24 v2 - Liquidity Sweep + Reversal")
print("="*80)
print("Quick 6-month validation test")
print("="*80)

end = datetime.now()
start = end - timedelta(days=180)

configs = [
    {'name': 'No Volume Filter', 'vol': 0.0, 'use_vol': False},
    {'name': 'Volume >1.5x', 'vol': 1.5, 'use_vol': True},
    {'name': 'Volume >2.0x', 'vol': 2.0, 'use_vol': True},
]

for cfg in configs:
    print(f"\n{cfg['name']}:")
    print("-"*60)
    
    all_trades = []
    total_stats = {'sweeps': 0, 'reclaims': 0, 'entered': 0}
    
    for sym in SYMBOLS:
        trades, stats = backtest_liquidity_sweep(sym, start, end, cfg['vol'], cfg['use_vol'])
        all_trades.extend(trades)
        total_stats['sweeps'] += stats['sweeps']
        total_stats['reclaims'] += stats['reclaims']
        total_stats['entered'] += stats['entered']
    
    m = calculate_metrics(all_trades)
    
    print(f"  Sweeps detected: {total_stats['sweeps']}")
    print(f"  Reclaims: {total_stats['reclaims']}")
    print(f"  Trades taken: {m['trades']} ({total_stats['entered']} setups)")
    print(f"  Win Rate: {m['win_rate']:.1f}%")
    print(f"  Profit Factor: {m['profit_factor']:.2f}")
    print(f"  Total R: {m['total_r']:+.1f}")
    print(f"  Avg R/Trade: {m['avg_r']:+.3f}")

print("\n" + "="*80)

# Best config full analysis
best_cfg = {'vol': 1.5, 'use_vol': True}
print(f"\nFull 2024-2026 Analysis (Volume >1.5x):")
print("="*80)

periods = [
    ('2024 Full Year', datetime(2024, 1, 1), datetime(2024, 12, 31)),
    ('2025 Full Year', datetime(2025, 1, 1), datetime(2025, 12, 31)),
    ('2026 YTD', datetime(2026, 1, 1), datetime.now())
]

all_period_results = []

for label, p_start, p_end in periods:
    print(f"\n{label}:")
    print("-"*60)
    
    period_trades = []
    sym_results = {}
    
    for sym in SYMBOLS:
        trades, _ = backtest_liquidity_sweep(sym, p_start, p_end, best_cfg['vol'], best_cfg['use_vol'])
        period_trades.extend(trades)
        sym_results[sym] = calculate_metrics(trades)
    
    m = calculate_metrics(period_trades)
    all_period_results.append((label, m, sym_results))
    
    print(f"Total: {m['trades']} trades | WR: {m['win_rate']:.1f}% | PF: {m['profit_factor']:.2f} | R: {m['total_r']:+.1f}")
    
    # Symbol breakdown
    print(f"\n  Profitable symbols:")
    for sym in SYMBOLS:
        sm = sym_results[sym]
        if sm['profit_factor'] >= 1.0 and sm['trades'] >= 5:
            print(f"    {sym}: {sm['trades']}t | {sm['win_rate']:.0f}%WR | PF{sm['profit_factor']:.2f}")

# Multi-year summary
print("\n" + "="*80)
print("MULTI-YEAR SUMMARY")
print("="*80)
print(f"{'Period':<20} {'Trades':>8} {'Win%':>7} {'PF':>6} {'Total R':>8} {'Avg R':>7}")
print("-"*60)
for label, m, _ in all_period_results:
    print(f"{label:<20} {m['trades']:>8} {m['win_rate']:>6.1f}% {m['profit_factor']:>6.2f} {m['total_r']:>+7.1f} {m['avg_r']:>+6.3f}")

# Consistency check
print("\nCONSISTENCY CHECK:")
pf_values = [m['profit_factor'] for _, m, _ in all_period_results]
consistent = all(pf >= 1.2 for pf in pf_values)
print(f"  PF > 1.2 all years: {'✓ PASS' if consistent else '✗ FAIL'}")
for label, m, _ in all_period_results:
    status = '✓' if m['profit_factor'] >= 1.2 else '✗'
    print(f"  {label}: PF {m['profit_factor']:.2f} {status}")
