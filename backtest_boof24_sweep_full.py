"""BOOF 24 - Liquidity Sweep: Full Analysis with Regime & Time Filters"""
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
ORB_MINUTES = 15
SWEEP_LOOKBACK_BARS = 12  # Slightly expanded
RECLAIM_BARS = 4
TP_PCT = 0.008
SL_PCT = 0.004
MAX_TIME_MINUTES = 90  # Only first 90 min of day

# Core test symbols
CORE_SYMBOLS = ['NVDA', 'TSLA', 'META', 'SPY', 'QQQ']
# Extended list for robustness
EXTENDED_SYMBOLS = ['NVDA', 'TSLA', 'META', 'SPY', 'QQQ', 'AAPL', 'AMZN', 'GOOGL', 'NFLX', 'AMD', 'MSFT', 'IWM']

def compute_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    cumtpv = (typical * df['volume']).cumsum()
    cumvol = df['volume'].cumsum()
    return cumtpv / cumvol

def get_minutes_since_open(timestamp):
    """Get minutes since 9:30 AM ET
    Handles both EST (UTC-5, winter) and EDT (UTC-4, summer)
    """
    # Check if DST is active (simplified: March-Nov = DST)
    month = timestamp.month
    is_dst = 3 <= month <= 11
    utc_offset = 4 if is_dst else 5
    
    et_hour = timestamp.hour - utc_offset
    et_minute = timestamp.minute
    if et_hour < 0:
        et_hour += 24
    return (et_hour - 9) * 60 + et_minute

def is_market_hours(timestamp):
    mins = get_minutes_since_open(timestamp)
    return 0 <= mins < 390

def is_within_time_window(timestamp, max_minutes=90):
    mins = get_minutes_since_open(timestamp)
    return 0 <= mins < max_minutes

def get_spy_regime(spy_df, day_date):
    """Determine if SPY was trending or ranging on a given day
    Trend = ADX-like measure or range % of day"""
    day_bars = spy_df[spy_df['date'] == day_date]
    if len(day_bars) < 20:
        return 'unknown'
    
    # Simple range vs close-to-close measure
    day_range = day_bars['high'].max() - day_bars['low'].min()
    open_price = day_bars['open'].iloc[0]
    close_price = day_bars['close'].iloc[-1]
    
    # Trending if close is near high or low of day (70%+ of range)
    day_mid = (day_bars['high'].max() + day_bars['low'].min()) / 2
    
    # Range % - how much of the day's range did we use directionally
    directional_move = abs(close_price - open_price)
    
    if directional_move / day_range > 0.6:
        return 'trending'
    else:
        return 'ranging'

def backtest_sweep_full(symbol, start_date, end_date, spy_df=None, 
                        use_time_filter=True, max_minutes=90,
                        use_regime_filter=False, target_regime='ranging'):
    """Liquidity Sweep with full filtering options"""
    trades = []
    stats = {'sweeps': 0, 'reclaims': 0, 'entered': 0, 'time_filtered': 0, 'regime_filtered': 0}
    
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
        df['mins_open'] = df['time'].apply(get_minutes_since_open)
        
        for date, day_df in df.groupby('date'):
            if len(day_df) < ORB_MINUTES + 15:
                continue
            
            # Time filter check for day
            if use_time_filter:
                last_bar_mins = day_df['mins_open'].iloc[-1]
                if last_bar_mins < ORB_MINUTES + 20:  # Not enough bars after ORB
                    continue
            
            # Regime filter
            if use_regime_filter and spy_df is not None:
                regime = get_spy_regime(spy_df, date)
                if regime != target_regime:
                    stats['regime_filtered'] += 1
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
            
            # Skip tiny range days
            if orb_range / orb_mid < 0.002:
                continue
            
            post_orb = day_df.iloc[ORB_MINUTES:].reset_index(drop=True)
            
            # Time filter - cap lookback based on time window
            max_lookback = SWEEP_LOOKBACK_BARS
            if use_time_filter:
                # How many bars fit in remaining time window
                first_post_orb_mins = get_minutes_since_open(day_df['time'].iloc[ORB_MINUTES])
                bars_remaining = (max_minutes - first_post_orb_mins) // 5
                max_lookback = min(SWEEP_LOOKBACK_BARS, max(3, bars_remaining))
            
            if len(post_orb) < max_lookback + 3:
                continue
            
            sweep_window = post_orb.iloc[:max_lookback]
            
            # Find sweep up
            sweep_up_idx = None
            for i, (_, row) in enumerate(sweep_window.iterrows()):
                if not is_within_time_window(row['time'], max_minutes):
                    continue
                if row['high'] > orb_high and row['close'] < orb_high:
                    sweep_up_idx = i
                    stats['sweeps'] += 1
                    break
            
            # Find sweep down
            sweep_down_idx = None
            for i, (_, row) in enumerate(sweep_window.iterrows()):
                if not is_within_time_window(row['time'], max_minutes):
                    continue
                if row['low'] < orb_low and row['close'] > orb_low:
                    sweep_down_idx = i
                    stats['sweeps'] += 1
                    break
            
            # Enter SHORT after sweep up (reclaim ORB mid)
            if sweep_up_idx is not None:
                reclaim_start = sweep_up_idx + 1
                reclaim_end = min(reclaim_start + RECLAIM_BARS, len(post_orb))
                
                for j in range(reclaim_start, reclaim_end):
                    if j >= len(post_orb):
                        break
                    row = post_orb.iloc[j]
                    
                    # Time check for entry
                    if use_time_filter and not is_within_time_window(row['time'], max_minutes):
                        stats['time_filtered'] += 1
                        continue
                    
                    # Entry: Below ORB midpoint = confirmation sweep failed
                    if row['close'] < orb_mid:
                        entry = row['close']
                        stats['reclaims'] += 1
                        stats['entered'] += 1
                        
                        tp = entry * (1 - TP_PCT)
                        sl = entry * (1 + SL_PCT)
                        
                        remaining = post_orb.iloc[j+1:]
                        for _, exit_row in remaining.iterrows():
                            if exit_row['low'] <= tp:
                                trades.append({
                                    'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': tp,
                                    'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win',
                                    'regime': get_spy_regime(spy_df, date) if spy_df is not None else 'unknown'
                                })
                                break
                            elif exit_row['high'] >= sl:
                                trades.append({
                                    'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': sl,
                                    'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss',
                                    'regime': get_spy_regime(spy_df, date) if spy_df is not None else 'unknown'
                                })
                                break
                        break
            
            # Enter LONG after sweep down
            if sweep_down_idx is not None:
                reclaim_start = sweep_down_idx + 1
                reclaim_end = min(reclaim_start + RECLAIM_BARS, len(post_orb))
                
                for j in range(reclaim_start, reclaim_end):
                    if j >= len(post_orb):
                        break
                    row = post_orb.iloc[j]
                    
                    if use_time_filter and not is_within_time_window(row['time'], max_minutes):
                        stats['time_filtered'] += 1
                        continue
                    
                    if row['close'] > orb_mid:
                        entry = row['close']
                        stats['reclaims'] += 1
                        stats['entered'] += 1
                        
                        tp = entry * (1 + TP_PCT)
                        sl = entry * (1 - SL_PCT)
                        
                        remaining = post_orb.iloc[j+1:]
                        for _, exit_row in remaining.iterrows():
                            if exit_row['high'] >= tp:
                                trades.append({
                                    'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': tp,
                                    'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win',
                                    'regime': get_spy_regime(spy_df, date) if spy_df is not None else 'unknown'
                                })
                                break
                            elif exit_row['low'] <= sl:
                                trades.append({
                                    'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': sl,
                                    'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss',
                                    'regime': get_spy_regime(spy_df, date) if spy_df is not None else 'unknown'
                                })
                                break
                        break
                
    except Exception as e:
        print(f"  {symbol} error: {e}")
        
    return trades, stats

def calculate_metrics(trades):
    if not trades:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'profit_factor': 0, 'total_r': 0, 'avg_r': 0}
    
    df = pd.DataFrame(trades)
    total = len(df)
    wins = len(df[df['r'] > 0])
    gross_wins = df[df['r'] > 0]['r'].sum() if wins > 0 else 0
    gross_losses = abs(df[df['r'] < 0]['r'].sum()) if len(df[df['r'] < 0]) > 0 else 0
    pf = gross_wins / gross_losses if gross_losses > 0 else 0
    
    return {
        'trades': total, 'wins': wins, 'losses': total - wins,
        'win_rate': wins / total * 100 if total > 0 else 0,
        'profit_factor': pf,
        'total_r': df['r'].sum(),
        'avg_r': df['r'].sum() / total if total > 0 else 0
    }

# Fetch SPY for regime analysis
print("="*80)
print("BOOF 24 - Liquidity Sweep: Full 2024-2026 + Regime Analysis")
print("="*80)

print("\nFetching SPY data for regime classification...")
end = datetime.now()
start_2024 = datetime(2024, 1, 1)

try:
    spy_df = api.get_bars(
        'SPY', '5Min',
        start=start_2024.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        limit=10000,
        feed='iex'
    ).df
    spy_df = spy_df.reset_index()
    if 'timestamp' in spy_df.columns:
        spy_df['time'] = pd.to_datetime(spy_df['timestamp'])
    spy_df['date'] = spy_df['time'].dt.date
    print(f"SPY: {len(spy_df)} bars loaded")
except Exception as e:
    print(f"SPY load failed: {e}")
    spy_df = None

# Test configurations
configs = [
    {'name': 'Raw (no filters)', 'time_filter': False, 'max_min': 390, 'regime': False},
    {'name': 'First 90 min only', 'time_filter': True, 'max_min': 90, 'regime': False},
    {'name': 'First 60 min only', 'time_filter': True, 'max_min': 60, 'regime': False},
    {'name': 'SPY ranging days only', 'time_filter': True, 'max_min': 90, 'regime': True, 'target': 'ranging'},
]

# Run 6-month quick test on CORE symbols
print("\n" + "="*80)
print("QUICK 6-MONTH TEST: Core Symbols (NVDA, TSLA, META, SPY, QQQ)")
print("="*80)

end = datetime.now()
start = end - timedelta(days=180)

for cfg in configs:
    print(f"\n{cfg['name']}:")
    print("-"*60)
    
    all_trades = []
    all_stats = {'sweeps': 0, 'reclaims': 0, 'entered': 0, 'time_filtered': 0, 'regime_filtered': 0}
    
    for sym in CORE_SYMBOLS:
        trades, stats = backtest_sweep_full(
            sym, start, end, spy_df,
            use_time_filter=cfg['time_filter'],
            max_minutes=cfg.get('max_min', 90),
            use_regime_filter=cfg.get('regime', False),
            target_regime=cfg.get('target', 'ranging')
        )
        all_trades.extend(trades)
        for k in stats:
            all_stats[k] += stats[k]
    
    m = calculate_metrics(all_trades)
    print(f"  Sweeps: {all_stats['sweeps']} | Reclaims: {all_stats['reclaims']} | Entered: {all_stats['entered']}")
    print(f"  Trades: {m['trades']} | WR: {m['win_rate']:.1f}% | PF: {m['profit_factor']:.2f} | R: {m['total_r']:+.1f}")
    
    # By symbol
    print("  By symbol:", end='')
    for sym in CORE_SYMBOLS:
        sym_trades = [t for t in all_trades if t['symbol'] == sym]
        sm = calculate_metrics(sym_trades)
        if sm['trades'] > 0:
            print(f" {sym}={sm['trades']}t/{sm['profit_factor']:.1f}PF", end='')
    print()

# Full 2.5 year test on best config
print("\n" + "="*80)
print("FULL 2024-2026 ANALYSIS: Best Config")
print("="*80)

# Use first 90 min config (usually best)
best_cfg = {'time_filter': True, 'max_min': 90, 'regime': False}

periods = [
    ('2024 Full', datetime(2024, 1, 1), datetime(2024, 12, 31)),
    ('2025 Full', datetime(2025, 1, 1), datetime(2025, 12, 31)),
    ('2026 YTD', datetime(2026, 1, 1), datetime.now()),
]

# Extended symbols
print(f"\nSymbols: {', '.join(EXTENDED_SYMBOLS)}")

all_results = []

for label, p_start, p_end in periods:
    print(f"\n{label}:")
    print("-"*60)
    
    period_trades = []
    sym_metrics = {}
    
    for sym in EXTENDED_SYMBOLS:
        trades, _ = backtest_sweep_full(
            sym, p_start, p_end, spy_df,
            use_time_filter=best_cfg['time_filter'],
            max_minutes=best_cfg['max_min'],
            use_regime_filter=best_cfg['regime']
        )
        period_trades.extend(trades)
        sym_metrics[sym] = calculate_metrics(trades)
    
    m = calculate_metrics(period_trades)
    all_results.append((label, m, sym_metrics))
    
    print(f"Total: {m['trades']} trades | WR: {m['win_rate']:.1f}% | PF: {m['profit_factor']:.2f} | R: {m['total_r']:+.1f}")
    
    # Symbol breakdown
    print("\n  Symbol Performance:")
    print(f"  {'Sym':>5} {'Trades':>7} {'Win%':>7} {'PF':>6} {'R':>7} {'Status':>6}")
    print("  " + "-"*45)
    profitable_count = 0
    for sym in EXTENDED_SYMBOLS:
        sm = sym_metrics[sym]
        status = '✓' if sm['profit_factor'] >= 1.0 and sm['trades'] >= 3 else '✗'
        if sm['profit_factor'] >= 1.0 and sm['trades'] >= 3:
            profitable_count += 1
        print(f"  {sym:>5} {sm['trades']:>7} {sm['win_rate']:>6.1f}% {sm['profit_factor']:>6.2f} {sm['total_r']:>+6.1f} {status:>6}")
    print(f"\n  Profitable: {profitable_count}/{len(EXTENDED_SYMBOLS)} symbols")

# Multi-year summary
print("\n" + "="*80)
print("MULTI-YEAR SUMMARY")
print("="*80)
print(f"{'Period':<15} {'Trades':>8} {'Win%':>7} {'PF':>6} {'Total R':>8} {'Avg R':>7}")
print("-"*60)
for label, m, _ in all_results:
    print(f"{label:<15} {m['trades']:>8} {m['win_rate']:>6.1f}% {m['profit_factor']:>6.2f} {m['total_r']:>+7.1f} {m['avg_r']:>+6.3f}")

# Consistency
print("\nCONSISTENCY CHECK (PF > 1.0):")
pfs = [m['profit_factor'] for _, m, _ in all_results]
consistently_profitable = all(pf >= 1.0 for pf in pfs)
for label, m, _ in all_results:
    status = '✓' if m['profit_factor'] >= 1.0 else '✗'
    print(f"  {label}: PF {m['profit_factor']:.2f} {status}")
print(f"\nAll years profitable: {'✓ PASS' if consistently_profitable else '✗ FAIL'}")

# Robustness check - how many symbols profitable each year
print("\n" + "="*80)
print("ROBUSTNESS: Symbols Profitable Each Year")
print("="*80)
for label, _, sym_metrics in all_results:
    prof_syms = [s for s in EXTENDED_SYMBOLS if sym_metrics[s]['profit_factor'] >= 1.0 and sym_metrics[s]['trades'] >= 3]
    print(f"{label}: {len(prof_syms)}/{len(EXTENDED_SYMBOLS)} - {', '.join(prof_syms) if prof_syms else 'None'}")
