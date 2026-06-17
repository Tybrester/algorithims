"""
Analyze boof50 trades — check option P&L and current value of stuck positions.
"""
import alpaca_trade_api as t
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest
import pytz
from datetime import datetime

ET = pytz.timezone("America/New_York")
api50 = t.REST('PKUE2IRNMB5ZUCK3ISPE3RIUX4','Cb3rxrN6SNSYkpYEbVn96i7FjM5KCBcpR8bLq7hKRciB','https://paper-api.alpaca.markets')
odc   = OptionHistoricalDataClient('PKUE2IRNMB5ZUCK3ISPE3RIUX4','Cb3rxrN6SNSYkpYEbVn96i7FjM5KCBcpR8bLq7hKRciB')

# Trades: (opt_sym, side, qty, entry_fill, exit_fill or None, exit_time or None)
trades = [
    # Closed trades (exit at 11:30:47 market sell)
    ("TSLA260617P00395000",  "short", 2, 1.78, 1.57, "11:30"),
    ("TSLA260617C00417500",  "long",  1, 3.75, 3.75, "11:30"),  # TP hit
    ("MSFT260617C00407500",  "long",  2, 1.71, 1.56, "11:30"),
    ("HOOD260618C00102000",  "long",  2, 1.87, 1.93, "11:30"),  # small win
    ("COIN260618C00182500",  "long",  2, 1.85, 1.65, "11:30"),
    ("NVDA260617P00210000",  "short", 2, None, 1.40, "11:01"),  # sold before we see buy — orphan

    # Still open (stuck, can't close after hours)
    ("AMD260618P00135000",   "short", 2, 0.07, None, None),
    ("AMZN260617P00245000",  "long",  2, 1.87, None, None),
    ("APP260618P00270000",   "short", 1, 3.50, None, None),
    ("CRWD260618P00155000",  "short", 1, 4.80, None, None),
    ("HOOD260618C00099000",  "long",  1, 3.25, None, None),
    ("HOOD260618P00100000",  "short", 1, 3.30, None, None),
    ("MSFT260617P00305000",  "short", 2, 1.76, None, None),
    ("MSFT260617P00397500",  "short", 1, 3.50, None, None),
    ("MSTR260618P00049000",  "short", 1, 0.05, None, None),
    ("SMCI260618C00028000",  "long",  2, 3.43, None, None),  # avg of 3.40+3.45
    ("TSLA260617C00427500",  "long",  2, 1.63, None, None),
    ("TSLA260617P00402500",  "short", 1, 3.15, None, None),
    ("UPST260618C00032000",  "long",  2, 1.63, None, None),
]

# Get current quotes for open positions
open_syms = [t[0] for t in trades if t[4] is None]
print(f"Fetching quotes for {len(open_syms)} open positions...")
try:
    snaps = odc.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=open_syms))
except Exception as e:
    snaps = {}
    print(f"Snapshot error: {e}")

current_prices = {}
for sym in open_syms:
    s = snaps.get(sym)
    if s and s.latest_quote:
        bid = s.latest_quote.bid_price or 0
        ask = s.latest_quote.ask_price or 0
        current_prices[sym] = (bid + ask) / 2 if ask else bid
    else:
        current_prices[sym] = None

# Print analysis
print(f"\n{'Symbol':<28} {'Side':<6} {'Qty':>3} {'Entry':>6} {'Exit':>6} {'P&L$':>8} {'Status'}")
print("-" * 75)

total_pl = 0
closed_pl = 0
open_pl = 0
wins = losses = 0

for opt_sym, side, qty, entry, exit_px, exit_time in trades:
    if exit_px is not None and entry is not None:
        pl = (exit_px - entry) * qty * 100
        status = f"CLOSED {exit_time}"
        if pl > 0: wins += 1
        else: losses += 1
        closed_pl += pl
    elif entry is None:
        pl = 0
        status = "ORPHAN (no entry)"
    else:
        cur = current_prices.get(opt_sym)
        if cur:
            pl = (cur - entry) * qty * 100
            status = f"OPEN  cur={cur:.2f}"
        else:
            pl = 0
            status = "OPEN  (no quote)"
        open_pl += pl

    total_pl += pl
    entry_str = f"{entry:.2f}" if entry else "  ?"
    exit_str  = f"{exit_px:.2f}" if exit_px else "  —"
    pl_str    = f"${pl:+.0f}"
    print(f"{opt_sym:<28} {side:<6} {qty:>3} {entry_str:>6} {exit_str:>6} {pl_str:>8}  {status}")

print("-" * 75)
print(f"{'Closed P&L':>45}: ${closed_pl:+.0f}  ({wins}W/{losses}L)")
print(f"{'Open P&L (mark)':>45}: ${open_pl:+.0f}")
print(f"{'Total P&L':>45}: ${total_pl:+.0f}")
