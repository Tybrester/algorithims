import sys, pickle, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21

TRADE=250; TP=0.35; SL=-0.10; TM=0.08
SYMBOLS = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MONTHS = ['Jan 25','Feb 25','Mar 25','Apr 25','May 25','Jun 25',
          'Jul 25','Aug 25','Sep 25','Oct 25','Nov 25','Dec 25']
MONTH_DAYS = [23,20,21,22,21,21,23,21,22,23,20,23]

cache = pickle.load(open('_boof21_cache.pkl','rb'))

print('Boof 21 | correct: +35% TP / -10% SL / $250/trade / 11 syms')
print('='*60)
yearly_pnl=0; yearly_n=0
for mo,days in zip(MONTHS,MONTH_DAYS):
    mo_pnl=0; mo_n=0
    for sym in SYMBOLS:
        df = cache.get((sym,mo))
        if df is None or len(df)<100: continue
        trades = bt21.backtest(df, symbol=sym)
        for t in trades:
            et=t['exit_type']
            pnl = TRADE*TP if et=='tp' else TRADE*SL if et=='stop' else TRADE*TM
            mo_pnl+=pnl; mo_n+=1
    yearly_pnl+=mo_pnl; yearly_n+=mo_n
    print(f'  {mo}: {mo_n:>4} trades  {mo_n/days:>5.1f}/day  ${mo_pnl:>8,.0f}')
print('='*60)
print(f'  Annual:      ${yearly_pnl:,.0f}')
print(f'  Monthly avg: ${yearly_pnl/12:,.0f}')
print(f'  Trades/day:  {yearly_n/252:.1f}')
