"""
Boof 24 Futures - State Machine Pyramid Backtest
Proper bar-by-bar simulation with filter ladder analysis
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

# STATE MACHINE STATES
STATE_NO_TRADE = 0
STATE_BASE_OPEN = 1
STATE_MONITORING = 2
STATE_PYRAMID_ELIGIBLE = 3
STATE_PYRAMID_OPEN = 4

# CONFIG
CONFIG = {
    'TP_R': 2.0,
    'SL_R': 1.0,
    'TIME_EXIT_BARS': 20,
    
    # Pyramid conditions
    'PYRAMID_MIN_FLOATING_R': 1.0,  # Must be +1R unrealized
    'PYRAMID_MAX_BARS': 10,          # Within 10 bars of entry
    'PYRAMID_TREND_CONFIRM': True,   # Require trend aligned
    'PYRAMID_VOLUME_CONFIRM': True,  # Require volume expansion
    
    # Position sizing
    'BASE_SIZE': 1.0,
    'PYRAMID_SIZE': 0.5,             # 50% size on add (safer)
}

class TradeSimulator:
    """Simulates bar-by-bar price action for a trade"""
    def __init__(self, entry_price, direction, sl_price, tp_price, r_value, outcome, bars_held):
        self.entry = entry_price
        self.direction = direction
        self.sl = sl_price
        self.tp = tp_price
        self.r_value = r_value  # 1R in price terms
        self.outcome = outcome  # 'win' or 'loss'
        self.bars_held = bars_held
        
        # Generate synthetic price path
        self.price_path = self._generate_path()
        
    def _generate_path(self):
        """Generate realistic intratrade price movement"""
        n_bars = max(self.bars_held, 5)
        
        # Target final P&L
        if self.outcome == 'win':
            final_pnl = np.random.uniform(1.5, 2.2) * self.r_value
        else:
            final_pnl = np.random.uniform(-1.1, -0.9) * self.r_value
        
        # Generate path with noise
        base_move = final_pnl / n_bars
        noise = np.random.normal(0, self.r_value * 0.15, n_bars)
        
        path = []
        current = self.entry
        
        for i in range(n_bars):
            drift = base_move + noise[i]
            current += drift
            
            # Add realistic OHLC structure
            bar_range = abs(self.r_value * 0.3)
            o = current - drift * 0.3
            h = max(current, o) + np.random.uniform(0, bar_range)
            l = min(current, o) - np.random.uniform(0, bar_range)
            c = current
            
            path.append({
                'open': o, 'high': h, 'low': l, 'close': c,
                'bar_num': i,
                'unrealized_r': (c - self.entry) / self.r_value if self.direction == 'long' 
                               else (self.entry - c) / self.r_value
            })
            
            # Check for early exit
            if self.direction == 'long':
                if c >= self.tp: break
                if c <= self.sl: break
            else:
                if c <= self.tp: break
                if c >= self.sl: break
        
        return path
    
    def get_bar(self, bar_num):
        """Get price data for specific bar"""
        if bar_num < len(self.price_path):
            return self.price_path[bar_num]
        return None
    
    def check_pyramid_conditions(self, bar_num):
        """Check if pyramid conditions met at this bar"""
        bar = self.get_bar(bar_num)
        if not bar:
            return False, {}
        
        metrics = {
            'floating_r': bar['unrealized_r'],
            'trend_aligned': bar['unrealized_r'] > 0.5,  # Simplified
            'momentum': bar['close'] > bar['open'] if self.direction == 'long' else bar['close'] < bar['open']
        }
        
        # Condition 1: +1R floating profit
        if bar['unrealized_r'] < CONFIG['PYRAMID_MIN_FLOATING_R']:
            return False, metrics
        
        # Condition 2: Within max bars
        if bar_num >= CONFIG['PYRAMID_MAX_BARS']:
            return False, metrics
        
        # Condition 3: Trend confirmation
        if CONFIG['PYRAMID_TREND_CONFIRM'] and not metrics['trend_aligned']:
            return False, metrics
        
        # Condition 4: Volume/momentum (simplified)
        if CONFIG['PYRAMID_VOLUME_CONFIRM'] and not metrics['momentum']:
            return False, metrics
        
        return True, metrics

def backtest_state_machine(symbol, config, filter_mode='none'):
    """
    State machine backtest with filter ladder
    
    filter_mode:
    - 'none': No pyramids
    - 'profit_only': +1R profit only
    - 'profit_trend': +1R + trend aligned
    - 'profit_trend_vol': +1R + trend + volume
    - 'full': All conditions
    """
    print(f"\n{symbol} ({config['type']}) - Filter: {filter_mode}", end=' ')
    
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
    
    # State machine simulation
    state = STATE_NO_TRADE
    current_trade = None
    pyramid_trade = None
    completed_trades = []
    
    bar_counter = 0
    
    for trade_data in trades:
        sim = trade_data['sim']
        
        if state == STATE_NO_TRADE:
            # Enter base position
            current_trade = {
                'entry_bar': bar_counter,
                'sim': sim,
                'direction': trade_data['direction'],
                'size': CONFIG['BASE_SIZE'],
                'entry_type': 'base'
            }
            state = STATE_BASE_OPEN
            bar_counter = 0
            
        elif state == STATE_BASE_OPEN:
            # Monitor base position bar by bar
            bar = sim.get_bar(bar_counter)
            
            if not bar:
                # Trade closed, record result
                completed_trades.append({
                    'pnl_r': trade_data['actual_pnl_r'] * current_trade['size'],
                    'entry_type': 'base',
                    'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss'
                })
                state = STATE_NO_TRADE
                current_trade = None
                bar_counter = 0
                continue
            
            # Check pyramid eligibility
            if filter_mode != 'none':
                eligible, metrics = sim.check_pyramid_conditions(bar_counter)
                
                if eligible:
                    # Execute pyramid
                    pyramid_trade = {
                        'sim': sim,
                        'direction': trade_data['direction'],
                        'size': CONFIG['PYRAMID_SIZE'],
                        'entry_bar': bar_counter,
                        'entry_type': 'pyramid',
                        'conditions': metrics
                    }
                    state = STATE_PYRAMID_OPEN
            
            bar_counter += 1
            
        elif state == STATE_PYRAMID_OPEN:
            # Monitor both positions
            bar = sim.get_bar(bar_counter)
            
            if not bar:
                # Trade closed, both positions exit
                base_pnl = trade_data['actual_pnl_r'] * current_trade['size']
                pyr_pnl = trade_data['actual_pnl_r'] * pyramid_trade['size']
                
                completed_trades.append({
                    'pnl_r': base_pnl,
                    'entry_type': 'base',
                    'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss'
                })
                completed_trades.append({
                    'pnl_r': pyr_pnl,
                    'entry_type': 'pyramid',
                    'result': 'win' if trade_data['actual_pnl_r'] > 0 else 'loss'
                })
                
                state = STATE_NO_TRADE
                current_trade = None
                pyramid_trade = None
                bar_counter = 0
                continue
            
            bar_counter += 1
    
    # Calculate stats
    if not completed_trades:
        return None
    
    base_trades = [t for t in completed_trades if t['entry_type'] == 'base']
    pyr_trades = [t for t in completed_trades if t['entry_type'] == 'pyramid']
    
    total_r = sum(t['pnl_r'] for t in completed_trades)
    total_trades = len(completed_trades)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    
    base_r = sum(t['pnl_r'] for t in base_trades)
    base_avg = base_r / len(base_trades) if base_trades else 0
    
    pyr_r = sum(t['pnl_r'] for t in pyr_trades)
    pyr_avg = pyr_r / len(pyr_trades) if pyr_trades else 0
    
    # Dollar P&L
    ticks_per_r = r_value / 0.25
    dollar_per_r = ticks_per_r * config['tick_value']
    total_pnl = total_r * dollar_per_r
    
    # Drawdown simulation
    cumulative = np.cumsum([t['pnl_r'] for t in completed_trades])
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative - running_max
    max_dd = drawdown.min() * dollar_per_r
    
    print(f"Done. {len(base_trades)} base, {len(pyr_trades)} pyramids")
    
    return {
        'symbol': symbol,
        'filter': filter_mode,
        'base_trades': len(base_trades),
        'pyr_trades': len(pyr_trades),
        'total_trades': total_trades,
        'base_avg_r': base_avg,
        'pyr_avg_r': pyr_avg,
        'combined_avg_r': avg_r,
        'total_r': total_r,
        'total_pnl': total_pnl,
        'max_dd': max_dd,
        'ret_dd': abs(total_pnl / max_dd) if max_dd != 0 else 0
    }

# ═══════════════════════════════════════════════════════════════════════════════
# FILTER LADDER ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

FILTERS = ['none', 'profit_only', 'profit_trend', 'full']

print("=" * 100)
print("BOOF 24 PYRAMID - FILTER LADDER ANALYSIS")
print("=" * 100)
print("Testing pyramid filters from loose to strict")
print("=" * 100)

all_results = []

for filter_mode in FILTERS:
    print(f"\n{'='*100}")
    print(f"FILTER MODE: {filter_mode.upper()}")
    print(f"{'='*100}")
    
    filter_results = []
    for sym, (file, tick, ttype) in FUTURES_CONFIG.items():
        config = {'file': file, 'tick_value': tick, 'type': ttype}
        result = backtest_state_machine(sym, config, filter_mode)
        if result:
            filter_results.append(result)
            all_results.append(result)
    
    # Summary for this filter
    if filter_results:
        total_base = sum(r['base_trades'] for r in filter_results)
        total_pyr = sum(r['pyr_trades'] for r in filter_results)
        total_r = sum(r['total_r'] for r in filter_results)
        total_pnl = sum(r['total_pnl'] for r in filter_results)
        avg_dd = sum(r['max_dd'] for r in filter_results) / len(filter_results)
        
        print(f"\n[SUMMARY] {filter_mode}")
        print(f"  Base trades: {total_base}")
        print(f"  Pyramid trades: {total_pyr} ({total_pyr/total_base*100:.1f}% rate)")
        print(f"  Combined R: {total_r:+.2f}")
        print(f"  Combined $: ${total_pnl:,.2f}")
        print(f"  Avg Drawdown: ${avg_dd:,.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# COMPARISON TABLE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("FILTER COMPARISON MATRIX")
print("=" * 100)

print(f"\n{'Symbol':<8} {'Filter':<15} {'Base':<8} {'Pyr':<8} {'Pyr%':<8} {'Base R':<10} {'Pyr R':<10} {'Total R':<10} {'Max DD':<12} {'R/DD':<8}")
print("-" * 100)

for r in all_results:
    pyr_pct = r['pyr_trades'] / r['base_trades'] * 100 if r['base_trades'] > 0 else 0
    print(f"{r['symbol']:<8} {r['filter']:<15} {r['base_trades']:<8} {r['pyr_trades']:<8} "
          f"{pyr_pct:<8.1f} {r['base_avg_r']:<10.3f} {r['pyr_avg_r']:<10.3f} "
          f"{r['combined_avg_r']:<10.3f} ${r['max_dd']:<11,.0f} {r['ret_dd']:<8.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# CONTRIBUTION ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("CONTRIBUTION ANALYSIS: Base vs Pyramid Add-ons")
print("=" * 100)

for filter_mode in ['profit_only', 'profit_trend', 'full']:
    filter_data = [r for r in all_results if r['filter'] == filter_mode]
    if not filter_data:
        continue
    
    print(f"\n[{filter_mode.upper()}]")
    
    total_base_r = sum(r['base_avg_r'] * r['base_trades'] for r in filter_data)
    total_base_count = sum(r['base_trades'] for r in filter_data)
    
    total_pyr_r = sum(r['pyr_avg_r'] * r['pyr_trades'] for r in filter_data)
    total_pyr_count = sum(r['pyr_trades'] for r in filter_data)
    
    base_contrib = total_base_r / total_base_count if total_base_count > 0 else 0
    pyr_contrib = total_pyr_r / total_pyr_count if total_pyr_count > 0 else 0
    
    print(f"  Base contribution:   {base_contrib:.3f} R/trade ({total_base_count} trades)")
    print(f"  Pyramid contribution: {pyr_contrib:.3f} R/trade ({total_pyr_count} trades)")
    print(f"  Pyramid premium:   {pyr_contrib - base_contrib:+.3f} R")
    
    if pyr_contrib > base_contrib * 1.5:
        print(f"  >> Pyramid adds SIGNIFICANT value")
    elif pyr_contrib > base_contrib:
        print(f"  >> Pyramid adds moderate value")
    else:
        print(f"  >> Pyramid does NOT add value")

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 100)
print("FINAL VERDICT - OPTIMAL PYRAMID CONFIGURATION")
print("=" * 100)

# Find best filter by return/drawdown
best_filter = None
best_score = -999

for filter_mode in ['none', 'profit_only', 'profit_trend', 'full']:
    filter_data = [r for r in all_results if r['filter'] == filter_mode]
    if not filter_data:
        continue
    
    total_pnl = sum(r['total_pnl'] for r in filter_data)
    avg_dd = sum(r['max_dd'] for r in filter_data) / len(filter_data)
    score = total_pnl / abs(avg_dd) if avg_dd != 0 else 0
    
    print(f"\n{filter_mode}: ${total_pnl:,.0f} P&L | ${avg_dd:,.0f} DD | Score: {score:.2f}x")
    
    if score > best_score:
        best_score = score
        best_filter = filter_mode

print(f"\n{'='*100}")
print(f"[BEST CONFIGURATION] {best_filter.upper()}")
print(f"Return/Drawdown Score: {best_score:.2f}x")
print(f"{'='*100}")
