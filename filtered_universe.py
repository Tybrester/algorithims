import pandas as pd
df = pd.read_csv('gap_breakout_results.csv')

SCENARIOS = [('TP1.0_SL0.5',1.0,0.5),('TP1.5_SL0.5',1.5,0.5),('TP2.0_SL1.0',2.0,1.0)]

for bucket, blabel in [('all','ALL GAP >1%'),('gap_1_2','Gap 1-2%'),('gap_2plus','Gap >2%')]:
    sub = df if bucket=='all' else df[df.gap_bucket==bucket]

    print(f'\n{"="*70}')
    print(f'{blabel}')
    print(f'{"="*70}')

    for name, tp, sl in SCENARIOS:
        rc = f'{name}_result'
        rv = f'{name}_ret'

        # find winning symbols (positive avg EV on this scenario)
        sym_ev = sub.groupby('sym')[rv].mean()
        winners = sym_ev[sym_ev > 0].index.tolist()
        losers  = sym_ev[sym_ev <= 0].index.tolist()

        full = sub
        filt = sub[sub.sym.isin(winners)]

        def stats(s, label):
            if len(s) == 0:
                return
            tp_n  = (s[rc]=='TP').sum()
            sl_n  = (s[rc]=='SL').sum()
            eod_n = (s[rc]=='EOD').sum()
            total = len(s)
            wr    = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
            ev    = s[rv].mean()
            wins  = s[s[rv]>0][rv].sum()
            loss  = s[s[rv]<0][rv].abs().sum()
            pf    = wins/loss if loss>0 else 999.0
            tot   = s[rv].sum()
            print(f'    {label:<22} N={total:>4}  syms={s.sym.nunique():>3}  TP={tp_n/total*100:>5.1f}%  SL={sl_n/total*100:>5.1f}%  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  PF={pf:.3f}  TotRet={tot:>+7.2f}%')

        print(f'\n  TP={tp:.1f}% / SL={sl:.1f}%')
        print(f'    {"Label":<22} {"N":>5}  {"syms":>5}  {"TP%":>6}  {"SL%":>6}  {"WR":>6}  {"EV":>7}  {"PF":>6}  {"TotRet":>9}')
        print('    '+'-'*82)
        stats(full, 'Full universe')
        stats(filt, f'Winners only ({len(winners)} syms)')
        print(f'    Dropped symbols ({len(losers)}): {", ".join(sorted(losers))}')
