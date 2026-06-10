"""
Continuation — Tests 3 & 4 only (Test 1+2 results already printed).
Uses pre-computed trade data from Test 1 year_trades.
"""
import pandas as pd, numpy as np, importlib.util

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

TP_MAIN, SL_MAIN = 0.0045, 0.0018


def collect(syms, start, end, tp, sl):
    trades = []
    for sym in syms:
        df = mod.load_symbol(sym, start, end)
        if df is None: continue
        t = mod.run_boof23_strict_5sig_1exec(df, sym, tp_pct=tp, sl_pct=sl)
        if t: trades += t
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
    eq    = np.cumsum(pnl)
    peak  = np.maximum.accumulate(eq)
    dd    = (eq - peak).min()*100
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")
    print(f"  Trades: {len(pnl)}  WR: {wr:.1f}%  PF: {pf:.2f}")
    print(f"  Avg:    {avg:+.4f}%  Total: {ret:+.2f}%  MaxDD: {dd:+.2f}%")
    return dict(n=len(pnl), wr=wr, pf=pf, ret=ret, dd=dd)


def monte_carlo(trades, n_sims=2000, title="Monte Carlo"):
    if not trades: return
    pnl = np.array([t['pnl_pct'] for t in trades])
    n   = len(pnl)
    wrs, pfs, rets, dds = [], [], [], []
    for _ in range(n_sims):
        s    = np.random.choice(pnl, size=n, replace=True)
        wins = s[s > 0]; loss = s[s <= 0]
        wrs.append((s > 0).mean()*100)
        pfs.append(wins.sum()/abs(loss.sum()) if len(loss) else float('inf'))
        rets.append(s.sum()*100)
        eq = np.cumsum(s); peak = np.maximum.accumulate(eq)
        dds.append((eq - peak).min()*100)
    print(f"\n{'='*65}")
    print(f"  {title}  ({n_sims} sims, {n} trades/sim)")
    print(f"{'='*65}")
    print(f"  WR        med={np.median(wrs):.1f}%   "
          f"p5={np.percentile(wrs,5):.1f}%   p95={np.percentile(wrs,95):.1f}%")
    print(f"  PF        med={np.median(pfs):.2f}    "
          f"p5={np.percentile(pfs,5):.2f}    p95={np.percentile(pfs,95):.2f}")
    print(f"  Total Ret med={np.median(rets):+.1f}%  "
          f"p5={np.percentile(rets,5):+.1f}%  p95={np.percentile(rets,95):+.1f}%")
    print(f"  Max DD    med={np.median(dds):+.2f}%  "
          f"worst p5={np.percentile(dds,5):+.2f}%")
    print(f"  P(profit)  = {(np.array(rets)>0).mean()*100:.1f}%")
    print(f"  P(WR>50%)  = {(np.array(wrs)>50).mean()*100:.1f}%")
    print(f"  P(WR>55%)  = {(np.array(wrs)>55).mean()*100:.1f}%")


import pickle, os

TRADE_CACHE = "boof23_suite_trades.pkl"

# ── Load or compute year trades ───────────────────────────────────────
if os.path.exists(TRADE_CACHE):
    print(f"Loading cached trades from {TRADE_CACHE} ...")
    year_trades = pickle.load(open(TRADE_CACHE, "rb"))
    for y, t in year_trades.items():
        print(f"  {y}: {len(t)} trades (cached)")
else:
    print("Computing trades (first run — will cache for next time) ...")
    year_trades = {}
    for year, (s, e) in PERIODS.items():
        print(f"  {year} ...", end=" ", flush=True)
        t = collect(SYMS, s, e, TP_MAIN, SL_MAIN)
        year_trades[year] = t
        print(f"{len(t)} trades")
    pickle.dump(year_trades, open(TRADE_CACHE, "wb"))
    print(f"Saved to {TRADE_CACHE}")

# ─────────────────────────────────────────────────────────────────────
# TEST 3 — Monte Carlo
# ─────────────────────────────────────────────────────────────────────
print("\n" + "#"*65)
print("TEST 3 -- MONTE CARLO  (2000 simulations each)")
print("#"*65)

np.random.seed(42)
for year, trades in year_trades.items():
    monte_carlo(trades, n_sims=2000, title=f"Monte Carlo -- {year}")

all_trades = sum(year_trades.values(), [])
monte_carlo(all_trades, n_sims=3000, title="Monte Carlo -- ALL YEARS COMBINED")

# ─────────────────────────────────────────────────────────────────────
# TEST 4 — TP/SL grid on 2026
# ─────────────────────────────────────────────────────────────────────
print("\n" + "#"*65)
print("TEST 4 -- TP/SL GRID  (2026 only)")
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
        t = year_trades.get("2026", [])
    else:
        print(f"\n  Computing {lbl} ...")
        t = collect(SYMS, s26, e26, tp, sl)
    r = summary(t, f"Grid -- {lbl}")
    if r: grid_rows.append((lbl, r))

print(f"\n{'='*65}")
print("  GRID SUMMARY (2026)")
print(f"{'='*65}")
print(f"  {'CONFIG':<22} {'N':>5} {'WR':>7} {'PF':>6} {'RET':>8} {'DD':>8}")
print("  " + "-"*58)
for lbl, r in grid_rows:
    print(f"  {lbl:<22} {r['n']:>5} {r['wr']:>6.1f}%"
          f" {r['pf']:>6.2f} {r['ret']:>+7.2f}% {r['dd']:>+7.2f}%")
