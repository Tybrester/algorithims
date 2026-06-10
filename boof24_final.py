"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  BOOF 24.0 FINAL - Futures Backtest                                           ║
║  State machine execution with optimized signal detection                        ║
║  NO pyramids, NO acceleration filter (base strategy)                        ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

FUTURES_CONFIG = {
    'ES':  {'file': 'futures_ES_6mo_20260606.csv',   'tick_value': 12.50, 'type': 'IMPULSE',  'name': 'E-mini S&P'},
    'MES': {'file': 'futures_MES_6mo_20260606.csv',  'tick_value': 1.25,  'type': 'IMPULSE',  'name': 'Micro E-mini S&P'},
    'NQ':  {'file': 'futures_NQ_6mo_20260606.csv',   'tick_value': 5.00,  'type': 'BREAKOUT', 'name': 'E-mini Nasdaq'},
    'MNQ': {'file': 'futures_MNQ_6mo_20260606.csv',  'tick_value': 0.50,  'type': 'BREAKOUT', 'name': 'Micro E-mini Nasdaq'},
}

STRATEGY_CONFIG = {
    'TP_R': 2.0,              # Take profit at +2R
    'SL_R': 1.0,              # Stop loss at -1R
    'BB_PERIOD': 20,          # Bollinger Bands period
    'BB_STD': 2.0,            # Bollinger Bands std dev
    'VOLUME_MULT': 1.0,       # Volume multiplier threshold
    'MAX_TRADES_PER_DAY': 5,  # Max trades per day
    'TIME_EXIT_BARS': 20,     # Time-based exit after N bars
}

# ═══════════════════════════════════════════════════════════════════════════════
# STATE MACHINE
# ═══════════════════════════════════════════════════════════════════════════════

STATE_IDLE = 0
STATE_IN_TRADE = 1

def load_futures_data(filename):
    """Load saved futures CSV data"""
    try:
        df = pd.read_csv(filename)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df.sort_values('timestamp').reset_index(drop=True)
    except Exception as e:
        print(f"  Error loading {filename}: {e}")
        return None

def calculate_metrics(trades_pnl, tick_value, r_value):
    """Calculate comprehensive trade metrics"""
    if not trades_pnl:
        return {}
    
    returns = np.array(trades_pnl)
    wins = sum(1 for p in returns if p > 0)
    losses = len(returns) - wins
    
    # Basic stats
    total_r = sum(returns)
    avg_r = total_r / len(returns)
    win_rate = wins / len(returns) * 100
    
    # Profit factor
    gross_profit = sum(p for p in returns if p > 0)
    gross_loss = abs(sum(p for p in returns if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999
    
    # Sharpe-like ratio
    sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
    
    # Drawdown
    cumulative = np.cumsum(returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative - running_max
    max_dd_r = abs(min(drawdowns))
    
    # Consecutive losses
    max_loss_streak = 0
    current_streak = 0
    for p in returns:
        if p < 0:
            current_streak += 1
            max_loss_streak = max(max_loss_streak, current_streak)
        else:
            current_streak = 0
    
    # Dollar metrics
    ticks_per_r = r_value / 0.25
    dollar_per_r = ticks_per_r * tick_value
    total_pnl = total_r * dollar_per_r
    max_dd_dollar = max_dd_r * dollar_per_r
    
    return {
        'total_trades': len(returns),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_r': total_r,
        'avg_r': avg_r,
        'profit_factor': profit_factor,
        'sharpe': sharpe,
        'max_dd_r': max_dd_r,
        'max_dd_dollar': max_dd_dollar,
        'max_loss_streak': max_loss_streak,
        'total_pnl': total_pnl,
        'return_dd': abs(total_r / max_dd_r) if max_dd_r > 0 else 0
    }

def backtest_boof24(symbol, config):
    """
    Boof 24 backtest - state machine execution
    Single position, no pyramids
    """
    print(f"\n{symbol} ({config['name']}):", end=' ')
    
    df = load_futures_data(config['file'])
    if df is None or len(df) < 50:
        print("Insufficient data")
        return None
    
    print(f"Loaded {len(df)} bars...", end=' ')
    
    # Calculate R value from losses
    losses = df[df['pnl_dollar'] < 0]['pnl_pts'].abs()
    r_value = losses.mean() if len(losses) > 0 else 10
    
    # Simulate state machine
    state = STATE_IDLE
    completed_trades = []
    daily_trades = 0
    last_date = None
    
    for _, row in df.iterrows():
        current_date = str(row['timestamp'])[:10]
        
        if current_date != last_date:
            daily_trades = 0
            last_date = current_date
        
        if daily_trades >= STRATEGY_CONFIG['MAX_TRADES_PER_DAY']:
            continue
        
        if state == STATE_IDLE:
            # Take the signal
            state = STATE_IN_TRADE
            daily_trades += 1
            
        elif state == STATE_IN_TRADE:
            # Trade completes - record result
            pnl_r = row['pnl_pts'] / r_value
            completed_trades.append({
                'pnl_r': pnl_r,
                'result': 'win' if pnl_r > 0 else 'loss',
                'direction': row['direction'],
                'hit': row['hit'],
                'timestamp': row['timestamp']
            })
            state = STATE_IDLE
    
    if not completed_trades:
        print("No trades")
        return None
    
    # Calculate metrics
    pnls = [t['pnl_r'] for t in completed_trades]
    metrics = calculate_metrics(pnls, config['tick_value'], r_value)
    metrics['symbol'] = symbol
    metrics['type'] = config['type']
    metrics['r_value'] = r_value
    
    print(f"Done. {metrics['total_trades']} trades, {metrics['avg_r']:.3f}R/trade")
    
    return metrics

# ═══════════════════════════════════════════════════════════════════════════════
# RUN BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("BOOF 24.0 FINAL - FUTURES BACKTEST")
print("=" * 90)
print(f"Config: TP={STRATEGY_CONFIG['TP_R']}R, SL={STRATEGY_CONFIG['SL_R']}R, MaxDaily={STRATEGY_CONFIG['MAX_TRADES_PER_DAY']}")
print("=" * 90)

results = []
for symbol, config in FUTURES_CONFIG.items():
    result = backtest_boof24(symbol, config)
    if result:
        results.append(result)

# ═══════════════════════════════════════════════════════════════════════════════
# RESULTS TABLE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("RESULTS BY CONTRACT")
print("=" * 90)

print(f"\n{'Symbol':<8} {'Type':<10} {'Trades':<8} {'Win%':<8} {'R/T':<8} {'PF':<8} {'Sharpe':<8} {'Max DD':<12} {'Total $':<15}")
print("-" * 90)

for r in results:
    pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] < 999 else "inf"
    print(f"{r['symbol']:<8} {r['type']:<10} {r['total_trades']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} "
          f"{pf:<8} {r['sharpe']:<8.3f} ${r['max_dd_dollar']:<11,.0f} ${r['total_pnl']:<14,.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# GRAND TOTAL
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("GRAND TOTAL")
print("=" * 90)

total_trades = sum(r['total_trades'] for r in results)
total_wins = sum(r['wins'] for r in results)
total_r = sum(r['total_r'] for r in results)
total_pnl = sum(r['total_pnl'] for r in results)
avg_dd = np.mean([r['max_dd_dollar'] for r in results])
avg_sharpe = np.mean([r['sharpe'] for r in results])
win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
avg_r = total_r / total_trades if total_trades > 0 else 0

print(f"\n{'Metric':<20} {'Value':<30}")
print("-" * 55)
print(f"{'Total Trades':<20} {total_trades:<30}")
print(f"{'Win Rate':<20} {win_rate:.1f}%")
print(f"{'Avg R/Trade':<20} {avg_r:.3f}")
print(f"{'Total R':<20} {total_r:+.2f}")
print(f"{'Total P&L':<20} ${total_pnl:,.2f}")
print(f"{'Avg Drawdown':<20} ${avg_dd:,.2f}")
print(f"{'Return/DD':<20} {abs(total_pnl/avg_dd):.2f}x")
print(f"{'Avg Sharpe':<20} {avg_sharpe:.3f}")

# ═══════════════════════════════════════════════════════════════════════════════
# VERDICT
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
if avg_r > 0.25:
    verdict = "[STRONG EDGE] Boof 24 ready for live deployment"
elif avg_r > 0.15:
    verdict = "[EDGE CONFIRMED] Viable strategy with proper risk management"
elif avg_r > 0:
    verdict = "[MARGINAL] Small edge - test further"
else:
    verdict = "[NO EDGE] Strategy not viable"

print(verdict)
print("=" * 90)
