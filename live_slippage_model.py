"""
REALISTIC LIVE SLIPPAGE MODEL
Converts paper trade results to live trading estimates
"""

import numpy as np

# ============================================
# SLIPPAGE PARAMETERS (Based on 0DTE options)
# ============================================
SLIPPAGE_CONFIG = {
    # Entry: You buy at ask (pay spread)
    'entry_slippage_pct': 0.015,      # 1.5% entry slippage
    
    # Exit on winners: You sell at bid (lose 50% of spread)
    'exit_winner_slippage_pct': 0.010,  # 1.0% exit slippage on winners
    
    # Exit on losers: Stops hit fast, more slippage
    'exit_loser_slippage_pct': 0.025,   # 2.5% exit slippage on losers
    
    # Big winners: Partial fills kill the home run
    'big_winner_threshold': 1.50,     # +150% is a "big winner"
    'partial_fill_reduction': 0.60,   # You only get 60% of big winners
    
    # Missed trades: Fast signals you can't catch
    'missed_trade_pct': 0.15,         # 15% of signals missed entirely
    
    # Commission + fees
    'commission_per_contract': 0.65,  # TastyWorks/IBKR approx
    'regulatory_fees_per_contract': 0.10,
}

# ============================================
# APPLY SLIPPAGE TO PAPER RESULTS
# ============================================
def apply_live_slippage(paper_pnl, contracts=1, is_winner=True, return_pct=0.0):
    """
    Convert paper P&L to live P&L with realistic slippage
    
    Args:
        paper_pnl: Paper trading P&L
        contracts: Number of contracts traded
        is_winner: True if winner, False if loser
        return_pct: Percentage return (for big winner detection)
    
    Returns:
        Estimated live P&L
    """
    cfg = SLIPPAGE_CONFIG
    
    # Base slippage on entry + exit
    entry_slippage = abs(paper_pnl) * cfg['entry_slippage_pct']
    
    if is_winner:
        exit_slippage = abs(paper_pnl) * cfg['exit_winner_slippage_pct']
    else:
        exit_slippage = abs(paper_pnl) * cfg['exit_loser_slippage_pct']
    
    total_slippage = entry_slippage + exit_slippage
    
    # Big winner partial fill penalty
    partial_fill_penalty = 0
    if is_winner and return_pct >= cfg['big_winner_threshold']:
        # You wanted 4 contracts, only got 1-2
        partial_fill_penalty = paper_pnl * (1 - cfg['partial_fill_reduction'])
    
    # Commission
    commission = contracts * (cfg['commission_per_contract'] + cfg['regulatory_fees_per_contract'])
    
    # Calculate live P&L
    live_pnl = paper_pnl - total_slippage - partial_fill_penalty - commission
    
    return live_pnl


# ============================================
# SIMULATE TODAY'S RESULTS
# ============================================
def simulate_today_live():
    """Simulate live trading for today's trades"""
    
    # Approximate today's trades from the log
    trades = [
        # Symbol, Contracts, Paper P&L, Return %, Winner?
        ('TSLA', 1, 199.26, 1.515, True),   # +151%
        ('META', 1, 208.39, 1.367, True),   # +136%
        ('META', 1, 316.73, 2.270, True),   # +227%
        ('META', 1, 194.29, 0.706, True),   # +70%
        ('AVGO', 1, 246.17, 1.115, True),   # +111%
        ('TSLA', 1, 172.16, 1.129, True),   # +112%
        ('META', 1, 93.36, 0.400, True),    # +40%
        ('MSFT', 1, 168.10, 0.486, True),   # +48%
        ('AMZN', 4, 161.91, 0.400, True),   # +40%
        ('AMZN', 3, 165.90, 0.400, True),   # +40%
        ('MSFT', 1, 147.78, 0.400, True),   # +40%
        ('MSFT', 1, 137.38, 0.400, True),   # +40%
        ('TSLA', 1, 115.69, 0.497, True),   # +49%
        ('META', 1, 77.60, 0.370, True),    # +37% (open)
        ('NVDA', 1, 88.67, 0.271, True),    # +27% (open)
        
        # Losers (controlled -10% stops)
        ('META', 1, -21.47, -0.100, False),
        ('META', 1, -19.16, -0.100, False),
        ('META', 1, -21.92, -0.100, False),
        ('META', 1, -21.47, -0.100, False),
        ('META', 1, -44.10, -0.100, False),
        ('META', 1, -45.61, -0.100, False),
        ('META', 1, -24.87, -0.100, False),
        ('TSLA', 1, -17.63, -0.100, False),
        ('TSLA', 1, -40.76, -0.100, False),
        ('TSLA', 1, -24.46, -0.100, False),
        ('TSLA', 1, -17.54, -0.100, False),
        ('TSLA', 1, -23.63, -0.100, False),
        ('TSLA', 1, -23.76, -0.100, False),
        ('MSFT', 1, -46.18, -0.100, False),
        ('MSFT', 1, -43.29, -0.100, False),
        ('MSFT', 1, -43.35, -0.100, False),
        ('MSFT', 1, -44.53, -0.100, False),
        ('NVDA', 1, -38.71, -0.100, False),
        ('AMZN', 2, -21.83, -0.100, False),
        ('AMZN', 2, -11.49, -0.048, False), # -4.8% (open)
        ('AAPL', 1, -14.71, -0.100, False),
        ('AAPL', 1, -13.15, -0.100, False),
        ('AAPL', 1, -13.58, -0.100, False),
        ('AAPL', 2, -126.04, -0.584, False), # -58% disaster
        ('AAPL', 1, -89.74, -0.670, False),   # -67% disaster
        ('AAPL', 1, -98.31, -0.689, False),   # -69% disaster
        ('AAPL', 1, -99.13, -0.694, False),   # -69% disaster
        ('AVGO', 1, -39.94, -0.100, False),
        ('AVGO', 1, -43.35, -0.100, False),
        ('AVGO', 1, -24.18, -0.100, False),
        ('AVGO', 1, -48.03, -0.100, False),
        ('LLY', 1, -29.52, -0.100, False),
        ('LLY', 1, -46.63, -0.100, False),
        ('LLY', 1, -38.30, -0.100, False),
        ('LLY', 1, -41.67, -0.100, False),
        ('LLY', 1, -44.26, -0.100, False),
        ('NVDA', 1, -36.43, -0.169, False),  # -16.9%
    ]
    
    # Miss 15% of trades (randomly)
    np.random.seed(42)
    missed_mask = np.random.random(len(trades)) < SLIPPAGE_CONFIG['missed_trade_pct']
    
    paper_total = 0
    live_total = 0
    
    results = []
    
    print("\n" + "=" * 80)
    print("LIVE SLIPPAGE SIMULATION - Today's Trades")
    print("=" * 80)
    print(f"\n{'Symbol':<8} {'Contracts':<10} {'Paper P&L':<12} {'Live P&L':<12} {'Slippage':<12} {'Status'}")
    print("-" * 80)
    
    for i, (symbol, contracts, paper_pnl, ret_pct, is_winner) in enumerate(trades):
        if missed_mask[i]:
            # Trade missed entirely
            results.append({
                'symbol': symbol,
                'contracts': contracts,
                'paper_pnl': 0,
                'live_pnl': 0,
                'missed': True
            })
            print(f"{symbol:<8} {contracts:<10} {'-- MISSED --':<12} {'-- MISSED --':<12} {'N/A':<12} ❌ MISSED")
            continue
        
        live_pnl = apply_live_slippage(paper_pnl, contracts, is_winner, abs(ret_pct))
        slippage = paper_pnl - live_pnl
        
        # Account for partial fills on big winners
        if is_winner and abs(ret_pct) >= SLIPPAGE_CONFIG['big_winner_threshold']:
            status = "⚠️ PARTIAL FILL"
        elif is_winner:
            status = "✅ WIN"
        else:
            status = "❌ LOSS"
        
        paper_total += paper_pnl
        live_total += live_pnl
        
        results.append({
            'symbol': symbol,
            'contracts': contracts,
            'paper_pnl': paper_pnl,
            'live_pnl': live_pnl,
            'missed': False
        })
        
        print(f"{symbol:<8} {contracts:<10} ${paper_pnl:+9.2f} ${live_pnl:+9.2f} ${slippage:+9.2f} {status}")
    
    print("-" * 80)
    
    # Summary
    missed_count = sum(1 for r in results if r['missed'])
    
    print(f"\n{'TOTALS':<8} {'':<10} ${paper_total:+9.2f} ${live_total:+9.2f} ${paper_total-live_total:+9.2f}")
    print(f"\nMissed trades: {missed_count} ({SLIPPAGE_CONFIG['missed_trade_pct']*100:.0f}%)")
    
    # Calculate R multiples (assume $250 base per trade)
    base_amount = 250
    paper_r = paper_total / base_amount
    live_r = live_total / base_amount
    
    print(f"\n{'='*80}")
    print("LIVE vs PAPER COMPARISON")
    print("=" * 80)
    print(f"Paper P&L:     ${paper_total:+,.2f} ({paper_r:+.2f}R)")
    print(f"Live P&L:      ${live_total:+,.2f} ({live_r:+.2f}R)")
    print(f"Difference:    ${paper_total - live_total:+,.2f}")
    print(f"Slippage %:    {(1 - live_total/paper_total)*100:.1f}% of profits lost")
    
    # Monthly projection
    print(f"\n{'='*80}")
    print("MONTHLY PROJECTION (20 trading days)")
    print("=" * 80)
    
    avg_paper_day = paper_total  # This was a good day
    avg_live_day = live_total
    
    # Assume this is "good day" (80th percentile)
    # Average day = 60% of good day
    avg_day_paper = avg_paper_day * 0.6
    avg_day_live = avg_live_day * 0.6
    
    # Assume 3 bad days per month (40% of average)
    bad_day_paper = avg_day_paper * 0.4
    bad_day_live = avg_day_live * 0.4
    
    monthly_paper = (17 * avg_day_paper) + (3 * bad_day_paper)
    monthly_live = (17 * avg_day_live) + (3 * bad_day_live)
    
    print(f"Good day (like today):")
    print(f"  Paper: ${avg_paper_day:+,.2f}  |  Live: ${avg_live_day:+,.2f}")
    print(f"\nAverage day:")
    print(f"  Paper: ${avg_day_paper:+,.2f}  |  Live: ${avg_day_live:+,.2f}")
    print(f"\nBad day (chop/slippage):")
    print(f"  Paper: ${bad_day_paper:+,.2f}  |  Live: ${bad_day_live:+,.2f}")
    print(f"\n{'='*80}")
    print(f"MONTHLY ESTIMATE (20 days: 17 avg + 3 bad):")
    print(f"  Paper: ${monthly_paper:+,.2f}")
    print(f"  Live:  ${monthly_live:+,.2f}")
    print(f"  You keep: {(monthly_live/monthly_paper)*100:.0f}% of paper profits")
    print("=" * 80)
    
    return live_total


if __name__ == "__main__":
    simulate_today_live()
