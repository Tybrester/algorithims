"""
Boof 24 Futures - Acceleration-Based Continuation Detection
Pyramid entry when price shows acceleration, not just +1R profit
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
    'TIME_EXIT_BARS': 20,
    
    # Acceleration detection
    'ACCEL_LOOKBACK': 5,           # Bars to measure velocity
    'ACCEL_THRESHOLD': 1.5,         # Min velocity to consider continuation
    'VOLUME_ACCEL_MIN': 1.2,       # Volume must be 1.2x recent average
    
    # Pyramid sizing
    'BASE_SIZE': 1.0,
    'PYRAMID_SIZE': 0.5,
    
    # Filters to test
    'MAX_PYRAMID_DELAY': 8,        # Must pyramid within 8 bars
}

def calculate_acceleration_metrics(price_path, current_bar, direction):
    """
    Calculate price and volume acceleration metrics
    Returns dict with acceleration signals
    """
    if current_bar < 2:
        return {'valid': False}
    
    # Get recent price action (simulated from path)
    recent_bars = price_path[max(0, current_bar-CONFIG['ACCEL_LOOKBACK']):current_bar+1]
    if len(recent_bars) < 3:
        return {'valid': False}
    
    closes = [b['close'] for b in recent_bars]
    
    # Price velocity (rate of change)
    velocity = []
    for i in range(1, len(closes)):
        velocity.append(closes[i] - closes[i-1])
    
    # Acceleration (change in velocity)
    accel = []
    for i in range(1, len(velocity)):
        accel.append(velocity[i] - velocity[i-1])
    
    avg_velocity = np.mean(velocity) if velocity else 0
    avg_accel = np.mean(accel) if accel else 0
    
    # Trend strength - higher highs/lows
    if direction == 'long':
        higher_highs = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        trend_strength = higher_highs / (len(closes) - 1)
        momentum_aligned = closes[-1] > np.mean(closes[:-1])
    else:
        lower_lows = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])
        trend_strength = lower_lows / (len(closes) - 1)
        momentum_aligned = closes[-1] < np.mean(closes[:-1])
    
    # Volume simulation (based on price range)
    ranges = [b['high'] - b['low'] for b in recent_bars]
    avg_range = np.mean(ranges[:-1]) if len(ranges) > 1 else 1
    current_range = ranges[-1] if ranges else 1
    volume_accel = current_range / avg_range if avg_range > 0 else 1.0
    
    return {
        'valid': True,
        'velocity': avg_velocity,
        'acceleration': avg_accel,
        'trend_strength': trend_strength,
        'momentum_aligned': momentum_aligned,
        'volume_accel': volume_accel,
        'recent_closes': closes
    }

def check_acceleration_continuation(price_path, current_bar, direction, unrealized_r):
    """
    Check if acceleration supports continuation (pyramid entry)
    
    Returns: (eligible, score, metrics)
    """
    metrics = calculate_acceleration_metrics(price_path, current_bar, direction)
    
    if not metrics['valid']:
        return False, 0, metrics
    
    score = 0
    reasons = []
    
    # 1. Must have positive unrealized (some profit buffer)
    if unrealized_r < 0.3:
        return False, 0, metrics
    score += min(unrealized_r * 10, 20)  # Up to 20 points for profit
    
    # 2. Trend strength (must be strong continuation)
    if metrics['trend_strength'] >= 0.7:  # 70%+ bars in direction
        score += 25
        reasons.append('strong_trend')
    elif metrics['trend_strength'] >= 0.6:
        score += 15
        reasons.append('moderate_trend')
    
    # 3. Momentum alignment (current bar continuing)
    if metrics['momentum_aligned']:
        score += 20
        reasons.append('momentum_aligned')
    
    # 4. Volume acceleration
    if metrics['volume_accel'] >= CONFIG['VOLUME_ACCEL_MIN']:
        score += 20
        reasons.append('volume_accel')
    elif metrics['volume_accel'] >= 1.0:
        score += 10
        reasons.append('volume_normal')
    
    # 5. Price acceleration (second derivative positive)
    if direction == 'long' and metrics['acceleration'] > 0:
        score += 15
        reasons.append('price_accel')
    elif direction == 'short' and metrics['acceleration'] < 0:
        score += 15
        reasons.append('price_accel')
    
    # Threshold: need 60+ score to pyramid
    eligible = score >= 60
    
    return eligible, score, metrics

class TradeSimulator:
    """Simulates realistic price path for a trade"""
    def __init__(self, entry_price, direction, sl_price, tp_price, r_value, outcome, bars_held):
        self.entry = entry_price
        self.direction = direction
        self.sl = sl_price
        self.tp = tp_price
        self.r_value = r_value
        self.outcome = outcome
        self.target_bars = bars_held
        
        # Generate realistic intratrade price path
        self.price_path = self._generate_path()
        
    def _generate_path(self):
        """Generate realistic OHLC path through the trade"""
        n_bars = max(self.target_bars, 5)
        
        # Determine final outcome and magnitude
        if self.outcome == 'win':
            # Winner - could hit TP or time exit positive
            final_pnl = np.random.uniform(1.2, 2.3) * self.r_value
        else:
            # Loser - could hit SL or time exit negative
            final_pnl = np.random.uniform(-1.3, -0.5) * self.r_value
        
        # Generate realistic path
        path = []
        current = self.entry
        
        for bar_num in range(n_bars):
            # Progress toward final outcome with noise
            progress = bar_num / n_bars
            target_price = self.entry + final_pnl * progress
            
            # Add intrabar noise
            noise = np.random.normal(0, self.r_value * 0.25)
            
            # Create OHLC
            o = current
            c = target_price + noise
            
            # Add wicks (price exploration)
            bar_range = abs(self.r_value * 0.4)
            h = max(o, c) + np.random.uniform(0, bar_range * 0.6)
            l = min(o, c) - np.random.uniform(0, bar_range * 0.6)
            
            # Calculate unrealized R
            if self.direction == 'long':
                unrealized = (c - self.entry) / self.r_value
            else:
                unrealized = (self.entry - c) / self.r_value
            
            path.append({
                'open': o, 'high': h, 'low': l, 'close': c,
                'bar_num': bar_num,
                'unrealized_r': unrealized
            })
            
            current = c
            
            # Check for early exit
            if self.direction == 'long':
                if c >= self.tp: break
                if c <= self.sl: break
            else:
                if c <= self.tp: break
                if c >= self.sl: break
        
        return path
    
    def get_bar(self, bar_num):
        if bar_num < len(self.price_path):
            return self.price_path[bar_num]
        return None

def backtest_acceleration_pyramid(symbol, config, use_acceleration=True):
    """
    Backtest with acceleration-based pyramid detection
    """
    print(f"\n{symbol} - {'Acceleration' if use_acceleration else 'Base Only'}", end=' ')
    
    df = pd.read_csv(config['file'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate R value
    losses = df[df['pnl_dollar'] < 0]['pnl_pts'].abs()
    avg_loss_pts = losses.mean() if len(losses) > 0 else 10
    r_value = avg_loss_pts
    
    # Create trade simulators
    trades = []
    for _, row in df.iterrows():
        direction = row['direction']
        entry = row['entry']
        sl = entry - r_value if direction == 'long' else entry + r_value
        tp = entry + 2*r_value if direction == 'long' else entry - 2*r_value
        outcome = 'win' if row['pnl_dollar'] > 0 else 'loss'
        bars = row['bars'] if 'bars' in row else 10
        
        sim = TradeSimulator(entry, direction, sl, tp, r_value, outcome, bars)
        trades.append({
            'sim': sim,
            'timestamp': row['timestamp'],
            'direction': direction,
            'actual_pnl_r': row['pnl_pts'] / r_value,
            'actual_hit': row['hit']
        })
    
    # State machine
    STATE_IDLE = 0
    STATE_IN_BASE = 1
    STATE_PYRAMID = 2
    
    state = STATE_IDLE
    completed_trades = []
    bar_counter = 0
    
    acceleration_signals = []  # Track when accel triggers
    
    for trade_data in trades:
        sim = trade_data['sim']
        direction = trade_data['direction']
        
        if state == STATE_IDLE:
            # Enter base position
            state = STATE_IN_BASE
            bar_counter = 0
            pyramid_added = False
            
        elif state == STATE_IN_BASE:
            bar = sim.get_bar(bar_counter)
            
            if not bar:
                # Trade closed - record base only
                completed_trades.append({
                    'pnl_r': trade_data['actual_pnl_r'] * CONFIG['BASE_SIZE'],
                    'entry_type': 'base',
                    'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss',
                    'accel_triggered': False
                })
                state = STATE_IDLE
                continue
            
            # Check for acceleration-based pyramid
            if use_acceleration and not pyramid_added and bar_counter <= CONFIG['MAX_PYRAMID_DELAY']:
                eligible, score, metrics = check_acceleration_continuation(
                    sim.price_path, bar_counter, direction, bar['unrealized_r']
                )
                
                if eligible:
                    acceleration_signals.append({
                        'symbol': symbol,
                        'bar': bar_counter,
                        'score': score,
                        'unrealized_r': bar['unrealized_r'],
                        'metrics': metrics
                    })
                    pyramid_added = True
            
            bar_counter += 1
            
            # Continue monitoring until trade closes
            next_bar = sim.get_bar(bar_counter)
            if not next_bar:
                # Trade closed
                base_pnl = trade_data['actual_pnl_r'] * CONFIG['BASE_SIZE']
                
                if pyramid_added:
                    # Both positions exit together
                    pyr_pnl = trade_data['actual_pnl_r'] * CONFIG['PYRAMID_SIZE']
                    completed_trades.append({
                        'pnl_r': base_pnl,
                        'entry_type': 'base',
                        'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss',
                        'accel_triggered': True
                    })
                    completed_trades.append({
                        'pnl_r': pyr_pnl,
                        'entry_type': 'pyramid',
                        'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss',
                        'accel_triggered': True
                    })
                else:
                    completed_trades.append({
                        'pnl_r': base_pnl,
                        'entry_type': 'base',
                        'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss',
                        'accel_triggered': False
                    })
                
                state = STATE_IDLE
    
    # Calculate stats
    if not completed_trades:
        return None
    
    base_trades = [t for t in completed_trades if t['entry_type'] == 'base']
    pyr_trades = [t for t in completed_trades if t['entry_type'] == 'pyramid']
    accel_trades = [t for t in completed_trades if t['accel_triggered']]
    
    total_r = sum(t['pnl_r'] for t in completed_trades)
    total_trades = len(completed_trades)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    
    base_r = sum(t['pnl_r'] for t in base_trades) / len(base_trades) if base_trades else 0
    pyr_r = sum(t['pnl_r'] for t in pyr_trades) / len(pyr_trades) if pyr_trades else 0
    
    # Dollar P&L
    ticks_per_r = r_value / 0.25
    dollar_per_r = ticks_per_r * config['tick_value']
    total_pnl = total_r * dollar_per_r
    
    # Drawdown
    cumulative = np.cumsum([t['pnl_r'] for t in completed_trades])
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative - running_max
    max_dd = drawdown.min() * dollar_per_r
    
    # Win rates
    base_wins = sum(1 for t in base_trades if t['result'] == 'win')
    pyr_wins = sum(1 for t in pyr_trades if t['result'] == 'win')
    base_wr = base_wins / len(base_trades) * 100 if base_trades else 0
    pyr_wr = pyr_wins / len(pyr_trades) * 100 if pyr_trades else 0
    
    print(f"Done. {len(base_trades)} base, {len(pyr_trades)} accel-pyramids")
    
    return {
        'symbol': symbol,
        'use_accel': use_acceleration,
        'base_trades': len(base_trades),
        'pyr_trades': len(pyr_trades),
        'accel_rate': len(pyr_trades) / len(base_trades) * 100 if base_trades else 0,
        'base_wr': base_wr,
        'pyr_wr': pyr_wr,
        'base_r': base_r,
        'pyr_r': pyr_r,
        'combined_avg_r': avg_r,
        'total_r': total_r,
        'total_pnl': total_pnl,
        'max_dd': max_dd,
        'ret_dd': abs(total_pnl / max_dd) if max_dd != 0 else 0,
        'acceleration_signals': len(acceleration_signals)
    }

# ═══════════════════════════════════════════════════════════════════════════════
# RUN ACCELERATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 100)
print("BOOF 24 - ACCELERATION-BASED CONTINUATION DETECTION")
print("=" * 100)
print("Pyramid when: trend strength + momentum + volume acceleration + price accel")
print("=" * 100)

results_base = []
results_accel = []

for sym, (file, tick, ttype) in FUTURES_CONFIG.items():
    config = {'file': file, 'tick_value': tick, 'type': ttype}
    
    # Base only
    result_base = backtest_acceleration_pyramid(sym, config, use_acceleration=False)
    if result_base:
        results_base.append(result_base)
    
    # With acceleration pyramid
    result_accel = backtest_acceleration_pyramid(sym, config, use_acceleration=True)
    if result_accel:
        results_accel.append(result_accel)

# ═══════════════════════════════════════════════════════════════════════════════
# COMPARISON
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("BASE vs ACCELERATION PYRAMID COMPARISON")
print("=" * 100)

print(f"\n{'Symbol':<8} {'Mode':<12} {'Trades':<10} {'Pyr Rate':<12} {'Base WR':<10} {'Pyr WR':<10} {'Base R':<10} {'Pyr R':<10} {'Combined':<10}")
print("-" * 100)

for i, sym in enumerate(['ES', 'MES', 'NQ', 'MNQ']):
    base = results_base[i] if i < len(results_base) else None
    accel = results_accel[i] if i < len(results_accel) else None
    
    if base:
        print(f"{sym:<8} {'BASE ONLY':<12} {base['base_trades']:<10} {'0%':<12} {base['base_wr']:<10.1f} {'N/A':<10} {base['base_r']:<10.3f} {'N/A':<10} {base['combined_avg_r']:<10.3f}")
    
    if accel:
        pyr_rate = f"{accel['accel_rate']:.1f}%"
        pyr_wr = f"{accel['pyr_wr']:.1f}"
        pyr_r = f"{accel['pyr_r']:.3f}"
        print(f"{sym:<8} {'ACCEL PYR':<12} {accel['base_trades']:<10} {pyr_rate:<12} {accel['base_wr']:<10.1f} {pyr_wr:<10} {accel['base_r']:<10.3f} {pyr_r:<10} {accel['combined_avg_r']:<10.3f}")

# ═══════════════════════════════════════════════════════════════════════════════
# TOTALS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("GRAND TOTALS")
print("=" * 100)

base_total_r = sum(r['total_r'] for r in results_base)
base_total_pnl = sum(r['total_pnl'] for r in results_base)
base_avg_dd = sum(r['max_dd'] for r in results_base) / len(results_base) if results_base else 1

accel_total_r = sum(r['total_r'] for r in results_accel)
accel_total_pnl = sum(r['total_pnl'] for r in results_accel)
accel_avg_dd = sum(r['max_dd'] for r in results_accel) / len(results_accel) if results_accel else 1

print(f"\n{'Strategy':<20} {'Total R':<15} {'Total $':<15} {'Avg DD':<15} {'R/DD':<10}")
print("-" * 80)
print(f"{'Base Only':<20} {base_total_r:<15.2f} ${base_total_pnl:<14,.0f} ${base_avg_dd:<14,.0f} {abs(base_total_pnl/base_avg_dd):<10.2f}")
print(f"{'Accel Pyramid':<20} {accel_total_r:<15.2f} ${accel_total_pnl:<14,.0f} ${accel_avg_dd:<14,.0f} {abs(accel_total_pnl/accel_avg_dd):<10.2f}")

improvement = (accel_total_pnl - base_total_pnl) / abs(base_total_pnl) * 100 if base_total_pnl else 0
print(f"\nAcceleration improvement: {improvement:+.1f}% profit | DD change: ${accel_avg_dd - base_avg_dd:+.0f}")

# ═══════════════════════════════════════════════════════════════════════════════
# ACCELERATION SCORE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("ACCELERATION SIGNAL BREAKDOWN")
print("=" * 100)

print("\nAcceleration Score Components (need 60+ to trigger):")
print("  + Unrealized profit (0-20 pts based on +R)")
print("  + Trend strength 70%+ (25 pts) or 60%+ (15 pts)")
print("  + Momentum aligned (20 pts)")
print("  + Volume accel 1.2x+ (20 pts) or 1.0x+ (10 pts)")
print("  + Price acceleration (15 pts)")

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
base_score = abs(base_total_pnl / base_avg_dd) if base_avg_dd else 0
accel_score = abs(accel_total_pnl / accel_avg_dd) if accel_avg_dd else 0

if accel_score > base_score * 1.1:
    print(f"[ACCELERATION WORKS] Return/DD improved from {base_score:.1f}x to {accel_score:.1f}x")
elif accel_score > base_score * 0.9:
    print(f"[NEUTRAL] Acceleration similar to base ({base_score:.1f}x vs {accel_score:.1f}x)")
else:
    print(f"[ACCELERATION FAILS] Return/DD degraded from {base_score:.1f}x to {accel_score:.1f}x")

print(f"{'='*100}")
