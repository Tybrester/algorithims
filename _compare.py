TRADE = 250
TP_PCT, SL_PCT, TM_PCT = 0.35, -0.15, 0.08

data = [
    ('February', (36,50,16), (37,45,13), 20),
    ('March',    (22,49,12), (25,48,18), 21),
    ('April',    (29,47,16), (31,42,18), 21),
    ('May 1-24', (23,48,16), (23,35,17), 21),
]

def calc(tp,sl,tm):
    return tp*TRADE*TP_PCT + sl*TRADE*SL_PCT + tm*TRADE*TM_PCT

def pf(tp,sl,tm):
    w = tp*TP_PCT + tm*TM_PCT
    l = abs(sl*SL_PCT)
    return round(w/l, 2) if l else 999

print('         |   Q Q Q                      |   S P Y')
print('Month    | Trades  WR    PF    PnL       | Trades  WR    PF    PnL')
print('-'*76)
qqq_tot = spy_tot = 0
for mo, q, s, days in data:
    qt,qs,qtm = q; st,ss,stm = s
    qn = calc(*q); sn = calc(*s)
    qqq_tot += qn; spy_tot += sn
    qtr = qt+qs+qtm; str_ = st+ss+stm
    qwr = round(qt/qtr*100); swr = round(st/str_*100)
    qpf = pf(*q); spf = pf(*s)
    print(mo.ljust(9)+'| '+str(qtr).ljust(6)+str(qwr)+'%   '+str(qpf)+'   +'+str(round(qn)).ljust(8)+'| '+str(str_).ljust(6)+str(swr)+'%   '+str(spf)+'   +'+str(round(sn)))

print('-'*76)
print('4mo total|                     +'+str(round(qqq_tot)).ljust(9)+'|                     +'+str(round(spy_tot)))
print('Avg/mo   |                     +'+str(round(qqq_tot/4)).ljust(9)+'|                     +'+str(round(spy_tot/4)))
print()
print('SPY earns '+str(round(spy_tot/qqq_tot,1))+'x more than QQQ over 4 months')
