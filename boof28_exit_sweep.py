"""
BOOF 28 - Exit Time Sweep + Trailing Stop
Tests: 5min, 10min, 15min, 20min, 25min, 30min exits + trail (1% activate, 0.75% trail)
Entry always at 9:35
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","LRCX","KLAC",
    "MRVL","INTC","ON","NXPI","TXN","ARM","HOOD","COIN","SQ","SOFI","CAVA",
    "CAT","ETN","DE","GE","URI","ISRG","MRNA","VRTX","REGN","LLY",
    "META","MSFT","GOOGL","AAPL","TSLA","UBER","RCL","CCL","ABNB"
]

EXIT_TIMES = {
    "10:15 (base)": "10:15",
    "10:20 (+45m)": "10:20",
    "10:25 (+50m)": "10:25",
    "10:30 (+55m)": "10:30",
    "10:45 (+70m)": "10:45",
    "11:00 (+85m)": "11:00",
}

def load_cached(s):
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

def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []

    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue
        q5 = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']

        qopen_bar = qday.between_time('09:30','09:30')
        if len(qopen_bar) == 0: continue
        qqq_open_price = qopen_bar.iloc[0]['open']
        e50 = get_ema(ema50, d)
        if e50 is None: continue

        bull = qqq_open_price > e50 and q5 >= 0.001
        bear = qqq_open_price < e50 and q5 <= -0.001
        if not bull and not bear: continue

        for sym in SYMBOLS:
            if sym not in all_data: continue
            df  = all_data[sym].copy()
            df  = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day) == 0: continue

            so = day.between_time('09:30','09:34')
            if len(so) == 0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']

            en = day.between_time('09:35','09:35')
            if len(en) == 0: continue
            entry_price = en.iloc[0]['open']

            direction = None
            if bull and 0.006 <= s5 <= 0.007:
                direction = 'LONG'
            elif bear and -0.015 <= s5 <= -0.008:
                direction = 'SHORT'
            if direction is None: continue

            trade = {'date': d, 'symbol': sym, 'direction': direction}

            # Fixed time exits
            for label, exit_time in EXIT_TIMES.items():
                ex = day.between_time(exit_time, exit_time)
                if len(ex) == 0:
                    trade[label] = None
                    continue
                ep = ex.iloc[0]['open']
                if direction == 'LONG':
                    trade[label] = (ep - entry_price) / entry_price * 100
                else:
                    trade[label] = (entry_price - ep) / entry_price * 100

            trades.append(trade)

    return trades

def summarize(trades, label):
    if not trades:
        print(f"\n{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    n  = len(df)

    cols = list(EXIT_TIMES.keys())
    labels_display = list(EXIT_TIMES.keys())

    print(f"\n{'='*80}")
    print(f" {label}  (n={n})")
    print(f"{'='*80}")
    print(f"  {'Exit':22} {'WR%':>6}  {'Avg':>9}  {'Total':>9}  {'PF':>5}  {'MaxDD':>8}")
    print(f"  {'-'*70}")

    results = []
    for col, disp in zip(cols, labels_display):
        sub = df[col].dropna()
        if len(sub) == 0: continue
        wins = sub[sub > 0]; loss = sub[sub <= 0]
        wr  = len(wins) / len(sub) * 100
        avg = sub.mean(); tot = sub.sum()
        gp  = wins.sum(); gl = abs(loss.sum())
        pf  = gp / gl if gl > 0 else 0
        cum = sub.cumsum()
        dd  = (cum.expanding().max() - cum).max()
        results.append((disp, wr, avg, tot, pf, dd))
        print(f"  {disp:22} {wr:>5.1f}%  {avg:>+8.3f}%  {tot:>+8.2f}%  {pf:>5.2f}  -{dd:>6.2f}%")

    # Highlight best
    best = max(results, key=lambda x: x[3])
    print(f"\n  ★ Best total P&L: {best[0]}  →  {best[3]:+.2f}%  (PF {best[4]:.2f})")

# ── Main ─────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + SYMBOLS:
    df = load_cached(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

print("Running 2025..."); t25 = collect(all_data, ema50, s25s, s25e)
print("Running 2026..."); t26 = collect(all_data, ema50, s26s, s26e)

summarize(t25,       "2025 FULL YEAR")
summarize(t26,       "2026 YTD (Jan-Jun 9)")
summarize(t25 + t26, "COMBINED (2025 + 2026 YTD)")
