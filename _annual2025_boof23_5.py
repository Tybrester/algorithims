import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23_5 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE        = 200
TP_PCT       =  0.40   # options TP +40%
SL_PCT       = -0.10   # options SL -10%
CHOP_TP_PCT  =  0.08   # 8% TP in chop mode
CHOP_SL_PCT  = -0.06   # 6% SL in chop mode

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
    """Calculate options P&L."""
    return tp * TRADE * TP_PCT + sl * TRADE * SL_PCT + tm * TRADE * 0.08

print('BOOF 23.5 ANNUAL BACKTEST (ZigZag + Chop Detection)')
print('Fetching ' + str(len(SYMBOLS)) + ' symbols x ' + str(len(months)) + ' months ...')
print()

results = []
sym_totals = {s: 0 for s in SYMBOLS}

for label, start, end, tdays in months:
    month_trades = 0
    month_chop = 0
    month_normal = 0
    month_pnl    = 0.0
    month_tp = month_sl = month_tm = 0
    losing_syms  = []

    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100:
            continue

        trades = bt.run_boof23_5(df, symbol=sym, tp_mult=4.0, sl_mult=2.0)

        tp_ct  = sum(1 for t in trades if t['exit_type'] == 'tp')
        sl_ct  = sum(1 for t in trades if t['exit_type'] == 'sl')
        tm_ct  = sum(1 for t in trades if t['exit_type'] == 'time')
        chop_ct = sum(1 for t in trades if t.get('mode') == 'chop')
        
        # Calculate P&L
        pnl = tp_ct * TRADE * TP_PCT + sl_ct * TRADE * SL_PCT + tm_ct * TRADE * 0.08

        month_trades += len(trades)
        month_chop += chop_ct
        month_normal += len(trades) - chop_ct
        month_tp     += tp_ct
        month_sl     += sl_ct
        month_tm     += tm_ct
        month_pnl    += pnl
        sym_totals[sym] += pnl

        if pnl < 0:
            losing_syms.append(sym)

    gross_win  = month_tp * TRADE * TP_PCT
    gross_loss = max(month_sl * TRADE * abs(SL_PCT), 1)
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 0
    losing_str = '  LOSING: ' + ', '.join(losing_syms) if losing_syms else ''
    perday = round(month_trades / tdays, 1)

    print(f"{label} done: {month_trades} trades  PF={pf}  opt=${round(month_pnl)}  chop={month_chop}/{month_normal}{losing_str}")
    results.append((label, month_trades, tdays, pf, month_pnl, losing_syms, month_chop, month_normal))

print()
print('='*75)
print('BOOF 23.5 ANNUAL SUMMARY')
print('='*75)

# Summary stats
total_trades = sum(r[1] for r in results)
total_chop = sum(r[6] for r in results)
total_normal = sum(r[7] for r in results)
total_pnl = sum(r[4] for r in results)
avg_pf = round(sum(r[3] for r in results) / len(results), 2)

print(f"Total Trades: {total_trades}")
print(f"  Chop Mode:   {total_chop} ({round(100*total_chop/total_trades,1) if total_trades > 0 else 0}%)")
print(f"  Normal Mode: {total_normal} ({round(100*total_normal/total_trades,1) if total_trades > 0 else 0}%)")
print(f"Total P&L: ${round(total_pnl):,}")
print(f"Avg PF: {avg_pf}")
print()

print('Per Symbol:')
for sym, pnl in sorted(sym_totals.items(), key=lambda x: -x[1]):
    print(f"  {sym}: ${round(pnl):,}")
