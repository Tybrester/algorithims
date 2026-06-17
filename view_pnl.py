"""
View first hour data + calculate P&L with 0.5% and 1% targets
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 150 liquid stocks
STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","MRVL","SNPS","CDNS","KLAC",
    "JPM","V","MA","BAC","GS","WFC","C","AXP","BLK","SPGI",
    "UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","BMY",
    "AMGN","GILD","REGN","VRTX","ZTS","ISRG","ELV","CI","HUM","CVS",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","TGT","DG","ROST","BKNG","MAR","HLT","ABNB","DASH","UBER",
    "XOM","CVX","COP","EOG","SLB","OXY","MPC","VLO","PSX","KMI",
    "GE","HON","UPS","BA","CAT","DE","LMT","NOC","RTX","UNP",
    "VZ","CMCSA","T","TMUS","CHTR","DIS",
    "LIN","APD","SHW","FCX","NUE","DOW",
    "PLD","AMT","CCI","SPG","PSA","WPC","O",
    "F","GM","RIVN","LCID","NIO","XPEV",
    "DAL","UAL","AAL","LUV","ALK",
    "COIN","HOOD","MSTR","RIOT","MARA",
    "GME","AMC","PLTR","BB","NOK",
    "SOFI","RBLX","HOOD","APP","FIGS",
    "SPY","QQQ","IWM"
]

def simulate_targets(df, entry_idx, direction, target_pct=1.0, stop_pct=0.5):
    """Simulate trade with specified target and stop"""
    entry_price = df['close'].iloc[entry_idx]
    
    if direction == 'LONG':
        tp = entry_price * (1 + target_pct/100)
        sl = entry_price * (1 - stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + 12, len(df))):
            if df['high'].iloc[i] >= tp:
                return target_pct, 'TP'
            if df['low'].iloc[i] <= sl:
                return -stop_pct, 'SL'
    else:  # SHORT
        tp = entry_price * (1 - target_pct/100)
        sl = entry_price * (1 + stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + 12, len(df))):
            if df['low'].iloc[i] <= tp:
                return target_pct, 'TP'
            if df['high'].iloc[i] >= sl:
                return -stop_pct, 'SL'
    
    # Time exit
    exit_price = df['close'].iloc[min(entry_idx + 11, len(df) - 1)]
    if direction == 'LONG':
        return (exit_price - entry_price) / entry_price * 100, 'TIME'
    else:
        return (entry_price - exit_price) / entry_price * 100, 'TIME'

test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
fetch_start = test_date - timedelta(days=5)
fetch_end = test_date + timedelta(days=1)

print('='*100)
print('P&L VIEWER - First Hour (9:30-10:30) with 0.5% and 1% targets')
print(f'Date: {test_date.date()}')
print('='*100)
print(f'{"#":<4} {"Sym":<6} {"Entry":>8} {"0.5% Target":>12} {"1% Target":>12} {"Dir":>5} {"Result"}')
print('-'*100)

total_pnl_05 = 0
total_pnl_1 = 0
trades_count = 0

results = []

for i, sym in enumerate(STOCKS, 1):
    try:
        df = fetch_alpaca_bars(sym, fetch_start, fetch_end, '5Min', creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) == 0:
            continue
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        day_data = df[df['timestamp'].dt.date == test_date.date()].reset_index(drop=True)
        
        if len(day_data) < 3:
            continue
        
        # Entry at bar 2 (roughly 9:40)
        entry_idx = 2
        entry_price = day_data['close'].iloc[entry_idx]
        
        # Determine direction based on VWAP
        vwap = (day_data['close'] * day_data['volume']).cumsum() / day_data['volume'].cumsum()
        direction = 'LONG' if entry_price > vwap.iloc[entry_idx] else 'SHORT'
        
        # Simulate with 0.5% target
        pnl_05, exit_05 = simulate_targets(day_data, entry_idx, direction, 0.5, 0.25)
        
        # Simulate with 1% target  
        pnl_1, exit_1 = simulate_targets(day_data, entry_idx, direction, 1.0, 0.5)
        
        results.append({
            'sym': sym,
            'entry': entry_price,
            'direction': direction,
            'pnl_05': pnl_05,
            'exit_05': exit_05,
            'pnl_1': pnl_1,
            'exit_1': exit_1
        })
        
        total_pnl_05 += pnl_05
        total_pnl_1 += pnl_1
        trades_count += 1
        
        print(f"{i:<4} {sym:<6} {entry_price:>8.2f} {pnl_05:>+10.2f}% {pnl_1:>+10.2f}% {direction:>5}  {exit_05}/{exit_1}")
        
        time.sleep(0.05)
        
    except Exception as e:
        pass

print('='*100)
print(f'SUMMARY: {trades_count} trades')
print(f'0.5% Target: Total P&L = {total_pnl_05:+.2f}% | Avg = {total_pnl_05/trades_count:.3f}%' if trades_count > 0 else 'No trades')
print(f'1% Target:   Total P&L = {total_pnl_1:+.2f}% | Avg = {total_pnl_1/trades_count:.3f}%' if trades_count > 0 else 'No trades')

# Show best performers for 1% target
if results:
    print('\nTop 10 (1% target):')
    top = sorted(results, key=lambda x: x['pnl_1'], reverse=True)[:10]
    for r in top:
        print(f"  {r['sym']}: {r['pnl_1']:+.2f}% ({r['direction']})")

print('='*100)
