"""
Boof 24 Futures with Pyramid Add-On Strategy
Allow 2nd entry only if:
1. First trade is +1R already
2. Trend regime confirmed
"""
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

FUTURES_CONFIG = {
    'ES':   {'file': 'futures_ES_6mo_20260606.csv',   'tick_value': 12.50, 'type': 'IMPULSE',  'name': 'E-mini S&P'},
    'MES':  {'file': 'futures_MES_6mo_20260606.csv',  'tick_value': 1.25,  'type': 'IMPULSE',  'name': 'Micro E-mini S&P'},
    'NQ':   {'file': 'futures_NQ_6mo_20260606.csv',   'tick_value': 5.00,  'type': 'BREAKOUT', 'name': 'E-mini Nasdaq'},
    'MNQ':  {'file': 'futures_MNQ_6mo_20260606.csv',  'tick_value': 0.50,  'type': 'BREAKOUT', 'name': 'Micro E-mini Nasdaq'},
}

CONFIG = {
    'TP_R': 2.0,
    'SL_R': 1.0,
    'BB_PERIOD': 20,
    'BB_STD': 2.0,
    'VOLUME_MULT': 1.0,
    'MAX_TRADES_PER_DAY': 5,
    'TIME_EXIT_BARS': 20,
    # Pyramid settings
    'PYRAMID_MIN_R': 1.0,        # First trade must be +1R to pyramid
    'MAX_POSITIONS': 2,          # Max 2 contracts per direction
    'TREND_LOOKBACK': 10,        # Bars for trend confirmation
}

def load_futures_data(filename):
    """Load saved futures CSV data"""
    try:
        df = pd.read_csv(filename)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception as e:
        print(f"  Error loading {filename}: {e}")
        return None

def compute_bb(closes, period=20, std_dev=2.0):
    """Bollinger Bands"""
    sma = pd.Series(closes).rolling(window=period).mean()
    std = pd.Series(closes).rolling(window=period).std()
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    return upper.iloc[-1], lower.iloc[-1], sma.iloc[-1]

def check_trend_regime(df, i, direction):
    """Check if trend regime confirms the trade direction"""
    if i < CONFIG['TREND_LOOKBACK']:
        return False
    
    # Simple trend: price moving in trade direction
    lookback = CONFIG['TREND_LOOKBACK']
    prices = df['close'].iloc[i-lookback:i+1].values
    
    if direction == 'long':
        # Trend up: higher highs, higher lows
        return prices[-1] > prices[0] and prices[-1] > np.mean(prices)
    else:
        # Trend down: lower highs, lower lows  
        return prices[-1] < prices[0] and prices[-1] < np.mean(prices)

def backtest_pyramid(symbol, config):
    """Backtest with pyramid add-on strategy"""
    print(f"\n{symbol} ({config['name']}, {config['type']}):", end=' ')
    
    df = load_futures_data(config['file'])
    if df is None or len(df) < 100:
        print("Insufficient data")
        return None
    
    print(f"Loaded {len(df)} bars...", end=' ')
    
    # Track multiple positions
    positions = []  # List of active positions
    trades = []     # All completed trades
    daily_trades = 0
    last_date = None
    
    avg_range = (df['high'] - df['low']).mean()
    r_points = max(avg_range * 0.3, 2.0)
    
    for i in range(50, len(df) - 1):
        curr_bar = df.iloc[i]
        current_date = str(curr_bar['timestamp'])[:10]
        
        # Reset daily counter
        if current_date != last_date:
            daily_trades = 0
            last_date = current_date
        
        if daily_trades >= CONFIG['MAX_TRADES_PER_DAY']:
            continue
        
        current_price = curr_bar['close']
        
        # Update and check existing positions
        for pos in positions[:]:
            bars_in_trade = i - pos['entry_idx']
            
            if pos['direction'] == 'long':
                pnl_points = current_price - pos['entry_price']
                pnl_r = pnl_points / r_points
            else:
                pnl_points = pos['entry_price'] - current_price
                pnl_r = pnl_points / r_points
            
            # Update current R for position
            pos['current_r'] = pnl_r
            
            # Check exits
            exited = False
            if pnl_r >= CONFIG['TP_R']:
                trades.append({
                    'pnl_r': CONFIG['TP_R'], 
                    'result': 'win', 
                    'bars': bars_in_trade,
                    'entry_r': pos['entry_num'],
                    'symbol': symbol
                })
                exited = True
            elif pnl_r <= -CONFIG['SL_R']:
                trades.append({
                    'pnl_r': -CONFIG['SL_R'], 
                    'result': 'loss', 
                    'bars': bars_in_trade,
                    'entry_r': pos['entry_num'],
                    'symbol': symbol
                })
                exited = True
            elif bars_in_trade >= CONFIG['TIME_EXIT_BARS']:
                trades.append({
                    'pnl_r': pnl_r, 
                    'result': 'win' if pnl_r > 0 else 'loss', 
                    'bars': bars_in_trade,
                    'entry_r': pos['entry_num'],
                    'symbol': symbol
                })
                exited = True
            
            if exited:
                positions.remove(pos)
                daily_trades += 1
        
        # Check for new entry
        # Signal logic (simplified - using random for demo since we have trade data)
        # In real implementation, this would check breakout/impulse conditions
        
        # Count how many positions we have
        current_positions = len(positions)
        
        # Determine if we can add a position
        can_enter_base = current_positions == 0 and daily_trades < CONFIG['MAX_TRADES_PER_DAY']
        can_pyramid = False
        
        if current_positions == 1 and len(positions) > 0:
            # Check pyramid conditions
            first_pos = positions[0]
            first_pos_profit = first_pos['current_r'] >= CONFIG['PYRAMID_MIN_R']
            
            # Trend regime check
            trend_confirmed = check_trend_regime(df, i, first_pos['direction'])
            
            can_pyramid = first_pos_profit and trend_confirmed and daily_trades < CONFIG['MAX_TRADES_PER_DAY']
        
        # Simulate signal based on original trade data pattern
        # Using the actual trade direction from the saved data as signal
        if i < len(df):
            signal_dir = df.iloc[i]['direction']
            if signal_dir in ['long', 'short']:
                if can_enter_base:
                    # First entry
                    positions.append({
                        'entry_price': current_price,
                        'direction': signal_dir,
                        'entry_idx': i,
                        'entry_num': 1,
                        'current_r': 0
                    })
                elif can_pyramid:
                    # Pyramid entry - only if first position +1R and trend confirmed
                    positions.append({
                        'entry_price': current_price,
                        'direction': signal_dir,
                        'entry_idx': i,
                        'entry_num': 2,
                        'current_r': 0
                    })
    
    if not trades:
        print("No trades")
        return None
    
    # Calculate stats
    wins = sum(1 for t in trades if t['result'] == 'win')
    losses = len(trades) - wins
    win_rate = wins / len(trades) * 100
    total_r = sum(t['pnl_r'] for t in trades)
    avg_r = total_r / len(trades)
    
    # First entries vs pyramids
    first_entries = [t for t in trades if t['entry_r'] == 1]
    pyramids = [t for t in trades if t['entry_r'] == 2]
    
    first_r = sum(t['pnl_r'] for t in first_entries) / len(first_entries) if first_entries else 0
    pyramid_r = sum(t['pnl_r'] for t in pyramids) / len(pyramids) if pyramids else 0
    
    # Dollar P&L (using 1 contract sizing)
    tick_value = config['tick_value']
    ticks_per_r = r_points / 0.25  # ES/MES tick size
    dollar_per_r = ticks_per_r * tick_value
    total_pnl = total_r * dollar_per_r
    
    print(f"Done. {len(trades)} trades")
    
    return {
        'symbol': symbol,
        'type': config['type'],
        'trades': len(trades),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_r': total_r,
        'avg_r': avg_r,
        'total_pnl': total_pnl,
        'first_entries': len(first_entries),
        'pyramids': len(pyramids),
        'first_r': first_r,
        'pyramid_r': pyramid_r,
        'r_points': r_points,
        'tick_value': tick_value
    }

# ═══════════════════════════════════════════════════════════════════════════════
# RUN BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("BOOF 24.0 FUTURES - PYRAMID ADD-ON STRATEGY")
print("=" * 90)
print(f"Pyramid Rules: 2nd entry only if 1st trade +{CONFIG['PYRAMID_MIN_R']}R + trend confirmed")
print("=" * 90)

results = []
for symbol, config in FUTURES_CONFIG.items():
    result = backtest_pyramid(symbol, config)
    if result:
        results.append(result)

# ═══════════════════════════════════════════════════════════════════════════════
# PRINT RESULTS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("RESULTS BY CONTRACT")
print("=" * 90)

print(f"\n{'Symbol':<8} {'Type':<10} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WR%':<7} {'Total R':<10} {'R/T':<8} {'1st R':<8} {'Pyr R':<8}")
print("-" * 90)

for r in results:
    status = "[STRONG]" if r['avg_r'] > 0.15 else "[OK]" if r['avg_r'] > 0.05 else "[WEAK]"
    print(f"{r['symbol']:<8} {r['type']:<10} {r['trades']:<8} {r['wins']:<6} {r['losses']:<6} "
          f"{r['win_rate']:<7.1f} {r['total_r']:<10.2f} {r['avg_r']:<8.3f} "
          f"{r['first_r']:<8.3f} {r['pyramid_r']:<8.3f} {status}")

# ═══════════════════════════════════════════════════════════════════════════════
# PYRAMID BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("PYRAMID BREAKDOWN")
print("=" * 90)

total_first = sum(r['first_entries'] for r in results)
total_pyramid = sum(r['pyramids'] for r in results)

print(f"\nFirst Entries: {total_first} trades")
print(f"Pyramid Adds:  {total_pyramid} trades")
print(f"Pyramid Rate:  {total_pyramid/(total_first+total_pyramid)*100:.1f}% of all trades")

first_avg = sum(r['first_r'] * r['first_entries'] for r in results) / total_first if total_first > 0 else 0
pyramid_avg = sum(r['pyramid_r'] * r['pyramids'] for r in results) / total_pyramid if total_pyramid > 0 else 0

print(f"\nFirst Entry Avg R: {first_avg:.3f}")
print(f"Pyramid Add Avg R: {pyramid_avg:.3f}")

if pyramid_avg > first_avg:
    print(f"\n✓ Pyramiding adds value! (+{pyramid_avg-first_avg:.3f} R improvement)")
else:
    print(f"\n✗ Pyramiding hurts performance ({pyramid_avg-first_avg:.3f} R worse)")

# ═══════════════════════════════════════════════════════════════════════════════
# TOTAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("GRAND TOTAL")
print("=" * 90)

total_trades = sum(r['trades'] for r in results)
total_wins = sum(r['wins'] for r in results)
total_r = sum(r['total_r'] for r in results)
total_pnl = sum(r['total_pnl'] for r in results)
avg_r = total_r / total_trades if total_trades > 0 else 0
win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0

print(f"\nTotal Trades:  {total_trades}")
print(f"Win Rate:      {win_rate:.1f}%")
print(f"Total R:       {total_r:+.2f}")
print(f"R per Trade:   {avg_r:.3f}")
print(f"Total P&L:     ${total_pnl:,.2f}")

print(f"\n{'=' * 90}")
if avg_r > 0.15:
    print("[STRONG EDGE] Pyramid strategy viable for deployment")
elif avg_r > 0.10:
    print("[EDGE CONFIRMED] Pyramid strategy shows promise")
elif avg_r > 0:
    print("[MARGINAL] Pyramid adds marginal value - test further")
else:
    print("[NO EDGE] Pyramiding degrades performance")
print(f"{'=' * 90}")
