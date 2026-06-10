"""
BOOF 28 - Sector Analysis: Winners vs Losers by Sector
Rules:
  LONG:  QQQ>EMA50, QQQ_5m>=+0.10%, stock_5m 0.60-0.70%, entry 9:35, exit 10:15
  SHORT: QQQ<EMA50, QQQ_5m<=-0.10%, stock_5m -0.80 to -1.50%, entry 9:35, exit 10:15
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SECTORS = {
    "Semiconductors": ["NVDA","AMD","AVGO","QCOM","MU","AMAT","ASML","TSM","LRCX","KLAC","MRVL","ADI","NXPI","TXN","MCHP","ON","MPWR","ARM"],
    "Fintech":        ["HOOD","COIN","CAVA","SQ","FI"],
    "Industrials":    ["CAT","ETN","PH","TT","DE","URI"],
    "Mega-cap Tech":  ["META","AMZN","GOOGL","MSFT","AAPL"],
}

# Build reverse lookup: symbol -> sector
SYM_TO_SECTOR = {}
for sector, syms in SECTORS.items():
    for s in syms:
        SYM_TO_SECTOR[s] = sector

ALL_SYMBOLS = list(SYM_TO_SECTOR.keys())

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

def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []

    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue
        q5 = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open'] * 100

        qcb  = qday.between_time('16:00','16:00')
        qc   = qcb.iloc[-1]['close'] if len(qcb) > 0 else qday.iloc[-1]['close']
        e50  = get_ema(ema50, d)
        if e50 is None: continue

        bull = qc > e50
        bear = qc < e50

        for sym in ALL_SYMBOLS:
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

            sector = SYM_TO_SECTOR.get(sym, 'Other')

            if bull and q5 >= 0.10 and (0.60 <= s5 < 0.70):
                pnl = (xp - ep) / ep * 100
                trades.append({'sym': sym, 'sector': sector, 'side': 'LONG',  'pnl': pnl})

            elif bear and q5 <= -0.10 and (-1.50 <= s5 <= -0.80):
                pnl = (ep - xp) / ep * 100
                trades.append({'sym': sym, 'sector': sector, 'side': 'SHORT', 'pnl': pnl})

    return trades

def sector_report(df):
    sector_order = ["Semiconductors","Mega-cap Tech","Software","Cloud","AI","Cybersecurity","Fintech","Biotech","Industrials","Other"]
    print(f"\n{'Sector':16} {'Trades':>7} {'Win%':>6} {'Avg P&L':>9} {'Total':>9} {'PF':>5}  {'Best Sym':>10}")
    print("-"*80)
    for sector in sector_order:
        sub = df[df['sector'] == sector]
        if len(sub) == 0: continue
        wins = sub[sub['pnl'] > 0]
        loss = sub[sub['pnl'] <= 0]
        wr   = len(wins) / len(sub) * 100
        avg  = sub['pnl'].mean()
        tot  = sub['pnl'].sum()
        gp   = wins['pnl'].sum()
        gl   = abs(loss['pnl'].sum())
        pf   = gp / gl if gl > 0 else 0
        # Best symbol in sector
        sym_tot = sub.groupby('sym')['pnl'].sum().sort_values(ascending=False)
        best = sym_tot.index[0] if len(sym_tot) > 0 else '---'
        print(f"  {sector:14} {len(sub):>7} {wr:>5.1f}% {avg:>+8.3f}% {tot:>+8.2f}% {pf:>5.2f}  {best:>10}")

def sym_report(df, label, top_n=10):
    sym_stats = []
    for sym, grp in df.groupby('sym'):
        wins = grp[grp['pnl'] > 0]
        loss = grp[grp['pnl'] <= 0]
        wr   = len(wins) / len(grp) * 100
        avg  = grp['pnl'].mean()
        tot  = grp['pnl'].sum()
        gp   = wins['pnl'].sum()
        gl   = abs(loss['pnl'].sum())
        pf   = gp / gl if gl > 0 else 0
        sym_stats.append({'sym': sym, 'sector': grp.iloc[0]['sector'],
                          'n': len(grp), 'wr': wr, 'avg': avg, 'total': tot, 'pf': pf})
    sym_df = pd.DataFrame(sym_stats).sort_values('total', ascending=False)

    print(f"\n  TOP {top_n} SYMBOLS by Total P&L ({label}):")
    print(f"  {'Sym':6} {'Sector':14} {'N':>5} {'WR%':>6} {'Avg':>8} {'Total':>8} {'PF':>5}")
    print(f"  {'-'*65}")
    for _, r in sym_df.head(top_n).iterrows():
        print(f"  {r['sym']:6} {r['sector']:14} {r['n']:>5} {r['wr']:>5.1f}% {r['avg']:>+7.3f}% {r['total']:>+7.2f}% {r['pf']:>5.2f}")

    print(f"\n  BOTTOM {top_n} SYMBOLS by Total P&L ({label}):")
    print(f"  {'Sym':6} {'Sector':14} {'N':>5} {'WR%':>6} {'Avg':>8} {'Total':>8} {'PF':>5}")
    print(f"  {'-'*65}")
    for _, r in sym_df.tail(top_n).iterrows():
        print(f"  {r['sym']:6} {r['sector']:14} {r['n']:>5} {r['wr']:>5.1f}% {r['avg']:>+7.3f}% {r['total']:>+7.2f}% {r['pf']:>5.2f}")

# ── Main ─────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + ALL_SYMBOLS:
    df = load_cached(sym)
    if df is not None:
        all_data[sym] = df
print(f"Loaded {len(all_data)} symbols")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

print("Collecting trades...")
t25  = collect(all_data, ema50, s25s, s25e)
t26  = collect(all_data, ema50, s26s, s26e)
tall = t25 + t26

df_all = pd.DataFrame(tall)

print(f"\nTotal trades: {len(df_all)}  |  LONG: {len(df_all[df_all['side']=='LONG'])}  |  SHORT: {len(df_all[df_all['side']=='SHORT'])}")

# ── Combined ─────────────────────────────────────────────────────────
print("\n" + "="*80)
print("SECTOR BREAKDOWN — COMBINED (2025 + 2026 YTD)")
print("="*80)
sector_report(df_all)
sym_report(df_all, "COMBINED")

# ── LONG only ────────────────────────────────────────────────────────
df_long = df_all[df_all['side'] == 'LONG']
print("\n" + "="*80)
print("SECTOR BREAKDOWN — LONGS ONLY")
print("="*80)
sector_report(df_long)

# ── SHORT only ───────────────────────────────────────────────────────
df_short = df_all[df_all['side'] == 'SHORT']
print("\n" + "="*80)
print("SECTOR BREAKDOWN — SHORTS ONLY")
print("="*80)
sector_report(df_short)
