import pandas as pd
import numpy as np

df = pd.read_csv('walkforward_test.csv')
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('ret_2h')

print("="*65)
print("WORST TRADES (losers to understand)")
print("="*65)
worst = df.nsmallest(10, 'ret_2h')[['sym','date','gap_pct','rvol','gap_bucket','ret_2h']]
for _, r in worst.iterrows():
    print(f"  {r.sym:<6} {str(r.date.date())}  gap={r.gap_pct:>5.2f}%  rvol={r.rvol:.1f}  {r.gap_bucket:<10}  ret={r.ret_2h:>+6.3f}%")

print()
print("="*65)
print("BEST TRADES (winners)")
print("="*65)
best = df.nlargest(10, 'ret_2h')[['sym','date','gap_pct','rvol','gap_bucket','ret_2h']]
for _, r in best.iterrows():
    print(f"  {r.sym:<6} {str(r.date.date())}  gap={r.gap_pct:>5.2f}%  rvol={r.rvol:.1f}  {r.gap_bucket:<10}  ret={r.ret_2h:>+6.3f}%")

print()
print("="*65)
print("WHAT TP/SL WOULD HAVE DONE vs 2HR HOLD")
print("="*65)
# Simulate various TP/SL combinations on the 2hr return data
# Note: these are approximations since we only have the 2hr close return
# For proper TP/SL we need bar-by-bar — but ret_2h gives us the endpoint
# We can look at what % of trades hit various thresholds within 2hrs
# using the actual TP/SL columns already computed in earlier runs

# Load the ideas_backtest which has both
ideas = pd.read_csv('ideas_backtest_results.csv')
# filter to same frozen universe
frozen = df.sym.unique().tolist()
ideas_filt = ideas[ideas.sym.isin(frozen)]

print(f"\n  On frozen universe ({len(ideas_filt)} trades from ideas_backtest):")
for name, rc, rv in [('TP=1%/SL=0.5%','TP1.0_SL0.5_result','TP1.0_SL0.5_ret'),
                      ('TP=1.5%/SL=0.5%','TP1.5_SL0.5_result','TP1.5_SL0.5_ret'),
                      ('TP=2%/SL=1%','TP2.0_SL1.0_result','TP2.0_SL1.0_ret')]:
    if rc not in ideas_filt.columns: continue
    sub = ideas_filt.dropna(subset=[rv])
    tp_n = (sub[rc]=='TP').sum(); sl_n = (sub[rc]=='SL').sum(); n=len(sub)
    wr = tp_n/(tp_n+sl_n)*100 if tp_n+sl_n else 0
    ev = sub[rv].mean()
    w=sub[sub[rv]>0][rv].sum(); l=sub[sub[rv]<0][rv].abs().sum()
    pf=w/l if l else 999
    print(f"  {name:<18}  N={n:>3}  TP={tp_n/n*100:>5.1f}%  SL={sl_n/n*100:>5.1f}%  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  PF={pf:.3f}")

sub2h = ideas_filt.dropna(subset=['ret_2h'])
n=len(sub2h); wr=(sub2h.ret_2h>0).mean()*100; ev=sub2h.ret_2h.mean()
w=sub2h[sub2h.ret_2h>0].ret_2h.sum(); l=sub2h[sub2h.ret_2h<0].ret_2h.abs().sum()
pf=w/l if l else 999
print(f"  2hr fixed hold      N={n:>3}  {'':>22}  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  PF={pf:.3f}")

print()
print("="*65)
print("OPTIMAL HOLD TIME — what if you exited at different thresholds")
print("="*65)
# On the test data, look at distribution
sub = df.copy()
for thresh in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
    hit = (sub.ret_2h >= thresh).sum()
    print(f"  Reached +{thresh:.1f}%:  {hit:>3}/{len(sub)} = {hit/len(sub)*100:.1f}%  of trades")

print()
for thresh in [-0.5, -1.0, -1.5, -2.0]:
    hit = (sub.ret_2h <= thresh).sum()
    print(f"  Fell to  {thresh:.1f}%:  {hit:>3}/{len(sub)} = {hit/len(sub)*100:.1f}%  of trades")

print()
print("="*65)
print("RETURN BUCKETS — full distribution")
print("="*65)
buckets = [
    ("<-2%",   sub.ret_2h < -2),
    ("-2 to -1%", (sub.ret_2h>=-2)&(sub.ret_2h<-1)),
    ("-1 to -0.5%",(sub.ret_2h>=-1)&(sub.ret_2h<-0.5)),
    ("-0.5 to 0%", (sub.ret_2h>=-0.5)&(sub.ret_2h<0)),
    ("0 to +0.5%", (sub.ret_2h>=0)&(sub.ret_2h<0.5)),
    ("+0.5 to +1%",(sub.ret_2h>=0.5)&(sub.ret_2h<1.0)),
    ("+1 to +1.5%",(sub.ret_2h>=1.0)&(sub.ret_2h<1.5)),
    ("+1.5 to +2%",(sub.ret_2h>=1.5)&(sub.ret_2h<2.0)),
    ("+2 to +3%",  (sub.ret_2h>=2.0)&(sub.ret_2h<3.0)),
    (">+3%",       sub.ret_2h>=3.0),
]
for lbl, mask in buckets:
    cnt = mask.sum()
    bar = "#" * int(cnt/len(sub)*40)
    print(f"  {lbl:<16} {cnt:>3} ({cnt/len(sub)*100:>4.1f}%)  {bar}")
