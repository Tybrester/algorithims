import pandas as pd
df = pd.read_csv('gap_breakout_results.csv')

SCENARIOS = [('TP1.0_SL0.5',1.0,0.5),('TP1.5_SL0.5',1.5,0.5),('TP2.0_SL1.0',2.0,1.0)]

for bucket, blabel in [('all','ALL GAP >1%'),('gap_1_2','Gap 1-2%'),('gap_2plus','Gap >2%')]:
    sub = df if bucket=='all' else df[df.gap_bucket==bucket]
    print(f'\n{"="*75}')
    print(f'{blabel} (N={len(sub)}) — sorted by EV, min 3 entries')
    print(f'{"="*75}')

    for name, tp, sl in SCENARIOS:
        rc = f'{name}_result'
        rv = f'{name}_ret'

        rows = []
        for sym, g in sub.groupby('sym'):
            if len(g) < 3:
                continue
            tp_n = (g[rc]=='TP').sum()
            sl_n = (g[rc]=='SL').sum()
            wr   = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
            ev   = g[rv].mean()
            tot  = g[rv].sum()
            rows.append((sym, len(g), tp_n, sl_n, wr, ev, tot))

        rows.sort(key=lambda x: x[5], reverse=True)
        pos = [r for r in rows if r[5] > 0]
        neg = [r for r in rows if r[5] <= 0]

        print(f'\n  TP={tp:.1f}% SL={sl:.1f}%  |  {len(pos)} profitable, {len(neg)} negative')
        print(f'  {"Sym":<7} {"N":>4}  {"TP":>4}  {"SL":>4}  {"WR":>6}  {"AvgEV":>8}  {"TotRet":>8}')
        print('  '+'-'*52)
        print('  -- BEST --')
        for sym, n, tp_n, sl_n, wr, ev, tot in rows[:15]:
            mark = ' +' if ev > 0 else '  '
            print(f'  {sym:<7} {n:>4}  {tp_n:>4}  {sl_n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {tot:>+7.2f}%{mark}')
        print('  -- WORST --')
        for sym, n, tp_n, sl_n, wr, ev, tot in rows[-15:]:
            print(f'  {sym:<7} {n:>4}  {tp_n:>4}  {sl_n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {tot:>+7.2f}%')
