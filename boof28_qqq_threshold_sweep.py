"""
BOOF 28 - QQQ 5m Threshold Sweep
Tests: 0.00%, 0.05%, 0.10%, 0.15%, 0.20%
Reports: Trades, PF, Avg Trade, Max DD
2025 + 2026 YTD combined
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA","AMD","AVGO","QCOM","AMAT","MU","MRVL","LRCX","KLAC","ASML","TSM","ARM","INTC","ON",
    "MCHP","ADI","NXPI","TXN","MPWR","TER","SMCI","ANET","DELL","HPE","STM",
    "MSFT","GOOGL","META","AMZN","AAPL","TSLA","NFLX",
    "CRM","ADBE","INTU","NOW","SHOP","ORCL","IBM","CSCO",
    "PLTR","SNOW","DDOG","MDB","NET","CRWD","PANW","ZS","ESTC","S",
    "AI","PATH","DOCN","FSLY","AKAM",
    "PYPL","SQ","HOOD","COIN","ADP","FIS","FI","GPN","JKHY",
    "UBER","ABNB","DASH","RBLX","APP",
    "TTD","DUOL","CELH","CAVA","RKLB",
    "LLY","NVO","ABBV","JNJ","MRK","AMGN","GILD","REGN","VRTX","ISRG",
    "BIIB","BMY","PFE","MRNA","NBIX",
    "GE","CAT","ETN","PH","TT","DE","HON","EMR","ROP","URI"
]

THRESHOLDS = [0.00, 0.05, 0.10, 0.15, 0.20]

def load_cached(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    return d.groupby('date')['close'].last().ewm(span=50, adjust=False).mean()

def get_ema(s, date):
    v = s.get(date)
    if v is None:
        prior = [d for d in s.index if d < date]
        v = s[prior[-1]] if prior else None
    return v

def collect_all(all_data, ema50, start, end):
    """Collect all candidate trades with qqq_5m tagged — filter later"""
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []

    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue

        q5 = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open'] * 100

        qcb   = qday.between_time('16:00','16:00')
        qc    = qcb.iloc[-1]['close'] if len(qcb) > 0 else qday.iloc[-1]['close']
        e50   = get_ema(ema50, d)
        if e50 is None: continue

        bull = qc > e50
        bear = qc < e50

        for sym in SYMBOLS:
            if sym not in all_data: continue
            df  = all_data[sym].copy()
            df  = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day) == 0: continue

            so = day.between_time('09:30','09:34')
            if len(so) == 0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open'] * 100

            en = day.between_time('09:35','09:35')
            ex = day.between_time('10:15','10:15')
            if len(en) == 0 or len(ex) == 0: continue

            ep = en.iloc[0]['close']
            xp = ex.iloc[0]['close']

            if bull and (0.60 <= s5 < 0.70):
                trades.append({'side':'L', 'pnl':(xp-ep)/ep*100, 'qqq_5m': q5})
            elif bear and (-1.50 <= s5 <= -0.80):
                trades.append({'side':'S', 'pnl':(ep-xp)/ep*100, 'qqq_5m': q5})

    return trades

def calc_stats(trades):
    if not trades:
        return {'n':0,'wr':0,'avg':0,'total':0,'pf':0,'maxdd':0}
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    wr   = len(wins) / len(df) * 100
    avg  = df['pnl'].mean()
    tot  = df['pnl'].sum()
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = gp / gl if gl > 0 else 0
    df['cum'] = df['pnl'].cumsum()
    dd   = (df['cum'].expanding().max() - df['cum']).max()
    return {'n':len(df),'wr':wr,'avg':avg,'total':tot,'pf':pf,'maxdd':dd}

# ── Load data ────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + SYMBOLS:
    df = load_cached(sym)
    if df is not None:
        all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

# Collect once, filter by threshold
print("Collecting 2025 trades...")
raw25 = collect_all(all_data, ema50, s25s, s25e)
print("Collecting 2026 trades...")
raw26 = collect_all(all_data, ema50, s26s, s26e)
raw_all = raw25 + raw26

print(f"\nBase trades (no 5m filter): {len(raw_all)}\n")

# ── Results table ────────────────────────────────────────────────────
def bar(val, max_val, width=20, fill='█'):
    if max_val == 0: return ''
    n = int(val / max_val * width)
    return fill * n

results = []
for thr in THRESHOLDS:
    filtered = [t for t in raw_all if
                (t['side']=='L' and t['qqq_5m'] >= thr) or
                (t['side']=='S' and t['qqq_5m'] <= -thr)]
    s = calc_stats(filtered)
    s['thr'] = thr
    results.append(s)

# ── Print comparison ─────────────────────────────────────────────────
print("="*90)
print("QQQ 5m THRESHOLD SWEEP  (combined 2025 + 2026 YTD)")
print("="*90)
print(f"{'Threshold':>12}  {'Trades':>7}  {'WR%':>6}  {'Avg/Trade':>10}  {'Total%':>8}  {'PF':>5}  {'MaxDD%':>8}")
print("-"*90)

max_n    = max(r['n']    for r in results if r['n']>0)
max_avg  = max(r['avg']  for r in results if r['n']>0)
max_pf   = max(r['pf']   for r in results if r['n']>0)
min_dd   = max(r['maxdd']for r in results if r['n']>0)

for r in results:
    if r['n'] == 0:
        print(f"  >= {r['thr']:.2f}%    {'0':>7}  {'---':>6}  {'---':>10}  {'---':>8}  {'---':>5}  {'---':>8}")
        continue
    print(f"  >= {r['thr']:.2f}%    {r['n']:>7}  {r['wr']:>5.1f}%  {r['avg']:>+9.3f}%  {r['total']:>+7.2f}%  {r['pf']:>5.2f}  -{r['maxdd']:>7.2f}%")

print("="*90)

# ── ASCII chart ──────────────────────────────────────────────────────
labels = [f">={r['thr']:.2f}%" for r in results]
W = 35

print("\n── TRADES ─────────────────────────────────────────────────────")
mx = max(r['n'] for r in results)
for r, lbl in zip(results, labels):
    b = bar(r['n'], mx, W)
    print(f"  {lbl:8}  {b:<35}  {r['n']}")

print("\n── PROFIT FACTOR ──────────────────────────────────────────────")
mx = max(r['pf'] for r in results)
for r, lbl in zip(results, labels):
    b = bar(r['pf'], mx, W)
    print(f"  {lbl:8}  {b:<35}  {r['pf']:.2f}")

print("\n── AVG TRADE (%) ──────────────────────────────────────────────")
mx = max(r['avg'] for r in results)
for r, lbl in zip(results, labels):
    b = bar(r['avg'], mx, W)
    print(f"  {lbl:8}  {b:<35}  {r['avg']:+.3f}%")

print("\n── MAX DRAWDOWN (lower = better) ──────────────────────────────")
mx = max(r['maxdd'] for r in results)
for r, lbl in zip(results, labels):
    b = bar(r['maxdd'], mx, W)
    print(f"  {lbl:8}  {b:<35}  -{r['maxdd']:.2f}%")

print()
