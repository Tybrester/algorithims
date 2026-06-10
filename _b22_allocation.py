"""
Boof 22 — Capital Allocation Test
Strategy: instead of $200 flat per trade, allocate differently to Core vs Expanded

Core    = slack >= 1.4 (high-convexity, fewer signals, larger size)
Expanded = 0.6–1.4 (more signals, smaller base size)

Tests various splits of total daily capital:
  e.g. $X per expanded trade, $Y per core trade
  keeping total expected daily deployment similar

Also tests: fixed budget per day split by ratio
"""
import pickle, sys, numpy as np, pandas as pd, random
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

random.seed(42); np.random.seed(42)
TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; F=FRACTAL_BARS
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
MOS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

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
            if not fp and not ft: continue
            peak_slack=(highs[i]-closes[i])/atr
            trough_slack=(closes[i]-lows[i])/atr
            for direction,is_valid,slack in [('short',fp,peak_slack),('long',ft,trough_slack)]:
                if not is_valid: continue
                if i+1>=len(df)-MAX_HOLD-2: continue
                ep=float(df.iloc[i+1]['open'])
                s=i+2; e=min(s+MAX_HOLD+2,len(df))
                candidates.append({'slack':slack,'ep':ep,'atr':atr,'d':direction,
                                   'highs':highs[s:e],'lows':lows[s:e],'closes':closes[s:e]})

core     = [c for c in candidates if c['slack']>=1.4]
expanded = [c for c in candidates if 0.6<=c['slack']<1.4]
print(f'  Core: {len(core):,}   Expanded: {len(expanded):,}   Total: {len(core)+len(expanded):,}\n')

TRADING_DAYS = 252  # full year

def sim_group(cands, trade_size):
    pnls=[]
    for c in cands:
        ep=c['ep']; atr=c['atr']; d=c['d']
        h=c['highs']; l=c['lows']; cl=c['closes']
        if len(cl)==0: continue
        tp_p=ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP
        sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
        et='time'
        for i in range(min(MAX_HOLD,len(cl))):
            hi=h[i]; lo=l[i]
            if d=='long':
                if hi>=tp_p: et='tp'; break
                if lo<=sl_p: et='sl'; break
            else:
                if lo<=tp_p: et='tp'; break
                if hi>=sl_p: et='sl'; break
        pnl=(trade_size*(atr*ATR_TP/ep) if et=='tp'
             else -trade_size*(atr*ATR_SL/ep) if et=='sl'
             else trade_size*TM)
        pnls.append(pnl)
    return np.array(pnls)

def stats(arr, n_trades, label=''):
    if len(arr)==0: return
    w=arr[arr>0]; l=arr[arr<0]
    wr=round(len(w)/len(arr)*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(arr)),2)
    annual=round(float(sum(arr)),0)
    monthly=round(annual/12,0)
    cum=np.cumsum(arr); dd=round(float((np.maximum.accumulate(cum)-cum).max()),2)
    tpd=round(n_trades/TRADING_DAYS,1)
    return wr,pf,ev,annual,monthly,dd,tpd

# ── Baseline: flat $200 everything ────────────────────────────────
base_c = sim_group(core,     200)
base_e = sim_group(expanded, 200)
base_all = np.concatenate([base_c, base_e])
n_all = len(base_all)
bwr,bpf,bev,bann,bmo,bdd,btpd = stats(base_all, n_all)

print(f'{"═"*80}')
print(f'ALLOCATION TEST — Core vs Expanded trade sizing')
print(f'Full year 2025 | {len(core):,} core + {len(expanded):,} expanded = {n_all:,} total trades')
print(f'{"═"*80}')
print(f'\nBASELINE: $200 flat for ALL trades')
print(f'  WR={bwr}%  PF={bpf}  EV=${bev}  Annual=${bann:,.0f}  Monthly=${bmo:,.0f}  MaxDD=${bdd}')

# Per-trade EV for each group at $200
ev_core_200 = float(np.mean(base_c))
ev_exp_200  = float(np.mean(base_e))
print(f'  Core EV@$200:    ${ev_core_200:.2f}  ({len(core):,} trades)')
print(f'  Expanded EV@$200:${ev_exp_200:.2f}  ({len(expanded):,} trades)')

# ── Allocation grid ────────────────────────────────────────────────
# Concept: total budget is N * $200 per day (same as flat baseline)
# Split between core and expanded by ratio
# Core gets more per trade (high-convexity boost), expanded gets less

print(f'\n{"─"*80}')
print(f'ALLOCATION SPLITS — same total capital deployed as $200 flat baseline')
print(f'(total capital = {n_all} trades × $200 = ${n_all*200:,})')
print(f'{"─"*80}')

# Calculate average daily counts
avg_core_day   = len(core)   / TRADING_DAYS
avg_exp_day    = len(expanded) / TRADING_DAYS
total_cap_day  = n_all / TRADING_DAYS * 200  # daily capital budget

print(f'\n  Avg core trades/day:     {avg_core_day:.1f}')
print(f'  Avg expanded trades/day: {avg_exp_day:.1f}')
print(f'  Total daily budget:      ${total_cap_day:.0f}')

print(f'\n  {"Alloc":<22}{"Core$":>8}{"Exp$":>8}{"WR%":>7}{"PF":>7}{"EV$":>8}{"Annual$":>12}{"Monthly$":>10}{"MaxDD$":>9}{"vs base":>10}')
print(f'  {"-"*96}')

results=[]

# Test allocations: (core_pct_of_budget, expanded_pct_of_budget)
# These percentages go to EACH trade in that group (not total group)
allocs = [
    # label,                    core_size, exp_size
    ('Flat $200 (baseline)',     200,       200),
    ('Core 2x / Exp 1x',        400,       200),
    ('Core 3x / Exp 1x',        600,       200),
    ('Core 2x / Exp 0.75x',     400,       150),
    ('Core 2x / Exp 0.5x',      400,       100),
    ('Core 3x / Exp 0.75x',     600,       150),
    ('Core 3x / Exp 0.5x',      600,       100),
    ('Core 4x / Exp 0.5x',      800,       100),
    ('Core 1.5x / Exp 0.85x',   300,       170),
    ('Core 2x / Exp 0.85x',     400,       170),
    # Budget-neutral splits (total = same as baseline)
    # total = core_n*core_$ + exp_n*exp_$ ≈ n_all*200
]

# Also test budget-neutral versions (solve for exp_size given core_size and budget)
total_budget = n_all * 200
for core_mult in [1.5, 2.0, 2.5, 3.0, 4.0]:
    core_s = int(200 * core_mult)
    exp_s = round((total_budget - len(core)*core_s) / len(expanded))
    if exp_s < 50: continue
    allocs.append((f'BudgetNeutral Core×{core_mult}', core_s, exp_s))

for label, core_size, exp_size in allocs:
    ca = sim_group(core,     core_size)
    ea = sim_group(expanded, exp_size)
    combined = np.concatenate([ca, ea])
    r = stats(combined, len(combined))
    if not r: continue
    wr,pf,ev,ann,mo,dd,tpd = r
    delta = ann - bann
    sign = '+' if delta >= 0 else ''
    results.append((label, core_size, exp_size, wr, pf, ev, ann, mo, dd, delta))
    marker = ' ← baseline' if label.startswith('Flat') else ''
    print(f'  {label:<28}{core_size:>6}  {exp_size:>6}{wr:>7}{pf:>7}{ev:>8}  ${ann:>10,.0f}  ${mo:>8,.0f}  ${dd:>7}  {sign}${delta:,.0f}{marker}')

print(f'\n{"─"*80}')
print('TOP 5 BY ANNUAL P&L:')
for r in sorted(results, key=lambda x:-x[6])[:5]:
    print(f'  [{r[0]}] Core=${r[1]} Exp=${r[2]}  WR={r[3]}%  PF={r[4]}  EV=${r[5]}  Annual=${r[6]:,.0f}  Monthly=${r[7]:,.0f}  delta={"+" if r[9]>=0 else ""}${r[9]:,.0f}')

# ── Section 2: Pure ratio — 70/30 capital allocation ──────────────
print(f'\n{"═"*80}')
print(f'SECTION 2 — Fixed monthly budget split by ratio (e.g. $10k/mo total)')
print(f'{"═"*80}')
MONTHLY_BUDGET = 10000

# Simulate: allocate X% to expanded group, (1-X)% to core
# Per-trade size = group_budget / avg_trades_in_group_per_month
avg_core_mo   = len(core)   / 12
avg_exp_mo    = len(expanded) / 12

print(f'  Monthly budget: ${MONTHLY_BUDGET:,}')
print(f'  Avg core trades/mo: {avg_core_mo:.0f}   Avg expanded trades/mo: {avg_exp_mo:.0f}')
print(f'\n  {"Exp%/Core%":<16}{"Core$/trade":>14}{"Exp$/trade":>13}{"WR%":>7}{"PF":>7}{"EV$":>8}{"Annual$":>12}{"Monthly$":>10}')
print(f'  {"-"*80}')

for exp_pct in [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    core_pct = 1 - exp_pct
    core_budget_mo = MONTHLY_BUDGET * core_pct
    exp_budget_mo  = MONTHLY_BUDGET * exp_pct
    core_trade_size = round(core_budget_mo / avg_core_mo)
    exp_trade_size  = round(exp_budget_mo  / avg_exp_mo)
    ca = sim_group(core,     core_trade_size)
    ea = sim_group(expanded, exp_trade_size)
    combined = np.concatenate([ca, ea])
    r = stats(combined, len(combined))
    if not r: continue
    wr,pf,ev,ann,mo,dd,_ = r
    print(f'  {int(exp_pct*100)}% exp/{int(core_pct*100)}% core   ${core_trade_size:>10}  ${exp_trade_size:>10}{wr:>7}{pf:>7}{ev:>8}  ${ann:>10,.0f}  ${mo:>8,.0f}')
