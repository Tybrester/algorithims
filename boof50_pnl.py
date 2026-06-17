import yfinance as yf
import pytz
from datetime import timedelta

ET = pytz.timezone('America/New_York')

# Closed option pairs (buy then sell = round trip)
# Format: sym, strike, direction, entry_time, exit_time, entry_fill, exit_fill, qty
trades = [
    ('AAPL', 297.50, 'long',  '07:35', '07:54', 1.47, 1.92, 1),   # AAPL call +$0.45
    ('AAPL', 295.00, 'long',  '07:49', '07:53', 2.33, 3.05, 1),   # AAPL call +$0.72
    ('TSLA', 417.50, 'long',  '07:43', '07:50', 2.06, 2.71, 1),   # TSLA call +$0.65
    ('AMD',  492.50, 'short', '07:40', '08:22', 2.08, 2.71, 1),   # AMD put +$0.63
    ('HOOD',  97.00, 'short', '07:39', '08:23', 1.88, 2.44, 1),   # HOOD put +$0.56
    ('SMCI',  30.50, 'short', '07:47', '08:19', 1.03, 1.34, 2),   # SMCI put +$0.31
    ('PLTR', 129.00, 'short', '07:35', '08:13', 1.06, 1.38, 2),   # PLTR put +$0.32
    # Still open / no sell recorded:
    ('MSTR', 134.00, 'long',  '07:42', None,    2.14, None, 1),    # MSTR call - open
    ('AAPL', 295.00, 'put',   '07:41', None,    2.09, None, 1),    # AAPL put - open
    ('AMZN', 242.50, 'short', '07:40', None,    0.70, None, 2),    # AMZN put - open
    ('UPST',  26.50, 'short', '07:35', None,    0.40, None, 2),    # UPST put - open
    ('APP',  410.00, 'short', '07:35', None,    1.05, None, 2),    # APP put - open
    ('HOOD', 103.00, 'long',  '07:34', None,    1.82, None, 1),    # HOOD call - open
    ('PLTR', 134.00, 'long',  '07:48', None,    2.12, None, 1),    # PLTR call - open
]

print("Fetching intraday data...\n")
syms = list(set(t[0] for t in trades))
hist_cache = {}
for sym in syms:
    t = yf.Ticker(sym)
    h = t.history(period='5d', interval='1m', prepost=True)
    if h.index.tz is None:
        h.index = h.index.tz_localize('UTC')
    h.index = h.index.tz_convert(ET)
    today = h.index[-1].date()
    hist_cache[sym] = h[h.index.date == today]

def get_price_at(sym, time_str):
    h = hist_cache.get(sym)
    if h is None or h.empty: return None
    hh, mm = map(int, time_str.split(':'))
    rows = h.between_time(f'{hh:02d}:{mm:02d}', f'{hh:02d}:{mm+2:02d}')
    return float(rows['Open'].iloc[0]) if not rows.empty else float(h['Open'].iloc[0])

def get_close(sym):
    h = hist_cache.get(sym)
    if h is None or h.empty: return None
    rth = h.between_time('09:30', '16:00')
    return float(rth['Close'].iloc[-1]) if not rth.empty else None

print(f"{'Symbol':<6} {'Dir':<6} {'Entry$':>8} {'Exit$':>8} {'StockMv':>8} {'Dir?':>6} {'OptPnL':>8} {'StockPnL':>9}")
print('-'*72)

total_opt = 0
total_stk = 0

for sym, strike, direction, entry_t, exit_t, opt_entry, opt_exit, qty in trades:
    stock_entry = get_price_at(sym, entry_t)
    if exit_t:
        stock_exit = get_price_at(sym, exit_t)
        label = exit_t
    else:
        stock_exit = get_close(sym)
        label = 'close'

    if not stock_entry or not stock_exit:
        print(f"{sym:<6} {'?':>6}  no data")
        continue

    move = stock_exit - stock_entry
    is_long = direction == 'long'
    correct = move > 0 if is_long else move < 0
    marker = 'YES' if correct else 'NO'

    # Option P&L
    if opt_exit:
        opt_pnl = (opt_exit - opt_entry) * qty * 100
    else:
        opt_pnl = None  # still open

    # Stock P&L ($750 budget)
    shares = max(1, int(750 / stock_entry))
    stk_pnl = (move if is_long else -move) * shares

    opt_str = f"${opt_pnl:>+.0f}" if opt_pnl is not None else "  open"
    total_opt += opt_pnl if opt_pnl is not None else 0
    total_stk += stk_pnl

    print(f"{sym:<6} {direction:<6} ${stock_entry:>7.2f} ${stock_exit:>7.2f} {move:>+7.2f}  {marker:>5}  {opt_str:>7}  ${stk_pnl:>+7.2f}")

print('-'*72)
print(f"{'TOTALS (closed trades only)':>45}  {f'${total_opt:>+.0f}':>7}  ${total_stk:>+7.2f}")
