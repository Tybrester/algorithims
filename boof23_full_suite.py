"""
Boof 23 Full Test Suite — Strict 4-rule | 5-min signal + 1-min execution
  Test 1: Per-year (2024, 2025, 2026) at TP=0.45% SL=0.18%
  Test 2: Walk-forward — train 2024-2025, test 2026
  Test 3: Monte Carlo on each year + combined
  Test 4: TP/SL grid — (0.45/0.18), (0.40/0.20), (0.50/0.20) on 2026
"""
import pandas as pd, numpy as np, importlib.util, random

spec = importlib.util.spec_from_file_location("b23", "boof23_analysis.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ET = mod.ET

SYMS = [
    'TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE',
    'MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB',
    'NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY',
    'MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ',
    'FCX','VRTX','S','CSCO','DE','HUM'
]

PERIODS = {
    "2024": (pd.Timestamp("2024-01-01", tz=ET), pd.Timestamp("2024-12-31", tz=ET)),
    "2025": (pd.Timestamp("2025-01-01", tz=ET), pd.Timestamp("2025-12-31", tz=ET)),
    "2026": (pd.Timestamp("2026-01-01", tz=ET), pd.Timestamp("2026-06-09", tz=ET)),
}


def collect(syms, start, end, tp, sl, label=""):
    trades = []
    for sym in syms:
        df = mod.load_symbol(sym, start, end)
        if df is None: continue
        t = mod.run_boof23_strict_5sig_1exec(df, sym, tp_pct=tp, sl_pct=sl)
        if t:
            trades += t
            if label:
                pnl = [x['pnl_pct'] for x in t]
                wr = sum(p>0 for p in pnl)/len(pnl)*100
                print(f"    {sym:<6} {len(t):>4}  WR={wr:.1f}%")
    return trades


def summary(trades, title):
    if not trades:
        print(f"\n  {title}: no trades"); return {}
    pnl   = [t['pnl_pct'] for t in trades]
    wins  = [p for p in pnl if p > 0]
    loss  = [p for p in pnl if p <= 0]
    wr    = len(wins)/len(pnl)*100
    pf    = sum(wins)/abs(sum(loss)) if loss else float('inf')
    ret   = sum(pnl)*100
    avg   = np.mean(pnl)*100
    # max drawdown on cumulative equity
    eq    = np.cumsum(pnl)
    peak  = np.maximum.accumulate(eq)
    dd    = (eq - peak).min()*100
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")
    print(f"  Trades:   {len(pnl)}")
    print(f"  WR:       {wr:.1f}%")
    print(f"  PF:       {pf:.2f}")
    print(f"  Avg:      {avg:+.4f}%")
    print(f"  Total:    {ret:+.2f}%")
    print(f"  Max DD:   {dd:+.2f}%")
    return dict(n=len(pnl), wr=wr, pf=pf, ret=ret, dd=dd)


def monte_carlo(trades, n_sims=2000, title="Monte Carlo"):
    if not trades: return
    pnl = np.array([t['pnl_pct'] for t in trades])
    n   = len(pnl)
    wrs, pfs, rets, dds = [], [], [], []
    for _ in range(n_sims):
        s     = np.random.choice(pnl, size=n, replace=True)
        wins  = s[s > 0]; loss = s[s <= 0]
        wrs.append((s > 0).mean()*100)
        pfs.append(wins.sum()/abs(loss.sum()) if len(loss) else float('inf'))
        rets.append(s.sum()*100)
        eq   = np.cumsum(s); peak = np.maximum.accumulate(eq)
        dds.append((eq - peak).min()*100)
    print(f"\n{'='*65}")
    print(f"  {title}  (n={n_sims} sims, {n} trades)")
    print(f"{'='*65}")
    print(f"  WR         med={np.median(wrs):.1f}%   p5={np.percentile(wrs,5):.1f}%  p95={np.percentile(wrs,95):.1f}%")
    print(f"  PF         med={np.median(pfs):.2f}   p5={np.percentile(pfs,5):.2f}  p95={np.percentile(pfs,95):.2f}")
    print(f"  Total Ret  med={np.median(rets):+.2f}%  p5={np.percentile(rets,5):+.2f}%  p95={np.percentile(rets,95):+.2f}%")
    print(f"  Max DD     med={np.median(dds):+.2f}%  worst p5={np.percentile(dds,5):+.2f}%")
    print(f"  P(profit):      {(np.array(rets)>0).mean()*100:.1f}%")
    print(f"  P(WR>50%):      {(np.array(wrs)>50).mean()*100:.1f}%")
    print(f"  P(WR>55%):      {(np.array(wrs)>55).mean()*100:.1f}%")


# ─────────────────────────────────────────────────────────────────────
# TEST 1 — Per-year at TP=0.45% SL=0.18%
# ─────────────────────────────────────────────────────────────────────
print("\n" + "#"*65)
print("TEST 1 — PER-YEAR  |  TP=0.45%  SL=0.18%")
print("#"*65)

TP_MAIN, SL_MAIN = 0.0045, 0.0018
year_trades = {}

for year, (s, e) in PERIODS.items():
    print(f"\n--- {year} ---")
    t = collect(SYMS, s, e, TP_MAIN, SL_MAIN, label=year)
    year_trades[year] = t
    summary(t, f"Strict Boof 23 — {year}  [TP={TP_MAIN*100:.2f}%  SL={SL_MAIN*100:.2f}%]")

# ─────────────────────────────────────────────────────────────────────
# TEST 2 — Walk-forward: train 2024+2025 → test 2026
# ─────────────────────────────────────────────────────────────────────
print("\n" + "#"*65)
print("TEST 2 — WALK-FORWARD  |  Train=2024+2025  Test=2026")
print("#"*65)

train = year_trades.get("2024", []) + year_trades.get("2025", [])
test  = year_trades.get("2026", [])

tr = summary(train, "TRAIN  2024+2025")
te = summary(test,  "TEST   2026")

if tr and te:
    print(f"\n  DEGRADATION:")
    print(f"    WR:  {tr['wr']:.1f}% -> {te['wr']:.1f}%  ({te['wr']-tr['wr']:+.1f}pp)")
    print(f"    PF:  {tr['pf']:.2f} -> {te['pf']:.2f}")
    print(f"    Ret: {tr['ret']:+.2f}% -> {te['ret']:+.2f}%")

# ─────────────────────────────────────────────────────────────────────
# TEST 3 — Monte Carlo
# ─────────────────────────────────────────────────────────────────────
print("\n" + "#"*65)
print("TEST 3 — MONTE CARLO")
print("#"*65)

np.random.seed(42)
for year, trades in year_trades.items():
    monte_carlo(trades, n_sims=2000, title=f"Monte Carlo — {year}")

all_trades = sum(year_trades.values(), [])
monte_carlo(all_trades, n_sims=3000, title="Monte Carlo — ALL YEARS COMBINED")

# ─────────────────────────────────────────────────────────────────────
# TEST 4 — TP/SL grid on 2026
# ─────────────────────────────────────────────────────────────────────
print("\n" + "#"*65)
print("TEST 4 — TP/SL GRID  (tested on 2026)")
print("#"*65)

s26, e26 = PERIODS["2026"]
grid = [
    (0.0045, 0.0018, "TP=0.45%  SL=0.18%"),
    (0.0040, 0.0020, "TP=0.40%  SL=0.20%"),
    (0.0050, 0.0020, "TP=0.50%  SL=0.20%"),
]

grid_rows = []
for tp, sl, lbl in grid:
    if tp == TP_MAIN and sl == SL_MAIN:
        t = year_trades.get("2026", [])  # reuse already-computed
    else:
        print(f"\n  Computing {lbl} ...")
        t = collect(SYMS, s26, e26, tp, sl)
    r = summary(t, f"Grid — {lbl}")
    if r: grid_rows.append((lbl, r))

print(f"\n{'='*65}")
print(f"  GRID SUMMARY (2026)")
print(f"{'='*65}")
print(f"  {'CONFIG':<22} {'N':>5} {'WR':>7} {'PF':>6} {'RET':>8} {'DD':>8}")
print("  " + "-"*58)
for lbl, r in grid_rows:
    print(f"  {lbl:<22} {r['n']:>5} {r['wr']:>6.1f}% {r['pf']:>6.2f}"
          f" {r['ret']:>+7.2f}% {r['dd']:>+7.2f}%")
