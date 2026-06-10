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

# ── Load or fetch ────────────────────────────────────────────────────
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

# ── Collect all trades once ──────────────────────────────────────────
print('Running backtest (one pass)...')
all_trades = []
for mo_label, _, _, _ in months:
    for sym in SYMBOLS:
        df = dfs.get((sym, mo_label))
        if df is None: continue
        trades = bt21.backtest(df, symbol=sym)
        all_trades.extend(trades)

total = len(all_trades)
tps   = sum(1 for t in all_trades if t['exit_type']=='tp')
sls   = sum(1 for t in all_trades if t['exit_type']=='stop')
tms   = sum(1 for t in all_trades if t['exit_type']=='time')
wr    = round(tps/max(total,1)*100, 1)
tpd   = round(total/252, 1)

print(f'Total trades: {total}  ({tpd}/day)  Win rate: {wr}%')
print(f'TP={tps}  SL={sls}  TM={tms}\n')

TRADE = 200
print(f'{"SL %":<8} {"Annual P&L":>12} {"Monthly":>10} {"Your window/mo":>16}')
print('-'*50)
for sl in [-0.25, -0.20, -0.15, -0.10]:
    pnl = tps*TRADE*0.40 + sls*TRADE*sl + tms*TRADE*0.08
    annual  = round(pnl)
    monthly = round(pnl/12)
    window  = round(pnl*0.69/12)
    pf = round((tps*0.40) / max(sls*abs(sl), 0.01), 2)
    print(f'{str(int(sl*100))+"%":<8} ${annual:>11,}  ${monthly:>9,}  ${window:>14,}   PF={pf}')
