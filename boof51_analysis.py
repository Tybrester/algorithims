"""
Analyze boof51 trades from today — match buys to sells, compute option P&L,
then replay stock bars to get stock-level W/L.
"""
import alpaca_trade_api as t
import pytz
from datetime import datetime

ET  = pytz.timezone("America/New_York")
api = t.REST('PKWKMWREJIGNRMBOQWORXFRMDS','7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW','https://paper-api.alpaca.markets')

# Matched pairs: (opt_sym, underlying, qty, buy_fill, sell_fill, buy_time, sell_time)
trades = [
    # TSLA first batch
    ("TSLA260617P00400000", "TSLA", 1, 2.87, 2.64, "11:13", "11:18"),   # L
    # CLSK first batch  
    ("CLSK260618P00020000", "CLSK", 1, 2.97, 2.43, "11:16", "11:18"),   # L
    # MU
    ("MU260618P00870000",   "MU",   1, 3.00, 2.76, "11:20", "11:26"),   # L
    # MRVL
    ("MRVL260618P00265000", "MRVL", 1, 2.93, 2.68, "11:21", "11:26"),   # L
    # TSLA second
    ("TSLA260617P00400000", "TSLA", 1, 2.84, 2.80, "11:25", "11:26"),   # L
    # HOOD first
    ("HOOD260618P00096000", "HOOD", 2, 1.55, 1.49, "11:25", "11:26"),   # L
    # CLSK second
    ("CLSK260618P00018500", "CLSK", 2, 1.32, 1.20, "11:30", "11:39"),   # L
    # NVDA first
    ("NVDA260617P00210000", "NVDA", 2, 1.55, 1.53, "11:44", "11:46"),   # L
    # AMD
    ("AMD260618P00500000",  "AMD",  1, 3.10, 2.96, "11:49", "12:53"),   # L
    # ADBE
    ("ADBE260618P00207500", "ADBE", 1, 3.55, 3.55, "11:49", "12:50"),   # B/E
    # HOOD second
    ("HOOD260618P00096000", "HOOD", 2, 1.54, 1.48, "11:50", "12:51"),   # L
    # CLSK third
    ("CLSK260618P00019000", "CLSK", 2, 1.67, 1.69, "11:52", "12:00"),   # W
    # COIN
    ("COIN260618P00167500", "COIN", 1, 3.15, 3.25, "11:54", "12:42"),   # W
    # NVDA second
    ("NVDA260617P00212500", "NVDA", 1, 2.80, 2.40, "11:59", "12:59"),   # L
]

# Option P&L
print("=" * 75)
print("OPTION P&L")
print(f"{'Opt':<28} {'Qty':>3} {'Buy':>5} {'Sell':>5} {'P&L$':>7} {'Hold':>8} {'Result'}")
print("-" * 75)

total_opt_pl = 0
opt_wins = opt_losses = 0

for opt_sym, sym, qty, buy, sell, bt, st in trades:
    pl = (sell - buy) * qty * 100
    hold = f"{bt}-{st}"
    result = "WIN" if pl > 0 else ("B/E" if pl == 0 else "LOSS")
    if pl > 0: opt_wins += 1
    elif pl < 0: opt_losses += 1
    total_opt_pl += pl
    print(f"{opt_sym:<28} {qty:>3} {buy:>5.2f} {sell:>5.2f} {pl:>+7.0f}  {hold:<13} {result}")

print("-" * 75)
print(f"Option P&L: ${total_opt_pl:+.0f}  ({opt_wins}W / {opt_losses}L)")

# Now replay stock bars
print()
print("=" * 75)
print("STOCK WIN RATE (did stock move in put direction?)")
print(f"{'Sym':<6} {'Entry':>6} {'Entry$':>8} {'TP%':>6} {'SL%':>6} {'Result':<8} {'Exit':>6} {'Bars':>5}")
print("-" * 55)

syms = list(set(t[1] for t in trades))
bars = {}
for sym in syms:
    try:
        df = api.get_bars(sym, '1Min', start='2026-06-15', feed='iex', limit=500).df.tz_convert(ET)
        bars[sym] = df
    except Exception as e:
        print(f"  {sym} FAILED: {e}")

TP_PCT = 0.0050
SL_PCT = 0.0050

stock_wins = stock_losses = stock_timeouts = 0
stock_results = []

for opt_sym, sym, qty, buy, sell, bt, st in trades:
    if sym not in bars:
        continue
    df = bars[sym]
    h, m = map(int, bt.split(":"))
    entry_dt = ET.localize(datetime(2026, 6, 15, h, m, 0))
    after = df[df.index >= entry_dt]
    if after.empty:
        continue
    entry_px = after.iloc[0]["open"]

    outcome = "TIMEOUT"
    exit_t = ""
    bars_held = 0

    for ts, row in after.iterrows():
        bars_held += 1
        # put = short = stock should go DOWN
        down_move = (entry_px - row["low"])  / entry_px
        up_move   = (row["high"] - entry_px) / entry_px
        if down_move >= TP_PCT:
            outcome = "WIN";  exit_t = ts.strftime("%H:%M"); break
        if up_move >= SL_PCT:
            outcome = "LOSS"; exit_t = ts.strftime("%H:%M"); break
        if bars_held >= 60:
            outcome = "TIMEOUT"; exit_t = ts.strftime("%H:%M"); break

    stock_results.append((sym, bt, entry_px, outcome, exit_t, bars_held))
    if outcome == "WIN":     stock_wins += 1
    elif outcome == "LOSS":  stock_losses += 1
    else:                    stock_timeouts += 1

    print(f"{sym:<6} {bt:>6} {entry_px:>8.2f} {TP_PCT*100:>5.2f}% {SL_PCT*100:>5.2f}% {outcome:<8} {exit_t:>6} {bars_held:>5}")

total_stock = stock_wins + stock_losses + stock_timeouts
wr = stock_wins / total_stock * 100 if total_stock else 0
print("-" * 55)
print(f"Stock Trades: {total_stock}  Wins: {stock_wins}  Losses: {stock_losses}  Timeouts: {stock_timeouts}")
print(f"Stock Win Rate: {wr:.1f}%")
print()
print(f"SUMMARY: {len(trades)} option trades | Opt P&L ${total_opt_pl:+.0f} | Stock WR {wr:.1f}%")
