"""
Boof 22 — Core vs Expanded signal deep comparison
Core    = slack >= 1.4 (pass old threshold — existed before change)
Expanded = 0.6 <= slack < 1.4 (only exist after lowering threshold)

Per group: EV, WR, PF, slippage sensitivity across 5 levels
Also: per-symbol breakdown, exit type distribution, avg hold time
"""
import pickle, sys, numpy as np, pandas as pd, random
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

random.seed(42); np.random.seed(42)
TRADE=200; TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; F=FRACTAL_BARS
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MOS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

# ── Collect all candidates with full metadata ──────────────────────
print('Pre-computing signals...')
candidates = []

for mo in MOS:
    for sym in SYMS:
        df = dfs.get((sym, mo))
        if df is None or len(df) < 100: continue
        df = df.copy().reset_index(drop=True)
        atr_s = compute_atr(df); df['atr'] = atr_s
        df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
        df['rvol'] = (df['volume'] / df['vol_sma'] * 100).fillna(0)
        df['hi_vol'] = df['volume'] > df['vol_sma'] * 1.3
        cp, _ = build_cluster_array(df, atr_s, 1.3)
        highs = df['high'].values; lows = df['low'].values; closes = df['close'].values

        for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - MAX_HOLD - 3):
            row = df.iloc[i]
            if row['rvol'] < 80: continue
            atr = row['atr']
            if pd.isna(atr) or atr == 0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'], cp, atr) > SR_DIST_MAX: continue

            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min()) and(lows[i]<rl.min())
            if not fp and not ft: continue

            peak_slack   = (highs[i] - closes[i]) / atr
            trough_slack = (closes[i] - lows[i])  / atr

            for direction, is_valid, slack in [('short',fp,peak_slack),('long',ft,trough_slack)]:
                if not is_valid: continue
                if i+1 >= len(df)-MAX_HOLD-2: continue
                ep = float(df.iloc[i+1]['open'])
                s = i+2; e = min(s+MAX_HOLD+2, len(df))
                candidates.append({
                    'slack': slack, 'ep': ep, 'atr': atr, 'd': direction,
                    'highs': highs[s:e], 'lows': lows[s:e], 'closes': closes[s:e],
                    'sym': sym, 'mo': mo, 'rvol': float(row['rvol']),
                    'atr_pct': atr/ep*100
                })

slacks = np.array([c['slack'] for c in candidates])
core     = [c for c in candidates if c['slack'] >= 1.4]
expanded = [c for c in candidates if 0.6 <= c['slack'] < 1.4]
print(f'  Core    (slack ≥ 1.4): {len(core):,}')
print(f'  Expanded (0.6–1.4):   {len(expanded):,}')
print(f'  Total at 0.6:          {len(core)+len(expanded):,}\n')

# ── Slippage sim ───────────────────────────────────────────────────
def dyn_spread(atr, price, mn=0.0005, mx=0.002):
    return mn + (mx-mn) * min(atr/price, 0.01)/0.01

def sim(cands, spread_mult=0.0, delay_prob=0.0, miss_prob=0.0, intrabar=False):
    pnls=[]; exit_types={'tp':0,'sl':0,'time':0}; holds=[]
    for c in cands:
        ep_raw=c['ep']; atr=c['atr']; d=c['d']
        h=c['highs']; l=c['lows']; cl=c['closes']
        if len(cl)==0: continue
        spread = dyn_spread(atr, ep_raw) * spread_mult
        if miss_prob>0 and random.random()<miss_prob:
            pnls.append(TRADE*TM - ep_raw*spread*TRADE/ep_raw)
            exit_types['time']+=1; holds.append(MAX_HOLD); continue
        start=1 if delay_prob>0 and random.random()<delay_prob else 0
        ep = ep_raw*(1+spread) if d=='long' else ep_raw*(1-spread)
        tp_p=ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP
        sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        et='time'; exit_px=cl[-1]; hold=MAX_HOLD
        for i in range(start, min(MAX_HOLD,len(cl))):
            hi=h[i]; lo=l[i]
            tp_hit=(d=='long' and hi>=tp_p)or(d=='short' and lo<=tp_p)
            sl_hit=(d=='long' and lo<=sl_p)or(d=='short' and hi>=sl_p)
            if tp_hit and sl_hit and intrabar:
                if random.random()<0.5: sl_hit=False
                else: tp_hit=False
            if tp_hit:
                et='tp'; exit_px=tp_p*(1-spread) if d=='long' else tp_p*(1+spread); hold=i+1; break
            if sl_hit:
                et='sl'; exit_px=sl_p*(1-spread) if d=='long' else sl_p*(1+spread); hold=i+1; break
        if et=='tp':   pnl=TRADE*abs(exit_px-ep)/ep
        elif et=='sl': pnl=-TRADE*abs(exit_px-ep)/ep
        else:          pnl=TRADE*TM-ep_raw*spread*TRADE/ep_raw
        pnls.append(pnl); exit_types[et]+=1; holds.append(hold)
    return np.array(pnls), exit_types, np.mean(holds) if holds else 0

LEVELS = [
    ('L0 Baseline',  0.0, 0.00, 0.00, False),
    ('L1 Light',     1.0, 0.10, 0.00, False),
    ('L2 Realistic', 1.0, 0.30, 0.03, False),
    ('L3 Bad',       1.5, 0.40, 0.05, True),
    ('L4 Extreme',   2.0, 0.50, 0.10, True),
]

def stats(arr):
    if len(arr)==0: return 0,0,0,0,0
    n=len(arr); w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),4)
    ann=round(float(sum(arr)),0)
    cum=np.cumsum(arr); dd=round(float((np.maximum.accumulate(cum)-cum).max()),0)
    return wr,pf,ev,ann,dd

# ══════════════════════════════════════════════════════════════════
# SECTION 1 — Slippage table per group
# ══════════════════════════════════════════════════════════════════
print('='*80)
print('SECTION 1 — Core vs Expanded: Performance at each slippage level')
print('='*80)

core_evs=[]; exp_evs=[]

for label,sm,dp,mp,ib in LEVELS:
    ca, cet, ch = sim(core,     sm, dp, mp, ib)
    ea, eet, eh = sim(expanded, sm, dp, mp, ib)
    cwr,cpf,cev,cann,cdd = stats(ca)
    ewr,epf,eev,eann,edd = stats(ea)
    core_evs.append(cev); exp_evs.append(eev)

    print(f'\n  {label}')
    print(f'  {"Group":<14}{"n":>7}{"WR%":>7}{"PF":>8}{"EV$":>9}{"Annual$":>12}{"MaxDD$":>9}{"AvgHold":>9}')
    print(f'  {"-"*75}')
    print(f'  {"🟢 CORE":<14}{len(core):>7}{cwr:>7}{cpf:>8}{cev:>9}  ${cann:>9,.0f}  ${cdd:>7,.0f}{ch:>9.1f} bars')
    print(f'  {"🟡 EXPANDED":<14}{len(expanded):>7}{ewr:>7}{epf:>8}{eev:>9}  ${eann:>9,.0f}  ${edd:>7,.0f}{eh:>9.1f} bars')

# ══════════════════════════════════════════════════════════════════
# SECTION 2 — EV degradation curve
# ══════════════════════════════════════════════════════════════════
print(f'\n{"="*80}')
print(f'SECTION 2 — EV Degradation Curve')
print(f'{"="*80}')
print(f'  {"Level":<16}{"Core EV":>10}{"Exp EV":>10}{"Core Δ%":>11}{"Exp Δ%":>11}  Faster degrader?')
print(f'  {"-"*72}')
base_c=core_evs[0]; base_e=exp_evs[0]
for i,(label,*_) in enumerate(LEVELS):
    dc=round((core_evs[i]-base_c)/abs(base_c)*100,1) if base_c else 0
    de=round((exp_evs[i]-base_e)/abs(base_e)*100,1) if base_e else 0
    faster='🟢 Core degrades faster' if dc<de else ('🟡 Expanded degrades faster' if de<dc else 'Equal')
    print(f'  {label:<16}{core_evs[i]:>10}{exp_evs[i]:>10}{dc:>+10.1f}%{de:>+10.1f}%  {faster}')

# ══════════════════════════════════════════════════════════════════
# SECTION 3 — Exit type distribution
# ══════════════════════════════════════════════════════════════════
print(f'\n{"="*80}')
print(f'SECTION 3 — Exit Type Distribution (baseline, no slippage)')
print(f'{"="*80}')
for label, cands in [('🟢 CORE', core), ('🟡 EXPANDED', expanded)]:
    arr,et,h = sim(cands, 0, 0, 0, False)
    n=len(arr)
    tp_r=round(et['tp']/n*100,1); sl_r=round(et['sl']/n*100,1); tm_r=round(et['time']/n*100,1)
    print(f'  {label}  n={n:,}  TP={tp_r}%  SL={sl_r}%  Time={tm_r}%  AvgHold={h:.1f}bars')

# ══════════════════════════════════════════════════════════════════
# SECTION 4 — Per-symbol breakdown
# ══════════════════════════════════════════════════════════════════
print(f'\n{"="*80}')
print(f'SECTION 4 — Per-Symbol EV & WR (baseline, core vs expanded)')
print(f'{"="*80}')
print(f'  {"Symbol":<8}{"Core n":>8}{"Core WR":>9}{"Core EV":>9}{"Exp n":>8}{"Exp WR":>9}{"Exp EV":>9}{"Delta EV":>10}')
print(f'  {"-"*75}')
for sym in SYMS:
    c_sym=[x for x in core     if x['sym']==sym]
    e_sym=[x for x in expanded if x['sym']==sym]
    ca,_,_ = sim(c_sym,0,0,0,False) if c_sym else (np.array([]),{},0)
    ea,_,_ = sim(e_sym,0,0,0,False) if e_sym else (np.array([]),{},0)
    cwr_s=round(len(ca[ca>0])/len(ca)*100,1) if len(ca)>0 else 0
    ewr_s=round(len(ea[ea>0])/len(ea)*100,1) if len(ea)>0 else 0
    cev_s=round(float(np.mean(ca)),2) if len(ca)>0 else 0
    eev_s=round(float(np.mean(ea)),2) if len(ea)>0 else 0
    delta=round(eev_s-cev_s,2)
    arrow='↑' if delta>=0 else '↓'
    print(f'  {sym:<8}{len(c_sym):>8}{cwr_s:>9}{cev_s:>9}  {len(e_sym):>6}{ewr_s:>9}{eev_s:>9}  {arrow}{abs(delta):>8}')

# ══════════════════════════════════════════════════════════════════
# SECTION 5 — Slack bucket quality heatmap
# ══════════════════════════════════════════════════════════════════
print(f'\n{"="*80}')
print(f'SECTION 5 — Signal quality by slack bucket (baseline)')
print(f'{"="*80}')
print(f'  {"Slack bucket":<18}{"n":>7}{"WR%":>7}{"PF":>8}{"EV$":>9}{"Annual$":>12}')
print(f'  {"-"*65}')
buckets = [(0.6,0.8),(0.8,1.0),(1.0,1.2),(1.2,1.4),(1.4,1.6),(1.6,1.8),(1.8,2.0),(2.0,99)]
for lo,hi in buckets:
    grp=[c for c in candidates if lo<=c['slack']<hi]
    if not grp: continue
    arr,_,_ = sim(grp,0,0,0,False)
    wr_b=round(len(arr[arr>0])/len(arr)*100,1)
    pf_b=round(float(sum(arr[arr>0])/max(abs(sum(arr[arr<0])),0.01)),2)
    ev_b=round(float(np.mean(arr)),4)
    an_b=round(float(sum(arr)),0)
    tag='[CORE]' if lo>=1.4 else '[EXPANDED]'
    print(f'  {lo:.1f}–{hi if hi<99 else "∞":<12}  {tag:<12}{len(grp):>5}{wr_b:>7}{pf_b:>8}{ev_b:>9}  ${an_b:>9,.0f}')

# ══════════════════════════════════════════════════════════════════
# FINAL VERDICT
# ══════════════════════════════════════════════════════════════════
print(f'\n{"="*80}')
print(f'FINAL VERDICT')
print(f'{"="*80}')
ca_b,_,_ = sim(core,    0,0,0,False)
ea_b,_,_ = sim(expanded,0,0,0,False)
ca_4,_,_ = sim(core,    2.0,0.50,0.10,True)
ea_4,_,_ = sim(expanded,2.0,0.50,0.10,True)

ev_drop_core = round((np.mean(ca_4)-np.mean(ca_b))/abs(np.mean(ca_b))*100,1)
ev_drop_exp  = round((np.mean(ea_4)-np.mean(ea_b))/abs(np.mean(ea_b))*100,1)

print(f'  Core EV drop baseline→L4:     {ev_drop_core:+.1f}%')
print(f'  Expanded EV drop baseline→L4: {ev_drop_exp:+.1f}%')
print(f'  Expanded trades are {"MORE" if abs(ev_drop_exp)<abs(ev_drop_core) else "LESS"} resilient to slippage.')
print(f'  Expanded WR: {round(len(ea_b[ea_b>0])/len(ea_b)*100,1)}%  vs Core WR: {round(len(ca_b[ca_b>0])/len(ca_b)*100,1)}%')
print(f'  Verdict: {"✅ KEEP 0.6 — expanded signals are equal or better quality" if abs(ev_drop_exp)<=abs(ev_drop_core) else "⚠️  0.6 trades degrade faster — reconsider"}')
