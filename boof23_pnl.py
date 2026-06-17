import yfinance as yf
import pytz
from datetime import timedelta

ET = pytz.timezone('America/New_York')

# Decode from option symbols:
# HOOD260618P00096000 -> HOOD $96 put (bearish) exp Jun 18
# NVDA260617C00210000 -> NVDA $210 call (bullish) exp Jun 17
# ORCL260618C00200000 -> ORCL $200 call (bullish) exp Jun 18

trades = [
    # sym,  strike, direction, opt_pnl
    ('HOOD', 96.00,  'short', -7.00),
    ('NVDA', 210.00, 'long',  -87.00),
    ('ORCL', 200.00, 'long',  -114.00),
]

print("Fetching 1-min intraday data...\n")
for sym, strike, direction, opt_pnl in trades:
    t = yf.Ticker(sym)
    hist = t.history(period='5d', interval='1m', prepost=True)
    if hist.index.tz is None:
        hist.index = hist.index.tz_localize('UTC')
    hist.index = hist.index.tz_convert(ET)
    # Keep only today
    today = hist.index[-1].date()
    hist = hist[hist.index.date == today]
    rth = hist.between_time('09:30', '16:00')

    open_price = float(rth['Open'].iloc[0]) if not rth.empty else 0
    close_price = float(rth['Close'].iloc[-1]) if not rth.empty else 0
    high = float(rth['High'].max()) if not rth.empty else 0
    low  = float(rth['Low'].min()) if not rth.empty else 0
    move = close_price - open_price

    # Was direction correct?
    if direction == 'long':
        correct = close_price > open_price
        stock_pnl_1sh = move
    else:
        correct = close_price < open_price
        stock_pnl_1sh = -move

    marker = 'CORRECT' if correct else 'WRONG'

    print(f"{sym} | {direction.upper()} | Strike=${strike:.0f}")
    print(f"  Open={open_price:.2f}  Close={close_price:.2f}  Move={move:+.2f}  H={high:.2f} L={low:.2f}")
    print(f"  Direction: {marker}")
    print(f"  Option P&L: ${opt_pnl:.2f}")
    print(f"  Stock P&L (1sh): ${stock_pnl_1sh:+.2f}")
    # $750 budget sizing
    shares_750 = max(1, int(750 / open_price))
    stock_pnl_750 = stock_pnl_1sh * shares_750
    print(f"  Stock P&L ($750 budget, {shares_750}sh): ${stock_pnl_750:+.2f}")
    print()
