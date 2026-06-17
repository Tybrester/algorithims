import yfinance as yf
from datetime import datetime
import pytz

ET = pytz.timezone('America/New_York')

# Filled trades with actual entry times
trades = [
    # sym,   entry_time ET,   strike,  qty,  put/short
    ('AMD',  '07:33', 490.00, 1),
    ('TSLA', '08:02', 392.50, 2),   # first entry
    ('TSLA', '08:10', 392.50, 2),   # second entry
    ('UPST', '08:34', 25.50,  2),
]

print(f"{'Symbol':<6} {'Entry':>6}  {'Entry$':>8}  {'Exit(+30m)':>10}  {'Exit$':>8}  {'Move':>8}  {'Qty':>4}  {'P&L':>9}")
print('-'*72)

total = 0
for sym, entry_str, strike, qty in trades:
    t = yf.Ticker(sym)
    hist = t.history(period='1d', interval='1m', prepost=True)
    hist.index = hist.index.tz_convert(ET)

    # Find entry bar
    entry_h, entry_m = map(int, entry_str.split(':'))
    entry_rows = hist.between_time(f'{entry_h:02d}:{entry_m:02d}', f'{entry_h:02d}:{entry_m+2:02d}')
    if entry_rows.empty:
        print(f"{sym:<6} {entry_str}  no data")
        continue
    entry_price = float(entry_rows['Open'].iloc[0])
    entry_time  = entry_rows.index[0]

    # Exit bar: ~20-30 min later
    exit_time_target = entry_time + __import__('datetime').timedelta(minutes=25)
    exit_rows = hist[hist.index >= exit_time_target]
    if exit_rows.empty:
        exit_price = float(hist['Close'].iloc[-1])
        exit_label = 'close'
    else:
        exit_price = float(exit_rows['Open'].iloc[0])
        exit_label = exit_rows.index[0].strftime('%H:%M')

    move = exit_price - entry_price
    # Short (put signal) = profit when price drops
    pnl = -move * qty
    total += pnl
    marker = '✓' if pnl > 0 else '✗'
    print(f"{sym:<6} {entry_str:>6}  ${entry_price:>7.2f}  {exit_label:>10}  ${exit_price:>7.2f}  {move:>+7.2f}  {qty:>4}  ${pnl:>8.2f}  {marker}")

print('-'*72)
print(f"{'TOTAL':>60}  ${total:>8.2f}")
