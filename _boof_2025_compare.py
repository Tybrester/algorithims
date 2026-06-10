# -*- coding: utf-8 -*-
"""
Boof 21 / 22 / 23 -- Full Year 2025 Comparison
+35% TP / -15% SL static options-premium exits for all three
Symbols: AAPL, NVDA, META, GOOGL, AMD
Shows: monthly P&L, running cumulative P&L, avg trades/day, WR, EV, PF
"""
import sys, numpy as np, pandas as pd, requests
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import get_alpaca_credentials

def fetch_bars(symbol, start_str, end_str, api_key, secret_key):
    """Paginated 1-min bar fetch — handles >10k bar months."""
    all_bars = []
    url = f'https://data.alpaca.markets/v2/stocks/{symbol}/bars'
    params = {'timeframe':'1Min','start':start_str+'T09:30:00Z',
              'end':end_str+'T20:00:00Z','adjustment':'raw',
              'feed':'sip','limit':10000}
    headers = {'APCA-API-KEY-ID':api_key,'APCA-API-SECRET-KEY':secret_key}
    while True:
        r = requests.get(url, params=params, headers=headers)
        if r.status_code != 200:
            print(f'API {r.status_code}', end=' '); break
        d = r.json()
        bars = d.get('bars', [])
        all_bars.extend(bars)
        token = d.get('next_page_token')
        if not token: break
        params['page_token'] = token
    if not all_bars: return None
    df = pd.DataFrame(all_bars)
    df['time'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})
    df = df[['time','open','high','low','close','volume']].set_index('time')
    return df

from backtest_boof22 import (run_boof22, compute_atr as b22_atr,
                              build_cluster_array, nearest_sr_distance,
                              SYMBOL_PARAMS as B22_PARAMS, DEFAULT_PARAMS as B22_DEF,
                              ATR_LEN as B22_ATR_LEN, VOL_LEN as B22_VOL_LEN,
                              FRACTAL_BARS as B22_FRAC)
import backtest_boof23 as b23mod
from backtest_boof23 import (compute_atr as b23_atr, build_cluster_array as b23_clusters,
                              nearest_sr_distance as b23_sr, _build_zigzag,
                              SYMBOL_PARAMS as B23_PARAMS, DEFAULT_PARAMS as B23_DEF,
                              ATR_LEN as B23_ATR_LEN, VOL_LEN as B23_VOL_LEN,
                              FRACTAL_BARS as B23_FRAC, MAX_HOLD as B23_MAX_H)
from backtest_boof21 import backtest as b21_backtest
b23mod.CLUSTER_COMPLETION = False
b23mod.LOW_VOL_FILTER     = False

# ─────────────────────────────────────────────
SYMS   = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
TP_PCT = 0.35   # +35% option premium TP
SL_PCT = 0.15   # -15% option premium SL
TP_ATR = 0.70   # underlying ATR proxy for +35% prem (0.35*2)
SL_ATR = 0.30   # underlying ATR proxy for -15% prem (0.15*2)

B21_SIZE = 250
B22_CORE = 600; B22_EXP = 200
B23_CORE = 500; B23_EXP = 200

MONTHS     = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MDAYS      = [ 23,   20,   21,   22,   21,   21,   23,   21,   21,   23,   19,   23]
TOTAL_DAYS = sum(MDAYS)

MONTH_DATES = {
    'Jan': ('2025-01-02','2025-01-31'), 'Feb': ('2025-02-03','2025-02-28'),
    'Mar': ('2025-03-03','2025-03-31'), 'Apr': ('2025-04-01','2025-04-30'),
    'May': ('2025-05-01','2025-05-30'), 'Jun': ('2025-06-02','2025-06-30'),
    'Jul': ('2025-07-01','2025-07-31'), 'Aug': ('2025-08-01','2025-08-29'),
    'Sep': ('2025-09-02','2025-09-30'), 'Oct': ('2025-10-01','2025-10-31'),
    'Nov': ('2025-11-03','2025-11-28'), 'Dec': ('2025-12-01','2025-12-31'),
}

# ─────────────────────────────────────────────
# B21 — use real backtest() engine, remap pnl to static +35%/-15% option exits
# The native backtest() returns underlying % pnl. We replace that with fixed
# option premium exits: TP hit (pnl>0) = +35% of $250, SL hit (pnl<0) = -15% of $250,
# time exit = small flat (use actual underlying pnl * leverage proxy).
# ─────────────────────────────────────────────
def run_b21_month(df, sym):
    if df is None or len(df) < 500: return []
    raw = b21_backtest(df, sym)
    result = []
    for t in raw:
        et = t['exit_type']
        if et == 'tp':
            pnl = TP_PCT * B21_SIZE
        elif et == 'stop':
            pnl = -SL_PCT * B21_SIZE
        else:
            # time exit: use underlying % * leverage proxy (option ~2x ATR sensitivity)
            pnl = float(t['pnl']) * B21_SIZE * 2.0
            pnl = max(-SL_PCT * B21_SIZE, min(TP_PCT * B21_SIZE, pnl))
        result.append({'pnl': pnl, 'exit_type': et})
    return result

# ─────────────────────────────────────────────
# B22 — static exits via ATR-fraction thresholds (re-run signal loop)
# ─────────────────────────────────────────────
def run_b22_month(df, sym):
    if df is None or len(df) < 200: return []
    trades_raw = []
    params   = B22_PARAMS.get(sym, B22_DEF)
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']; sr_dist = params['sr_dist']
    df2 = df.copy().reset_index(drop=True)
    atr_s = b22_atr(df2)
    df2['atr']    = atr_s
    df2['vol_sma']= df2['volume'].rolling(B22_VOL_LEN).mean()
    df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
    df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
    cluster_prices, _ = build_cluster_array(df2, atr_s, vol_mult)

    opens=df2['open'].values; highs=df2['high'].values
    lows=df2['low'].values; closes=df2['close'].values; atrs=df2['atr'].values
    F=B22_FRAC; MAX_H=30; warmup=B22_VOL_LEN+B22_ATR_LEN+F
    in_trade=False; trade_end=0

    for i in range(warmup, len(df2)-F-MAX_H-3):
        if in_trade and i<=trade_end: continue
        atr=atrs[i]
        if np.isnan(atr) or atr==0: continue
        if df2.iloc[i]['rvol']<80: continue
        if not df2.iloc[i]['hi_vol']: continue
        if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist: continue
        lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
        ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
        fp=(highs[i]>lh.max()) and (highs[i]>rh.max())
        ft=(lows[i]<ll.min())  and (lows[i]<rl.min())
        ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
        ar=closes[i]<highs[i]-atr*atr_mult; ab=closes[i]>lows[i]+atr*atr_mult
        direction=None; slack=0.0
        if fp and ar: direction='short'; slack=ps
        elif ft and ab: direction='long'; slack=ts
        if direction is None: continue
        entry_bar=i+1
        if entry_bar>=len(df2)-MAX_H-2: continue
        ep=float(opens[entry_bar])
        tp_p=ep+atr*TP_ATR if direction=='long' else ep-atr*TP_ATR
        sl_p=ep-atr*SL_ATR if direction=='long' else ep+atr*SL_ATR
        et='time'; exit_bar=min(entry_bar+MAX_H, len(df2)-1)
        for j in range(entry_bar+1, min(entry_bar+MAX_H+1, len(df2))):
            h=highs[j]; l=lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break
        in_trade=True; trade_end=exit_bar
        size=B22_CORE if slack>=1.4 else B22_EXP
        pnl=TP_PCT*size if et=='tp' else -SL_PCT*size if et=='sl' else 0.05*size
        trades_raw.append({'pnl': pnl, 'exit_type': et, 'size': size})
    return trades_raw

# ─────────────────────────────────────────────
# B23 — static exits via ATR-fraction thresholds + ZigZag gate
# ─────────────────────────────────────────────
def run_b23_month(df, sym):
    if df is None or len(df) < 200: return []
    params   = B23_PARAMS.get(sym, B23_DEF)
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']; sr_dist = params['sr_dist']
    df2 = df.copy().reset_index(drop=True)
    atr_s = b23_atr(df2)
    df2['atr']    = atr_s
    df2['vol_sma']= df2['volume'].rolling(B23_VOL_LEN).mean()
    df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
    df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
    cluster_prices, _ = b23_clusters(df2, atr_s, vol_mult)

    opens=df2['open'].values; highs=df2['high'].values
    lows=df2['low'].values; closes=df2['close'].values; atrs=df2['atr'].values
    zz_trend, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag(highs, lows, opens, closes)

    F=B23_FRAC; MAX_H=B23_MAX_H; warmup=B23_VOL_LEN+B23_ATR_LEN+F
    ZZ_PROX = 30
    in_trade=False; trade_end=0; trades=[]

    for i in range(warmup, len(df2)-F-MAX_H-3):
        if in_trade and i<=trade_end: continue
        atr=atrs[i]
        if np.isnan(atr) or atr==0: continue
        if df2.iloc[i]['rvol']<80: continue
        if not df2.iloc[i]['hi_vol']: continue
        if b23_sr(closes[i], cluster_prices, atr) > sr_dist: continue

        lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
        ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
        fp=(highs[i]>lh.max()) and (highs[i]>rh.max())
        ft=(lows[i]<ll.min())  and (lows[i]<rl.min())
        ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
        ar=closes[i]<highs[i]-atr*atr_mult; ab=closes[i]>lows[i]+atr*atr_mult

        zzt = zz_trend[i]
        direction=None; slack=0.0
        if fp and ar and zzt=='up'   and abs(i-int(zz_high_bar[i]))<=ZZ_PROX:
            direction='short'; slack=ps
        elif ft and ab and zzt=='down' and abs(i-int(zz_low_bar[i]))<=ZZ_PROX:
            direction='long'; slack=ts
        if direction is None: continue

        entry_bar=i+1
        if entry_bar>=len(df2)-MAX_H-2: continue
        ep=float(opens[entry_bar])
        tp_p=ep+atr*TP_ATR if direction=='long' else ep-atr*TP_ATR
        sl_p=ep-atr*SL_ATR if direction=='long' else ep+atr*SL_ATR

        et='time'; exit_bar=min(entry_bar+MAX_H, len(df2)-1)
        for j in range(entry_bar+1, min(entry_bar+MAX_H+1, len(df2))):
            h=highs[j]; l=lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break

        in_trade=True; trade_end=exit_bar
        size=B23_CORE if slack>=1.4 else B23_EXP
        pnl=TP_PCT*size if et=='tp' else -SL_PCT*size if et=='sl' else 0.05*size
        trades.append({'pnl': pnl, 'exit_type': et, 'size': size})
    return trades

# ─────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────
def stats(arr):
    if not arr: return dict(n=0,wr=0,ev=0,pf=0,total=0)
    p=np.array(arr); pos=p[p>0]; neg=p[p<0]
    return dict(n=len(p), wr=round(len(pos)/len(p)*100,1),
                ev=round(float(np.mean(p)),2),
                pf=round(float(sum(pos)/max(abs(sum(neg)),0.01)),2),
                total=round(float(sum(p)),0))

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
creds = get_alpaca_credentials()

results = {s: {mo: [] for mo in MONTHS} for s in ['b21','b22','b23']}

for mo_idx, mo in enumerate(MONTHS):
    start, end = MONTH_DATES[mo]
    print(f'\n-- {mo} 2025 ({start} to {end}) --')
    for sym in SYMS:
        print(f'  {sym}...', end=' ', flush=True)
        try:
            df = fetch_bars(sym, start, end,
                            api_key=creds['api_key'], secret_key=creds['secret_key'])
        except Exception as e:
            print(f'FETCH ERROR: {e}'); continue
        if df is None or len(df) < 300:
            print('skip'); continue
        print(f'{len(df)} bars', end=' | ', flush=True)

        t21 = run_b21_month(df, sym)
        t22 = run_b22_month(df, sym)
        t23 = run_b23_month(df, sym)
        results['b21'][mo] += [t['pnl'] for t in t21]
        results['b22'][mo] += [t['pnl'] for t in t22]
        results['b23'][mo] += [t['pnl'] for t in t23]
        print(f'B21={len(t21)} B22={len(t22)} B23={len(t23)}')

# ─────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────
W = 80
print('\n' + '='*W)
print(f"  BOOF 21 / 22 / 23 — FULL YEAR 2025  (+{int(TP_PCT*100)}% TP / -{int(SL_PCT*100)}% SL)")
print(f"  Symbols: {', '.join(SYMS)}")
print('='*W)

# Monthly breakdown + running total
hdr = f"  {'Month':<6}  {'B21 P&L':>10}  {'B22 P&L':>10}  {'B23 P&L':>10}  {'B21 Run':>10}  {'B22 Run':>10}  {'B23 Run':>10}  {'T/d B21':>7}  {'T/d B22':>7}  {'T/d B23':>7}"
print(hdr)
print('  ' + '-'*(W-2))

run = {'b21':0,'b22':0,'b23':0}
all_pnl = {'b21':[],'b22':[],'b23':[]}

for mo, days in zip(MONTHS, MDAYS):
    for s in ['b21','b22','b23']:
        p = results[s][mo]
        all_pnl[s] += p
        run[s]     += sum(p)
    n21=len(results['b21'][mo]); n22=len(results['b22'][mo]); n23=len(results['b23'][mo])
    tpd21=round(n21/days,1); tpd22=round(n22/days,1); tpd23=round(n23/days,1)
    mo21=sum(results['b21'][mo]); mo22=sum(results['b22'][mo]); mo23=sum(results['b23'][mo])
    print(f"  {mo:<6}  ${mo21:>9,.0f}  ${mo22:>9,.0f}  ${mo23:>9,.0f}  "
          f"${run['b21']:>9,.0f}  ${run['b22']:>9,.0f}  ${run['b23']:>9,.0f}  "
          f"{tpd21:>7.1f}  {tpd22:>7.1f}  {tpd23:>7.1f}")

print('  ' + '='*(W-2))

# Summary stats
print(f"\n{'':=<{W}}")
print(f"  ANNUAL SUMMARY  (+{int(TP_PCT*100)}% / -{int(SL_PCT*100)}%)")
print(f"{'':=<{W}}")
print(f"  {'Metric':<22}  {'Boof 21':>14}  {'Boof 22':>14}  {'Boof 23':>14}")
print(f"  {'-'*22}  {'-'*14}  {'-'*14}  {'-'*14}")

for s,label in [('b21','Boof 21'),('b22','Boof 22'),('b23','Boof 23')]:
    st = stats(all_pnl[s])
    tpd = round(st['n'] / TOTAL_DAYS, 1)
    print(f"\n  {label}")
    print(f"  {'Total Trades':<22}  {st['n']:>14,}")
    print(f"  {'Avg Trades/Day':<22}  {tpd:>14.1f}")
    print(f"  {'Win Rate':<22}  {st['wr']:>13.1f}%")
    print(f"  {'EV / Trade':<22}  ${st['ev']:>13.2f}")
    print(f"  {'Profit Factor':<22}  {st['pf']:>14.2f}")
    print(f"  {'Total 2025 P&L':<22}  ${st['total']:>13,.0f}")
    red = sum(1 for mo in MONTHS if sum(results[s][mo]) < 0)
    print(f"  {'Red Months':<22}  {red:>14}")

# Side-by-side annual
print(f"\n{'':=<{W}}")
print(f"  SIDE-BY-SIDE ANNUAL")
print(f"{'':=<{W}}")
for s,label in [('b21','Boof 21 $250/trade'),('b22','Boof 22 core$600/exp$200'),('b23','Boof 23 core$500/exp$200')]:
    st=stats(all_pnl[s]); tpd=round(st['n']/TOTAL_DAYS,1)
    print(f"  {label:<32}  N={st['n']:>5,}  T/d={tpd:>5.1f}  WR={st['wr']:>5.1f}%  EV=${st['ev']:>7.2f}  PF={st['pf']:>5.2f}  P&L=${st['total']:>10,.0f}")
print('='*W)
