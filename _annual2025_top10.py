import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE    = 200
TP_PCT   =  0.40
SL_PCT   = -0.15
TM_PCT   =  0.08

SYMBOLS = ["SPY", "QQQ", "GOOGL", "TSLA", "NVDA", "COIN", "PLTR", "AMD", "AAPL", "AMZN", "META"]

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
    ('Jan 26', datetime(2026,1,1),  datetime(2026,1,31),  21),
    ('Feb 26', datetime(2026,2,1),  datetime(2026,2,28),  20),
    ('Mar 26', datetime(2026,3,1),  datetime(2026,3,31),  21),
    ('Apr 26', datetime(2026,4,1),  datetime(2026,4,30),  21),
    ('May 26', datetime(2026,5,1),  datetime(2026,5,23),  16),
]

def opt_pnl(tp, sl, tm):
    return tp*TRADE*TP_PCT + sl*TRADE*SL_PCT + tm*TRADE*TM_PCT

print('Fetching ' + str(len(SYMBOLS)) + ' symbols x ' + str(len(months)) + ' months ...')
print()

results = []
sym_totals = {s: 0 for s in SYMBOLS}

for label, s, e, tdays in months:
    bt.START_DATE = s
    bt.END_DATE   = e
    all_trades = []
    sym_pnls = {}

    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, s, e, timeframe='1Min',
                               api_key=creds['api_key'], secret_key=creds['secret_key'])
        trades = bt.backtest(df, sym)
        tp_ct = sum(1 for t in trades if t['exit_type'] == 'tp')
        sl_ct = sum(1 for t in trades if t['exit_type'] == 'stop')
        tm_ct = sum(1 for t in trades if t['exit_type'] == 'time')
        pnl   = opt_pnl(tp_ct, sl_ct, tm_ct)
        sym_pnls[sym] = (len(trades), pnl)
        sym_totals[sym] += pnl
        all_trades.extend(trades)

    if not all_trades:
        results.append((label, 0, 0, 0, 0, tdays, sym_pnls))
        continue

    wins   = [t for t in all_trades if t['pnl'] > 0]
    losses = [t for t in all_trades if t['pnl'] <= 0]
    tp_ct  = sum(1 for t in all_trades if t['exit_type'] == 'tp')
    sl_ct  = sum(1 for t in all_trades if t['exit_type'] == 'stop')
    tm_ct  = sum(1 for t in all_trades if t['exit_type'] == 'time')
    pf     = round(sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)), 2) if losses else 999
    pnl    = opt_pnl(tp_ct, sl_ct, tm_ct)
    results.append((label, len(all_trades), pf, pnl, tdays, tdays, sym_pnls))
    print(label + ' done: ' + str(len(all_trades)) + ' trades  PF=' + str(pf) + '  opt=$' + str(round(pnl)))

print()
print('='*75)
print('Jan 2025 - May 2026  |  11 Symbols  |  $250/trade  |  +35% TP / -10% SL')
print('='*75)
print('Month  Trades  /day   PF      PnL         Losing syms')
print('-'*75)
total_pnl = 0
losing_months = 0
for label, n, pf, pnl, tdays, _, sym_pnls in results:
    tpd = round(n/tdays, 1) if tdays else 0
    total_pnl += pnl
    losers = [s for s in SYMBOLS if sym_pnls.get(s, (0,0))[1] < 0]
    sign = '+' if pnl >= 0 else ''
    if pnl < 0: losing_months += 1
    print(label + '    ' + str(n).ljust(7) + str(tpd).ljust(7) + str(pf).ljust(8) + (sign+str(round(pnl))).ljust(12) + ', '.join(losers))

print('-'*75)
print('TOTAL                              +' + str(round(total_pnl)))
n_months = len(results)
n_days   = sum(r[4] for r in results)
print('Avg/month  :  +' + str(round(total_pnl/n_months)))
print('Avg/day    :  +' + str(round(total_pnl/n_days)))
print('Losing months: ' + str(losing_months) + '/' + str(n_months))
print()
print('Per-symbol 2025 totals:')
print('-'*40)
for sym in SYMBOLS:
    sign = '+' if sym_totals[sym] >= 0 else ''
    print('  ' + sym.ljust(6) + sign + str(round(sym_totals[sym])))
