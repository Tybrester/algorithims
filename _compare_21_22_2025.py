import sys, pickle
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
import backtest_boof22 as bt22
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE = 200
TP_PCT = 0.35
SL_PCT = -0.15
STOCK_TP_PCT = 0.008
STOCK_SL_PCT = -0.004

# Boof 21 symbols (full Boofinator list)
SYMBOLS_21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
# Boof 22 symbols (no ETFs)
SYMBOLS_22 = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

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

print('='*70)
print('Boof 21.0 vs 22.0 | 2025 Full Year | +35% TP / -20% SL | $200/trade')
print('='*70)
print()

# Boof 21.0
print('Fetching Boof 21.0 data (11 symbols) x 12 months...')
dfs_21 = {}
for sym in SYMBOLS_21:
    for label, start, end, _ in months:
        dfs_21[(sym,label)] = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
print('Done.\n')

print('Fetching Boof 22.0 data (9 stocks) x 12 months...')
dfs_22 = {}
for sym in SYMBOLS_22:
    for label, start, end, _ in months:
        dfs_22[(sym,label)] = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
print('Done.\n')

print('Running Boof 21.0 backtest...')
total_tr_21 = total_tp_21 = total_sl_21 = total_tm_21 = 0
for label, start, end, tdays in months:
    month_tr = month_tp = month_sl = month_tm = 0
    for sym in SYMBOLS_21:
        df = dfs_21.get((sym,label))
        if df is None: continue
        trades = bt21.backtest(df, symbol=sym)
        month_tr += len(trades)
        month_tp += sum(1 for t in trades if t['exit_type']=='tp')
        month_sl += sum(1 for t in trades if t['exit_type']=='sl')
        month_tm += sum(1 for t in trades if t['exit_type']=='time')
    total_tr_21 += month_tr
    total_tp_21 += month_tp
    total_sl_21 += month_sl
    total_tm_21 += month_tm
    pnl = month_tp*TRADE*TP_PCT + month_sl*TRADE*SL_PCT + month_tm*TRADE*0.08
    gross_win = month_tp*TRADE*TP_PCT
    gross_loss = max(month_sl*TRADE*abs(SL_PCT), 1)
    pf = round(gross_win/gross_loss, 2)
    print(f'{label}: {month_tr} trades  PF={pf}  ${round(pnl)}')

pnl_21 = total_tp_21*TRADE*TP_PCT + total_sl_21*TRADE*SL_PCT + total_tm_21*TRADE*0.08
gross_win_21 = total_tp_21*TRADE*TP_PCT
gross_loss_21 = max(total_sl_21*TRADE*abs(SL_PCT), 1)
pf_21 = round(gross_win_21/gross_loss_21, 2)
print(f'Boof 21.0 TOTAL: {total_tr_21} trades  PF={pf_21}  ${round(pnl_21)}')
print()

# Boof 22.0
print('Running Boof 22.0 backtest (using cached data)...')
total_tr_22 = total_tp_22 = total_sl_22 = total_tm_22 = 0
for label, start, end, tdays in months:
    month_tr = month_tp = month_sl = month_tm = 0
    for sym in SYMBOLS_22:
        df = dfs_22.get((sym,label))
        if df is None: continue
        trades = bt22.run_boof22(df, symbol=sym, tp_pct=STOCK_TP_PCT, sl_pct=STOCK_SL_PCT)
        month_tr += len(trades)
        month_tp += sum(1 for t in trades if t['exit_type']=='tp')
        month_sl += sum(1 for t in trades if t['exit_type']=='sl')
        month_tm += sum(1 for t in trades if t['exit_type']=='time')
    total_tr_22 += month_tr
    total_tp_22 += month_tp
    total_sl_22 += month_sl
    total_tm_22 += month_tm
    pnl = month_tp*TRADE*TP_PCT + month_sl*TRADE*SL_PCT + month_tm*TRADE*0.08
    gross_win = month_tp*TRADE*TP_PCT
    gross_loss = max(month_sl*TRADE*abs(SL_PCT), 1)
    pf = round(gross_win/gross_loss, 2)
    print(f'{label}: {month_tr} trades  PF={pf}  ${round(pnl)}')

pnl_22 = total_tp_22*TRADE*TP_PCT + total_sl_22*TRADE*SL_PCT + total_tm_22*TRADE*0.08
gross_win_22 = total_tp_22*TRADE*TP_PCT
gross_loss_22 = max(total_sl_22*TRADE*abs(SL_PCT), 1)
pf_22 = round(gross_win_22/gross_loss_22, 2)
print(f'Boof 22.0 TOTAL: {total_tr_22} trades  PF={pf_22}  ${round(pnl_22)}')
print()

print('='*70)
print('SUMMARY | 2025 Full Year | +35% TP / -20% SL | $200/trade')
print('='*70)
print(f'Boof 21.0 (SPY+QQQ):  {total_tr_21} trades  PF={pf_21}  ${round(pnl_21)}  {round(total_tr_21/252,1)}/day')
print(f'Boof 22.0 (9 stocks): {total_tr_22} trades  PF={pf_22}  ${round(pnl_22)}  {round(total_tr_22/252,1)}/day')
print('='*70)
