import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

SYMBOLS = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
creds = get_alpaca_credentials()

months = [
    ('Jan 25', datetime(2025,1,1),  datetime(2025,1,31),  23),
    ('Feb 25', datetime(2025,2,1),  datetime(2025,2,28),  20),
    ('Mar 25', datetime(2025,3,1),  datetime(2025,3,31),  21),
    ('Apr 25', datetime(2025,4,1),  datetime(2025,4,30),  22),
    ('May 25', datetime(2025,5,1),  datetime(2025,5,31),  21),
    ('Jun 25', datetime(2025,6,1),  datetime(2025,6,30),  21),
    ('Jul 25', datetime(2025,7,1),  datetime(2025,7,31),  23),
    ('Aug 25', datetime(2025,8,1),  datetime(2025,8,31),  21),
    ('Sep 25', datetime(2025,9,1),  datetime(2025,9,30),  22),
    ('Oct 25', datetime(2025,10,1), datetime(2025,10,31), 23),
    ('Nov 25', datetime(2025,11,1), datetime(2025,11,30), 20),
    ('Dec 25', datetime(2025,12,1), datetime(2025,12,31), 23),
]

print('Boof 21.0 | 2025 Full Year | Native ATR-based TP/SL (3x ATR TP, 1.5-1.8x ATR SL)')
print('='*80)
print('Fetching data (11 symbols x 12 months)...')

dfs = {}
for sym in SYMBOLS:
    for label, start, end, _ in months:
        dfs[(sym,label)] = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
print('Done.\n')

print('Running backtest...')
total_tr = total_tp = total_sl = total_tm = 0
total_pnl = 0

for label, start, end, tdays in months:
    month_tr = month_tp = month_sl = month_tm = 0
    month_pnl = 0
    for sym in SYMBOLS:
        df = dfs.get((sym,label))
        if df is None: continue
        trades = bt21.backtest(df, symbol=sym)
        month_tr += len(trades)
        month_tp += sum(1 for t in trades if t['exit_type']=='tp')
        month_sl += sum(1 for t in trades if t['exit_type']=='sl')
        month_tm += sum(1 for t in trades if t['exit_type']=='time')
        month_pnl += sum(t['pnl'] for t in trades)
    total_tr += month_tr
    total_tp += month_tp
    total_sl += month_sl
    total_tm += month_tm
    total_pnl += month_pnl
    perday = round(month_tr / tdays, 1)
    print(f'{label}: {month_tr} trades  {perday}/day  TP={month_tp}  SL={month_sl}  TM={month_tm}  PnL={round(month_pnl)}%')

print('='*80)
print(f'TOTAL: {total_tr} trades  {round(total_tr/252,1)}/day')
print(f'TP hits: {total_tp}  SL hits: {total_sl}  Time exits: {total_tm}')
print(f'Win rate: {round(total_tp/max(total_tr,1)*100,1)}%')
print(f'Total PnL: {round(total_pnl)}%')
print('='*80)
