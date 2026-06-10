data = {
    'ENPH': {'trades': 95,  'pnl_pct': 623.58},
    'AMD':  {'trades': 72,  'pnl_pct': 438.11},
    'TSLA': {'trades': 66,  'pnl_pct': 241.10},
    'MRNA': {'trades': 125, 'pnl_pct': 200.57},
    'SMCI': {'trades': 82,  'pnl_pct': 181.07},
    'PLTR': {'trades': 67,  'pnl_pct': 135.69},
    # dropped after realizing losers
    'CCL':  {'trades': 80,  'pnl_pct': -264.81},
    'COIN': {'trades': 59,  'pnl_pct': -569.52},
    'NVDA': {'trades': 71,  'pnl_pct': -456.50},
}

stake        = 300
trading_days = 22

# Assume losers caught after 1 week (5 days) before cutting
loser_days   = 5

print(f"Stake per trade: ${stake}  |  Trading days: {trading_days}")
print()
print(f"  {'SYMBOL':<6} {'TRADES':>7} {'PNL%':>8} {'DOLLAR':>10} {'PER DAY':>9}  NOTE")
print(f"  {'-'*60}")

total_winners = 0
total_losers  = 0

for sym, d in data.items():
    is_loser = d['pnl_pct'] < 0
    if is_loser:
        # Only traded for loser_days before cutting — scale losses proportionally
        scale  = loser_days / trading_days
        dollar = stake * (d['pnl_pct'] / 100) * scale
        note   = f"cut after ~{loser_days}d"
        total_losers += dollar
    else:
        dollar = stake * (d['pnl_pct'] / 100)
        note   = "kept"
        total_winners += dollar
    per_day = dollar / (loser_days if is_loser else trading_days)
    print(f"  {sym:<6} {d['trades']:>7} {d['pnl_pct']:>7.1f}%  ${dollar:>8,.0f}  ${per_day:>7,.0f}/day  {note}")

print(f"  {'-'*60}")
gross   = total_winners + total_losers
print(f"  {'Winners':<13}                  ${total_winners:>8,.0f}")
print(f"  {'Losers (cut)':<13}                  ${total_losers:>8,.0f}")
print(f"  {'NET TOTAL':<13}                  ${gross:>8,.0f}  (${gross/trading_days:,.0f}/day)")
print()
print(f"  Monthly:  ${gross:,.0f}")
print(f"  Annual:   ${gross*12:,.0f}  (if consistent)")
