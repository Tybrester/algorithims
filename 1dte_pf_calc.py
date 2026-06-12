#!/usr/bin/env python3
"""
1DTE Options Profit Factor Calculator
Strategy: Buy 2 ATM contracts
- Contract #1: Sell at +50%
- Contract #2: Sell at +100%  
- Stop Loss: -30% (both contracts)
"""

# Scaled exit analysis
def calc_scaled_pf(win_rate_pct, second_contract_hits_100_pct=0.5):
    """
    win_rate_pct = % of trades that hit at least +50% (first target)
    second_contract_hits_100_pct = % of winning trades where 2nd contract hits +100% vs stopped
    """
    win_rate = win_rate_pct / 100
    loss_rate = 1 - win_rate
    
    # Scenario 1: Loss (-30% on both contracts)
    loss_amount = 0.30 * 2  # -60% total
    
    # Scenario 2: Win (first contract +50%, second contract either +100% or stopped)
    # First contract always exits at +50%
    first_contract_profit = 0.50
    
    # Second contract: 
    # - second_contract_hits_100_pct of time hits +100%
    # - (1 - that) hits stop at -30%
    second_contract_profit = (
        second_contract_hits_100_pct * 1.00 + 
        (1 - second_contract_hits_100_pct) * (-0.30)
    )
    
    total_win_amount = first_contract_profit + second_contract_profit
    
    # PF = (Win Rate × Avg Win) / (Loss Rate × Avg Loss)
    gross_profits = win_rate * total_win_amount
    gross_losses = loss_rate * loss_amount
    
    pf = gross_profits / gross_losses if gross_losses > 0 else float('inf')
    
    return {
        'win_rate': win_rate_pct,
        'pf': pf,
        'avg_win': total_win_amount,
        'avg_loss': loss_amount,
        'second_contract_100_rate': second_contract_hits_100_pct * 100
    }

print("=== 1DTE SCALED EXIT ANALYSIS ===")
print("Entry: Buy 2 ATM 1DTE contracts")
print("Exit: Contract #1 at +50%, Contract #2 at +100%")
print("Stop Loss: -30% on both\n")

# At 45% win rate with different 2nd contract outcomes
print("At 45% win rate:")
print("-" * 50)
for second_hit_rate in [0.3, 0.5, 0.7]:
    result = calc_scaled_pf(45, second_hit_rate)
    print(f"2nd contract hits +100% {result['second_contract_100_rate']:.0f}% of time:")
    print(f"  Avg Win: +{result['avg_win']*100:.0f}%")
    print(f"  Avg Loss: -{result['avg_loss']*100:.0f}%")
    print(f"  → PF = {result['pf']:.2f}")
    print()

# Summary table
print("=== PF AT DIFFERENT WIN RATES ===")
print(f"{'Win Rate':<10} {'2nd=30%':<10} {'2nd=50%':<10} {'2nd=70%':<10}")
print("-" * 42)
for wr in [40, 45, 50, 55, 60]:
    pf_30 = calc_scaled_pf(wr, 0.3)['pf']
    pf_50 = calc_scaled_pf(wr, 0.5)['pf']
    pf_70 = calc_scaled_pf(wr, 0.7)['pf']
    print(f"{wr}%       {pf_30:<10.2f} {pf_50:<10.2f} {pf_70:<10.2f}")

print("\nAt 45% win rate with 50% of 2nd contracts hitting +100%:")
print(f"  Average Win: +{(0.50 + 0.35)*100:.0f}% (first +50%, second avg +35%)")
print(f"  Average Loss: -60%")
print(f"  → PF = {calc_scaled_pf(45, 0.5)['pf']:.2f}")
