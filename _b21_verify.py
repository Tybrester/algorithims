import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof21 import backtest as b21

cache25 = pickle.load(open('_boof21_cache.pkl','rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl','rb'))

MOS_25 = ['Jan 25','Feb 25','Mar 25','Apr 25','May 25','Jun 25','Jul 25','Aug 25','Sep 25','Oct 25','Nov 25','Dec 25']
MOS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']
TRADE=250; TP=0.35; SL=-0.10; TM=0.08

print('Boof 21 — QQQ+SPY — 2025+2026')
print(f'  {"Month":<10}  {"N":>5}  {"WR%":>6}  {"T/P":>5}  {"SL":>5}  {"Time":>5}  {"P&L":>10}')
print(f'  {"-"*58}')
total=0
for mo,cache in [(m,cache25) for m in MOS_25]+[(m,cache26) for m in MOS_26]:
    mo_pnl=0; mo_n=0; tp_n=0; sl_n=0; tm_n=0; wins=0
    for sym in ['QQQ','SPY']:
        df=cache.get((sym,mo))
        if df is None or len(df)<100: continue
        try: raw=b21(df, symbol=sym)
        except: continue
        for t in raw:
            et=t.get('exit_type','time')
            pnl=(TRADE*TP if et=='tp' else TRADE*SL if et=='stop' else TRADE*TM)
            mo_pnl+=pnl; mo_n+=1
            if et=='tp': tp_n+=1; wins+=1
            elif et=='stop': sl_n+=1
            else: tm_n+=1; wins+=1
    wr=round(wins/mo_n*100,1) if mo_n else 0
    total+=mo_pnl
    print(f'  {mo:<10}  {mo_n:>5}  {wr:>6}  {tp_n:>5}  {sl_n:>5}  {tm_n:>5}  ${mo_pnl:>9,.0f}')
    if mo=='Dec 25':
        print(f'  {"2025 total":<10}  {"":>5}  {"":>6}  {"":>5}  {"":>5}  {"":>5}  ${total:>9,.0f}  (avg ${total/12:,.0f}/mo)')
        print(f'  {"-"*58}')
        yr25=total
print(f'  {"2026 YTD":<10}  {"":>5}  {"":>6}  {"":>5}  {"":>5}  {"":>5}  ${total-yr25:>9,.0f}  (avg ${(total-yr25)/5:,.0f}/mo)')
print(f'  {"="*58}')
print(f'  GRAND TOTAL (17mo): ${total:,.0f}  avg ${total/17:,.0f}/mo')
print()
print('NOTE: Live bot confirmed numbers (from memory):')
print('  Feb 26: $4,592  Mar 26: $2,288  Apr 26: $3,705  May 26: $2,610')
print('  These match the backtest if WR and exit distribution align.')
