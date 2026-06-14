"""
Simple EV model: if +0.50% underlying = +X% on option
Uses actual hit rates from backtest (45.6% reach +0.50%)
"""
import numpy as np

HIT_RATE  = 0.456   # 45.6% of trades reach +0.50% (from b51_ttt.py)
N_TRADES  = 204     # 6 months of signals

print()
print("=" * 65)
print("  EV Model: +0.50% underlying move = +30% option profit")
print(f"  Hit rate: {HIT_RATE*100:.1f}%  |  Trades: {N_TRADES}  |  6 months")
print("=" * 65)

# Core question: entry cost vs assumed option gain/loss
for entry_cost in [200, 300, 400]:
    win_dollar  = entry_cost * 0.30          # +30% on option = user assumption
    loss_dollar = entry_cost * 0.50          # lose ~50% on misses (theta + no move)
    ev          = HIT_RATE * win_dollar - (1 - HIT_RATE) * loss_dollar
    total_6m    = ev * N_TRADES
    be_wr       = loss_dollar / (win_dollar + loss_dollar) * 100
    print(f"\n  Entry ${entry_cost}  Win=+${win_dollar:.0f}  Loss=-${loss_dollar:.0f}")
    print(f"    EV/trade : {ev:>+.2f}")
    print(f"    Total 6m : {total_6m:>+.0f}")
    print(f"    Break-even WR: {be_wr:.1f}%  (actual {HIT_RATE*100:.1f}%  -> {'POSITIVE' if HIT_RATE*100 > be_wr else 'NEGATIVE'})")

# Full grid: entry=300, vary assumed option gain % and loss %
entry_cost = 300
tps   = [0.20, 0.30, 0.40, 0.50, 0.75, 1.00]
losses= [0.20, 0.30, 0.40, 0.50, 0.60, 0.70]

print()
print("=" * 72)
print(f"  FULL EV GRID  |  Entry=$300  |  Hit rate={HIT_RATE*100:.1f}%")
print(f"  EV per trade ($) — positive = profitable  << marked")
print("=" * 72)

header = f"  {'Win%':<8}" + "".join([f"  Loss{int(l*100)}%" for l in losses])
print(header)
print("  " + "-" * 65)

for tp in tps:
    row = f"  +{int(tp*100)}%{'':<5}"
    for loss in losses:
        win_d  = entry_cost * tp
        loss_d = entry_cost * loss
        ev     = HIT_RATE * win_d - (1 - HIT_RATE) * loss_d
        tag    = "<<" if ev > 0 else "  "
        row += f"  {ev:>+6.0f}{tag}"
    print(row)

print()
print(f"  NOTE: If +0.50% underlying = +30% option profit (your assumption):")
win_d  = 300 * 0.30
loss_d = 300 * 0.50
ev     = HIT_RATE * win_d - (1 - HIT_RATE) * loss_d
total  = ev * N_TRADES
be     = loss_d / (win_d + loss_d) * 100
print(f"    Win  = +${win_d:.0f}/contract")
print(f"    Loss = -${loss_d:.0f}/contract (assumed 50% theta loss on miss)")
print(f"    EV   = {ev:>+.2f}/trade")
print(f"    Total 6m = {total:>+.0f}")
print(f"    Break-even WR = {be:.1f}%  vs actual {HIT_RATE*100:.1f}%")
print()

# Sensitivity: what loss% makes it break even at entry=300, win=+30%?
print("  SENSITIVITY: what max loss% still keeps EV positive? (entry=300, win=+30%)")
win_d = 300 * 0.30
for loss in np.arange(0.10, 0.85, 0.05):
    loss_d = 300 * loss
    ev = HIT_RATE * win_d - (1 - HIT_RATE) * loss_d
    if abs(ev) < 3:
        print(f"    Break-even at loss ~{loss*100:.0f}%  (lose ${loss_d:.0f}/miss)")
        break
    if ev > 0:
        print(f"    +{loss*100:.0f}% loss -> EV {ev:>+.2f}  POSITIVE")
    else:
        print(f"    +{loss*100:.0f}% loss -> EV {ev:>+.2f}  negative <- crossover here")
        break
