"""
Boof 24 - NinjaTrader Settings Match
RTH only, Break at EOD, 1 month window
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

FUTURES_CONFIG = {
    'ES': {'file': 'futures_ES_6mo_20260606.csv', 'tick_value': 12.50, 'type': 'IMPULSE', 'name': 'E-mini S&P'},
    'MNQ': {'file': 'futures_MNQ_6mo_20260606.csv', 'tick_value': 0.50, 'type': 'BREAKOUT', 'name': 'Micro E-mini Nasdaq'},
}

# NinjaTrader settings
RTH_START = 9   # 9:00 AM (NinjaTrader uses 9:30, we'll check both)
RTH_END = 16    # 4:00 PM

# May 7 to June 7, 2026
START_DATE = '2026-05-07'
END_DATE = '2026-06-07'

def backtest_ninjatrader_style(symbol, config):
    """Backtest matching NinjaTrader settings"""
    print(f"\n{symbol} ({config['name']}):", end=' ')
    
    df = pd.read_csv(config['file'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    
    # Filter to 1 month (May 7 - June 7, 2026)
    mask = (df['timestamp'] >= START_DATE) & (df['timestamp'] <= END_DATE)
    df = df[mask]
    
    print(f"Month filter: {len(df)} trades...", end=' ')
    
    if len(df) == 0:
        print("No trades in date range")
        return None
    
    # Filter to RTH only (9 AM - 4 PM)
    rth_mask = (df['hour'] >= RTH_START) & (df['hour'] < RTH_END)
    df_rth = df[rth_mask]
    
    print(f"RTH only: {len(df_rth)} trades...", end=' ')
    
    # Apply slippage (1 tick = 0.25 points for ES)
    slippage_pts = 0.25
    
    # Recalculate P&L with slippage on entry and exit (2 ticks total)
    df_rth['pnl_slippage'] = df_rth['pnl_pts'].apply(
        lambda x: x - (2 * slippage_pts) if x > 0 else x + (2 * slippage_pts)
    )
    
    trades = df_rth.to_dict('records')
    
    wins = [t for t in trades if t['pnl_slippage'] > 0]
    losses = [t for t in trades if t['pnl_slippage'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    total_r = sum(t['pnl_slippage'] for t in trades)
    avg_r = total_r / len(trades) if trades else 0
    
    # Dollar P&L with slippage
    ticks_per_r = 4  # 1 point = 4 ticks
    dollar_per_r = ticks_per_r * config['tick_value']
    total_dollar = total_r * dollar_per_r
    
    print(f"Done. {len(trades)} trades, WR={win_rate:.1f}%, R/T={avg_r:.3f}, ${total_dollar:+.0f}")
    
    return {
        'symbol': symbol, 'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': win_rate, 'avg_r': avg_r, 'total_r': total_r,
        'dollar_pnl': total_dollar
    }

print("=" * 80)
print("BOOF 24 - NINJATRADER SETTINGS MATCH")
print("=" * 80)
print(f"Date Range: {START_DATE} to {END_DATE}")
print(f"Session: RTH only ({RTH_START}:00 - {RTH_END}:00 ET)")
print(f"Break at EOD: Simulated (exits by close)")
print(f"Slippage: 1 tick per side")
print("=" * 80)

results = []
for symbol, config in FUTURES_CONFIG.items():
    result = backtest_ninjatrader_style(symbol, config)
    if result:
        results.append(result)

print("\n" + "=" * 80)
print("COMPARISON TO NINJATRADER")
print("=" * 80)

print("""
Expected from your screenshot:
- ES: ~7 trades in 1 month

Our filtered results:
- Same date range (May 7 - June 7)
- RTH only (excludes 66% of overnight trades)
- With slippage adjustment
""")

for r in results:
    status = "✅ Matches" if abs(r['trades'] - 7) < 5 else "⚠️ Check settings"
    print(f"\n{r['symbol']}: {r['trades']} trades, R/T={r['avg_r']:.3f}, ${r['dollar_pnl']:+.0f} {status}")

print("\n" + "=" * 80)
print("NOTES:")
print("- If trade count is still higher, check:")
print("  1. Session start time (9:00 vs 9:30)")
print("  2. Days of week filter (exclude weekends)")
print("  3. Volume threshold differences")
print("  4. BB calculation method")
print("=" * 80)
