import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof21 import backtest as bt_backtest
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE        = 200
TP_PCT       =  0.40   # options TP +40%
SL_PCT       = -0.10   # options SL -10%
STOCK_TP_PCT =  0.007  # underlying move for +40% option TP
STOCK_SL_PCT = -0.002  # underlying move for -10% option SL

SYMBOLS = ["TSLA", "NVDA", "COIN", "PLTR", "AMD", "AAPL", "AMZN", "META", "GOOGL"]

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

def opt_pnl(tp, sl, tm):
    return tp*TRADE*TP_PCT + sl*TRADE*SL_PCT + tm*TRADE*0.04

print(f'Fetching {len(SYMBOLS)} symbols x {len(months)} months ...')
print()

results = []
sym_totals = {s: 0 for s in SYMBOLS}

for label, start, end, tdays in months:
    month_tp = month_sl = month_tm = month_trades = 0
    month_pnl = 0.0
    losing_syms = []

    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100:
            continue
        trades = bt_backtest(df, sym)

        tp_ct = sum(1 for t in trades if t['exit_type'] == 'tp')
        sl_ct = sum(1 for t in trades if t['exit_type'] == 'stop')
        tm_ct = sum(1 for t in trades if t['exit_type'] == 'time')
        pnl   = opt_pnl(tp_ct, sl_ct, tm_ct)

        month_trades += len(trades)
        month_tp     += tp_ct
        month_sl     += sl_ct
        month_tm     += tm_ct
        month_pnl    += pnl
        sym_totals[sym] += pnl
        if pnl < 0:
            losing_syms.append(sym)

    gross_win  = max(month_tp * TRADE * TP_PCT, 1)
    gross_loss = max(month_sl * TRADE * abs(SL_PCT), 1)
    pf = round(gross_win / gross_loss, 2)
    results.append((label, month_trades, tdays, pf, month_pnl, losing_syms))
    losing_str = '  LOSING: ' + ', '.join(losing_syms) if losing_syms else ''
    print(f'{label} done: {month_trades} trades  PF={pf}  opt=${round(month_pnl)}{losing_str}')

print()
print('='*75)
print('Boof 21.0  |  Jan-Dec 2025  |  9 Symbols  |  $200/trade  |  +40% TP / -10% SL')
print('='*75)
print('Month  Trades  /day   PF      PnL         Losing syms')
print('-'*75)
total = 0
for label, n, tdays, pf, pnl, ls in results:
    total += pnl
    perday = round(n / tdays, 1)
    ls_str = '  ' + ', '.join(ls) if ls else ''
    sign = '+' if pnl >= 0 else ''
    print(label.ljust(7) + str(n).rjust(6) + str(perday).rjust(7) + str(pf).rjust(7) + f'  {sign}{round(pnl)}'.rjust(12) + ls_str)

print('-'*75)
losing_months = sum(1 for _, _, _, _, pnl, _ in results if pnl < 0)
print(f'TOTAL{str(round(total)).rjust(47)}')
print(f'Avg/month  : +{round(total/12)}')
print(f'Avg/day    : +{round(total/252)}')
print(f'Losing months: {losing_months}/12')
print()
print('Per-symbol 2025 totals:')
print('-'*40)
for sym, pnl in sorted(sym_totals.items(), key=lambda x: -x[1]):
    sign = '+' if pnl >= 0 else ''
    print(f'  {sym.ljust(6)}  {sign}{round(pnl)}')
