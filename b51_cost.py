"""Re-scale options sim to fixed entry costs"""
import pandas as pd
import numpy as np

df = pd.read_csv("boof52_QQQ_options.csv")
s  = df[df["config"] == "0DTE  IV25%"].copy()

hits  = s[s["exit_reason"].str.contains("hit")]
times = s[s["exit_reason"] == "time"]

W = 72
print(f"\n{'='*W}")
print(f"  0DTE Options | Fixed Entry Cost Scenarios | 204 trades")
print(f"{'='*W}")
print(f"  {'Cost':>6}  {'WR%':>6}  {'AvgPnL':>9}  {'Total':>9}  {'Best':>8}  {'Worst':>8}")
print(f"  {'':>6}  {'':>6}  {'Hits avg':>9}  {'Times avg':>9}")
print(f"  {'-'*66}")

for cost in [200, 250, 300, 350, 400, 450]:
    actual = s["p_entry"] * 100
    scale  = cost / actual
    pnl    = s["pnl_dollar"] * scale

    wr    = (pnl > 0).mean() * 100
    avg   = pnl.mean()
    total = pnl.sum()
    best  = pnl.max()
    worst = pnl.min()

    h_avg = (hits["pnl_dollar"] * (cost / (hits["p_entry"]*100))).mean()
    t_avg = (times["pnl_dollar"] * (cost / (times["p_entry"]*100))).mean()

    print(f"  {cost:>5}   {wr:>6.1f}%  {avg:>+9.2f}  {total:>+9.0f}  {best:>+8.0f}  {worst:>+8.0f}")
    print(f"  {'':>6}  {'':>6}  hits={h_avg:>+7.2f}  times={t_avg:>+8.2f}")
    print(f"  {'-'*66}")

# Break-even analysis
print(f"\n  BREAK-EVEN ANALYSIS")
print(f"  For the 48 trades that hit a target (+0.50% or +0.75%):")
for cost in [200, 300, 400]:
    scale  = cost / (hits["p_entry"] * 100)
    h_tot  = (hits["pnl_dollar"] * scale).sum()
    t_scale= cost / (times["p_entry"] * 100)
    t_tot  = (times["pnl_dollar"] * t_scale).sum()
    net    = h_tot + t_tot
    print(f"  Entry ${cost}: winners={h_tot:>+8.0f}  losers={t_tot:>+8.0f}  NET={net:>+8.0f}")

# What win rate do you need to break even?
print(f"\n  REQUIRED WIN RATE TO BREAK EVEN (AvgWin / (AvgWin + AvgLoss)):")
for cost in [200, 300, 400]:
    scale_h = cost / (hits["p_entry"] * 100)
    scale_t = cost / (times["p_entry"] * 100)
    avg_win  = (hits["pnl_dollar"] * scale_h).mean()
    avg_loss = abs((times["pnl_dollar"] * scale_t).mean())
    be_wr    = avg_loss / (avg_win + avg_loss) * 100
    print(f"  Entry ${cost}: AvgWin={avg_win:>+7.2f}  AvgLoss={avg_loss:>+7.2f}  Break-even WR={be_wr:.1f}%  Actual WR=45.6%")
