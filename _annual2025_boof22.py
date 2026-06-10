import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof22 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE        = 200
TP_PCT       =  0.40   # options TP +40%
SL_PCT       = -0.10   # options SL -10%
STOCK_TP_PCT =  0.007  # underlying move needed for +40% option TP (~delta 0.5)
STOCK_SL_PCT = -0.002  # underlying move needed for -10% option SL

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
    return tp*TRADE*TP_PCT + sl*TRADE*SL_PCT + tm*TRADE*0.08

print('Fetching ' + str(len(SYMBOLS)) + ' symbols x ' + str(len(months)) + ' months ...')
print()

results = []
sym_totals = {s: 0 for s in SYMBOLS}

for label, start, end, tdays in months:
    month_trades = 0
    month_pnl    = 0.0
    month_tp = month_sl = month_tm = 0
    losing_syms  = []

    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100:
            continue

        trades = bt.run_boof22(df, symbol=sym, tp_pct=STOCK_TP_PCT, sl_pct=STOCK_SL_PCT)

        tp_ct  = sum(1 for t in trades if t['exit_type'] == 'tp')
        sl_ct  = sum(1 for t in trades if t['exit_type'] == 'sl')
        tm_ct  = sum(1 for t in trades if t['exit_type'] == 'time')
        # Map underlying moves to options P&L using fixed model
        pnl    = tp_ct * TRADE * TP_PCT + sl_ct * TRADE * SL_PCT + tm_ct * TRADE * 0.08

        month_trades += len(trades)
        month_tp     += tp_ct
        month_sl     += sl_ct
        month_tm     += tm_ct
        month_pnl    += pnl
        sym_totals[sym] += pnl

        if pnl < 0:
            losing_syms.append(sym)

    gross_win  = month_tp * TRADE * TP_PCT
    gross_loss = max(month_sl * TRADE * abs(SL_PCT), 1)
    pf = round(gross_win / gross_loss, 2)
    losing_str = '  LOSING: ' + ', '.join(losing_syms) if losing_syms else ''
    perday = round(month_trades / tdays, 1)

    print(label + ' done: ' + str(month_trades) + ' trades  PF=' + str(pf) + '  opt=$' + str(round(month_pnl)))
    results.append((label, month_trades, tdays, pf, month_pnl, losing_syms))

print()
print('='*75)
print('Boof 22.0  |  Jan-Dec 2025  |  11 Symbols  |  $200/trade  |  +40% TP / -10% SL')
print('='*75)
print('Month  Trades  /day   PF      PnL         Losing syms')
print('-'*75)
total = 0
for label, n, tdays, pf, pnl, ls in results:
    total += pnl
    perday = round(n / tdays, 1)
    ls_str = '  ' + ', '.join(ls) if ls else ''
    print(label.ljust(7) + str(n).rjust(6) + str(perday).rjust(7) + str(pf).rjust(7) + ('  +' + str(round(pnl))).rjust(12) + ls_str)

tdays_total = sum(d for _,_,d,_,_,_ in results)
print('-'*75)
print('TOTAL' + ' '*35 + '+' + str(round(total)))
print('Avg/month  : +' + str(round(total / len(results))))
print('Avg/day    : +' + str(round(total / tdays_total)))
losing_months = sum(1 for _,_,_,_,p,_ in results if p < 0)
print('Losing months: ' + str(losing_months) + '/' + str(len(results)))
print()
print('Per-symbol 2025 totals:')
print('-'*40)
for sym, tot in sorted(sym_totals.items(), key=lambda x: -x[1]):
    print('  ' + sym.ljust(6) + '+' + str(round(tot)))
