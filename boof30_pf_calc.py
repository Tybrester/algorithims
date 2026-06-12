#!/usr/bin/env python3
"""
Boof 30 Profit Factor Calculator
TP = +0.40% | SL = -0.20% | R:R = 2:1
"""

# Boof 30 parameters
TP_PCT = 0.004  # +0.40%
SL_PCT = 0.002  # -0.20%

# Risk:Reward ratio
risk_reward = TP_PCT / SL_PCT
print(f"Risk:Reward Ratio: 1:{risk_reward:.1f}")

# Estimate win rate needed for breakeven
breakeven_winrate = SL_PCT / (TP_PCT + SL_PCT)
print(f"Breakeven Win Rate: {breakeven_winrate*100:.1f}%")

# Profit Factor formula: (Win Rate × Avg Win) / (Loss Rate × Avg Loss)
def calc_pf(win_rate_pct):
    win_rate = win_rate_pct / 100
    loss_rate = 1 - win_rate
    
    avg_win = TP_PCT
    avg_loss = SL_PCT
    
    pf = (win_rate * avg_win) / (loss_rate * avg_loss)
    return pf

print("\n--- Profit Factor at Different Win Rates ---")
for wr in [45, 50, 55, 60, 65, 70]:
    pf = calc_pf(wr)
    print(f"Win Rate {wr}% → PF = {pf:.2f}")
