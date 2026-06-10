import sys, os, pickle
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

SYMBOLS = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
CACHE   = 'c:/Users/tybre/Desktop/aivibe/_boof21_cache.pkl'

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

# ── Cache data ───────────────────────────────────────────────────────
if os.path.exists(CACHE):
    print('Loading from cache...')
    with open(CACHE,'rb') as f:
        dfs = pickle.load(f)
else:
    print('Fetching data (11 symbols x 12 months)...')
    creds = get_alpaca_credentials()
    dfs = {}
    for sym in SYMBOLS:
        for label, start, end, _ in months:
            dfs[(sym,label)] = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
    with open(CACHE,'wb') as f:
        pickle.dump(dfs, f)
print('Ready.\n')

# ── Run backtest and collect trades ─────────────────────────────────
def run_year(trade_size, tp_fixed=None, sl_fixed=None, label=''):
    """
    trade_size: dollars per trade
    tp_fixed / sl_fixed: if set, use fixed options % TP/SL
                         if None, use underlying ATR-based pnl
    """
    print(f'\n{"="*70}')
    print(f'Boof 21.0 | 2025 Full Year | {label} | ${trade_size}/trade')
    print(f'{"="*70}')

    yearly_tr = yearly_tp = yearly_sl = yearly_tm = 0
    yearly_pnl = 0

    for mo_label, _, _, tdays in months:
        month_tr = month_tp = month_sl = month_tm = 0
        month_pnl = 0
        for sym in SYMBOLS:
            df = dfs.get((sym, mo_label))
            if df is None: continue
            trades = bt21.backtest(df, symbol=sym)
            for t in trades:
                month_tr += 1
                et = t['exit_type']
                if et == 'tp':
                    month_tp += 1
                    pnl = trade_size * (tp_fixed if tp_fixed else t['pnl'])
                elif et == 'stop':
                    month_sl += 1
                    pnl = trade_size * (sl_fixed if sl_fixed else t['pnl'])
                else:
                    month_tm += 1
                    pnl = trade_size * (0.08 if tp_fixed else t['pnl'])
                month_pnl += pnl

        yearly_tr  += month_tr
        yearly_tp  += month_tp
        yearly_sl  += month_sl
        yearly_tm  += month_tm
        yearly_pnl += month_pnl
        tpd = round(month_tr / tdays, 1)
        print(f'{mo_label}: {month_tr} trades  {tpd}/day  TP={month_tp}  SL={month_sl}  TM={month_tm}  ${round(month_pnl)}')

    wr  = round(yearly_tp / max(yearly_tr, 1) * 100, 1)
    tpd = round(yearly_tr / 252, 1)
    print(f'{"-"*70}')
    print(f'TOTAL: {yearly_tr} trades  {tpd}/day  Win rate: {wr}%')
    print(f'TP={yearly_tp}  SL={yearly_sl}  TM={yearly_tm}')
    print(f'Annual P&L:  ${round(yearly_pnl)}')
    print(f'Monthly avg: ${round(yearly_pnl/12)}')
    print(f'Your window (69%): ~${round(yearly_pnl*0.69)} annual / ~${round(yearly_pnl*0.69/12)}/mo')

for sl in [-0.25, -0.20, -0.15, -0.10]:
    run_year(trade_size=200, tp_fixed=0.35, sl_fixed=sl,
             label=f'+35% TP / {int(sl*100)}% SL')
