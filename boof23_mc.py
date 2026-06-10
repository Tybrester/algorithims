"""
Monte Carlo on known Test 1 results.
Trade counts and WRs already confirmed:
  2024: 3809 trades, WR=48.5%, PF=2.35, avg=+0.1252%
  2025: 4485 trades, WR=52.0%, PF=2.70, avg=+0.1472%
  2026: 2129 trades, WR=52.5%, PF=2.76, avg=+0.1508%
We reconstruct a synthetic PnL distribution matching those exact stats,
then bootstrap 3000 sims per period.
"""
import numpy as np

TP = 0.0045
SL = 0.0018

def make_pnl(n, wr, avg_pct):
    """
    Build a minimal PnL array of length n with the given WR and avg.
    Wins = +TP, Losses = -SL (matches the binary TP/SL exit structure).
    Adjust win count to match stated WR exactly.
    """
    n_wins  = round(n * wr / 100)
    n_loss  = n - n_wins
    arr = np.array([TP] * n_wins + [-SL] * n_loss)
    np.random.shuffle(arr)
    return arr

def monte_carlo(pnl, n_sims, label):
    n = len(pnl)
    wrs, pfs, rets, dds = [], [], [], []
    for _ in range(n_sims):
        s    = np.random.choice(pnl, size=n, replace=True)
        wins = s[s > 0]; loss = s[s <= 0]
        wrs.append((s > 0).mean() * 100)
        pfs.append(wins.sum() / abs(loss.sum()) if len(loss) else float('inf'))
        rets.append(s.sum() * 100)
        eq   = np.cumsum(s)
        peak = np.maximum.accumulate(eq)
        dds.append((eq - peak).min() * 100)

    wrs  = np.array(wrs);  pfs  = np.array(pfs)
    rets = np.array(rets); dds  = np.array(dds)

    print(f"\n{'='*60}")
    print(f"  {label}  |  {n_sims} sims  |  {n} trades/sim")
    print(f"{'='*60}")
    print(f"  Metric       Median      p5       p95")
    print(f"  {'WR':<12} {np.median(wrs):>6.1f}%  {np.percentile(wrs,5):>6.1f}%  {np.percentile(wrs,95):>6.1f}%")
    print(f"  {'PF':<12} {np.median(pfs):>6.2f}   {np.percentile(pfs,5):>6.2f}   {np.percentile(pfs,95):>6.2f}")
    print(f"  {'Total Ret':<12} {np.median(rets):>+6.1f}%  {np.percentile(rets,5):>+6.1f}%  {np.percentile(rets,95):>+6.1f}%")
    print(f"  {'Max DD':<12} {np.median(dds):>+6.2f}%  {np.percentile(dds,5):>+6.2f}%  {np.percentile(dds,95):>+6.2f}%")
    print(f"  P(profitable) = {(rets > 0).mean()*100:.1f}%")
    print(f"  P(WR > 50%)   = {(wrs > 50).mean()*100:.1f}%")
    print(f"  P(WR > 55%)   = {(wrs > 55).mean()*100:.1f}%")
    print(f"  P(DD < -5%)   = {(dds < -5).mean()*100:.1f}%")

np.random.seed(42)

# Known results from Test 1
years = [
    ("2024", 3809, 48.5),
    ("2025", 4485, 52.0),
    ("2026", 2129, 52.5),
]

print("#"*60)
print("MONTE CARLO  |  Strict Boof 23  |  TP=0.45%  SL=0.18%")
print("#"*60)

all_pnl = []
for label, n, wr in years:
    pnl = make_pnl(n, wr, None)
    all_pnl.append(pnl)
    monte_carlo(pnl, 3000, f"MC -- {label}")

combined = np.concatenate(all_pnl)
monte_carlo(combined, 5000, "MC -- ALL YEARS COMBINED (10,423 trades)")
