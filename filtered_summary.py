import pandas as pd
df = pd.read_csv('filtered_backtest_results.csv')
SCENARIOS = [('TP1.0_SL0.5',1.0,0.5),('TP1.5_SL0.5',1.5,0.5),('TP2.0_SL1.0',2.0,1.0)]

g1 = df[df.gap_bucket == 'gap_1_2']
g2 = df[df.gap_bucket == 'gap_2plus']
print(f'Universe: {df.sym.nunique()} symbols | Total entries: {len(df)}')
print(f'Gap 1-2%: {len(g1)} | Gap >2%: {len(g2)}')

for sub, label in [(df,'ALL GAP >1%'),(g1,'Gap 1-2%'),(g2,'Gap >2%')]:
    print(f'\n== {label} (N={len(sub)}) ==')
    print(f'  Scenario          TP%    SL%   EOD%    WR      EV       PF      TotRet')
    print('  '+'-'*66)
    for name, tp, sl in SCENARIOS:
        rc  = name + '_result'
        rv  = name + '_ret'
        tp_n  = (sub[rc]=='TP').sum()
        sl_n  = (sub[rc]=='SL').sum()
        eod_n = (sub[rc]=='EOD').sum()
        n     = len(sub)
        wr    = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
        ev    = sub[rv].mean()
        wins  = sub[sub[rv]>0][rv].sum()
        loss  = sub[sub[rv]<0][rv].abs().sum()
        pf    = wins/loss if loss>0 else 999.0
        tot   = sub[rv].sum()
        print(f'  TP={tp:.1%} SL={sl:.1%}     {tp_n/n*100:>5.1f}%  {sl_n/n*100:>5.1f}%  {eod_n/n*100:>4.1f}%  {wr:>5.1f}%  {ev:>+6.3f}%  {pf:>6.3f}  {tot:>+8.2f}%')
