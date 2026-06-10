"""
BOOF 28 - Detailed Trade Analysis
Shows entry, exit, max/min, and captured % of available move
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

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

start_date = datetime(2026, 1, 13, tzinfo=timezone.utc)
end_date = datetime(2026, 1, 17, tzinfo=timezone.utc)

print('='*100)
print(f'DETAILED TRADE ANALYSIS: {start_date.date()} to {end_date.date()}')
print(f'Target: 1% TP | Stop: 0.5% SL')
print('='*100)

VOL_THRESHOLD = 2.0
MOVE_THRESHOLD = 0.005

days = []
current = start_date
while current <= end_date:
    if current.weekday() < 5:
        days.append(current)
    current += timedelta(days=1)

all_trades = []

for day in days:
    print(f'\n{day.date()}:')
    
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
            
            # Filter to market hours (9:30 AM - 11:30 AM)
            today['hour'] = today['timestamp'].dt.hour
            today['minute'] = today['timestamp'].dt.minute
            today['time_val'] = today['hour'] * 100 + today['minute']
            
            # 9:30 = 930, 11:30 = 1130
            market_mask = (today['time_val'] >= 930) & (today['time_val'] <= 1130)
            today = today[market_mask].reset_index(drop=True)
            
            if len(today) < 10:
                continue
            
            avg_vol = today['volume'].mean()
            
            # Only check first 12 bars of market hours (9:30-10:30)
            for i in range(min(12, len(today) - 6)):
                vol_ratio = today['volume'].iloc[i] / avg_vol if avg_vol > 0 else 0
                if vol_ratio < VOL_THRESHOLD:
                    continue
                
                move = (today['close'].iloc[i+5] - today['close'].iloc[i]) / today['close'].iloc[i]
                if abs(move) < MOVE_THRESHOLD:
                    continue
                
                direction = 'LONG' if move > 0 else 'SHORT'
                entry_idx = i + 5
                entry_price = today['close'].iloc[entry_idx]
                
                # Convert UTC to ET (UTC-5 hours)
                entry_ts = today['timestamp'].iloc[entry_idx] - pd.Timedelta(hours=5)
                entry_time = entry_ts.strftime('%H:%M')
                
                # Simulate with tracking
                exit_price = None
                exit_time = None
                exit_type = None
                
                if direction == 'LONG':
                    tp_target = entry_price * 1.01
                    sl_target = entry_price * 0.995
                    
                    for j in range(entry_idx + 1, min(entry_idx + 18, len(today))):
                        if today['high'].iloc[j] >= tp_target:
                            exit_price = tp_target
                            exit_ts = today['timestamp'].iloc[j] - pd.Timedelta(hours=5)
                            exit_time = exit_ts.strftime('%H:%M')
                            exit_type = 'TP'
                            break
                        if today['low'].iloc[j] <= sl_target:
                            exit_price = sl_target
                            exit_ts = today['timestamp'].iloc[j] - pd.Timedelta(hours=5)
                            exit_time = exit_ts.strftime('%H:%M')
                            exit_type = 'SL'
                            break
                else:  # SHORT
                    tp_target = entry_price * 0.99
                    sl_target = entry_price * 1.005
                    
                    for j in range(entry_idx + 1, min(entry_idx + 18, len(today))):
                        if today['low'].iloc[j] <= tp_target:
                            exit_price = tp_target
                            exit_ts = today['timestamp'].iloc[j] - pd.Timedelta(hours=5)
                            exit_time = exit_ts.strftime('%H:%M')
                            exit_type = 'TP'
                            break
                        if today['high'].iloc[j] >= sl_target:
                            exit_price = sl_target
                            exit_ts = today['timestamp'].iloc[j] - pd.Timedelta(hours=5)
                            exit_time = exit_ts.strftime('%H:%M')
                            exit_type = 'SL'
                            break
                
                # Time exit if no TP/SL hit
                if exit_price is None:
                    final_idx = min(entry_idx + 17, len(today) - 1)
                    exit_price = today['close'].iloc[final_idx]
                    exit_ts = today['timestamp'].iloc[final_idx] - pd.Timedelta(hours=5)
                    exit_time = exit_ts.strftime('%H:%M')
                    exit_type = 'TIME'
                
                # Calculate P&L
                if direction == 'LONG':
                    pnl = (exit_price - entry_price) / entry_price * 100
                else:
                    pnl = (entry_price - exit_price) / entry_price * 100
                
                # Calculate max/min after entry
                post_entry = today.iloc[entry_idx+1:min(entry_idx + 18, len(today))]
                max_price = post_entry['high'].max()
                min_price = post_entry['low'].min()
                
                # Calculate captured % of available move
                if direction == 'LONG':
                    available = max_price - entry_price
                    captured = exit_price - entry_price
                else:
                    available = entry_price - min_price
                    captured = entry_price - exit_price
                
                captured_pct = (captured / available * 100) if available > 0 else 0
                
                # Print trade details
                print(f"  {sym:5s} {direction:5s} | Entry: {entry_time} ${entry_price:.2f}")
                print(f"         Exit:  {exit_time} ${exit_price:.2f} ({exit_type})")
                print(f"         Range: ${min_price:.2f} - ${max_price:.2f}")
                print(f"         P&L: {pnl:+.2f}% | Captured: {captured_pct:.1f}% of available")
                print()
                
                all_trades.append({
                    'sym': sym, 'day': day.date(), 'dir': direction,
                    'entry_time': entry_time, 'exit_time': exit_time,
                    'entry': entry_price, 'exit': exit_price,
                    'max': max_price, 'min': min_price,
                    'pnl': pnl, 'captured_pct': captured_pct,
                    'exit_type': exit_type
                })
            
            time.sleep(0.02)
        except Exception as e:
            pass

print('='*100)
if all_trades:
    wins = len([t for t in all_trades if t['pnl'] > 0])
    total_pnl = sum(t['pnl'] for t in all_trades)
    avg_captured = sum(t['captured_pct'] for t in all_trades) / len(all_trades)
    
    tp_exits = len([t for t in all_trades if t['exit_type'] == 'TP'])
    sl_exits = len([t for t in all_trades if t['exit_type'] == 'SL'])
    time_exits = len([t for t in all_trades if t['exit_type'] == 'TIME'])
    
    print(f'\nWEEK SUMMARY: {len(all_trades)} trades')
    print(f'Win Rate: {wins/len(all_trades)*100:.1f}%')
    print(f'Total P&L: {total_pnl:+.2f}%')
    print(f'Avg P&L: {total_pnl/len(all_trades):.3f}%')
    print(f'\nExit Types: TP={tp_exits} | SL={sl_exits} | TIME={time_exits}')
    print(f'Avg Captured of Available Move: {avg_captured:.1f}%')
else:
    print('No trades')
print('='*100)
