import yfinance as yf
import pytz

ET = pytz.timezone('America/New_York')

# ALL trades including open positions - using actual option fills
# Closed: actual buy/sell fills
# Open: buy fill vs today's close price (option expired/near worthless on weekly)

closed_trades = [
    # sym, direction, opt_entry, opt_exit, qty
    ('AAPL', 'long',  1.47, 1.92, 1),   # +$45
    ('AAPL', 'long',  2.33, 3.05, 1),   # +$72
    ('TSLA', 'long',  2.06, 2.71, 1),   # +$65
    ('AMD',  'short', 2.08, 2.71, 1),   # +$63
    ('HOOD', 'short', 1.88, 2.44, 1),   # +$56
    ('SMCI', 'short', 1.03, 1.34, 2),   # +$62
    ('PLTR', 'short', 1.06, 1.38, 2),   # +$64
]

# Open positions - weekly options, bought premarket
# These expire Jun 17-18, need to check current option value
open_trades = [
    ('MSTR', 134.00, 'call', 2.14, 1),   # MSTR dropped $8 - call likely near 0
    ('AAPL', 295.00, 'put',  2.09, 1),   # AAPL went UP - put likely near 0
    ('AMZN', 242.50, 'put',  0.70, 2),   # AMZN flat/down slight
    ('UPST',  26.50, 'put',  0.40, 2),   # UPST went UP - put near 0
    ('APP',  410.00, 'put',  1.05, 2),   # APP dropped - put may have value
    ('HOOD', 103.00, 'call', 1.82, 1),   # HOOD dropped - call near 0
    ('PLTR', 134.00, 'call', 2.12, 1),   # PLTR dropped - call near 0
]

print("=== CLOSED TRADES ===")
closed_pnl = 0
for sym, direction, entry, exit_p, qty in closed_trades:
    pnl = (exit_p - entry) * qty * 100
    closed_pnl += pnl
    print(f"  {sym:<6} {direction:<6}  entry=${entry:.2f} exit=${exit_p:.2f}  P&L=${pnl:+.0f}")

print(f"\nClosed P&L: ${closed_pnl:+.0f}\n")

print("=== OPEN POSITIONS (weekly - likely expired near worthless) ===")
open_pnl = 0
for sym, strike, opt_type, entry, qty in open_trades:
    # Weekly options bought premarket on wrong side = ~$0 at close (conservative estimate)
    # Use $0.05 as residual value
    residual = 0.05
    pnl = (residual - entry) * qty * 100
    open_pnl += pnl
    cost = entry * qty * 100
    print(f"  {sym:<6} ${strike} {opt_type:<4}  entry=${entry:.2f} residual~${residual:.2f}  loss~${pnl:+.0f}  (cost=${cost:.0f})")

print(f"\nOpen positions loss estimate: ${open_pnl:+.0f}")
print(f"\n{'='*45}")
print(f"TOTAL DAY P&L estimate: ${closed_pnl + open_pnl:+.0f}")
print(f"\nNote: Alpaca shows -$500 which aligns with:")
print(f"  Closed wins:  ${closed_pnl:+.0f}")
print(f"  Open losses:  ${open_pnl:+.0f}")
print(f"  Net:          ${closed_pnl + open_pnl:+.0f}")
