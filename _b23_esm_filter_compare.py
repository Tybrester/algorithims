"""
Boof 23 — ESM Filter Comparison Backtest
=========================================
Runs 4 configurations side-by-side on 12 months × 9 symbols:
  A) Baseline       — no filters (current live)
  B) Low-vol filter — skip ATR/price < 0.057%
  C) Mid-burst skip — skip middle entries in clusters
  D) Both filters   — A + B combined

Reports per config: trades/day, WR, EV/trade, PF, monthly P&L, annual P&L
Also: monthly breakdown so you can see if any month turns red.
"""
import pickle, sys, importlib
import numpy as np
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof23 as b23

B23_SYMS   = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','LLY']
MONTHS     = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MONTH_DAYS = [23,20,21,22,21,21,23,21,22,23,20,23]
B23_EXP    = 200; B23_CORE = 500
TOTAL_DAYS = sum(MONTH_DAYS)

print('Loading cache...')
cache = pickle.load(open('_boof22_cache.pkl','rb'))
print('  Done.\n')

CONFIGS = [
    ('A  Baseline',        False, False),
    ('B  Low-vol filter',  True,  False),
    ('C  Mid-burst skip',  False, True),
    ('D  Both filters',    True,  True),
]

def run_config(low_vol, mid_burst):
    b23.LOW_VOL_FILTER    = low_vol
    b23.SKIP_MIDDLE_BURST = mid_burst
    # Reload the module to ensure flag changes propagate
    # (flags are module-level, already mutated above — no reload needed)
    trades_by_month = defaultdict(list)
    for mo in MONTHS:
        for sym in B23_SYMS:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue
            trades = b23.run_boof23(df, symbol=sym)
            for t in trades:
                pnl = t['pnl_pct'] * (B23_CORE if t['tier']=='core' else B23_EXP)
                trades_by_month[mo].append(pnl)
    return trades_by_month

results = {}
for name, lv, mb in CONFIGS:
    print(f'  Running {name}...')
    results[name] = run_config(lv, mb)

# ── Stats helper ──────────────────────────────────────────────────
def stats(pnl_list):
    if not pnl_list: return 0, 0.0, 0.0, 0.0, 0.0
    p = np.array(pnl_list)
    pos = p[p>0]; neg = p[p<0]
    n   = len(p)
    wr  = len(pos)/n*100
    ev  = float(np.mean(p))
    pf  = float(sum(pos)/max(abs(sum(neg)),0.01))
    tot = float(sum(p))
    return n, round(wr,1), round(ev,2), round(pf,2), round(tot,0)

SEP = '=' * 82

# ── Summary table ─────────────────────────────────────────────────
print(f'\n{SEP}')
print('  CONFIGURATION COMPARISON — Annual Summary')
print(SEP)
print(f'  {"Config":<22}  {"Trades":>7}  {"T/day":>6}  {"WR":>7}  '
      f'{"EV/trade":>10}  {"PF":>7}  {"Annual":>12}  {"vs Base":>8}')
print(f'  {"-"*78}')
base_annual = None
for name, _, _ in CONFIGS:
    all_pnl = [p for mo in MONTHS for p in results[name][mo]]
    n, wr, ev, pf, tot = stats(all_pnl)
    annual = tot * 2
    tpd    = n / TOTAL_DAYS
    vs     = f'{(annual-base_annual)/base_annual*100:+.1f}%' if base_annual else 'base'
    if base_annual is None: base_annual = annual
    print(f'  {name:<22}  {n:>7}  {tpd:>6.1f}  {wr:>6.1f}%  '
          f'${ev:>9.2f}  {pf:>7.2f}  ${annual:>11,.0f}  {vs:>8}')

# ── Monthly breakdown ─────────────────────────────────────────────
print(f'\n{SEP}')
print('  MONTHLY P&L BREAKDOWN')
print(SEP)

header = f'  {"Month":<8}'
for name, _, _ in CONFIGS:
    short = name.split()[0]
    header += f'  {short:>11}'
print(header)
print(f'  {"-"*58}')

for mo, days in zip(MONTHS, MONTH_DAYS):
    row = f'  {mo:<8}'
    for name, _, _ in CONFIGS:
        pnl = sum(results[name][mo]) * 2
        flag = '  RED' if pnl < 0 else ''
        row += f'  ${pnl:>9,.0f}'
    # Append any red flags
    flags = []
    for name, _, _ in CONFIGS:
        pnl = sum(results[name][mo]) * 2
        if pnl < 0: flags.append(name.split()[0])
    if flags: row += f'  << RED: {",".join(flags)}'
    print(row)

# Totals row
row = f'  {"ANNUAL":<8}'
for name, _, _ in CONFIGS:
    total = sum(p for mo in MONTHS for p in results[name][mo]) * 2
    row += f'  ${total:>9,.0f}'
print(f'  {"-"*58}')
print(row)

# ── EV lift analysis ─────────────────────────────────────────────
print(f'\n{SEP}')
print('  EV LIFT ANALYSIS — what each filter removes vs what it keeps')
print(SEP)

for name, lv, mb in CONFIGS[1:]:  # skip baseline
    base_pnl = [p for mo in MONTHS for p in results['A  Baseline'][mo]]
    filt_pnl = [p for mo in MONTHS for p in results[name][mo]]
    n_base, wr_base, ev_base, pf_base, _ = stats(base_pnl)
    n_filt, wr_filt, ev_filt, pf_filt, _ = stats(filt_pnl)
    removed = n_base - n_filt
    ev_gain = ev_filt - ev_base
    wr_gain = wr_filt - wr_base
    print(f'  {name}:')
    print(f'    Trades removed: {removed} ({removed/n_base*100:.1f}%)  '
          f'EV: ${ev_base:.2f} → ${ev_filt:.2f} ({ev_gain:+.2f})  '
          f'WR: {wr_base:.1f}% → {wr_filt:.1f}% ({wr_gain:+.1f}pp)  '
          f'PF: {pf_base:.1f} → {pf_filt:.1f}')
    print()

# ── Per-symbol breakdown for config D ────────────────────────────
print(f'\n{SEP}')
print('  PER-SYMBOL: Baseline (A) vs Best Filter (D)')
print(SEP)
print(f'  {"Symbol":<8}  {"A trades":>9}  {"A EV":>8}  {"A annual":>10}  '
      f'{"D trades":>9}  {"D EV":>8}  {"D annual":>10}  {"delta":>8}')
print(f'  {"-"*76}')

for sym in B23_SYMS:
    # Re-run per-symbol
    def sym_run(low_vol, mid_burst, sym=sym):
        b23.LOW_VOL_FILTER = low_vol
        b23.SKIP_MIDDLE_BURST = mid_burst
        pnls = []
        for mo in MONTHS:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue
            for t in b23.run_boof23(df, symbol=sym):
                pnls.append(t['pnl_pct'] * (B23_CORE if t['tier']=='core' else B23_EXP))
        return pnls

    pa = sym_run(False, False)
    pd = sym_run(True, True)
    na, wra, eva, pfa, tota = stats(pa)
    nd, wrd, evd, pfd, totd = stats(pd)
    delta = (totd - tota) * 2
    print(f'  {sym:<8}  {na:>9}  ${eva:>7.2f}  ${tota*2:>9,.0f}  '
          f'{nd:>9}  ${evd:>7.2f}  ${totd*2:>9,.0f}  ${delta:>7,.0f}')

print(f'\n{SEP}')
print('  VERDICT')
print(SEP)
all_base = [p for mo in MONTHS for p in results['A  Baseline'][mo]]
all_best = [p for mo in MONTHS for p in results['D  Both filters'][mo]]
nb, wrb, evb, pfb, totb = stats(all_base)
nd, wrd, evd, pfd, totd = stats(all_best)
print(f'  Baseline:    {nb} trades/yr  WR={wrb}%  EV=${evb}  PF={pfb}  Annual=${totb*2:,.0f}')
print(f'  Both filters:{nd} trades/yr  WR={wrd}%  EV=${evd}  PF={pfd}  Annual=${totd*2:,.0f}')
delta_ann = (totd - totb) * 2
print(f'  Net delta: ${delta_ann:+,.0f}/yr from {nb-nd} fewer trades')
print(f'  Recommendation: {"ENABLE BOTH" if delta_ann > 0 else "FILTERS HURT" if delta_ann < -2000 else "MARGINAL — KEEP BASELINE"}')
print(SEP)
