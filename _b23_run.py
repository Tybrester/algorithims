"""
Boof 23 — Initial backtest
SR Cluster Entry + ZigZag Regime Filter + Engulf Confirmation
2025 full year + 2026 YTD
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import run_boof23, BOOFINGTON23

CORE_SIZE = 600; EXP_SIZE = 200
MOS_25 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MOS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']
DAYS   = 252 + 90  # 17 months

MO_LABELS = {
    'Jan':'Jan 25','Feb':'Feb 25','Mar':'Mar 25','Apr':'Apr 25',
    'May':'May 25','Jun':'Jun 25','Jul':'Jul 25','Aug':'Aug 25',
    'Sep':'Sep 25','Oct':'Oct 25','Nov':'Nov 25','Dec':'Dec 25',
    'Jan 26':'Jan 26','Feb 26':'Feb 26','Mar 26':'Mar 26',
    'Apr 26':'Apr 26','May 26':'May 26',
}

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))

def trade_pnl(t):
    size = CORE_SIZE if t['tier'] == 'core' else EXP_SIZE
    return t['pnl_pct'] * size

print('Running Boof 23...')
rows = []
for mo, cache in [(m, cache25) for m in MOS_25] + [(m, cache26) for m in MOS_26]:
    mo_trades = []
    for sym in BOOFINGTON23:
        df = cache.get((sym, mo))
        if df is None or len(df) < 100: continue
        raw = run_boof23(df, symbol=sym)
        for t in raw:
            t['pnl'] = trade_pnl(t)
            mo_trades.append(t)

    arr  = np.array([t['pnl'] for t in mo_trades]) if mo_trades else np.array([0.0])
    n    = len(mo_trades)
    w    = arr[arr > 0]; l = arr[arr < 0]
    wr   = round(len(w) / max(n,1) * 100, 1)
    pf   = round(float(sum(w) / max(abs(sum(l)), 0.01)), 2)
    ev   = round(float(np.mean(arr)), 2)
    tot  = round(float(sum(arr)), 2)
    tpd  = round(n / 21, 1)
    core_n = sum(1 for t in mo_trades if t['tier'] == 'core')
    exp_n  = n - core_n
    tp_n   = sum(1 for t in mo_trades if t['exit_type'] == 'tp')
    sl_n   = sum(1 for t in mo_trades if t['exit_type'] == 'sl')
    rows.append({'mo': mo, 'n': n, 'wr': wr, 'pf': pf, 'ev': ev,
                 'pnl': tot, 'tpd': tpd, 'core': core_n, 'exp': exp_n,
                 'tp': tp_n, 'sl': sl_n})

# ── Print monthly table ────────────────────────────────────────────
print()
print('=' * 85)
print('  BOOF 23.0 — SR Cluster + ZigZag Regime + Engulf | BOOFINGTON (no ETFs)')
print('  Core (slack>=1.4): $600  |  Expanded: $200  |  TP: 4xATR  SL: 2xATR')
print('=' * 85)
print(f'  {"Month":<9}  {"N":>6}  {"T/day":>6}  {"Core":>6}  {"Exp":>5}  {"WR%":>6}  {"PF":>6}  {"EV$":>7}  {"TP/SL":>8}  {"P&L":>10}')
print(f'  {"-"*83}')

cum = 0; yr25 = 0
for r in rows:
    label = MO_LABELS.get(r['mo'], r['mo'])
    cum  += r['pnl']
    if '26' not in label: yr25 += r['pnl']
    print(f'  {label:<9}  {r["n"]:>6}  {r["tpd"]:>6}  {r["core"]:>6}  {r["exp"]:>5}  '
          f'{r["wr"]:>6}  {r["pf"]:>6}  {r["ev"]:>7}  {r["tp"]:>4}/{r["sl"]:<3}  ${r["pnl"]:>9,.0f}')
    if label == 'Dec 25':
        print(f'  {"─"*83}')
        print(f'  {"2025 TOT":<9}  {"":>6}  {"":>6}  {"":>6}  {"":>5}  {"":>6}  {"":>6}  {"":>7}  {"":>8}  ${yr25:>9,.0f}  (${yr25/12:,.0f}/mo)')
        print(f'  {"─"*83}')

yr26 = cum - yr25
print(f'  {"2026 YTD":<9}  {"":>6}  {"":>6}  {"":>6}  {"":>5}  {"":>6}  {"":>6}  {"":>7}  {"":>8}  ${yr26:>9,.0f}  (${yr26/5:,.0f}/mo)')
print(f'  {"="*83}')
print(f'  {"TOTAL":<9}  {"":>6}  {"":>6}  {"":>6}  {"":>5}  {"":>6}  {"":>6}  {"":>7}  {"":>8}  ${cum:>9,.0f}')

# ── Aggregate ─────────────────────────────────────────────────────
total_n   = sum(r['n'] for r in rows)
total_pnl = sum(r['pnl'] for r in rows)
avg_wr    = round(np.mean([r['wr'] for r in rows if r['n'] > 0]), 1)
avg_pf    = round(np.mean([r['pf'] for r in rows if r['n'] > 0]), 2)
avg_ev    = round(np.mean([r['ev'] for r in rows if r['n'] > 0]), 2)
green     = sum(1 for r in rows if r['pnl'] > 0)
mo_arr    = np.array([r['pnl'] for r in rows])
cum_arr   = np.cumsum(mo_arr)
max_dd    = round(float((np.maximum.accumulate(cum_arr) - cum_arr).max()))
n_mos     = len(rows)

print()
print('=' * 85)
print(f'  AGGREGATE — {n_mos} months (Jan 2025 – May 2026)')
print('=' * 85)
print(f'    Trades total:  {total_n:,}  ({round(total_n/DAYS,1)}/day)')
print(f'    Win Rate:      {avg_wr}%')
print(f'    Profit Factor: {avg_pf}')
print(f'    EV/trade:      ${avg_ev}')
print(f'    Total P&L:     ${total_pnl:,.0f}')
print(f'    Monthly avg:   ${round(total_pnl/n_mos):,}')
print(f'    Max Drawdown:  ${max_dd:,}  (monthly peak-to-trough)')
print(f'    Green months:  {green}/{n_mos}')
print('=' * 85)
