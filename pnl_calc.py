data = {
    'SPY':  {'trades': 78,  'pnl_pct': 5.55},
    'QQQ':  {'trades': 58,  'pnl_pct': 86.49},
    'TSLA': {'trades': 75,  'pnl_pct': 290.18},
    'AMD':  {'trades': 82,  'pnl_pct': 465.43},
}
stake        = 300
trading_days = 22

print(f"Stake per trade: ${stake}")
print(f"Trading days:    {trading_days}")
print()
print(f"  {'SYMBOL':<6} {'TRADES':>7} {'PNL%':>8} {'DOLLAR PNL':>12} {'PER DAY':>10}")
print(f"  {'-'*50}")

total_pnl = 0
for sym, d in data.items():
    dollar  = stake * (d['pnl_pct'] / 100)
    per_day = dollar / trading_days
    total_pnl += dollar
    print(f"  {sym:<6} {d['trades']:>7} {d['pnl_pct']:>7.1f}%  ${dollar:>9,.0f}  ${per_day:>7,.0f}/day")

print(f"  {'-'*50}")
print(f"  {'TOTAL':<6} {293:>7}           ${total_pnl:>9,.0f}  ${total_pnl/trading_days:>7,.0f}/day")
print()
print(f"  Monthly:  ${total_pnl:,.0f}")
print(f"  Annual:   ${total_pnl*12:,.0f}  (if April repeats)")
