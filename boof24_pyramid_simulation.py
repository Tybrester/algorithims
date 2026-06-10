"""
Boof 24 Pyramid Simulation
Analyze existing trade data to find pyramid opportunities
2nd entry only if: 1st trade +1R AND trend confirmed
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

FUTURES_CONFIG = {
    'ES':   ('futures_ES_6mo_20260606.csv',   12.50, 'IMPULSE'),
    'MES':  ('futures_MES_6mo_20260606.csv',  1.25,  'IMPULSE'),
    'NQ':   ('futures_NQ_6mo_20260606.csv',   5.00,  'BREAKOUT'),
    'MNQ':  ('futures_MNQ_6mo_20260606.csv',  0.50,  'BREAKOUT'),
}

CONFIG = {
    'TP_R': 2.0,
    'SL_R': 1.0,
    'PYRAMID_MIN_R': 1.0,      # First trade must be +1R to allow pyramid
    'PYRAMID_MAX_DELAY': 5,    # Max bars after first entry to pyramid
}

def simulate_pyramid(symbol, filename, tick_value, trade_type):
    """Simulate pyramid strategy on saved trade data"""
    print(f"\n{symbol} ({trade_type}):", end=' ')
    
    df = pd.read_csv(filename)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate R-multiple per trade
    losses = df[df['pnl_dollar'] < 0]['pnl_pts'].abs()
    avg_loss_pts = losses.mean() if len(losses) > 0 else 10
    r_value = avg_loss_pts  # 1R in points
    
    df['pnl_r'] = df['pnl_pts'] / r_value
    
    # Simulate base strategy (1 trade at a time)
    base_trades = []
    in_trade = False
    
    for i, row in df.iterrows():
        if not in_trade:
            base_trades.append({
                'timestamp': row['timestamp'],
                'direction': row['direction'],
                'pnl_r': row['pnl_r'],
                'entry_r': 1,
                'pyramid': False
            })
            in_trade = True
        else:
            # Next trade only after previous exits (sequential)
            in_trade = False
    
    # Simulate pyramid strategy
    # 2nd entry allowed if:
    # 1. First trade hit +1R profit
    # 2. Same direction trend
    pyramid_trades = []
    
    i = 0
    while i < len(df):
        row = df.iloc[i]
        
        # First entry (always take it)
        first_pnl = row['pnl_r']
        first_dir = row['direction']
        first_time = row['timestamp']
        
        pyramid_trades.append({
            'timestamp': first_time,
            'direction': first_dir,
            'pnl_r': first_pnl,
            'entry_r': 1,
            'pyramid': False,
            'hit': row['hit']
        })
        
        # Check if we can pyramid
        # Condition 1: First trade was +1R winner
        can_pyramid = first_pnl >= CONFIG['PYRAMID_MIN_R']
        
        if can_pyramid and i + 1 < len(df):
            next_row = df.iloc[i + 1]
            
            # Condition 2: Same direction (trend continuation)
            # Condition 3: Close in time (within delay bars - approx by time)
            time_diff = (next_row['timestamp'] - first_time).total_seconds() / 60  # minutes
            same_direction = next_row['direction'] == first_dir
            
            if same_direction and time_diff <= CONFIG['PYRAMID_MAX_DELAY'] * 5:  # 5-min bars
                # Take pyramid entry
                pyramid_trades.append({
                    'timestamp': next_row['timestamp'],
                    'direction': next_row['direction'],
                    'pnl_r': next_row['pnl_r'],
                    'entry_r': 2,
                    'pyramid': True,
                    'hit': next_row['hit']
                })
                i += 2  # Skip both trades
                continue
        
        i += 1
    
    # Calculate stats
    base_total = len(base_trades)
    base_wins = sum(1 for t in base_trades if t['pnl_r'] > 0)
    base_r = sum(t['pnl_r'] for t in base_trades)
    base_avg_r = base_r / base_total if base_total > 0 else 0
    
    pyr_total = len(pyramid_trades)
    pyr_wins = sum(1 for t in pyramid_trades if t['pnl_r'] > 0)
    pyr_r = sum(t['pnl_r'] for t in pyramid_trades)
    pyr_avg_r = pyr_r / pyr_total if pyr_total > 0 else 0
    
    # Breakdown
    first_entries = [t for t in pyramid_trades if not t['pyramid']]
    pyramids = [t for t in pyramid_trades if t['pyramid']]
    
    first_r_avg = sum(t['pnl_r'] for t in first_entries) / len(first_entries) if first_entries else 0
    pyr_r_avg = sum(t['pnl_r'] for t in pyramids) / len(pyramids) if pyramids else 0
    
    # Dollar P&L
    ticks_per_r = r_value / 0.25
    dollar_per_r = ticks_per_r * tick_value
    base_pnl = base_r * dollar_per_r
    pyr_pnl = pyr_r * dollar_per_r
    
    print(f"Base: {base_total} trades @ {base_avg_r:.3f}R | Pyramid: {pyr_total} trades @ {pyr_avg_r:.3f}R")
    
    return {
        'symbol': symbol,
        'type': trade_type,
        'base_trades': base_total,
        'base_r': base_r,
        'base_avg_r': base_avg_r,
        'base_pnl': base_pnl,
        'pyr_trades': pyr_total,
        'pyr_r': pyr_r,
        'pyr_avg_r': pyr_avg_r,
        'pyr_pnl': pyr_pnl,
        'first_count': len(first_entries),
        'pyramid_count': len(pyramids),
        'first_avg_r': first_r_avg,
        'pyr_only_avg_r': pyr_r_avg,
        'r_value': r_value,
        'tick_value': tick_value
    }

# ═══════════════════════════════════════════════════════════════════════════════
# RUN SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("BOOF 24 FUTURES - PYRAMID SIMULATION")
print("=" * 90)
print("Rules: 2nd entry only if 1st trade +1.0R AND same direction within 25 min")
print("=" * 90)

results = []
for sym, (file, tick, ttype) in FUTURES_CONFIG.items():
    result = simulate_pyramid(sym, file, tick, ttype)
    if result:
        results.append(result)

# ═══════════════════════════════════════════════════════════════════════════════
# COMPARISON TABLE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("BASE vs PYRAMID COMPARISON")
print("=" * 90)

print(f"\n{'Symbol':<8} {'Type':<10} {'Base Trades':<12} {'Base R/T':<10} {'Base $':<12} {'Pyr Trades':<12} {'Pyr R/T':<10} {'Pyr $':<12} {'Delta':<8}")
print("-" * 110)

total_base_r = 0
total_pyr_r = 0
total_base_pnl = 0
total_pyr_pnl = 0

for r in results:
    delta = r['pyr_avg_r'] - r['base_avg_r']
    delta_str = f"+{delta:.3f}" if delta > 0 else f"{delta:.3f}"
    status = "[BETTER]" if delta > 0.05 else "[SAME]" if delta > -0.05 else "[WORSE]"
    
    print(f"{r['symbol']:<8} {r['type']:<10} {r['base_trades']:<12} {r['base_avg_r']:<10.3f} ${r['base_pnl']:<11,.2f} "
          f"{r['pyr_trades']:<12} {r['pyr_avg_r']:<10.3f} ${r['pyr_pnl']:<11,.2f} {delta_str:<8} {status}")
    
    total_base_r += r['base_r']
    total_pyr_r += r['pyr_r']
    total_base_pnl += r['base_pnl']
    total_pyr_pnl += r['pyr_pnl']

# ═══════════════════════════════════════════════════════════════════════════════
# PYRAMID BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("PYRAMID ENTRY PERFORMANCE")
print("=" * 90)

total_first = sum(r['first_count'] for r in results)
total_pyramid = sum(r['pyramid_count'] for r in results)

first_r_total = sum(r['first_avg_r'] * r['first_count'] for r in results)
pyr_r_total = sum(r['pyr_only_avg_r'] * r['pyramid_count'] for r in results)

first_r_avg = first_r_total / total_first if total_first > 0 else 0
pyr_r_avg = pyr_r_total / total_pyramid if total_pyramid > 0 else 0

print(f"\nFirst Entries:  {total_first} trades | Avg R: {first_r_avg:.3f}")
print(f"Pyramid Adds:   {total_pyramid} trades | Avg R: {pyr_r_avg:.3f}")
print(f"Pyramid Rate:   {total_pyramid/total_first*100:.1f}% of first entries got pyramid add")

if pyr_r_avg > first_r_avg:
    print(f"\n>> Pyramid entries outperform first entries by +{pyr_r_avg - first_r_avg:.3f}R")
else:
    print(f"\n>> Pyramid entries underperform first entries by {pyr_r_avg - first_r_avg:.3f}R")

# ═══════════════════════════════════════════════════════════════════════════════
# TOTAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("GRAND TOTAL COMPARISON")
print("=" * 90)

base_avg = total_base_r / sum(r['base_trades'] for r in results)
pyr_avg = total_pyr_r / sum(r['pyr_trades'] for r in results)

print(f"\n{'Strategy':<15} {'Total Trades':<15} {'Total R':<15} {'R/Trade':<10} {'Total $':<15}")
print("-" * 75)
print(f"{'Base (1 pos)':<15} {sum(r['base_trades'] for r in results):<15} {total_base_r:+.2f}{'':<10} {base_avg:.3f}{'':<7} ${total_base_pnl:,.2f}")
print(f"{'Pyramid (2 pos)':<15} {sum(r['pyr_trades'] for r in results):<15} {total_pyr_r:+.2f}{'':<10} {pyr_avg:.3f}{'':<7} ${total_pyr_pnl:,.2f}")

delta_r = pyr_avg - base_avg
delta_pnl = total_pyr_pnl - total_base_pnl

print(f"\nPyramid adds: {delta_r:+.3f} R/trade | ${delta_pnl:+,.2f} total")

print(f"\n{'=' * 90}")
if delta_r > 0.05:
    print(f"[PYRAMID WORKS] Adding to winners increases edge by {delta_r:.3f}R")
elif delta_r > -0.05:
    print(f"[NEUTRAL] Pyramid doesn't significantly change performance")
else:
    print(f"[PYRAMID FAILS] Adding to winners hurts by {abs(delta_r):.3f}R")
print(f"{'=' * 90}")

# ═══════════════════════════════════════════════════════════════════════════════
# RISK ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("RISK ANALYSIS: DOUBLE POSITION DRAWDOWNS")
print("=" * 90)

print("\nWhen pyramid entry hits SL while first position still open:")
print("- Both positions take 1R loss simultaneously")
print("- Risk doubles: 2R total loss instead of 1R")
print("- Worst case: 24 consecutive pyramid entries = 48R loss potential")
print("\nRecommendation: Reduce base position size by 25-30% when pyramiding")
