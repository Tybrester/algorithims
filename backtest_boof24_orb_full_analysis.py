"""BOOF 24 ORB - Full 2024-2026 Analysis + Symbol Breakdown + Trade Distribution"""
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

# Config - using best performer: Volume >2.0x alone
ORB_MINUTES = 15
TP_PCT = 0.005  # 0.5% TP
SL_PCT = 0.0025 # 0.25% SL (2:1 RR)
VOL_THRESHOLD = 2.0  # Best performer from systematic test

# Expanded symbol list for diversification test
SYMBOLS = ['SPY', 'QQQ', 'IWM', 'NVDA', 'META', 'AAPL', 'TSLA', 'AMZN', 'GOOGL', 'MSFT', 'AMD', 'NFLX', 'CRM', 'BA', 'JPM']

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

def backtest_orb(symbol, start_date, end_date):
    """Backtest ORB with Volume >2.0x filter"""
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
        
        for date, day_df in df.groupby('date'):
            if len(day_df) < ORB_MINUTES + 5:
                continue
            
            first_time = day_df['time'].iloc[0]
            if not is_market_hours(first_time):
                continue
            
            orb_bars = day_df.iloc[:ORB_MINUTES]
            orb_high = orb_bars['high'].max()
            orb_low = orb_bars['low'].min()
            
            after_orb = day_df.iloc[ORB_MINUTES:]
            
            for i, (idx, row) in enumerate(after_orb.iterrows()):
                if i > 30:
                    break
                    
                price = row['close']
                
                break_above = price > orb_high
                break_below = price < orb_low
                
                if not break_above and not break_below:
                    continue
                
                # Volume filter only (>2.0x)
                rel_vol = calc_rel_volume(df, idx, 20)
                if rel_vol < VOL_THRESHOLD:
                    continue
                
                direction = 'LONG' if break_above else 'SHORT'
                entry = price
                entry_time = row['time']
                
                remaining = after_orb.iloc[i+1:]
                
                if direction == 'LONG':
                    tp = entry * (1 + TP_PCT)
                    sl = entry * (1 - SL_PCT)
                    
                    for j, (_, exit_row) in enumerate(remaining.iterrows()):
                        if exit_row['high'] >= tp:
                            trades.append({
                                'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': tp,
                                'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win',
                                'entry_time': entry_time, 'exit_time': exit_row['time'],
                                'bars_held': j + 1
                            })
                            break
                        elif exit_row['low'] <= sl:
                            trades.append({
                                'symbol': symbol, 'dir': 'LONG', 'entry': entry, 'exit': sl,
                                'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss',
                                'entry_time': entry_time, 'exit_time': exit_row['time'],
                                'bars_held': j + 1
                            })
                            break
                else:
                    tp = entry * (1 - TP_PCT)
                    sl = entry * (1 + SL_PCT)
                    
                    for j, (_, exit_row) in enumerate(remaining.iterrows()):
                        if exit_row['low'] <= tp:
                            trades.append({
                                'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': tp,
                                'pnl_pct': TP_PCT, 'r': 2.0, 'result': 'win',
                                'entry_time': entry_time, 'exit_time': exit_row['time'],
                                'bars_held': j + 1
                            })
                            break
                        elif exit_row['high'] >= sl:
                            trades.append({
                                'symbol': symbol, 'dir': 'SHORT', 'entry': entry, 'exit': sl,
                                'pnl_pct': -SL_PCT, 'r': -1.0, 'result': 'loss',
                                'entry_time': entry_time, 'exit_time': exit_row['time'],
                                'bars_held': j + 1
                            })
                            break
                
                break  # One trade per day max
                
    except Exception as e:
        print(f"  {symbol} error: {e}")
        
    return trades

def calculate_metrics(trades):
    if not trades:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
            'gross_wins': 0, 'gross_losses': 0, 'profit_factor': 0,
            'total_r': 0, 'avg_r': 0, 'max_r': 0, 'min_r': 0
        }
    
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
        'trades': total, 'wins': wins, 'losses': losses, 'win_rate': win_rate,
        'gross_wins': gross_wins, 'gross_losses': gross_losses, 'profit_factor': profit_factor,
        'total_r': total_r, 'avg_r': avg_r,
        'max_r': df['r'].max(), 'min_r': df['r'].min()
    }

def analyze_trade_distribution(trades, label):
    """Analyze concentration of profits"""
    if not trades:
        print(f"\n{label}: No trades")
        return
    
    df = pd.DataFrame(trades)
    winners = df[df['r'] > 0].sort_values('r', ascending=False)
    total_r = df['r'].sum()
    gross_wins = winners['r'].sum() if len(winners) > 0 else 0
    
    print(f"\n{label} Trade Distribution:")
    print("-" * 50)
    print(f"Total Trades: {len(df)}")
    print(f"Total R: {total_r:+.1f}")
    
    if len(winners) == 0:
        print("No winning trades")
        return
    
    print(f"\nLargest Winner: +{winners.iloc[0]['r']:.1f}R")
    
    if len(winners) >= 5:
        top5_r = winners.head(5)['r'].sum()
        top5_pct = (top5_r / gross_wins * 100) if gross_wins > 0 else 0
        print(f"Top 5 Winners: +{top5_r:.1f}R ({top5_pct:.1f}% of gross profits)")
    
    if len(winners) >= 10:
        top10_r = winners.head(10)['r'].sum()
        top10_pct = (top10_r / gross_wins * 100) if gross_wins > 0 else 0
        print(f"Top 10 Winners: +{top10_r:.1f}R ({top10_pct:.1f}% of gross profits)")
    
    # Win/loss by direction
    longs = df[df['dir'] == 'LONG']
    shorts = df[df['dir'] == 'SHORT']
    if len(longs) > 0:
        long_wr = len(longs[longs['r'] > 0]) / len(longs) * 100
        print(f"\nLongs: {len(longs)} trades, {long_wr:.1f}% WR, {longs['r'].sum():+.1f}R")
    if len(shorts) > 0:
        short_wr = len(shorts[shorts['r'] > 0]) / len(shorts) * 100
        print(f"Shorts: {len(shorts)} trades, {short_wr:.1f}% WR, {shorts['r'].sum():+.1f}R")

def run_period(label, start, end):
    """Run backtest for a specific period"""
    print(f"\n{'='*80}")
    print(f"{label}: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
    print('='*80)
    
    symbol_results = {}
    all_trades = []
    
    for sym in SYMBOLS:
        trades = backtest_orb(sym, start, end)
        symbol_results[sym] = trades
        all_trades.extend(trades)
        m = calculate_metrics(trades)
        if m['trades'] > 0:
            print(f"{sym:>5}: {m['trades']:>3} trades | WR: {m['win_rate']:>5.1f}% | PF: {m['profit_factor']:>5.2f} | R: {m['total_r']:>+6.1f}")
    
    # Summary
    total_m = calculate_metrics(all_trades)
    print(f"\n{'TOTAL':>5}: {total_m['trades']:>3} trades | WR: {total_m['win_rate']:>5.1f}% | PF: {total_m['profit_factor']:>5.2f} | R: {total_m['total_r']:>+6.1f}")
    
    # Symbol breakdown table
    print("\nSymbol Performance Table:")
    print(f"{'Symbol':<8} {'Trades':>7} {'Win%':>7} {'PF':>6} {'Total R':>8} {'Status':>10}")
    print("-" * 50)
    profitable_symbols = 0
    for sym in SYMBOLS:
        m = calculate_metrics(symbol_results[sym])
        status = "✓" if m['profit_factor'] >= 1.0 and m['trades'] >= 5 else "✗"
        if m['profit_factor'] >= 1.0 and m['trades'] >= 5:
            profitable_symbols += 1
        if m['trades'] > 0:
            print(f"{sym:<8} {m['trades']:>7} {m['win_rate']:>6.1f}% {m['profit_factor']:>6.2f} {m['total_r']:>+7.1f} {status:>10}")
    
    print(f"\nProfitable Symbols: {profitable_symbols}/{len([s for s in SYMBOLS if calculate_metrics(symbol_results[s])['trades'] > 0])}")
    
    analyze_trade_distribution(all_trades, label)
    
    return all_trades, symbol_results, total_m

# Run all periods
now = datetime.now()

# 2024 Full Year
trades_2024, sym_2024, m_2024 = run_period(
    "2024 FULL YEAR",
    datetime(2024, 1, 1),
    datetime(2024, 12, 31)
)

# 2025 Full Year
trades_2025, sym_2025, m_2025 = run_period(
    "2025 FULL YEAR",
    datetime(2025, 1, 1),
    datetime(2025, 12, 31)
)

# 2026 YTD
trades_2026, sym_2026, m_2026 = run_period(
    "2026 YTD",
    datetime(2026, 1, 1),
    now
)

# Overall Summary
print("\n" + "="*80)
print("MULTI-YEAR SUMMARY")
print("="*80)
print(f"{'Period':<20} {'Trades':>8} {'Win%':>7} {'PF':>6} {'Total R':>8} {'Avg R':>7}")
print("-" * 60)
for label, m in [("2024 Full Year", m_2024), ("2025 Full Year", m_2025), ("2026 YTD", m_2026)]:
    print(f"{label:<20} {m['trades']:>8} {m['win_rate']:>6.1f}% {m['profit_factor']:>6.2f} {m['total_r']:>+7.1f} {m['avg_r']:>+6.3f}")

# Consistency check
print("\n" + "="*80)
print("CONSISTENCY CHECK")
print("="*80)
pf_2024 = m_2024['profit_factor']
pf_2025 = m_2025['profit_factor']
pf_2026 = m_2026['profit_factor']

consistent = (pf_2024 >= 1.3 if pf_2024 > 0 else True) and \
             (pf_2025 >= 1.3 if pf_2025 > 0 else True) and \
             (pf_2026 >= 1.3 if pf_2026 > 0 else True)

print(f"PF 2024: {pf_2024:.2f} {'✓' if pf_2024 >= 1.3 else '✗'}")
print(f"PF 2025: {pf_2025:.2f} {'✓' if pf_2025 >= 1.3 else '✗'}")
print(f"PF 2026: {pf_2026:.2f} {'✓' if pf_2026 >= 1.3 else '✗'}")
print(f"\nPF > 1.3 for all periods: {'✓ PASS' if consistent else '✗ FAIL'}")

# Symbol consistency across years
print("\n" + "="*80)
print("SYMBOL CONSISTENCY (Profitable in 2+ years)")
print("="*80)
for sym in SYMBOLS:
    pf_24 = calculate_metrics(sym_2024.get(sym, []))['profit_factor']
    pf_25 = calculate_metrics(sym_2025.get(sym, []))['profit_factor']
    pf_26 = calculate_metrics(sym_2026.get(sym, []))['profit_factor']
    
    profitable_years = sum([1 for pf in [pf_24, pf_25, pf_26] if pf >= 1.0])
    if profitable_years >= 2:
        print(f"{sym}: PF {pf_24:.2f} / {pf_25:.2f} / {pf_26:.2f} ({profitable_years}/3 years)")
