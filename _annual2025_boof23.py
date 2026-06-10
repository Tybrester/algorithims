import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE        = 200
TP_PCT       =  0.40   # options TP +40%
SL_PCT       = -0.10   # options SL -10%
STOCK_TP_PCT =  0.007  # underlying move needed for +40% option TP
STOCK_SL_PCT = -0.002  # underlying move needed for -10% option SL

SYMBOLS = ['TSLA', 'NVDA', 'COIN', 'PLTR', 'AMD', 'AAPL', 'AMZN', 'META', 'GOOGL']

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

print(f'Fetching {len(SYMBOLS)} symbols x {len(months)} months ...')
print()

results = []
sym_totals = {s: 0 for s in SYMBOLS}

for label, start, end, days in months:
    month_trades = []
    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        if df is None or len(df) < 100:
            continue
        trades = bt.run_boof23(df, symbol=sym)
        for t in trades:
            t['month'] = label
            t['dollar_pnl'] = opt_pnl(
                1 if t['pnl_pct'] >= STOCK_TP_PCT else 0,
                1 if t['pnl_pct'] <= STOCK_SL_PCT else 0,
                1 if abs(t['pnl_pct']) < STOCK_TP_PCT and abs(t['pnl_pct']) < abs(STOCK_SL_PCT) else 0
            )
            month_trades.append(t)

    if not month_trades:
        print(f'{label}: No trades')
        continue

    total = sum(t['dollar_pnl'] for t in month_trades)
    wins  = sum(1 for t in month_trades if t['exit_type'] == 'tp')
    losses= sum(1 for t in month_trades if t['exit_type'] == 'sl')
    times = sum(1 for t in month_trades if t['exit_type'] == 'time')
    wr    = wins / len(month_trades) * 100 if month_trades else 0
    per_day = total / days if days else 0

    for t in month_trades:
        sym_totals[t['symbol']] = sym_totals.get(t['symbol'], 0) + t['dollar_pnl']

    results.append({'month': label, 'pnl': total, 'trades': len(month_trades), 'wr': wr, 'per_day': per_day})
    print(f'{label}: ${total:>8.0f}  |  {len(month_trades):>4} trades  |  WR {wr:.0f}%  |  TP {wins} SL {losses} TM {times}  |  ${per_day:.0f}/day')

print()
annual = sum(r['pnl'] for r in results)
total_trades = sum(r['trades'] for r in results)
avg_wr = sum(r['wr'] for r in results) / len(results) if results else 0
print(f'ANNUAL TOTAL: ${annual:,.0f}  |  {total_trades} trades  |  avg WR {avg_wr:.0f}%  |  ${annual/252:.0f}/day avg')
print()
print('Per-symbol totals:')
for sym, pnl in sorted(sym_totals.items(), key=lambda x: -x[1]):
    print(f'  {sym}: ${pnl:,.0f}')
