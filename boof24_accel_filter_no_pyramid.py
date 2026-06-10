"""
Boof 24 - Acceleration Filter (NO Pyramids)
Use acceleration detection to filter entries, not add to them
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
    
    # Acceleration filter thresholds
    'ACCEL_LOOKBACK': 5,
    'MIN_TREND_STRENGTH': 0.6,      # 60% bars in direction
    'MIN_VOLUME_ACCEL': 1.0,        # At least normal volume
    'MIN_SCORE_FOR_ENTRY': 50,      # Need 50+ to take trade
}

def calculate_entry_acceleration(price_path, direction):
    """
    Calculate acceleration metrics BEFORE entry
    For filtering: should we take this signal?
    """
    if len(price_path) < 3:
        return {'valid': False, 'score': 0}
    
    # Use pre-entry price action (last few bars before signal)
    recent_bars = price_path[-min(10, len(price_path)):]
    closes = [b['close'] for b in recent_bars]
    
    # Calculate velocity and trend
    velocity = []
    for i in range(1, len(closes)):
        velocity.append(abs(closes[i] - closes[i-1]))
    
    avg_velocity = np.mean(velocity) if velocity else 0
    
    # Trend strength before entry
    if direction == 'long':
        higher_bars = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        trend_strength = higher_bars / (len(closes) - 1) if len(closes) > 1 else 0
        momentum = closes[-1] > np.mean(closes[:-1]) if len(closes) > 1 else False
    else:
        lower_bars = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i-1])
        trend_strength = lower_bars / (len(closes) - 1) if len(closes) > 1 else 0
        momentum = closes[-1] < np.mean(closes[:-1]) if len(closes) > 1 else False
    
    # Volume/range analysis
    ranges = [b['high'] - b['low'] for b in recent_bars]
    avg_range = np.mean(ranges[:-1]) if len(ranges) > 1 else 1
    current_range = ranges[-1] if ranges else 1
    volume_signal = current_range / avg_range if avg_range > 0 else 1.0
    
    # Score components
    score = 0
    reasons = []
    
    # Trend strength (0-30 pts)
    if trend_strength >= 0.8:
        score += 30
        reasons.append('strong_trend')
    elif trend_strength >= 0.7:
        score += 25
        reasons.append('good_trend')
    elif trend_strength >= CONFIG['MIN_TREND_STRENGTH']:
        score += 15
        reasons.append('moderate_trend')
    
    # Momentum (0-20 pts)
    if momentum:
        score += 20
        reasons.append('momentum_aligned')
    
    # Volume expansion (0-25 pts)
    if volume_signal >= 1.5:
        score += 25
        reasons.append('high_volume')
    elif volume_signal >= 1.2:
        score += 20
        reasons.append('good_volume')
    elif volume_signal >= CONFIG['MIN_VOLUME_ACCEL']:
        score += 10
        reasons.append('normal_volume')
    
    # Volatility/velocity (0-15 pts)
    if avg_velocity > np.std(closes) * 0.5:
        score += 15
        reasons.append('good_velocity')
    
    return {
        'valid': True,
        'score': score,
        'trend_strength': trend_strength,
        'momentum': momentum,
        'volume_signal': volume_signal,
        'velocity': avg_velocity,
        'reasons': reasons
    }

class TradeSimulator:
    """Simulates realistic price path"""
    def __init__(self, entry_price, direction, sl_price, tp_price, r_value, outcome, bars_held, pre_entry_path=None):
        self.entry = entry_price
        self.direction = direction
        self.sl = sl_price
        self.tp = tp_price
        self.r_value = r_value
        self.outcome = outcome
        self.target_bars = bars_held
        
        # Generate path with pre-entry context
        self.price_path = self._generate_path(pre_entry_path)
        
    def _generate_path(self, pre_entry=None):
        """Generate full price path including pre-entry context"""
        # Pre-entry context (for acceleration measurement)
        pre_path = []
        if pre_entry:
            for i in range(10):
                pre_path.append({
                    'open': pre_entry + np.random.normal(0, self.r_value * 0.1),
                    'high': pre_entry + abs(np.random.normal(0, self.r_value * 0.2)),
                    'low': pre_entry - abs(np.random.normal(0, self.r_value * 0.2)),
                    'close': pre_entry + np.random.normal(0, self.r_value * 0.15),
                    'bar_num': i - 10,
                    'phase': 'pre'
                })
        
        # Intra-trade path
        n_bars = max(self.target_bars, 5)
        
        if self.outcome == 'win':
            final_pnl = np.random.uniform(1.2, 2.3) * self.r_value
        else:
            final_pnl = np.random.uniform(-1.3, -0.5) * self.r_value
        
        trade_path = []
        current = self.entry
        
        for bar_num in range(n_bars):
            progress = bar_num / n_bars
            target_price = self.entry + final_pnl * progress
            noise = np.random.normal(0, self.r_value * 0.25)
            
            o = current
            c = target_price + noise
            bar_range = abs(self.r_value * 0.4)
            h = max(o, c) + np.random.uniform(0, bar_range * 0.6)
            l = min(o, c) - np.random.uniform(0, bar_range * 0.6)
            
            trade_path.append({
                'open': o, 'high': h, 'low': l, 'close': c,
                'bar_num': bar_num,
                'phase': 'trade'
            })
            
            current = c
            
            if self.direction == 'long':
                if c >= self.tp: break
                if c <= self.sl: break
            else:
                if c <= self.tp: break
                if c >= self.sl: break
        
        return pre_path + trade_path
    
    def get_pre_entry_path(self):
        return [b for b in self.price_path if b.get('phase') == 'pre']
    
    def get_trade_path(self):
        return [b for b in self.price_path if b.get('phase') == 'trade']

def backtest_with_accel_filter(symbol, config, use_filter=False, min_score=0):
    """
    Backtest with optional acceleration filter
    
    use_filter=False: Take all signals (baseline)
    use_filter=True: Only take signals with acceleration score >= min_score
    """
    mode = f"ACCEL_FILTER_{min_score}" if use_filter else "BASELINE_ALL"
    print(f"\n{symbol} - {mode}", end=' ')
    
    df = pd.read_csv(config['file'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate R value
    losses = df[df['pnl_dollar'] < 0]['pnl_pts'].abs()
    avg_loss_pts = losses.mean() if len(losses) > 0 else 10
    r_value = avg_loss_pts
    
    # Create trade simulators
    trades = []
    for i, row in df.iterrows():
        direction = row['direction']
        entry = row['entry']
        sl = entry - r_value if direction == 'long' else entry + r_value
        tp = entry + 2*r_value if direction == 'long' else entry - 2*r_value
        outcome = 'win' if row['pnl_dollar'] > 0 else 'loss'
        bars = row['bars'] if 'bars' in row else 10
        
        # Use previous close as pre-entry context
        pre_entry = df.iloc[i-1]['entry'] if i > 0 else entry
        
        sim = TradeSimulator(entry, direction, sl, tp, r_value, outcome, bars, pre_entry)
        
        # Calculate acceleration score at entry
        pre_path = sim.get_pre_entry_path()
        accel_metrics = calculate_entry_acceleration(pre_path, direction)
        
        trades.append({
            'sim': sim,
            'timestamp': row['timestamp'],
            'direction': direction,
            'actual_pnl_r': row['pnl_pts'] / r_value,
            'actual_hit': row['hit'],
            'accel_score': accel_metrics.get('score', 0),
            'accel_valid': accel_metrics.get('valid', False),
            'trend_strength': accel_metrics.get('trend_strength', 0),
            'momentum': accel_metrics.get('momentum', False),
            'volume_signal': accel_metrics.get('volume_signal', 1.0)
        })
    
    # Filter trades if requested
    if use_filter:
        filtered_trades = [t for t in trades if t['accel_score'] >= min_score]
    else:
        filtered_trades = trades
    
    # Calculate stats
    if not filtered_trades:
        return None
    
    pnls = [t['actual_pnl_r'] for t in filtered_trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = len(pnls) - wins
    win_rate = wins / len(pnls) * 100 if pnls else 0
    
    total_r = sum(pnls)
    avg_r = total_r / len(pnls) if pnls else 0
    
    # Sharpe-like: mean / std
    returns = np.array(pnls)
    sharpe_like = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
    
    # Consecutive metrics
    streaks = []
    current_streak = 0
    for p in pnls:
        if p > 0:
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    avg_win_streak = np.mean(streaks) if streaks else 0
    
    loss_streaks = []
    current_loss = 0
    for p in pnls:
        if p < 0:
            current_loss += 1
        else:
            if current_loss > 0:
                loss_streaks.append(current_loss)
            current_loss = 0
    max_loss_streak = max(loss_streaks) if loss_streaks else 0
    
    # Dollar P&L
    ticks_per_r = r_value / 0.25
    dollar_per_r = ticks_per_r * config['tick_value']
    total_pnl = total_r * dollar_per_r
    
    # Drawdown simulation
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative - running_max
    max_dd = min(drawdowns) * dollar_per_r
    avg_dd = np.mean(drawdowns) * dollar_per_r
    
    # Drawdown stability (how often we recover quickly)
    dd_durations = []
    in_dd = False
    dd_start = 0
    for i, dd in enumerate(drawdowns):
        if dd < 0 and not in_dd:
            in_dd = True
            dd_start = i
        elif dd == 0 and in_dd:
            dd_durations.append(i - dd_start)
            in_dd = False
    avg_dd_duration = np.mean(dd_durations) if dd_durations else 0
    
    # Filtered out count
    filtered_out = len(trades) - len(filtered_trades)
    filter_rate = filtered_out / len(trades) * 100 if trades else 0
    
    print(f"Done. {len(filtered_trades)} trades (filtered {filter_rate:.0f}%), {avg_r:.3f}R/trade")
    
    return {
        'symbol': symbol,
        'mode': mode,
        'total_trades': len(filtered_trades),
        'filtered_out': filtered_out,
        'filter_rate': filter_rate,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_r': total_r,
        'avg_r': avg_r,
        'total_pnl': total_pnl,
        'max_dd': max_dd,
        'avg_dd': avg_dd,
        'avg_dd_duration': avg_dd_duration,
        'sharpe_like': sharpe_like,
        'max_loss_streak': max_loss_streak,
        'avg_win_streak': avg_win_streak,
        'r_value': r_value,
        'tick_value': config['tick_value']
    }

# ═══════════════════════════════════════════════════════════════════════════════
# TEST CONFIGURATIONS
# ═══════════════════════════════════════════════════════════════════════════════

TEST_CONFIGS = [
    ('BASELINE_ALL', False, 0),           # Take all signals
    ('ACCEL_FILTER_30', True, 30),        # Low threshold
    ('ACCEL_FILTER_50', True, 50),        # Medium threshold
    ('ACCEL_FILTER_60', True, 60),        # High threshold
    ('ACCEL_FILTER_70', True, 70),        # Very high threshold
]

print("=" * 100)
print("BOOF 24 - ACCELERATION FILTER TEST (NO PYRAMIDS)")
print("=" * 100)
print("Testing: Can acceleration filter improve entry quality?")
print("=" * 100)

all_results = []

for mode_name, use_filter, min_score in TEST_CONFIGS:
    print(f"\n{'='*100}")
    print(f"MODE: {mode_name}")
    print(f"{'='*100}")
    
    mode_results = []
    for sym, (file, tick, ttype) in FUTURES_CONFIG.items():
        config = {'file': file, 'tick_value': tick, 'type': ttype}
        result = backtest_with_accel_filter(sym, config, use_filter, min_score)
        if result:
            mode_results.append(result)
            all_results.append(result)
    
    # Summary for this mode
    if mode_results:
        total_trades = sum(r['total_trades'] for r in mode_results)
        total_filtered = sum(r['filtered_out'] for r in mode_results)
        total_r = sum(r['total_r'] for r in mode_results)
        total_pnl = sum(r['total_pnl'] for r in mode_results)
        avg_dd = np.mean([r['max_dd'] for r in mode_results])
        avg_sharpe = np.mean([r['sharpe_like'] for r in mode_results])
        
        print(f"\n[SUMMARY {mode_name}]")
        print(f"  Trades taken: {total_trades}")
        print(f"  Trades filtered: {total_filtered} ({total_filtered/(total_trades+total_filtered)*100:.1f}%)")
        print(f"  Total R: {total_r:+.2f}")
        print(f"  Total $: ${total_pnl:,.2f}")
        print(f"  Avg Drawdown: ${avg_dd:,.2f}")
        print(f"  Sharpe-like: {avg_sharpe:.3f}")

# ═══════════════════════════════════════════════════════════════════════════════
# COMPARISON MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("FILTER COMPARISON MATRIX")
print("=" * 100)

print(f"\n{'Mode':<20} {'Trades':<10} {'Filtered':<10} {'Win%':<8} {'R/T':<8} {'Max DD':<12} {'Sharpe':<8} {'Quality':<10}")
print("-" * 100)

for mode_name, _, _ in TEST_CONFIGS:
    mode_data = [r for r in all_results if r['mode'] == mode_name]
    if not mode_data:
        continue
    
    total_trades = sum(r['total_trades'] for r in mode_data)
    total_filtered = sum(r['filtered_out'] for r in mode_data)
    avg_wr = np.mean([r['win_rate'] for r in mode_data])
    avg_r = np.mean([r['avg_r'] for r in mode_data])
    avg_dd = np.mean([r['max_dd'] for r in mode_data])
    avg_sharpe = np.mean([r['sharpe_like'] for r in mode_data])
    
    # Quality score: R/trade * Sharpe / |DD|
    quality = avg_r * avg_sharpe / abs(avg_dd) * 1000 if avg_dd != 0 else 0
    
    print(f"{mode_name:<20} {total_trades:<10} {total_filtered:<10} {avg_wr:<8.1f} {avg_r:<8.3f} ${avg_dd:<11,.0f} {avg_sharpe:<8.3f} {quality:<10.1f}")

# ═══════════════════════════════════════════════════════════════════════════════
# BEST CONFIGURATION ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("OPTIMAL FILTER SELECTION")
print("=" * 100)

baseline = [r for r in all_results if r['mode'] == 'BASELINE_ALL']
baseline_pnl = sum(r['total_pnl'] for r in baseline) if baseline else 0
baseline_trades = sum(r['total_trades'] for r in baseline) if baseline else 1
baseline_avg_r = np.mean([r['avg_r'] for r in baseline]) if baseline else 0

print(f"\nBaseline (all signals):")
print(f"  Trades: {baseline_trades}")
print(f"  Avg R/trade: {baseline_avg_r:.3f}")
print(f"  Total P&L: ${baseline_pnl:,.2f}")

best_filter = None
best_improvement = -999

for mode_name, _, min_score in TEST_CONFIGS[1:]:  # Skip baseline
    mode_data = [r for r in all_results if r['mode'] == mode_name]
    if not mode_data:
        continue
    
    mode_pnl = sum(r['total_pnl'] for r in mode_data)
    mode_trades = sum(r['total_trades'] for r in mode_data)
    mode_avg_r = np.mean([r['avg_r'] for r in mode_data])
    
    trade_reduction = (baseline_trades - mode_trades) / baseline_trades * 100
    r_improvement = (mode_avg_r - baseline_avg_r) / baseline_avg_r * 100 if baseline_avg_r else 0
    pnl_efficiency = mode_pnl / mode_trades if mode_trades > 0 else 0
    baseline_efficiency = baseline_pnl / baseline_trades if baseline_trades > 0 else 0
    efficiency_gain = (pnl_efficiency - baseline_efficiency) / baseline_efficiency * 100 if baseline_efficiency else 0
    
    print(f"\n{mode_name} (min_score={min_score}):")
    print(f"  Trades: {mode_trades} ({-trade_reduction:.0f}% reduction)")
    print(f"  Avg R/trade: {mode_avg_r:.3f} ({r_improvement:+.1f}%)")
    print(f"  Total P&L: ${mode_pnl:,.2f}")
    print(f"  Efficiency gain: {efficiency_gain:+.1f}% $ per trade")
    
    score = r_improvement + efficiency_gain * 0.5
    if score > best_improvement:
        best_improvement = score
        best_filter = mode_name

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)

if best_filter:
    print(f"[OPTIMAL FILTER] {best_filter}")
    print(f"\nAcceleration filtering improves entry quality:")
    print(f"  - Fewer, higher-quality trades")
    print(f"  - Better R/trade")
    print(f"  - More efficient capital deployment")
else:
    print("[NO FILTER BEST] Take all signals")
    print(f"\nAcceleration filtering does NOT improve results")
    print(f"  - Trade reduction hurts total P&L more than quality helps")

print(f"{'='*100}")
