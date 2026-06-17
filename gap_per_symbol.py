import pandas as pd
df = pd.read_csv('gap_breakout_results.csv')

SCENARIOS = [('TP1.0_SL0.5',1.0,0.5),('TP1.5_SL0.5',1.5,0.5),('TP2.0_SL1.0',2.0,1.0)]

for bucket, blabel in [('all','ALL GAP >1%'),('gap_1_2','Gap 1-2%'),('gap_2plus','Gap >2%')]:
    sub = df if bucket=='all' else df[df.gap_bucket==bucket]
    print(f'\n{"="*90}')
    print(f'PER SYMBOL — {blabel} (N={len(sub)})')
    print(f'{"="*90}')

    for name, tp, sl in SCENARIOS:
        rc = f'{name}_result'
        rv = f'{name}_ret'

        print(f'\n  TP={tp:.1f}% / SL={sl:.1f}%')
        print(f'  {"Sym":<7} {"N":>4}  {"TP":>4}  {"SL":>4}  {"EOD":>4}  {"WR":>6}  {"EV":>8}  {"PF":>6}  {"TotRet":>8}')
        print('  '+'-'*65)

        rows = []
        for sym, g in sub.groupby('sym'):
            if len(g) < 3:
                continue
            tp_n  = (g[rc]=='TP').sum()
            sl_n  = (g[rc]=='SL').sum()
            eod_n = (g[rc]=='EOD').sum()
            wr    = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
            ev    = g[rv].mean()
            tot   = g[rv].sum()
            wins  = g[g[rv]>0][rv].sum()
            loss  = g[g[rv]<0][rv].abs().sum()
            pf    = wins/loss if loss>0 else 999.0
            rows.append((sym, len(g), tp_n, sl_n, eod_n, wr, ev, pf, tot))

        rows.sort(key=lambda x: x[6], reverse=True)
        for sym, n, tp_n, sl_n, eod_n, wr, ev, pf, tot in rows:
            flag = ' +' if ev > 0 else '  '
            print(f'  {sym:<7} {n:>4}  {tp_n:>4}  {sl_n:>4}  {eod_n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}  {tot:>+7.2f}%{flag}')
