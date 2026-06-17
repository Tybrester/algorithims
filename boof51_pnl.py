import yfinance as yf

syms = ['UPST','HOOD','MU','TSLA','MRVL','AMD']
closes = {}
for sym in syms:
    t = yf.Ticker(sym)
    hist = t.history(period='1d', interval='1m')
    if not hist.empty:
        closes[sym] = round(float(hist['Close'].iloc[-1]), 2)
    else:
        closes[sym] = None

print("Today's closes:")
for s,p in closes.items():
    print(f"  {s}: ${p}")

# Decode strikes from option symbols — these are approximate entry prices
# All puts = bearish signal, profit if stock drops below strike
trades = [
    # sym, direction, entry_strike, qty, status
    ('AMD',  'short', 490.00, 1, 'filled'),   # AMD260618P00490000 filled $2.02, sold $1.71
    ('TSLA', 'short', 392.50, 2, 'filled'),   # TSLA260617P00392500 filled $0.91, sold $0.96 (tp1)
    ('TSLA', 'short', 392.50, 2, 'filled'),   # second TSLA trade filled $1.00, sold $1.25 (tp2)
    ('MU',   'short', 875.00, 2, 'canceled'), # MU260618P00875000 canceled
    ('HOOD', 'short',  93.00, 2, 'canceled'), # HOOD260618P00093000 canceled
    ('UPST', 'short',  25.50, 2, 'filled'),   # UPST260618P00025500 filled $0.75, still open?
    ('MRVL', 'short', 270.00, 1, 'canceled'), # MRVL260618P00270000 canceled
]

print("\n--- As STOCK trades (short = sell at strike, cover at close) ---")
print(f"{'Symbol':<6} {'Strike':>8}  {'Close':>8}  {'Move':>8}  {'Qty':>4}  {'P&L':>9}  Status")
print('-'*65)

total = 0
for sym, direction, strike, qty, status in trades:
    close = closes.get(sym)
    if close is None or status == 'canceled':
        print(f"{sym:<6} ${strike:>7.2f}  {'N/A':>8}  {'N/A':>8}  {qty:>4}  {'canceled':>9}  {status}")
        continue
    # short = profit when price falls below entry
    pnl = (strike - close) * qty
    move = close - strike
    total += pnl
    marker = '✓' if pnl > 0 else '✗'
    print(f"{sym:<6} ${strike:>7.2f}  ${close:>7.2f}  {move:>+7.2f}  {qty:>4}  ${pnl:>8.2f}  {marker}")

print('-'*65)
print(f"{'TOTAL (filled only)':>45}  ${total:>8.2f}")
print(f"\nNote: TSLA had 2 separate entries/exits (already closed intraday)")
print(f"Note: UPST filled but may still be open — using close price")
