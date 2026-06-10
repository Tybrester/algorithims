import sys, calendar
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE    = 250
TP_PCT   =  0.35
SL_PCT   = -0.15
TM_PCT   =  0.08

creds = get_alpaca_credentials()

def opt_pnl(tp, sl, tm):
    return tp*TRADE*TP_PCT + sl*TRADE*SL_PCT + tm*TRADE*TM_PCT

months = [
    ('Jan', datetime(2024,1,1),  datetime(2024,1,31),  23),
    ('Feb', datetime(2024,2,1),  datetime(2024,2,29),  21),
    ('Mar', datetime(2024,3,1),  datetime(2024,3,31),  21),
    ('Apr', datetime(2024,4,1),  datetime(2024,4,30),  22),
    ('May', datetime(2024,5,1),  datetime(2024,5,31),  23),
    ('Jun', datetime(2024,6,1),  datetime(2024,6,30),  20),
    ('Jul', datetime(2024,7,1),  datetime(2024,7,31),  23),
    ('Aug', datetime(2024,8,1),  datetime(2024,8,31),  22),
    ('Sep', datetime(2024,9,1),  datetime(2024,9,30),  20),
    ('Oct', datetime(2024,10,1), datetime(2024,10,31), 23),
    ('Nov', datetime(2024,11,1), datetime(2024,11,30), 21),
    ('Dec', datetime(2024,12,1), datetime(2024,12,31), 21),
]

print('Fetching 2 symbols x 12 months ...')
print()

results = []
for label, s, e, tdays in months:
    bt.START_DATE = s
    bt.END_DATE   = e
    all_trades = []
    for sym in ['QQQ', 'SPY']:
        df = fetch_alpaca_bars(sym, s, e, timeframe='1Min',
                               api_key=creds['api_key'], secret_key=creds['secret_key'])
        all_trades.extend(bt.backtest(df, sym))

    if not all_trades:
        results.append((label, 0, 0, 0, 0, 0, 0, tdays))
        continue

    wins   = [t for t in all_trades if t['pnl'] > 0]
    losses = [t for t in all_trades if t['pnl'] <= 0]
    tp_ct  = sum(1 for t in all_trades if t['exit_type'] == 'tp')
    sl_ct  = sum(1 for t in all_trades if t['exit_type'] == 'stop')
    tm_ct  = sum(1 for t in all_trades if t['exit_type'] == 'time')
    pf     = round(sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)), 2) if losses else 999
    wr     = round(len(wins) / len(all_trades) * 100, 1)
    pnl    = opt_pnl(tp_ct, sl_ct, tm_ct)
    results.append((label, len(all_trades), wr, pf, tp_ct, sl_ct, pnl, tdays))
    print(label + ' done: ' + str(len(all_trades)) + ' trades  PF=' + str(pf) + '  opt=$' + str(round(pnl)))

print()
print('='*65)
print('2024 FULL YEAR  |  QQQ + SPY  |  $250/trade  |  +35% TP / -15% SL')
print('='*65)
print('Month  Trades  /day   WR     PF     TP   SL   PnL')
print('-'*65)
total_pnl = 0
losing = 0
for label, n, wr, pf, tp, sl, pnl, tdays in results:
    tpd = round(n/tdays, 1) if tdays else 0
    total_pnl += pnl
    if pnl < 0: losing += 1
    sign = '+' if pnl >= 0 else ''
    print(label + '    ' + str(n).ljust(6) + str(tpd).ljust(7) + str(wr).ljust(7) + str(pf).ljust(7) + str(tp).ljust(5) + str(sl).ljust(5) + sign + str(round(pnl)))

print('-'*65)
print('TOTAL                                              +' + str(round(total_pnl)))
print('Avg/month  :  +' + str(round(total_pnl/12)))
print('Avg/day    :  +' + str(round(total_pnl/252)))
print('Losing months: ' + str(losing) + '/12')
