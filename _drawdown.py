import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_boof22 import run_boof22

TRADE = 200
TP = 0.35; SL = -0.18; TM = 0.08

months21 = [('Jan 25',23),('Feb 25',20),('Mar 25',21),('Apr 25',22),
            ('May 25',21),('Jun 25',21),('Jul 25',23),('Aug 25',21),
            ('Sep 25',22),('Oct 25',23),('Nov 25',20),('Dec 25',23)]
months22 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
SYM21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
SYM22 = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

dfs21 = pickle.load(open('_boof21_cache.pkl','rb'))
dfs22 = pickle.load(open('_boof22_cache.pkl','rb'))

def analyze_dd(pnls, label):
    arr = np.array(pnls)
    n = len(arr)
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd_series = peak - cum

    max_dd = dd_series.max()
    max_dd_idx = dd_series.argmax()
    peak_idx = (cum[:max_dd_idx+1]).argmax()

    # Recovery
    recovery_idx = None
    for i in range(max_dd_idx, len(cum)):
        if cum[i] >= cum[peak_idx]:
            recovery_idx = i
            break

    # Consecutive losses
    max_consec = cur_consec = 0
    for p in arr:
        if p < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    annual_pnl = cum[-1]
    monthly_pnl = annual_pnl / 12
    wr = round(np.sum(arr > 0) / n * 100, 1)

    print(f'\n{"="*55}')
    print(label)
    print(f'{"="*55}')
    print(f'TP: +{int(TP*100)}%  SL: {int(SL*100)}%  Size: ${TRADE}/trade')
    print(f'Trades:          {n}  ({round(n/252,1)}/day)')
    print(f'Win Rate:        {wr}%')
    print(f'Annual P&L:      ${round(annual_pnl):,}')
    print(f'Monthly avg:     ${round(monthly_pnl):,}')
    print(f'Max Drawdown:    ${round(max_dd):,}  (trade #{max_dd_idx})')
    print(f'DD as % of ann:  {round(max_dd/max(annual_pnl,1)*100,1)}% of annual P&L')
    print(f'Max consec loss: {max_consec} trades in a row')
    if recovery_idx:
        print(f'Recovery after:  {recovery_idx - max_dd_idx} trades')
    else:
        print(f'Recovery:        Not recovered by year end')
    print(f'Calmar Ratio:    {round(annual_pnl/max(max_dd,1),2)}  (annual PnL / max DD)')

# Boof 21
pnls21 = []
for mo, _ in months21:
    for s in SYM21:
        df = dfs21.get((s, mo))
        if df is None: continue
        for t in bt21.backtest(df, symbol=s):
            et = t['exit_type']
            pnls21.append(TRADE*TP if et=='tp' else TRADE*SL if et=='stop' else TRADE*TM)

analyze_dd(pnls21, 'Boof 21.0 | 2025 Full Year | 11 Symbols')

# Boof 22
pnls22 = []
for mo in months22:
    for s in SYM22:
        df = dfs22.get((s, mo))
        if df is None: continue
        for t in run_boof22(df, symbol=s, tp_pct=TP, sl_pct=SL):
            et = t.get('exit_type', '')
            pnls22.append(TRADE*TP if et=='tp' else TRADE*SL if et=='sl' else TRADE*TM)

analyze_dd(pnls22, 'Boof 22.0 | 2025 Full Year | 9 Symbols')
