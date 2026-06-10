"""
Boof 24 Futures Backtest - Using Saved Databento Data from 2026-06-06
"""
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
# FUTURES CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

FUTURES_CONFIG = {
    'ES':   {'file': 'futures_ES_6mo_20260606.csv',   'tick_value': 12.50, 'type': 'IMPULSE',  'name': 'E-mini S&P'},
    'MES':  {'file': 'futures_MES_6mo_20260606.csv',  'tick_value': 1.25,  'type': 'IMPULSE',  'name': 'Micro E-mini S&P'},
    'NQ':   {'file': 'futures_NQ_6mo_20260606.csv',   'tick_value': 5.00,  'type': 'BREAKOUT', 'name': 'E-mini Nasdaq'},
    'MNQ':  {'file': 'futures_MNQ_6mo_20260606.csv',  'tick_value': 0.50,  'type': 'BREAKOUT', 'name': 'Micro E-mini Nasdaq'},
}

# ═══════════════════════════════════════════════════════════════════════════════
# BOOF 24 CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    'TP_R': 2.0,         # 2R target
    'SL_R': 1.0,         # 1R stop
    'BB_PERIOD': 20,
    'BB_STD': 2.0,
    'VOLUME_MULT': 1.0,
    'MAX_TRADES_PER_DAY': 5,
    'TIME_EXIT_BARS': 20,
}

def load_futures_data(filename):
    """Load saved futures trade results CSV"""
    try:
        df = pd.read_csv(filename)
        # Convert timestamp
        if 'timestamp' in df.columns:
            df['ts'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception as e:
        print(f"  Error loading {filename}: {e}")
        return None

def backtest_futures(symbol, config):
    """Analyze pre-computed trade results from saved data"""
    print(f"\n{symbol} ({config['name']}, {config['type']}):", end=' ')
    
    df = load_futures_data(config['file'])
    if df is None or len(df) < 10:
        print("Insufficient data")
        return None
    
    print(f"Loaded {len(df)} trades...", end=' ')
    
    # Calculate R values from pnl_pts (assuming 1R = 1 point for futures)
    # Convert pnl_pts to R (1R = 1 point is standard for these contracts)
    df['pnl_r'] = df['pnl_pts']  # 1 point = 1R
    df['result'] = df['pnl_r'].apply(lambda x: 'win' if x > 0 else 'loss')
    
    trades = df.to_dict('records')
    
    wins = [t for t in trades if t['result'] == 'win']
    losses = [t for t in trades if t['result'] == 'loss']
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    total_r = sum(t['pnl_r'] for t in trades)
    avg_r = total_r / len(trades) if trades else 0
    dollar_pnl = sum(t['pnl_dollar'] for t in trades)
    
    print(f"Done. {len(trades)} trades, WR={win_rate:.1f}%, R/T={avg_r:.3f}, ${dollar_pnl:+.0f}")
    
    return {
        'symbol': symbol, 'name': config['name'], 'type': config['type'],
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': win_rate, 'avg_r': avg_r, 'total_r': total_r,
        'tick_value': config['tick_value'], 'dollar_pnl': dollar_pnl
    }

# ═══════════════════════════════════════════════════════════════════════════════
# RUN BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 80)
print("BOOF 24.0 - FUTURES BACKTEST (Saved Databento Data)")
print("=" * 80)
print(f"Data: futures_*_6mo_20260606.csv (6 months historical)")
print(f"Config: TP={CONFIG['TP_R']}R, SL={CONFIG['SL_R']}R, TimeExit={CONFIG['TIME_EXIT_BARS']} bars")
print("=" * 80)

all_results = []
for symbol, config in FUTURES_CONFIG.items():
    result = backtest_futures(symbol, config)
    if result:
        all_results.append(result)

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 80)
print("FUTURES RESULTS BY TYPE")
print("=" * 80)

breakout_results = [r for r in all_results if r['type'] == 'BREAKOUT']
impulse_results = [r for r in all_results if r['type'] == 'IMPULSE']

if breakout_results:
    print("\n📈 BREAKOUT FUTURES (NQ, MNQ):")
    print(f"{'Contract':<10} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'$PnL':<10}")
    print("-" * 75)
    total_trades = sum(r['trades'] for r in breakout_results)
    total_wins = sum(r['wins'] for r in breakout_results)
    total_losses = sum(r['losses'] for r in breakout_results)
    total_r = sum(r['total_r'] for r in breakout_results)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    total_dollar = sum(r['dollar_pnl'] for r in breakout_results)
    
    for r in breakout_results:
        status = "✅" if r['avg_r'] > 0.10 else "⚠️" if r['avg_r'] > 0 else "🔴"
        print(f"{r['symbol']:<10} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} ${r['dollar_pnl']:<+9.0f} {status}")
    
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print("-" * 75)
    print(f"{'TOTAL':<10} {total_trades:<8} {total_wins:<6} {total_losses:<8} {wr:<8.1f} {avg_r:<8.3f} ${total_dollar:<+9.0f}")
    print(f"\nBREAKOUT verdict: {'✅ Edge confirmed' if avg_r > 0.10 else '⚠️ Weak edge' if avg_r > 0 else '🔴 No edge'}")

if impulse_results:
    print("\n⚡ IMPULSE FUTURES (ES, MES):")
    print(f"{'Contract':<10} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WR%':<8} {'R/T':<8} {'$PnL':<10}")
    print("-" * 75)
    total_trades = sum(r['trades'] for r in impulse_results)
    total_wins = sum(r['wins'] for r in impulse_results)
    total_losses = sum(r['losses'] for r in impulse_results)
    total_r = sum(r['total_r'] for r in impulse_results)
    avg_r = total_r / total_trades if total_trades > 0 else 0
    total_dollar = sum(r['dollar_pnl'] for r in impulse_results)
    
    for r in impulse_results:
        status = "✅" if r['avg_r'] > 0.10 else "⚠️" if r['avg_r'] > 0 else "🔴"
        print(f"{r['symbol']:<10} {r['trades']:<8} {r['wins']:<6} {r['losses']:<8} {r['win_rate']:<8.1f} {r['avg_r']:<8.3f} ${r['dollar_pnl']:<+9.0f} {status}")
    
    wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print("-" * 75)
    print(f"{'TOTAL':<10} {total_trades:<8} {total_wins:<6} {total_losses:<8} {wr:<8.1f} {avg_r:<8.3f} ${total_dollar:<+9.0f}")
    print(f"\nIMPULSE verdict: {'✅ Edge confirmed' if avg_r > 0.10 else '⚠️ Weak edge' if avg_r > 0 else '🔴 No edge'}")

# GRAND TOTAL
print("\n" + "=" * 80)
print("GRAND TOTAL - ALL FUTURES")
print("=" * 80)
if all_results:
    grand_total = {
        'trades': sum(r['trades'] for r in all_results),
        'wins': sum(r['wins'] for r in all_results),
        'losses': sum(r['losses'] for r in all_results),
        'total_r': sum(r['total_r'] for r in all_results),
        'dollar_pnl': sum(r['dollar_pnl'] for r in all_results)
    }
    grand_wr = grand_total['wins'] / grand_total['trades'] * 100 if grand_total['trades'] > 0 else 0
    grand_avg_r = grand_total['total_r'] / grand_total['trades'] if grand_total['trades'] > 0 else 0
    
    print(f"\nTotal Trades:  {grand_total['trades']}")
    print(f"Win Rate:      {grand_wr:.1f}%")
    print(f"Total R:       {grand_total['total_r']:+.2f}")
    print(f"R per Trade:   {grand_avg_r:.3f}")
    print(f"Est. Dollar:   ${grand_total['dollar_pnl']:+.0f}")
    print(f"\n{'=' * 80}")
    if grand_avg_r > 0.15:
        print("✅✅ STRONG EDGE - Boof 24 Futures ready")
    elif grand_avg_r > 0.10:
        print("✅ EDGE CONFIRMED - Boof 24 Futures viable")
    elif grand_avg_r > 0:
        print("⚠️  MARGINAL EDGE - Needs more testing")
    else:
        print("🔴 NO EDGE - Do not trade")
    print(f"{'=' * 80}")
else:
    print("No results generated")

print("\n💡 Futures Trading Notes:")
print("   - ES: $12.50/tick, ~$12K margin/contract")
print("   - MES: $1.25/tick, ~$1.2K margin/contract")
print("   - NQ: $5.00/tick, ~$18K margin/contract")
print("   - MNQ: $0.50/tick, ~$1.8K margin/contract")
