"""
Rolling monthly backtest — Boof 21 vs Boof 22 — Jan 2025 to May 2026
Fixed +35% TP / -18% SL for Boof 21
ATR 4x TP / 2x SL for Boof 22
"""
import pickle, sys
import numpy as np
from datetime import datetime
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_boof22 import run_boof22, compute_atr
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

TRADE   = 200
TP21    = 0.35
SL21    = -0.18
TM21    = 0.08
MAX_HOLD = 30

SYM21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
SYM22 = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

# All months Jan 2025 → May 2026
from datetime import date
months_cfg = [
    ('Jan 25', datetime(2025,1,1),  datetime(2025,1,31),  23),
    ('Feb 25', datetime(2025,2,1),  datetime(2025,2,28),  20),
    ('Mar 25', datetime(2025,3,1),  datetime(2025,3,31),  21),
    ('Apr 25', datetime(2025,4,1),  datetime(2025,4,30),  22),
    ('May 25', datetime(2025,5,1),  datetime(2025,5,31),  21),
    ('Jun 25', datetime(2025,6,1),  datetime(2025,6,30),  21),
    ('Jul 25', datetime(2025,7,1),  datetime(2025,7,31),  23),
    ('Aug 25', datetime(2025,8,1),  datetime(2025,8,31),  21),
    ('Sep 25', datetime(2025,9,1),  datetime(2025,9,30),  22),
    ('Oct 25', datetime(2025,10,1), datetime(2025,10,31), 23),
    ('Nov 25', datetime(2025,11,1), datetime(2025,11,30), 20),
    ('Dec 25', datetime(2025,12,1), datetime(2025,12,31), 23),
    ('Jan 26', datetime(2026,1,1),  datetime(2026,1,31),  22),
    ('Feb 26', datetime(2026,2,1),  datetime(2026,2,28),  20),
    ('Mar 26', datetime(2026,3,1),  datetime(2026,3,31),  21),
    ('Apr 26', datetime(2026,4,1),  datetime(2026,4,30),  22),
    ('May 26', datetime(2026,5,1),  datetime(2026,5,25),  18),  # partial
]

CACHE26 = '_boof_2026_cache.pkl'

print('Loading caches...')
cache21 = pickle.load(open('_boof21_cache.pkl','rb'))
cache22 = pickle.load(open('_boof22_cache.pkl','rb'))
creds = get_alpaca_credentials()

# Load or build 2026 cache
months_2026 = [
    ('Jan 26', datetime(2026,1,1),  datetime(2026,1,31)),
    ('Feb 26', datetime(2026,2,1),  datetime(2026,2,28)),
    ('Mar 26', datetime(2026,3,1),  datetime(2026,3,31)),
    ('Apr 26', datetime(2026,4,1),  datetime(2026,4,30)),
    ('May 26', datetime(2026,5,1),  datetime(2026,5,25)),
]
import os
if os.path.exists(CACHE26):
    print('Loading 2026 cache...')
    cache26 = pickle.load(open(CACHE26,'rb'))
else:
    print('Fetching 2026 data from API...')
    cache26 = {}
    all_syms = list(set(SYM21 + SYM22))
    total = len(all_syms) * len(months_2026)
    done = 0
    for label, start, end in months_2026:
        for sym in all_syms:
            done += 1
            print(f'  [{done}/{total}] {sym} {label}...', end=' ', flush=True)
            try:
                df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
                if df is not None and len(df) >= 100:
                    cache26[(sym, label)] = df
                    print(f'OK ({len(df)} bars)')
                else:
                    print('SKIP')
            except Exception as e:
                print(f'ERR: {e}')
    print(f'Saving 2026 cache ({len(cache26)} entries)...')
    pickle.dump(cache26, open(CACHE26,'wb'))
    print('Done.')

def calc_pf(pnls):
    w = [p for p in pnls if p > 0]
    l = [p for p in pnls if p < 0]
    return round(sum(w)/max(abs(sum(l)),0.01), 2) if l else float('inf')

def sim22_atr(df, sym):
    if 'atr' not in df.columns:
        df = df.copy(); df['atr'] = compute_atr(df)
    trades = run_boof22(df, symbol=sym, tp_pct=0.99, sl_pct=0.99)
    pnls = []
    for t in trades:
        bar_i = t.get('bar')
        if bar_i is None: continue
        atr = float(df['atr'].iloc[bar_i]) if bar_i < len(df) else 0
        if not atr or np.isnan(atr): continue
        ep = float(t['entry']); d = t['direction']
        tp_p = ep + atr*4.0 if d=='long' else ep - atr*4.0
        sl_p = ep - atr*2.0 if d=='long' else ep + atr*2.0
        et = 'time'
        bars = df['close'].iloc[bar_i+1: bar_i+MAX_HOLD+2].values
        for price in bars:
            if d=='long':
                if price >= tp_p: et='tp'; break
                if price <= sl_p: et='sl'; break
            else:
                if price <= tp_p: et='tp'; break
                if price >= sl_p: et='sl'; break
        if et=='tp':   pnls.append(TRADE*(atr*4.0/ep))
        elif et=='sl': pnls.append(-TRADE*(atr*2.0/ep))
        else:          pnls.append(TRADE*TM21)
    return pnls

results = []
rolling21 = rolling22 = 0.0

print('Running backtests...\n')

for label, start, end, tdays in months_cfg:
    mo_key_21 = label[:6].strip()  # 'Jan 25' etc
    mo_key_22 = label[:3]          # 'Jan' etc

    is_2026 = '26' in label
    print(f'  {label}...', end=' ', flush=True)

    # ── Boof 21 ──
    pnls21 = []
    for sym in SYM21:
        df = cache26.get((sym, label)) if is_2026 else cache21.get((sym, mo_key_21))
        if df is None or len(df) < 100: continue
        for t in bt21.backtest(df, symbol=sym):
            et = t['exit_type']
            pnls21.append(TRADE*TP21 if et=='tp' else TRADE*SL21 if et=='stop' else TRADE*TM21)

    # ── Boof 22 ──
    pnls22 = []
    for sym in SYM22:
        df = cache26.get((sym, label)) if is_2026 else cache22.get((sym, mo_key_22))
        if df is None or len(df) < 100: continue
        pnls22 += sim22_atr(df, sym)
    print('done')

    mo21 = round(sum(pnls21))
    mo22 = round(sum(pnls22))
    rolling21 += mo21
    rolling22 += mo22
    combined  = round(rolling21 + rolling22)

    n21 = len(pnls21); n22 = len(pnls22)
    pf21 = calc_pf(pnls21); pf22 = calc_pf(pnls22)
    wr21 = round(sum(1 for p in pnls21 if p>0)/max(n21,1)*100,1)
    wr22 = round(sum(1 for p in pnls22 if p>0)/max(n22,1)*100,1)

    results.append((label, tdays, mo21, mo22, rolling21, rolling22, combined, n21, n22, pf21, pf22, wr21, wr22))

# ── Print table ──
print(f'{"="*110}')
print(f'BOOF 21 vs BOOF 22 | Monthly + Rolling P&L | $200/trade')
print(f'Boof 21: +35% TP / -18% SL (fixed)   |   Boof 22: 4x ATR TP / 2x ATR SL')
print(f'{"="*110}')
print(f'{"Month":<8} {"Days":<5} | {"B21 Mo$":>9} {"Roll21":>10} {"PF21":>6} {"WR21":>6} | {"B22 Mo$":>9} {"Roll22":>10} {"PF22":>6} {"WR22":>6} | {"Combined":>10}')
print(f'{"-"*110}')

for r in results:
    label, tdays, mo21, mo22, r21, r22, comb, n21, n22, pf21, pf22, wr21, wr22 = r
    flag21 = '▼' if mo21 < 0 else ' '
    flag22 = '▼' if mo22 < 0 else ' '
    print(f'{label:<8} {tdays:<5} | {flag21}${mo21:>8,} ${r21:>9,} {pf21:>6} {wr21:>5}% | {flag22}${mo22:>8,} ${r22:>9,} {pf22:>6} {wr22:>5}% | ${comb:>9,}')

print(f'{"-"*110}')
total21 = results[-1][4]; total22 = results[-1][5]; total_comb = results[-1][6]
print(f'{"TOTAL":<14}| {"":>9} ${total21:>9,} {"":>6} {"":>6} | {"":>9} ${total22:>9,} {"":>6} {"":>6} | ${total_comb:>9,}')
print(f'{"="*110}')
print(f'\nBoof 21 avg/month: ${round(total21/len(results)):,}')
print(f'Boof 22 avg/month: ${round(total22/len(results)):,}')
print(f'Combined avg/month: ${round(total_comb/len(results)):,}')
losing21 = sum(1 for r in results if r[2] < 0)
losing22 = sum(1 for r in results if r[3] < 0)
print(f'Losing months — Boof 21: {losing21}/{len(results)}  |  Boof 22: {losing22}/{len(results)}')
