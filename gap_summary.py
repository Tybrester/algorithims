import pandas as pd
df = pd.read_csv('gap_breakout_results.csv')

print(f'Total entries: {len(df)} | Symbols: {df.sym.nunique()}')
print(f'Gap 1-2%: {len(df[df.gap_bucket=="gap_1_2"])} | Gap >2%: {len(df[df.gap_bucket=="gap_2plus"])}')

SCENARIOS = [('TP1.0_SL0.5',1.0,0.5),('TP1.5_SL0.5',1.5,0.5),('TP2.0_SL1.0',2.0,1.0)]

for bucket, blabel in [('all','ALL GAP >1%'),('gap_1_2','Gap 1-2%'),('gap_2plus','Gap >2%')]:
    sub = df if bucket=='all' else df[df.gap_bucket==bucket]
    print(f'\n== {blabel} (N={len(sub)}) ==')
    print(f'  {"Scenario":<18}  {"TP%":>6}  {"SL%":>6}  {"EOD%":>6}  {"WR":>6}  {"EV":>8}  {"PF":>6}')
    print('  '+'-'*62)
    for name, tp, sl in SCENARIOS:
        rc  = f'{name}_result'
        rv  = f'{name}_ret'
        tp_n  = (sub[rc]=='TP').sum()
        sl_n  = (sub[rc]=='SL').sum()
        eod_n = (sub[rc]=='EOD').sum()
        total = len(sub)
        wr    = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
        ev    = sub[rv].mean()
        wins  = sub[sub[rv]>0][rv].sum()
        loss  = sub[sub[rv]<0][rv].abs().sum()
        pf    = wins/loss if loss>0 else 999.0
        print(f'  TP={tp:.1f}% SL={sl:.1f}%        {tp_n/total*100:>5.1f}%  {sl_n/total*100:>5.1f}%  {eod_n/total*100:>5.1f}%  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}')
