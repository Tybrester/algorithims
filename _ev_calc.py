import pickle, sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_boof22 import run_boof22

TRADE = 200
TP = 0.35; SL = -0.18; TM = 0.08

def show_ev(pnls, label):
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    wr    = len(wins) / n
    lr    = 1 - wr
    avg_w = sum(wins) / len(wins) if wins else 0
    avg_l = sum(losses) / len(losses) if losses else 0
    ev    = (wr * avg_w) - (lr * abs(avg_l))
    tpd   = round(n / 252, 1)
    print(f'\n{"="*55}')
    print(label)
    print(f'{"="*55}')
    print(f'Trades:       {n}  ({tpd}/day)')
    print(f'Win Rate:     {round(wr*100,1)}%')
    print(f'Avg Win:      ${round(avg_w, 2)}')
    print(f'Avg Loss:     ${round(avg_l, 2)}')
    print(f'EV per trade: ${round(ev, 2)}')
    print(f'EV per day:   ${round(ev * tpd, 2)}')
    print(f'EV annual:    ${round(ev * n):,}')

months21 = [('Jan 25',23),('Feb 25',20),('Mar 25',21),('Apr 25',22),
            ('May 25',21),('Jun 25',21),('Jul 25',23),('Aug 25',21),
            ('Sep 25',22),('Oct 25',23),('Nov 25',20),('Dec 25',23)]
months22 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

SYM21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
SYM22 = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

dfs21 = pickle.load(open('_boof21_cache.pkl','rb'))
dfs22 = pickle.load(open('_boof22_cache.pkl','rb'))

pnls21 = []
for mo, _ in months21:
    for s in SYM21:
        df = dfs21.get((s, mo))
        if df is None: continue
        for t in bt21.backtest(df, symbol=s):
            et = t['exit_type']
            pnls21.append(TRADE*TP if et=='tp' else TRADE*SL if et=='stop' else TRADE*TM)

pnls22 = []
for mo in months22:
    for s in SYM22:
        df = dfs22.get((s, mo))
        if df is None: continue
        for t in run_boof22(df, symbol=s, tp_pct=TP, sl_pct=SL):
            et = t.get('exit_type', '')
            pnls22.append(TRADE*TP if et=='tp' else TRADE*SL if et=='sl' else TRADE*TM)

show_ev(pnls21, 'Boof 21.0 | +40% TP / -10% SL | $200/trade')
show_ev(pnls22, 'Boof 22.0 | +40% TP / -10% SL | $200/trade')
