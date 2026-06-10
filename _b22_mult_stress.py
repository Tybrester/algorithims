"""
Boof 22 — ATR mult 0.6 vs 1.4 stress test
1. 4-level slippage stress for both mults
2. EV degradation curve across slippage levels
3. Marginal trade quality test: core (>=1.4) vs expanded (0.6-1.4)
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

# ── Collect all candidates with their slack ratio ──────────────────
print('Pre-computing all candidates (one pass)...')
candidates = []  # {slack, ep, atr, d, highs, lows, closes}

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
                    'highs': highs[s:e], 'lows': lows[s:e], 'closes': closes[s:e]
                })

print(f'Total raw candidates: {len(candidates):,}')
slacks = np.array([c['slack'] for c in candidates])

# ── Simulation engine with slippage ───────────────────────────────
def dyn_spread(atr, price, sp_min=0.0005, sp_max=0.002):
    ratio = min(atr/price, 0.01)/0.01
    return sp_min + (sp_max - sp_min) * ratio

SLIPPAGE_LEVELS = [
    # (label, spread_mult, delay_prob, miss_prob, intrabar_coinflip)
    ('L0 Baseline',    0.0,  0.00, 0.00, False),
    ('L1 Light',       1.0,  0.10, 0.00, False),
    ('L2 Realistic',   1.0,  0.30, 0.03, False),
    ('L3 Bad',         1.5,  0.40, 0.05, True),
    ('L4 Extreme',     2.0,  0.50, 0.10, True),
]

def sim(cands, spread_mult, delay_prob, miss_prob, intrabar):
    pnls = []
    for c in cands:
        ep_raw=c['ep']; atr=c['atr']; d=c['d']
        h=c['highs']; l=c['lows']; cl=c['closes']
        if len(cl)==0: continue

        spread = dyn_spread(atr, ep_raw) * spread_mult

        # Miss — forced time exit at cost of spread
        if miss_prob > 0 and random.random() < miss_prob:
            pnls.append(TRADE * TM - ep_raw * spread * TRADE / ep_raw)
            continue

        # Delay
        start = 0
        if delay_prob > 0 and random.random() < delay_prob:
            start = 1

        ep = ep_raw * (1 + spread) if d=='long' else ep_raw * (1 - spread)
        tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL

        et='time'; exit_px=cl[-1]
        for i in range(start, min(MAX_HOLD, len(cl))):
            hi=h[i]; lo=l[i]
            tp_hit=(d=='long' and hi>=tp_p) or (d=='short' and lo<=tp_p)
            sl_hit=(d=='long' and lo<=sl_p) or (d=='short' and hi>=sl_p)
            if tp_hit and sl_hit and intrabar:
                if random.random()<0.5: sl_hit=False
                else: tp_hit=False
            if tp_hit:
                et='tp'; exit_px=tp_p*(1-spread) if d=='long' else tp_p*(1+spread); break
            if sl_hit:
                et='sl'; exit_px=sl_p*(1-spread) if d=='long' else sl_p*(1+spread); break

        if et=='tp':   pnl=TRADE*abs(exit_px-ep)/ep
        elif et=='sl': pnl=-TRADE*abs(exit_px-ep)/ep
        else:          pnl=TRADE*TM - ep_raw*spread*TRADE/ep_raw
        pnls.append(pnl)
    return np.array(pnls)

def stats(arr):
    if len(arr)==0: return 0,0,0,0,0
    n=len(arr); w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),4)
    ann=round(float(sum(arr)),2)
    cum=np.cumsum(arr); dd=round(float((np.maximum.accumulate(cum)-cum).max()),2)
    return wr,pf,ev,ann,dd

# ── Split by mult threshold ────────────────────────────────────────
MULT_A = 1.4   # core (current)
MULT_B = 0.6   # expanded

core_cands     = [c for c in candidates if c['slack'] >= MULT_A]
expanded_cands = [c for c in candidates if MULT_B <= c['slack'] < MULT_A]
all_cands_06   = [c for c in candidates if c['slack'] >= MULT_B]

print(f'  Core (slack ≥ 1.4):     {len(core_cands):,} signals')
print(f'  Expanded (0.6–1.4):     {len(expanded_cands):,} signals')
print(f'  All at mult=0.6:        {len(all_cands_06):,} signals\n')

# ══════════════════════════════════════════════════════════════════
# PART 1 — 4-level slippage stress: mult=1.4 vs mult=0.6
# ══════════════════════════════════════════════════════════════════
print(f'{"═"*78}')
print(f'PART 1 — 4-Level Slippage Stress Test: mult=1.4 vs mult=0.6')
print(f'{"═"*78}')
print(f'{"Level":<18}{"":>3}{"WR%":>6}{"PF":>7}{"EV$":>8}{"Annual$":>11}{"MaxDD$":>9}')
print(f'{"-"*78}')

ev_table = {'1.4': [], '0.6': []}

for label, smult, dprob, mprob, ib in SLIPPAGE_LEVELS:
    r14 = stats(sim(core_cands,   smult, dprob, mprob, ib))
    r06 = stats(sim(all_cands_06, smult, dprob, mprob, ib))
    ev_table['1.4'].append(r14[2])
    ev_table['0.6'].append(r06[2])
    print(f'\n{label}')
    print(f'  mult=1.4  WR={r14[0]}%  PF={r14[1]}  EV=${r14[2]}  Annual=${r14[3]:,.0f}  MaxDD=${r14[4]:,.0f}')
    print(f'  mult=0.6  WR={r06[0]}%  PF={r06[1]}  EV=${r06[2]}  Annual=${r06[3]:,.0f}  MaxDD=${r06[4]:,.0f}')

# ══════════════════════════════════════════════════════════════════
# PART 2 — EV degradation curve
# ══════════════════════════════════════════════════════════════════
print(f'\n{"═"*78}')
print(f'PART 2 — EV Degradation Curve (does 0.6 degrade faster?)')
print(f'{"═"*78}')
print(f'{"Level":<18}{"EV@1.4":>10}{"EV@0.6":>10}{"Δ1.4 from base":>16}{"Δ0.6 from base":>16}{"Faster?":>10}')
print(f'{"-"*78}')

base_14 = ev_table['1.4'][0]
base_06 = ev_table['0.6'][0]
level_labels = [x[0] for x in SLIPPAGE_LEVELS]

for i, lbl in enumerate(level_labels):
    e14 = ev_table['1.4'][i]; e06 = ev_table['0.6'][i]
    d14 = round(e14 - base_14, 4)
    d06 = round(e06 - base_06, 4)
    pct14 = round((d14/abs(base_14))*100, 1) if base_14 != 0 else 0
    pct06 = round((d06/abs(base_06))*100, 1) if base_06 != 0 else 0
    faster = '0.6 degrades faster' if pct06 < pct14 else ('same' if pct06==pct14 else '1.4 degrades faster')
    print(f'{lbl:<18}{e14:>10}{e06:>10}{pct14:>+15.1f}%{pct06:>+15.1f}%  {faster}')

# ══════════════════════════════════════════════════════════════════
# PART 3 — Marginal trade quality test
# ══════════════════════════════════════════════════════════════════
print(f'\n{"═"*78}')
print(f'PART 3 — Marginal Trade Quality Test')
print(f'{"═"*78}')
print(f'Core = signals with slack ≥ 1.4 (strong wick rejection)')
print(f'Expanded = signals with slack 0.6–1.4 (weaker wick rejection)')
print(f'{"-"*78}')

for lbl, cands_set in [('CORE (slack≥1.4)', core_cands), ('EXPANDED (0.6–1.4)', expanded_cands)]:
    print(f'\n  {lbl}  [{len(cands_set):,} signals]')
    for label, smult, dprob, mprob, ib in SLIPPAGE_LEVELS:
        r = stats(sim(cands_set, smult, dprob, mprob, ib))
        print(f'    {label:<18} WR={r[0]}%  PF={r[1]}  EV=${r[2]}  Annual=${r[3]:,.0f}  MaxDD=${r[4]:,.0f}')

# Slippage sensitivity: how much does EV drop per level?
print(f'\n  SLIPPAGE SENSITIVITY (EV drop per level):')
for lbl, cands_set in [('CORE', core_cands), ('EXPANDED', expanded_cands)]:
    evs = [stats(sim(cands_set, sm, dp, mp, ib))[2] for _,sm,dp,mp,ib in SLIPPAGE_LEVELS]
    drops = [round(evs[i]-evs[0],4) for i in range(len(evs))]
    print(f'    {lbl}: baseline=${evs[0]}  L1={drops[1]:+}  L2={drops[2]:+}  L3={drops[3]:+}  L4={drops[4]:+}')

# Win rate breakdown by group
print(f'\n  WIN RATE (baseline, no slippage):')
for lbl, cands_set in [('CORE', core_cands), ('EXPANDED', expanded_cands), ('ALL@0.6', all_cands_06)]:
    r = stats(sim(cands_set, 0, 0, 0, False))
    print(f'    {lbl:<20} WR={r[0]}%  PF={r[1]}  EV=${r[2]}  n={len(cands_set):,}')
