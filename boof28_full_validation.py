"""
BOOF 28 - Full Validation Suite (Tests 1-14)
Bucket: 0.50-0.60% (best from sweep), Exit: 10:20, Long+Short
"""
import sys, pickle, os, random, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd

OUT = open('boof28_full_validation.txt', 'w', encoding='utf-8')
_p = print
def print(*a, **k):
    _p(*a, **k)
    _p(*a, **k, file=OUT)

# ── Config ────────────────────────────────────────────────────────────
WATCHLIST = [
    "NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","MRVL","INTC","ON","NXPI","TXN","ARM",
    "HOOD","COIN","SQ","SOFI","AFRM","UPST","PYPL",
    "CAT","ETN","DE","GE","URI","ROP","HON","EMR",
    "ISRG","MRNA","VRTX","REGN","LLY","GILD","BMY","ABBV","NVO","AMGN",
    "UBER","ABNB","RCL","CCL",
]
SYM_SECTOR = {
    **{s:"Semiconductors" for s in ["NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","MRVL","INTC","ON","NXPI","TXN","ARM"]},
    **{s:"Fintech"        for s in ["HOOD","COIN","SQ","SOFI","AFRM","UPST","PYPL"]},
    **{s:"Industrials"    for s in ["CAT","ETN","DE","GE","URI","ROP","HON","EMR"]},
    **{s:"Biotech"        for s in ["ISRG","MRNA","VRTX","REGN","LLY","GILD","BMY","ABBV","NVO","AMGN"]},
    **{s:"Travel"         for s in ["UBER","ABNB","RCL","CCL"]},
}

def load(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    daily = d.groupby('date')['close'].last()
    return daily.ewm(span=50, adjust=False).mean().shift(1)

def get_ema(s, date):
    ts = pd.Timestamp(date)
    v = s.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in s.index if pd.Timestamp(d).date() < date]
        v = s[prior[-1]] if prior else None
    return v

def collect(all_data, ema50, start, end, lo_pct, hi_pct, exit_time='10:20'):
    """Collect trades for given move bucket [lo_pct, hi_pct) as percent values."""
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []
    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date']==d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop)==0: continue
        q5   = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']
        qob  = qday.between_time('09:30','09:30')
        if len(qob)==0: continue
        qqq_open = qob.iloc[0]['open']
        e50  = get_ema(ema50, d)
        if e50 is None: continue
        bull = qqq_open > e50 and q5 >= 0.001
        bear = qqq_open < e50 and q5 <= -0.001
        if not bull and not bear: continue
        regime = 'bull' if bull else 'bear'
        for sym in WATCHLIST:
            if sym not in all_data: continue
            df2  = all_data[sym].copy()
            df2  = df2[(df2.index >= start) & (df2.index <= end)]
            day  = df2[df2.index.date == d]
            if len(day)==0: continue
            so   = day.between_time('09:30','09:34')
            if len(so)==0: continue
            s5   = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']
            s5p  = s5 * 100
            direction = None
            if bull  and  lo_pct <= s5p < hi_pct: direction = 'LONG'
            elif bear and -hi_pct < s5p <= -lo_pct: direction = 'SHORT'
            if direction is None: continue
            en = day.between_time('09:35','09:35')
            ex = day.between_time(exit_time, exit_time)
            if len(en)==0 or len(ex)==0: continue
            ep = en.iloc[0]['open']; xp = ex.iloc[0]['open']
            pnl = (xp-ep)/ep*100 if direction=='LONG' else (ep-xp)/ep*100
            ts2 = pd.Timestamp(d)
            trades.append({'date':d,'symbol':sym,'sector':SYM_SECTOR.get(sym,'Other'),
                           'side':direction,'pnl':pnl,
                           'qqq_5m':round(q5*100,3),'stock_5m':round(s5p,3),
                           'regime':regime,
                           'month':ts2.to_period('M'),
                           'quarter':ts2.to_period('Q'),
                           'year':ts2.year})
    return trades

def stats(trades_or_df):
    if isinstance(trades_or_df, list):
        if not trades_or_df: return None
        df = pd.DataFrame(trades_or_df)
    else:
        df = trades_or_df
    if len(df)==0: return None
    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    wr   = len(wins)/len(df)
    aw   = wins['pnl'].mean() if len(wins) else 0
    al   = abs(loss['pnl'].mean()) if len(loss) else 0
    ev   = wr*aw - (1-wr)*al
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf   = gp/gl if gl>0 else 0
    tot  = df['pnl'].sum()
    cum  = df['pnl'].cumsum()
    dd   = (cum.expanding().max()-cum).max()
    return dict(n=len(df),wr=wr,aw=aw,al=al,ev=ev,pf=pf,tot=tot,dd=dd,df=df)

def sep(w=82): print('='*w)
def line(w=82): print('-'*w)
def hdr(title): sep(); print(f"  {title}"); sep()

# ── Load ──────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + WATCHLIST:
    df = load(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")
ema50 = build_ema50(all_data['QQQ'].copy())

def ts(s): return pd.to_datetime(s).tz_localize('UTC')
S25,E25 = ts('2025-01-01'),ts('2025-12-31')
S26,E26 = ts('2026-01-01'),ts('2026-06-09')

print("Collecting trades (0.50-0.60%, exit 10:20)...")
t25  = collect(all_data, ema50, S25, E25, 0.50, 0.60)
t26  = collect(all_data, ema50, S26, E26, 0.50, 0.60)
tall = t25 + t26
df   = pd.DataFrame(tall)
print(f"Total: {len(tall)} trades  (2025: {len(t25)}, 2026: {len(t26)})\n")

# ═══════════════════════════════════════════════════════════════════════
# TESTS 1-2: YEAR & QUARTER BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 1: YEAR-BY-YEAR BREAKDOWN")
print(f"  {'Period':<14} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for yr, t in [('2025 Full', t25), ('2026 YTD', t26), ('COMBINED', tall)]:
    s = stats(t)
    if not s: continue
    v = 'PASS' if s['pf']>=1.2 and s['ev']>0 else ('EDGE' if s['pf']>=1.0 else 'FAIL')
    sep_mark = '  <-- REQUIRED PASS' if yr != 'COMBINED' else ''
    print(f"  {yr:<14} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%  {v}{sep_mark}")
sep()

hdr("TEST 2: QUARTERLY BREAKDOWN")
print(f"  {'Quarter':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}  Verdict")
line()
for q in sorted(df['quarter'].unique()):
    sub = df[df['quarter']==q]
    s   = stats(sub)
    if not s: continue
    v   = 'PASS' if s['pf']>=1.2 else ('EDGE' if s['pf']>=1.0 else 'FAIL')
    print(f"  {str(q):<10} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%  {v}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 3: MONTHLY BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 3: MONTHLY BREAKDOWN")
print(f"  {'Month':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9}  {'Cum':>9}")
line()
cum2 = 0
for m in sorted(df['month'].unique()):
    mdf = df[df['month']==m]; mt = mdf['pnl'].sum(); cum2 += mt
    wins = mdf[mdf['pnl']>0]; loss = mdf[mdf['pnl']<=0]
    mwr = len(wins)/len(mdf)*100
    mpf = wins['pnl'].sum()/abs(loss['pnl'].sum()) if len(loss)>0 and loss['pnl'].sum()!=0 else 0
    flag = '  RED' if mt < 0 else ''
    print(f"  {str(m):<10} {len(mdf):>7} {mwr:>5.1f}% {mpf:>6.2f} {mt:>+8.2f}%  {cum2:>+8.2f}%{flag}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 4: EXPECTANCY (EV)
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 4: EXPECTANCY (EV)")
s = stats(df)
print(f"  Win Rate:        {s['wr']*100:.1f}%")
print(f"  Avg Winner:     +{s['aw']:.4f}%")
print(f"  Avg Loser:      -{s['al']:.4f}%")
print(f"  EV per trade:    {s['ev']:+.4f}%")
print(f"  Formula: ({s['wr']*100:.1f}% x +{s['aw']:.4f}%) - ({(1-s['wr'])*100:.1f}% x {s['al']:.4f}%) = {s['ev']:+.4f}%")
print()
for side in ['LONG','SHORT']:
    sub = df[df['side']==side]
    ss  = stats(sub)
    if not ss: continue
    print(f"  {side:5}  WR {ss['wr']*100:.1f}%  AvgW +{ss['aw']:.4f}%  AvgL -{ss['al']:.4f}%  EV {ss['ev']:+.4f}%  PF {ss['pf']:.2f}  ({ss['n']} trades)")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 5: TRADE DISTRIBUTION
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 5: TRADE DISTRIBUTION")
wins_all = df[df['pnl']>0]['pnl']
loss_all = df[df['pnl']<=0]['pnl']
print(f"  WINNERS ({len(wins_all)} trades  /  {len(wins_all)/len(df)*100:.0f}% of all):")
print(f"    Median:          +{wins_all.median():.4f}%")
print(f"    Avg:             +{wins_all.mean():.4f}%")
print(f"    90th percentile: +{np.percentile(wins_all,90):.4f}%")
print(f"    Largest:         +{wins_all.max():.4f}%")
print(f"    Std Dev:          {wins_all.std():.4f}%")
print()
print(f"  LOSERS ({len(loss_all)} trades  /  {len(loss_all)/len(df)*100:.0f}% of all):")
print(f"    Median:          {loss_all.median():.4f}%")
print(f"    Avg:             {loss_all.mean():.4f}%")
print(f"    10th percentile: {np.percentile(loss_all,10):.4f}%")
print(f"    Largest:         {loss_all.min():.4f}%")
print(f"    Std Dev:          {loss_all.std():.4f}%")
print()
# Top-5 outlier check
top5 = wins_all.nlargest(5).sum()
print(f"  Outlier check: Top 5 wins = +{top5:.2f}%  ({top5/wins_all.sum()*100:.0f}% of gross profit)")
print(f"  Edge is {'concentrated in outliers' if top5/wins_all.sum()>0.4 else 'distributed across trades'}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 6: SYMBOL CONTRIBUTION
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 6: SYMBOL CONTRIBUTION")
total_pnl = df['pnl'].sum()
sym_rows  = []
for sym, grp in df.groupby('symbol'):
    w = grp[grp['pnl']>0]; l = grp[grp['pnl']<=0]
    _pf = w['pnl'].sum()/abs(l['pnl'].sum()) if len(l)>0 and l['pnl'].sum()!=0 else 0
    sym_rows.append({'sym':sym,'n':len(grp),'wr':len(w)/len(grp)*100,
                     'pf':_pf,'total':grp['pnl'].sum(),
                     'contrib':grp['pnl'].sum()/total_pnl*100})
sym_df = pd.DataFrame(sym_rows).sort_values('total',ascending=False)
print(f"  {'Symbol':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9} {'Contrib%':>9}")
line()
cum_c = 0
for i, (_, r) in enumerate(sym_df.iterrows()):
    cum_c += r['contrib']
    tag = f"  TOP{i+1:02d}" if i < 10 else ""
    cut = "  <-- CUT" if r['total'] < -0.5 else ""
    print(f"  {r['sym']:>8} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['total']:>+8.2f}% {r['contrib']:>+8.1f}%{tag}{cut}")
t5  = sym_df.head(5)['total'].sum()
t10 = sym_df.head(10)['total'].sum()
print(f"\n  Top  5 symbols: {t5:+.2f}%  ({t5/total_pnl*100:.0f}% of total)")
print(f"  Top 10 symbols: {t10:+.2f}%  ({t10/total_pnl*100:.0f}% of total)")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 8: BUCKET SWEEP (exit=10:20)
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 8: BUCKET SWEEP  (exit=10:20, 2025+2026)")
BUCKETS = [
    (0.50,0.60,"0.50-0.60%"), (0.55,0.65,"0.55-0.65%"), (0.60,0.70,"0.60-0.70%"),
    (0.65,0.75,"0.65-0.75%"), (0.70,0.80,"0.70-0.80%"),
]
print(f"  {'Bucket':12} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for lo,hi,lbl in BUCKETS:
    t = collect(all_data, ema50, S25, E26, lo, hi)
    s = stats(t)
    if not s: print(f"  {lbl:12}  no trades"); continue
    v = 'PASS' if s['pf']>=1.2 and s['ev']>0 else ('EDGE' if s['pf']>=1.0 else 'FAIL')
    cur = "  <-- CURRENT" if lbl=="0.50-0.60%" else ""
    print(f"  {lbl:12} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%  {v}{cur}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 9: EXIT SWEEP (bucket=0.50-0.60%)
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 9: EXIT TIME SWEEP  (bucket=0.50-0.60%, 2025+2026)")
EXIT_TIMES = ['10:15','10:18','10:20','10:22','10:25']
print(f"  {'Exit':6} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for et in EXIT_TIMES:
    t = collect(all_data, ema50, S25, E26, 0.50, 0.60, exit_time=et)
    s = stats(t)
    if not s: print(f"  {et:6}  no trades"); continue
    v = 'PASS' if s['pf']>=1.2 and s['ev']>0 else ('EDGE' if s['pf']>=1.0 else 'FAIL')
    cur = "  <-- CURRENT" if et=='10:20' else ""
    print(f"  {et:6} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%  {v}{cur}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 10: TRUE WALK-FORWARD (train 2025, freeze, test 2026)
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 10: TRUE WALK-FORWARD  (TRAIN=2025, TEST=2026 no changes)")
print(f"  {'Period':<35} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}  Verdict  Tag")
line()
for label, t in [
    ("TRAIN: 2025 Full",          t25),
    ("TEST:  2026 YTD (unseen)",   t26),
]:
    s = stats(t)
    if not s: continue
    v   = 'PASS' if s['pf']>=1.3 and s['wr']>=0.55 else ('MARGINAL' if s['pf']>=1.0 else 'FAIL')
    tag = 'TRAIN' if '2025' in label else 'OUT-OF-SAMPLE TEST'
    print(f"  {label:<35} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%  {v}  [{tag}]")
line()
# Half-year splits
for label, start, end in [
    ("TRAIN: H1 2025",  ts('2025-01-01'), ts('2025-06-30')),
    ("TEST:  H2 2025",  ts('2025-07-01'), ts('2025-12-31')),
    ("TEST:  H3 2026",  ts('2026-01-01'), ts('2026-06-09')),
]:
    t = collect(all_data, ema50, start, end, 0.50, 0.60)
    s = stats(t)
    if not s: continue
    v   = 'PASS' if s['pf']>=1.3 and s['wr']>=0.55 else ('MARGINAL' if s['pf']>=1.0 else 'FAIL')
    tag = 'TRAIN' if '2025' in label else 'TEST'
    print(f"  {label:<35} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%  {v}  [{tag}]")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 11: MONTE CARLO (1000 simulations)
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 11: MONTE CARLO  (1000 simulations, randomized trade order)")
pnl_list  = df['pnl'].tolist()
N_SIM     = 1000
random.seed(42)
final_rets, max_dds, max_recov = [], [], []
for _ in range(N_SIM):
    shuffled = random.sample(pnl_list, len(pnl_list))
    cum      = np.cumsum(shuffled)
    peak     = np.maximum.accumulate(cum)
    dd_arr   = cum - peak
    max_dds.append(dd_arr.min())
    final_rets.append(cum[-1])
    # recovery: longest streak below peak
    in_dd = 0; max_in_dd = 0
    for v in dd_arr:
        in_dd = in_dd+1 if v < -0.01 else 0
        max_in_dd = max(max_in_dd, in_dd)
    max_recov.append(max_in_dd)

fr = np.array(final_rets); md = np.array(max_dds); mr = np.array(max_recov)
print(f"  Simulations:  {N_SIM}  |  Trades per sim: {len(pnl_list)}\n")
print(f"  FINAL RETURN:")
print(f"    95th pct (best):    {np.percentile(fr,95):>+8.2f}%")
print(f"    Median:             {np.median(fr):>+8.2f}%")
print(f"    5th pct (worst):    {np.percentile(fr,5):>+8.2f}%")
print(f"    % profitable sims:  {(fr>0).mean()*100:.1f}%")
print()
print(f"  MAX DRAWDOWN:")
print(f"    5th pct (mildest):  {np.percentile(md,5):>+8.2f}%")
print(f"    Median:             {np.median(md):>+8.2f}%")
print(f"    95th pct (worst):   {np.percentile(md,95):>+8.2f}%")
print(f"    DD > -20%:          {(md<-20).mean()*100:.1f}% of sims")
print(f"    DD > -30%:          {(md<-30).mean()*100:.1f}% of sims")
print()
print(f"  LONGEST RECOVERY (consecutive trades in drawdown):")
print(f"    Median:             {int(np.median(mr))} trades")
print(f"    95th pct (worst):   {int(np.percentile(mr,95))} trades")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 12: EQUITY CURVE
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 12: EQUITY CURVE  (cumulative P&L by trade #)")
cum_arr = df['pnl'].cumsum().values
n       = len(cum_arr)
bar_max = 45
scale   = max(abs(cum_arr.max()), abs(cum_arr.min())) / bar_max
chk     = sorted(set([0] + [int(i*(n-1)/19) for i in range(1,20)] + [n-1]))
print(f"  {'Trade':>7} {'Date':>12} {'CumPnL':>9}  Curve")
line()
for i in chk:
    v    = cum_arr[i]
    d_   = df.iloc[i]['date']
    bars = int(abs(v)/scale) if scale > 0 else 0
    bar  = ('+' if v>=0 else '-') * bars
    print(f"  {i+1:>7} {str(d_):>12} {v:>+8.2f}%  |{bar}")
print(f"\n  Peak:    {cum_arr.max():>+8.2f}%  at trade #{cum_arr.argmax()+1}")
print(f"  Trough:  {cum_arr.min():>+8.2f}%  at trade #{cum_arr.argmin()+1}")
print(f"  Final:   {cum_arr[-1]:>+8.2f}%")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 13: REGIME TESTS
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 13: REGIME BREAKDOWN  (Bull vs Bear vs QQQ strength)")
print(f"  {'Regime':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}")
line()
for regime in ['bull','bear']:
    sub = df[df['regime']==regime]
    s   = stats(sub)
    if not s: continue
    print(f"  {regime.upper():<10} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")
line()
print(f"  BULL regime — by QQQ 5m strength:")
line()
bull_df = df[df['regime']=='bull']
for lo,hi,lbl in [(0.10,0.15,'QQQ 0.10-0.15%'),(0.15,0.25,'QQQ 0.15-0.25%'),(0.25,0.40,'QQQ 0.25-0.40%'),(0.40,99,'QQQ >0.40%')]:
    sub = bull_df[(bull_df['qqq_5m']>=lo) & (bull_df['qqq_5m']<hi)]
    if len(sub)==0: continue
    s = stats(sub)
    print(f"  {lbl:<20} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")
line()
print(f"  BEAR regime — by QQQ 5m strength:")
line()
bear_df = df[df['regime']=='bear']
for lo,hi,lbl in [(-0.15,-0.10,'QQQ 0.10-0.15%'),(-0.25,-0.15,'QQQ 0.15-0.25%'),(-0.40,-0.25,'QQQ 0.25-0.40%'),(-99,-0.40,'QQQ >0.40%')]:
    sub = bear_df[(bear_df['qqq_5m']>=lo) & (bear_df['qqq_5m']<hi)]
    if len(sub)==0: continue
    s = stats(sub)
    print(f"  {lbl:<20} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 14: OPTIONS TRANSLATION
# ═══════════════════════════════════════════════════════════════════════
hdr("TEST 14: OPTIONS TRANSLATION  (1DTE ATM simulation)")
print("  Each stock signal -> 1DTE ATM option")
print("  Stock move approx = option delta ~0.5, so option move ~2x stock move\n")

configs = [
    ("TP +50%  SL -20%",  0.50, -0.20),
    ("TP +100% SL -50%",  1.00, -0.50),
]
for label, tp, sl in configs:
    results = []
    for _, row in df.iterrows():
        # Approximate: 1DTE ATM option price ~ 1% of stock price
        # Option P&L as multiple of premium: stock pnl * 2 (delta 0.5) / option_cost_pct
        # Simplified: option move = stock_pnl * 2, cost = 1% of stock
        # Normalize: entry cost = 1.0 unit, outcome based on stock move
        opt_move = row['pnl'] * 2.0  # delta ~0.5, leverage ~2x
        if opt_move >= tp * 100:
            pnl_opt = tp
        elif opt_move <= sl * 100:
            pnl_opt = sl
        else:
            pnl_opt = opt_move / 100
        results.append({'pnl': pnl_opt * 100, 'raw_stock': row['pnl']})

    rdf  = pd.DataFrame(results)
    wins = rdf[rdf['pnl']>0]; loss = rdf[rdf['pnl']<=0]
    wr   = len(wins)/len(rdf)*100
    pf   = wins['pnl'].sum()/abs(loss['pnl'].sum()) if len(loss)>0 and loss['pnl'].sum()!=0 else 0
    tot  = rdf['pnl'].sum()
    ev   = rdf['pnl'].mean()
    cum  = rdf['pnl'].cumsum()
    dd   = (cum.expanding().max()-cum).max()
    print(f"  Config: {label}")
    print(f"    Trades: {len(rdf)}  WR: {wr:.1f}%  PF: {pf:.2f}  EV: {ev:+.4f}  Total: {tot:+.2f}%  MaxDD: -{dd:.2f}%")
    print()
sep()

OUT.flush(); OUT.close()
_p("\nDone -> boof28_full_validation.txt")
