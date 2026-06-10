"""BOOF 24 ORB - Systematic Filter Testing"""
import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Alpaca credentials
ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

# Config
ORB_MINUTES = 15
TP_PCT = 0.005  # 0.5% TP
SL_PCT = 0.0025 # 0.25% SL (2:1 RR)
SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

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

def get_market_trend(spy_df, idx):
    if spy_df is None or len(spy_df) < 20:
        return 'neutral'
    # Use last 10 bars vs prior 10 bars
    start = max(0, idx - 20)
    recent = spy_df['close'].iloc[idx-10:idx].mean() if idx >= 10 else spy_df['close'].iloc[start:idx].mean()
    earlier = spy_df['close'].iloc[max(0,idx-20):max(0,idx-10)].mean()
    if earlier == 0:
        return 'neutral'
    change = (recent - earlier) / earlier
    if change > 0.001:
        return 'up'
    if change < -0.001:
        return 'down'
    return 'neutral'

def is_market_hours(timestamp):
    """Check if timestamp is during market hours (9:30-16:00 ET)"""
    et_hour = timestamp.hour - 4
    et_minute = timestamp.minute
    if et_hour < 0:
        et_hour += 24
    minutes_since_open = (et_hour - 9) * 60 + et_minute
    return 0 <= minutes_since_open < 390

def backtest_orb_filtered(symbol, start_date, end_date, spy_df=None, 
                          use_volume=False, vol_threshold=1.3,
                          use_vwap=False, 
                          use_trend=False):
    """Backtest ORB with configurable filters"""
    trades = []
    
    try:
        df = api.get_bars(
            symbol, '5Min',
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            limit=10000,
            feed='iex'
        ).df
        
        if len(df) < 50:
            return trades
            
        df = df.reset_index()
        if 'timestamp' in df.columns:
            df['time'] = pd.to_datetime(df['timestamp'])
        elif 'index' in df.columns:
            df['time'] = pd.to_datetime(df['index'])
        
        df['vwap'] = compute_vwap(df)
        df['date'] = df['time'].dt.date
        
        # Map spy_df index if provided
        spy_times = None
        if spy_df is not None:
            spy_df_copy = spy_df.copy()
            spy_times = spy_df_copy['time'].values
        
        for date, day_df in df.groupby('date'):
            if len(day_df) < ORB_MINUTES + 5:
                continue
            
            # Check first bar is near market open
            first_time = day_df['time'].iloc[0]
            if not is_market_hours(first_time):
                continue
            
            # ORB range
            orb_bars = day_df.iloc[:ORB_MINUTES]
            orb_high = orb_bars['high'].max()
            orb_low = orb_bars['low'].min()
            
            # After ORB
            after_orb = day_df.iloc[ORB_MINUTES:]
            
            for i, (idx, row) in enumerate(after_orb.iterrows()):
                if i > 30:  # First 2.5 hours only
                    break
                    
                price = row['close']
                vwap = row['vwap']
                
                break_above = price > orb_high
                break_below = price < orb_low
                
                if not break_above and not break_below:
                    continue
                
                # --- FILTERS ---
                
                # Volume filter
                if use_volume:
                    rel_vol = calc_rel_volume(df, idx, 20)
                    if rel_vol < vol_threshold:
                        continue
                
                # VWAP filter
                if use_vwap:
                    vwap_ok = (price > vwap and break_above) or (price < vwap and break_below)
                    if not vwap_ok:
                        continue
                
                # Trend filter
                if use_trend and spy_df is not None:
                    # Find corresponding spy index
                    current_time = row['time']
                    spy_trend = get_market_trend(spy_df, len(spy_df)-1)  # Simplified
                    trend_ok = spy_trend == 'neutral' or \
                              (spy_trend == 'up' and break_above) or \
                              (spy_trend == 'down' and break_below)
                    if not trend_ok:
                        continue
                
                # Enter trade
                direction = 'LONG' if break_above else 'SHORT'
                entry = price
                
                # Simulate exit
                remaining = after_orb.iloc[i+1:]
                
                if direction == 'LONG':
                    tp = entry * (1 + TP_PCT)
                    sl = entry * (1 - SL_PCT)
                    
                    for _, exit_row in remaining.iterrows():
                        if exit_row['high'] >= tp:
                            trades.append({'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': tp, 
                                          'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win'})
                            break
                        elif exit_row['low'] <= sl:
                            trades.append({'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': sl,
                                          'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss'})
                            break
                else:
                    tp = entry * (1 - TP_PCT)
                    sl = entry * (1 + SL_PCT)
                    
                    for _, exit_row in remaining.iterrows():
                        if exit_row['low'] <= tp:
                            trades.append({'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': tp,
                                          'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win'})
                            break
                        elif exit_row['high'] >= sl:
                            trades.append({'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': sl,
                                          'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss'})
                            break
                
                break  # One trade per day max
                
    except Exception as e:
        print(f"  {symbol} error: {e}")
        
    return trades

def calculate_metrics(trades):
    """Calculate performance metrics"""
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'profit_factor': 0, 'total_r': 0, 'avg_r': 0}
    
    df = pd.DataFrame(trades)
    total = len(df)
    wins = len(df[df['r'] > 0])
    losses = len(df[df['r'] < 0])
    win_rate = (wins / total * 100) if total > 0 else 0
    
    gross_wins = df[df['r'] > 0]['r'].sum() if wins > 0 else 0
    gross_losses = abs(df[df['r'] < 0]['r'].sum()) if losses > 0 else 0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
    
    total_r = df['r'].sum()
    avg_r = total_r / total if total > 0 else 0
    
    return {
        'trades': total,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_r': total_r,
        'avg_r': avg_r
    }

# Date range
end = datetime.now()
start = end - timedelta(days=180)

print("="*80)
print("BOOF 24 ORB - SYSTEMATIC FILTER TESTING")
print("="*80)
print(f"Period: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
print(f"Symbols: {', '.join(SYMBOLS)}")
print(f"ORB: {ORB_MINUTES} min | TP: {TP_PCT*100:.2f}% | SL: {SL_PCT*100:.2f}%")
print("="*80)

# Fetch SPY once
print("\nFetching SPY data...")
try:
    spy_df = api.get_bars(
        'SPY', '5Min',
        start=start.strftime('%Y-%m-%d'),
        end=end.strftime('%Y-%m-%d'),
        limit=10000,
        feed='iex'
    ).df
    spy_df = spy_df.reset_index()
    if 'timestamp' in spy_df.columns:
        spy_df['time'] = pd.to_datetime(spy_df['timestamp'])
    print(f"SPY: {len(spy_df)} bars")
except Exception as e:
    print(f"SPY failed: {e}")
    spy_df = None

# Test configurations
configs = [
    {'name': '1. BASELINE (no filters)', 'use_volume': False, 'use_vwap': False, 'use_trend': False},
    {'name': '2. + Volume (>1.0x)', 'use_volume': True, 'vol_threshold': 1.0, 'use_vwap': False, 'use_trend': False},
    {'name': '3. + Volume (>1.3x)', 'use_volume': True, 'vol_threshold': 1.3, 'use_vwap': False, 'use_trend': False},
    {'name': '4. + Volume (>2.0x)', 'use_volume': True, 'vol_threshold': 2.0, 'use_vwap': False, 'use_trend': False},
    {'name': '5. + VWAP Confirm', 'use_volume': False, 'use_vwap': True, 'use_trend': False},
    {'name': '6. + Trend Filter', 'use_volume': False, 'use_vwap': False, 'use_trend': True},
    {'name': '7. + Vol(1.3x) + VWAP', 'use_volume': True, 'vol_threshold': 1.3, 'use_vwap': True, 'use_trend': False},
    {'name': '8. + Vol(1.3x) + Trend', 'use_volume': True, 'vol_threshold': 1.3, 'use_vwap': False, 'use_trend': True},
    {'name': '9. + ALL FILTERS', 'use_volume': True, 'vol_threshold': 1.3, 'use_vwap': True, 'use_trend': True},
]

results = []

for config in configs:
    print(f"\n{config['name']}")
    print("-" * 80)
    
    all_trades = []
    for sym in SYMBOLS:
        trades = backtest_orb_filtered(
            sym, start, end, spy_df,
            use_volume=config.get('use_volume', False),
            vol_threshold=config.get('vol_threshold', 1.3),
            use_vwap=config.get('use_vwap', False),
            use_trend=config.get('use_trend', False)
        )
        all_trades.extend(trades)
        print(f"  {sym}: {len(trades)} trades", end='')
        if trades:
            m = calculate_metrics(trades)
            print(f" | WR: {m['win_rate']:.1f}% | R: {m['total_r']:+.1f}")
        else:
            print()
    
    metrics = calculate_metrics(all_trades)
    results.append({
        'name': config['name'],
        'metrics': metrics,
        'trades': all_trades
    })
    
    print(f"\n  TOTAL: {metrics['trades']} trades | WR: {metrics['win_rate']:.1f}% | "
          f"PF: {metrics['profit_factor']:.2f} | R: {metrics['total_r']:+.1f} | Avg: {metrics['avg_r']:+.3f}")

# Summary table
print("\n" + "="*80)
print("SUMMARY COMPARISON")
print("="*80)
print(f"{'Config':<35} {'Trades':>8} {'Win%':>7} {'PF':>6} {'Total R':>8} {'Avg R':>7}")
print("-"*80)
for r in results:
    m = r['metrics']
    print(f"{r['name']:<35} {m['trades']:>8} {m['win_rate']:>6.1f}% {m['profit_factor']:>6.2f} "
          f"{m['total_r']:>+7.1f} {m['avg_r']:>+6.3f}")
print("="*80)

# Best by metric
print("\nBEST BY METRIC:")
best_trades = max(results, key=lambda x: x['metrics']['trades'])
best_wr = max(results, key=lambda x: x['metrics']['win_rate'])
best_pf = max(results, key=lambda x: x['metrics']['profit_factor'] if x['metrics']['profit_factor'] != float('inf') else 0)
best_r = max(results, key=lambda x: x['metrics']['total_r'])
print(f"  Most trades:  {best_trades['name']} ({best_trades['metrics']['trades']})")
print(f"  Best Win%:   {best_wr['name']} ({best_wr['metrics']['win_rate']:.1f}%)")
print(f"  Best PF:     {best_pf['name']} ({best_pf['metrics']['profit_factor']:.2f})")
print(f"  Best Total R: {best_r['name']} ({best_r['metrics']['total_r']:+.1f}R)")
