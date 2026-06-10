"""
BOOF 28 - Week Test with Debug (100 stocks)
See what's passing/failing
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 100 stocks
STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","JPM","V","MA","BAC",
    "GS","WFC","UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","XOM","CVX","COP","GE","HON","UPS","BA","CAT","VZ",
    "DIS","LIN","PLD","F","GM","RIVN","DAL","UAL","COIN","GME",
    "PLTR","SOFI","RBLX","BABA","JD","SPY","QQQ","IWM","XLF","XLK",
    "XLE","XLU","XLI","ARKK","TLT","GLD","USO","SLV","BITO","MSTR"
]

# One week: Jan 13-17, 2026
start_date = datetime(2026, 1, 13, tzinfo=timezone.utc)
end_date = datetime(2026, 1, 17, tzinfo=timezone.utc)

print('='*80)
print(f'WEEK TEST: {start_date.date()} to {end_date.date()}')
print(f'100 stocks | Looser filters | Debug mode')
print('='*80)

# Looser criteria:
VOL_THRESHOLD = 2.0  # was 3.0
MOVE_THRESHOLD = 0.005  # was 0.01 (0.5% instead of 1%)

days = []
current = start_date
while current <= end_date:
    if current.weekday() < 5:
        days.append(current)
    current += timedelta(days=1)

print(f'\nScanning {len(days)} days...\n')

all_trades = []
debug_stats = {'checked': 0, 'vol_pass': 0, 'move_pass': 0, 'trades': 0}

for day in days:
    print(f'\n{day.date()}:', end=' ')
    day_trades = 0
    
    for sym in STOCKS:
        try:
            fetch_start = day - timedelta(days=25)
            fetch_end = day + timedelta(days=1)
            
            df = fetch_alpaca_bars(sym, fetch_start, fetch_end, '5Min', creds['api_key'], creds['secret_key'])
            if df is None or len(df) < 20:
                continue
            
            if 'open' not in df.columns:
                df.columns = [c.lower() for c in df.columns]
            df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
            
            today = df[df['timestamp'].dt.date == day.date()].reset_index(drop=True)
            if len(today) < 15:
                continue
            
            avg_vol = today['volume'].mean()
            
            for i in range(min(19, len(today) - 6)):
                debug_stats['checked'] += 1
                
                # Volume check
                vol_ratio = today['volume'].iloc[i] / avg_vol if avg_vol > 0 else 0
                if vol_ratio < VOL_THRESHOLD:
                    continue
                debug_stats['vol_pass'] += 1
                
                # Move check (5 bars later)
                move = (today['close'].iloc[i+5] - today['close'].iloc[i]) / today['close'].iloc[i]
                if abs(move) < MOVE_THRESHOLD:
                    continue
                debug_stats['move_pass'] += 1
                
                # Trade!
                direction = 'LONG' if move > 0 else 'SHORT'
                entry_price = today['close'].iloc[i+5]
                
                # Simulate
                pnl = None
                if direction == 'LONG':
                    for j in range(i+6, min(i+18, len(today))):
                        if today['high'].iloc[j] >= entry_price * 1.01:
                            pnl = 1.0
                            break
                        if today['low'].iloc[j] <= entry_price * 0.995:
                            pnl = -0.5
                            break
                else:
                    for j in range(i+6, min(i+18, len(today))):
                        if today['low'].iloc[j] <= entry_price * 0.99:
                            pnl = 1.0
                            break
                        if today['high'].iloc[j] >= entry_price * 1.005:
                            pnl = -0.5
                            break
                
                if pnl is None:
                    exit_price = today['close'].iloc[min(i+17, len(today)-1)]
                    if direction == 'LONG':
                        pnl = (exit_price - entry_price) / entry_price * 100
                    else:
                        pnl = (entry_price - exit_price) / entry_price * 100
                
                debug_stats['trades'] += 1
                day_trades += 1
                all_trades.append({'sym': sym, 'day': day.date(), 'dir': direction, 'pnl': pnl})
                
                # Print trade immediately
                print(f"  {sym:5s} {direction:5s} P&L: {pnl:+.2f}%")
            
            time.sleep(0.02)
        except Exception as e:
            pass
    
    print(f'{day_trades} trades')

print('\n' + '='*80)
print('DEBUG STATS:')
print(f"  Bars checked: {debug_stats['checked']}")
print(f"  Passed vol ({VOL_THRESHOLD}x): {debug_stats['vol_pass']}")
print(f"  Passed move ({MOVE_THRESHOLD*100}%): {debug_stats['move_pass']}")
print(f"  Trades: {debug_stats['trades']}")

if all_trades:
    wins = len([t for t in all_trades if t['pnl'] > 0])
    total_pnl = sum(t['pnl'] for t in all_trades)
    print(f'\nWEEK RESULTS: {len(all_trades)} trades')
    print(f'Win Rate: {wins/len(all_trades)*100:.1f}%')
    print(f'Total P&L: {total_pnl:+.2f}%')
    print(f'Avg P&L: {total_pnl/len(all_trades):.3f}%')
    
    print(f'\nLast 10 trades:')
    for t in all_trades[-10:]:
        print(f"  {t['day']} {t['sym']:5s} {t['dir']:5s} P&L: {t['pnl']:+.2f}%")
else:
    print('\nNo trades found - filters too strict or no volume spikes')

print('='*80)
