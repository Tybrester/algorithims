"""
BOOF 28 - Parameter Sweep
1. Move bucket sweep (0.50-0.60, 0.60-0.70, 0.70-0.80, 0.50-0.70, 0.55-0.75)
2. Exit time sweep (10:18, 10:20, 10:22, 10:25)
3. Walk-forward (Train 2025 / Test 2026)
4. Symbol contribution %
"""
import sys, pickle, os, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd

OUT = open('boof28_param_sweep_results.txt', 'w', encoding='utf-8')
_p = print
def print(*a, **k):
    _p(*a, **k)
    _p(*a, **k, file=OUT)

WATCHLIST = [
    "NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","MRVL","INTC","ON","NXPI","TXN","ARM",
    "HOOD","COIN","SQ","SOFI","AFRM","UPST","PYPL",
    "CAT","ETN","DE","GE","URI","ROP","HON","EMR",
    "ISRG","MRNA","VRTX","REGN","LLY","GILD","BMY","ABBV","NVO","AMGN",
    "UBER","ABNB","RCL","CCL",
]

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

# ── Core collector: captures all qualifying stocks per day, stores entry price
#    and raw exit bar data so we can test multiple exit times without re-scanning
def collect_raw(all_data, ema50, start, end, lo, hi):
    """Returns trades with entry_price and per-symbol bar data ref for exit flexibility."""
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    records = []  # (date, sym, side, entry_price, day_df, stock_5m, qqq_5m)
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
            if not (lo <= s5p < hi): continue
            # short filter
            direction = None
            if bull and s5 > 0:
                direction = 'LONG'
            elif bear and s5 < 0:
                direction = 'SHORT'
            if direction is None: continue
            en = day.between_time('09:35','09:35')
            if len(en)==0: continue
            ep = en.iloc[0]['open']
            records.append({'date':d,'symbol':sym,'side':direction,
                            'entry':ep,'day':day,'s5p':round(s5p,3),'q5p':round(q5*100,3),
                            'month':pd.Timestamp(d).to_period('M')})
    return records

def apply_exit(records, exit_time):
    trades = []
    hh, mm = exit_time.split(':')
    for r in records:
        ex = r['day'].between_time(exit_time, exit_time)
        if len(ex)==0: continue
        xp  = ex.iloc[0]['open']
        ep  = r['entry']
        pnl = (xp-ep)/ep*100 if r['side']=='LONG' else (ep-xp)/ep*100
        trades.append({**{k:v for k,v in r.items() if k != 'day'},
                       'pnl':pnl,'exit_time':exit_time})
    return trades

def stats(trades):
    if not trades: return {}
    df   = pd.DataFrame(trades) if isinstance(trades, list) else trades
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
    return dict(n=len(df),wr=wr,ev=ev,pf=pf,tot=tot,dd=dd,df=df)

def sep(c='=',w=80): print(c*w)
def line(w=80): print('-'*w)

# ── Load ──────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + WATCHLIST:
    df = load(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")
ema50 = build_ema50(all_data['QQQ'].copy())

def ts(s): return pd.to_datetime(s).tz_localize('UTC')
S25, E25 = ts('2025-01-01'), ts('2025-12-31')
S26, E26 = ts('2026-01-01'), ts('2026-06-09')
SALL, EALL = S25, E26

# ═══════════════════════════════════════════════════════════════════════
# TEST 1: MOVE BUCKET SWEEP  (exit fixed at 10:20)
# ═══════════════════════════════════════════════════════════════════════
sep()
print("  TEST 1: MOVE BUCKET SWEEP  (exit=10:20, long+short, 2025+2026)")
sep()
BUCKETS = [
    (0.50, 0.60, "0.50-0.60%"),
    (0.60, 0.70, "0.60-0.70%"),
    (0.70, 0.80, "0.70-0.80%"),
    (0.50, 0.70, "0.50-0.70%"),
    (0.55, 0.75, "0.55-0.75%"),
]
print(f"  {'Bucket':12} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for lo, hi, lbl in BUCKETS:
    # use absolute value for both long and short 5m move
    recs_l = collect_raw(all_data, ema50, SALL, EALL, lo, hi)
    recs_s = collect_raw(all_data, ema50, SALL, EALL, -hi, -lo)
    recs   = recs_l + recs_s
    trades = apply_exit(recs, '10:20')
    s = stats(trades)
    if not s:
        print(f"  {lbl:12}   no trades"); continue
    verdict = "PASS" if s['pf']>=1.3 and s['wr']>=0.55 else ("EDGE" if s['pf']>=1.0 else "FAIL")
    print(f"  {lbl:12} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%  {verdict}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 2: EXIT TIME SWEEP  (bucket fixed at 0.60-0.70%)
# ═══════════════════════════════════════════════════════════════════════
sep()
print("  TEST 2: EXIT TIME SWEEP  (bucket=0.60-0.70%, 2025+2026)")
sep()
EXIT_TIMES = ['10:18','10:20','10:22','10:25']
recs_base_l = collect_raw(all_data, ema50, SALL, EALL, 0.60, 0.70)
recs_base_s = collect_raw(all_data, ema50, SALL, EALL, -0.70, -0.60)
recs_base   = recs_base_l + recs_base_s
print(f"  {'Exit':6} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for et in EXIT_TIMES:
    trades = apply_exit(recs_base, et)
    s = stats(trades)
    if not s:
        print(f"  {et:6}   no trades"); continue
    verdict = "PASS" if s['pf']>=1.3 and s['wr']>=0.55 else ("EDGE" if s['pf']>=1.0 else "FAIL")
    marker = " <-- CURRENT" if et == '10:20' else ""
    print(f"  {et:6} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%  {verdict}{marker}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 3: WALK-FORWARD  (bucket 0.60-0.70%, exit 10:20)
# ═══════════════════════════════════════════════════════════════════════
sep()
print("  TEST 3: WALK-FORWARD  (bucket=0.60-0.70%, exit=10:20)")
sep()
print("  Parameters FIXED. Testing if 2026 out-of-sample holds up.\n")

def wf_run(start, end, label):
    rl = collect_raw(all_data, ema50, start, end, 0.60, 0.70)
    rs = collect_raw(all_data, ema50, start, end, -0.70, -0.60)
    t  = apply_exit(rl + rs, '10:20')
    s  = stats(t)
    if not s:
        print(f"  {label:<35}  no trades"); return
    tag = "TRAIN" if "2025" in label else "TEST (out-of-sample)"
    verdict = "PASS" if s['pf']>=1.3 and s['wr']>=0.55 else ("MARGINAL" if s['pf']>=1.0 else "FAIL")
    print(f"  {label:<35} {s['n']:>6} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%  {verdict}  [{tag}]")
    return s

print(f"  {'Period':<35} {'Trades':>6} {'WR%':>5} {'PF':>6} {'EV':>8} {'Total':>9}  Verdict")
line()
wf_run(S25, E25, "TRAIN: 2025 Full")
wf_run(S26, E26, "TEST:  2026 YTD (Jan-Jun 9)")
line()
# Half-year splits
SH1 = ts('2025-01-01'); EH1 = ts('2025-06-30')
SH2 = ts('2025-07-01'); EH2 = ts('2025-12-31')
wf_run(SH1, EH1, "TRAIN: H1 2025 (Jan-Jun)")
wf_run(SH2, EH2, "TEST:  H2 2025 (Jul-Dec)")
wf_run(S26, E26, "TEST:  H3 2026 (Jan-Jun)")
sep()

# ═══════════════════════════════════════════════════════════════════════
# TEST 4: SYMBOL CONTRIBUTION  (bucket 0.60-0.70%, exit 10:20, combined)
# ═══════════════════════════════════════════════════════════════════════
sep()
print("  TEST 4: SYMBOL CONTRIBUTION  (bucket=0.60-0.70%, exit=10:20, combined)")
sep()
rl = collect_raw(all_data, ema50, SALL, EALL, 0.60, 0.70)
rs = collect_raw(all_data, ema50, SALL, EALL, -0.70, -0.60)
all_trades = apply_exit(rl + rs, '10:20')
df_all = pd.DataFrame(all_trades)
gross_profit = df_all[df_all['pnl']>0]['pnl'].sum()
total_pnl    = df_all['pnl'].sum()

sym_rows = []
for sym, grp in df_all.groupby('symbol'):
    wins = grp[grp['pnl']>0]; loss = grp[grp['pnl']<=0]
    _wr  = len(wins)/len(grp)*100
    _pf  = wins['pnl'].sum()/abs(loss['pnl'].sum()) if len(loss)>0 and loss['pnl'].sum()!=0 else 0
    _tot = grp['pnl'].sum()
    _contrib = _tot / total_pnl * 100 if total_pnl != 0 else 0
    sym_rows.append({'sym':sym,'n':len(grp),'wr':_wr,'pf':_pf,'total':_tot,'contrib':_contrib})

sym_df = pd.DataFrame(sym_rows).sort_values('total', ascending=False)
cum_contrib = 0
print(f"  {'Symbol':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9} {'Contrib%':>9} {'CumContr%':>10}")
line()
for i, (_, r) in enumerate(sym_df.iterrows()):
    cum_contrib += r['contrib']
    flag = "  <-- TOP 10" if i < 10 else ""
    cut  = "  <-- CUT"    if r['total'] < -0.5 else ""
    print(f"  {r['sym']:>8} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['total']:>+8.2f}% {r['contrib']:>+8.1f}% {cum_contrib:>+9.1f}%{flag}{cut}")

print(f"\n  Total P&L:    {total_pnl:+.2f}%")
top10_total = sym_df.head(10)['total'].sum()
print(f"  Top 10 syms:  {top10_total:+.2f}%  ({top10_total/total_pnl*100:.0f}% of total P&L)")
rest_total  = sym_df.tail(len(sym_df)-10)['total'].sum()
print(f"  Rest ({len(sym_df)-10} syms): {rest_total:+.2f}%  ({rest_total/total_pnl*100:.0f}% of total P&L)")
sep()

OUT.flush(); OUT.close()
print("\nDone -> boof28_param_sweep_results.txt")
