"""
Boof 22 — Test QQQ and SPY with atr_mult=0.6, tiered sizing ($600 core / $200 expanded)
Compare vs current 5-symbol lineup
Uses 2025 cache + 2026 cache
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; F=FRACTAL_BARS; ATR_MULT=0.6
DAYS=252
MOS_25=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MOS_26=['Jan 26','Feb 26','Mar 26','Apr 26','May 26']

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl','rb'))
try:
    cache26 = pickle.load(open('_boof_2026_cache.pkl','rb'))
    has26 = True
except: has26 = False

def run_sym(sym, vol_mult=1.3):
    results = []
    for mo, cache in [(m, cache25) for m in MOS_25] + ([(m, cache26) for m in MOS_26] if has26 else []):
        df = cache.get((sym, mo))
        if df is None or len(df) < 100: continue
        df = df.copy().reset_index(drop=True)
        atr_s = compute_atr(df); df['atr'] = atr_s
        df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
        df['rvol'] = (df['volume'] / df['vol_sma'] * 100).fillna(0)
        df['hi_vol'] = df['volume'] > df['vol_sma'] * vol_mult
        cp, _ = build_cluster_array(df, atr_s, vol_mult)
        highs=df['high'].values; lows=df['low'].values; closes=df['close'].values

        for i in range(VOL_LEN+ATR_LEN+F, len(df)-F-MAX_HOLD-3):
            row=df.iloc[i]
            if row['rvol']<80: continue
            atr=row['atr']
            if pd.isna(atr) or atr==0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'],cp,atr)>SR_DIST_MAX: continue
            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min()) and(lows[i]<rl.min())
            peak_slack=(highs[i]-closes[i])/atr
            trough_slack=(closes[i]-lows[i])/atr
            for direction,is_valid,slack in [('short',fp,peak_slack),('long',ft,trough_slack)]:
                if not is_valid or slack<ATR_MULT: continue
                if i+1>=len(df)-MAX_HOLD-2: continue
                ep=float(df.iloc[i+1]['open'])
                tp_p=ep+atr*ATR_TP if direction=='long' else ep-atr*ATR_TP
                sl_p=ep-atr*ATR_SL if direction=='long' else ep+atr*ATR_SL
                size=600 if slack>=1.4 else 200
                et='time'
                for j in range(i+2,min(i+2+MAX_HOLD,len(df))):
                    h=df['high'].iloc[j]; l=df['low'].iloc[j]
                    if direction=='long':
                        if h>=tp_p: et='tp'; break
                        if l<=sl_p: et='sl'; break
                    else:
                        if l<=tp_p: et='tp'; break
                        if h>=sl_p: et='sl'; break
                pnl=(size*(atr*ATR_TP/ep) if et=='tp'
                     else -size*(atr*ATR_SL/ep) if et=='sl'
                     else size*TM)
                results.append({'pnl':pnl,'et':et,'slack':slack,'mo':mo,'direction':direction})
    return results

# ── Current 5-symbol lineup ────────────────────────────────────────
CURRENT = ['NVDA','META','AAPL','GOOGL','AMD']
CANDIDATES = ['QQQ','SPY']
ALL_SYMS = CURRENT + CANDIDATES

sym_stats = {}
for sym in ALL_SYMS:
    vm = 1.2 if sym in ('QQQ','SPY','AAPL') else 1.3
    trades = run_sym(sym, vm)
    if not trades:
        sym_stats[sym] = None; continue
    arr=np.array([t['pnl'] for t in trades])
    n=len(arr); w=arr[arr>0]; l=arr[arr<0]
    core_n=sum(1 for t in trades if t['slack']>=1.4)
    exp_n=n-core_n
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),2)
    annual=round(float(sum(arr)))
    tpd=round(n/DAYS,1)
    mo_n=len(set(t['mo'] for t in trades))
    sym_stats[sym]={'n':n,'core':core_n,'exp':exp_n,'tpd':tpd,'wr':wr,'pf':pf,'ev':ev,'annual':annual,'mo':mo_n}

print(f'\nBoof 22 | atr_mult=0.6 | Core=$600 Expanded=$200 | All symbols')
print(f'{"Sym":<7}{"Trades":>8}{"T/day":>7}{"Core":>7}{"Exp":>7}{"WR%":>7}{"PF":>7}{"EV$":>8}{"Annual$":>12}{"Months":>8}')
print(f'{"-"*73}')

print('  --- Current 5-symbol lineup ---')
curr_annual=0
for sym in CURRENT:
    s=sym_stats[sym]
    if not s: print(f'  {sym:<7} NO DATA'); continue
    curr_annual+=s['annual']
    print(f'  {sym:<7}{s["n"]:>8}{s["tpd"]:>7}{s["core"]:>7}{s["exp"]:>7}{s["wr"]:>7}{s["pf"]:>7}{s["ev"]:>8}  ${s["annual"]:>9,}  {s["mo"]:>5}mo')
print(f'  {"TOTAL":<7}{"":>8}{"":>7}{"":>7}{"":>7}{"":>7}{"":>7}{"":>8}  ${curr_annual:>9,}')

print(f'\n  --- Candidates ---')
for sym in CANDIDATES:
    s=sym_stats[sym]
    if not s: print(f'  {sym:<7} NO DATA'); continue
    delta=s['annual']
    print(f'  {sym:<7}{s["n"]:>8}{s["tpd"]:>7}{s["core"]:>7}{s["exp"]:>7}{s["wr"]:>7}{s["pf"]:>7}{s["ev"]:>8}  ${s["annual"]:>9,}  {s["mo"]:>5}mo  (+${delta:,}/yr if added)')

# ── Combo scenarios ────────────────────────────────────────────────
print(f'\n  --- Combo Scenarios ---')
scenarios = [
    ('Current 5',        CURRENT),
    ('Current + QQQ',    CURRENT+['QQQ']),
    ('Current + SPY',    CURRENT+['SPY']),
    ('Current + QQQ+SPY',CURRENT+['QQQ','SPY']),
    ('QQQ+SPY only',     ['QQQ','SPY']),
]
print(f'  {"Scenario":<26}{"Syms":>5}{"T/day":>8}{"Annual$":>12}{"Avg$/sym":>11}')
print(f'  {"-"*65}')
for label,syms in scenarios:
    valid=[s for s in syms if sym_stats.get(s)]
    ann=sum(sym_stats[s]['annual'] for s in valid)
    tpd=sum(sym_stats[s]['tpd'] for s in valid)
    avg=round(ann/len(valid)) if valid else 0
    print(f'  {label:<26}{len(valid):>5}{tpd:>8.1f}  ${ann:>10,}  ${avg:>9,}/sym')

# ── QQQ/SPY quality deep dive ─────────────────────────────────────
print(f'\n  --- QQQ & SPY Signal Quality (vs best current symbol) ---')
best_curr=max(CURRENT, key=lambda s: sym_stats[s]['annual'] if sym_stats[s] else 0)
print(f'  Best current: {best_curr} (${sym_stats[best_curr]["annual"]:,}/yr)')
for sym in CANDIDATES:
    s=sym_stats[sym]
    if not s: continue
    # Core vs expanded breakdown
    trades=run_sym(sym, 1.2)
    core_arr=np.array([t['pnl'] for t in trades if t['slack']>=1.4])
    exp_arr=np.array([t['pnl'] for t in trades if t['slack']<1.4])
    print(f'\n  {sym}:')
    for label,arr in [('Core (slack>=1.4)',core_arr),('Expanded (0.6-1.4)',exp_arr)]:
        if len(arr)==0: continue
        w=arr[arr>0]; l=arr[arr<0]
        wr_g=round(len(w)/len(arr)*100,1)
        pf_g=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
        ev_g=round(float(np.mean(arr)),2)
        print(f'    {label:<22}  n={len(arr):>5}  WR={wr_g}%  PF={pf_g}  EV=${ev_g}  Ann=${sum(arr):>10,.0f}')
