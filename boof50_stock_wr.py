"""
Boof50 stock win rate — replay stock bars from entry time,
check if stock hit TP (+30%) or SL (-20%) direction first.
Boof50 is VWAP cross: long = stock above VWAP, short = stock below VWAP.
TP/SL are on the OPTION (1.30x / 0.80x), but we want to know
if the underlying stock moved in the right direction.
We'll check if stock moved >0.5% in trade direction (win) or >0.25% against (loss).
"""
import alpaca_trade_api as t
import pytz
from datetime import datetime

ET  = pytz.timezone("America/New_York")
api = t.REST('PKUE2IRNMB5ZUCK3ISPE3RIUX4','Cb3rxrN6SNSYkpYEbVn96i7FjM5KCBcpR8bLq7hKRciB','https://paper-api.alpaca.markets')

# (sym, side, entry_time_ET, entry_price_approx)
# Side: long = stock should go UP, short = stock should go DOWN
# Entry price pulled from option symbol + approximate stock price at that time
trades = [
    # Closed batch (11:13 - 11:21)
    ("TSLA",  "short", "11:13", 409.50),   # P00395000 — short = stock should fall
    ("NVDA",  "short", "11:01", 211.00),   # P00210000 — short
    ("COIN",  "long",  "11:15", 183.00),   # C00182500 — long = stock should rise
    ("TSLA",  "long",  "11:18", 412.00),   # C00417500 — long
    ("HOOD",  "long",  "11:20", 101.00),   # C00102000 — long
    ("MSFT",  "long",  "11:21", 400.00),   # C00407500 — long

    # Second batch (11:41 - 11:59)
    ("SMCI",  "long",  "11:41", 27.50),    # C00028000 — long
    ("TSLA",  "long",  "11:46", 422.00),   # C00427500 — long
    ("HOOD",  "short", "11:46", 100.50),   # P00100000 — short
    ("AMZN",  "long",  "11:44", 245.00),   # P00245000 — wait, P = short
    ("AMZN",  "short", "11:44", 245.00),   # P00245000 — short (put = bearish)
    ("HOOD",  "long",  "11:58", 99.50),    # C00099000 — long
    ("TSLA",  "short", "11:58", 404.00),   # P00402500 — short
    ("UPST",  "long",  "11:58", 32.00),    # C00032000 — long
    ("MSFT",  "short", "11:59", 398.00),   # P00397500 — short
    ("APP",   "short", "11:59", 271.00),   # P00270000 — short

    # Still open (pre-filters, various times)
    ("AMD",   "short", "10:30", 135.00),   # P00135000
    ("CRWD",  "short", "10:30", 156.00),   # P00155000
    ("MSFT",  "short", "09:45", 306.00),   # P00305000 — deep OTM
    ("MSTR",  "short", "10:30", 49.50),    # P00049000
]

# Remove duplicate AMZN
trades = [t for t in trades if not (t[0]=="AMZN" and t[2]=="11:44" and t[1]=="long")]

# Fetch bars
syms = list(set(t[0] for t in trades))
print(f"Fetching bars for: {', '.join(syms)}")
bars = {}
for sym in syms:
    try:
        df = api.get_bars(sym, '1Min', start='2026-06-15', feed='iex', limit=500).df.tz_convert(ET)
        bars[sym] = df
    except Exception as e:
        print(f"  {sym} FAILED: {e}")

TP_MOVE = 0.005   # 0.5% move in right direction = win
SL_MOVE = 0.0025  # 0.25% move against = loss

print(f"\n{'Sym':<6} {'Side':<6} {'Entry':<6} {'EntryPx':>8} {'Result':<8} {'Exit':>6} {'Move%':>7}")
print("-" * 55)

wins = losses = timeouts = 0
results = []

for sym, side, entry_t, entry_px in trades:
    if sym not in bars:
        continue
    df = bars[sym]
    h, m = map(int, entry_t.split(":"))
    entry_dt = ET.localize(datetime(2026, 6, 15, h, m, 0))
    after = df[df.index >= entry_dt]

    outcome = "TIMEOUT"
    exit_t = ""
    max_move = 0.0

    for ts, row in after.iterrows():
        if side == "long":
            up_move   = (row["high"]  - entry_px) / entry_px
            down_move = (entry_px - row["low"])   / entry_px
            if up_move >= TP_MOVE:
                outcome = "WIN"; exit_t = ts.strftime("%H:%M"); max_move = up_move; break
            if down_move >= SL_MOVE:
                outcome = "LOSS"; exit_t = ts.strftime("%H:%M"); max_move = -down_move; break
        else:  # short
            down_move = (entry_px - row["low"])   / entry_px
            up_move   = (row["high"]  - entry_px) / entry_px
            if down_move >= TP_MOVE:
                outcome = "WIN"; exit_t = ts.strftime("%H:%M"); max_move = down_move; break
            if up_move >= SL_MOVE:
                outcome = "LOSS"; exit_t = ts.strftime("%H:%M"); max_move = -up_move; break

    results.append((sym, side, entry_t, entry_px, outcome, exit_t, max_move))
    if outcome == "WIN":     wins += 1
    elif outcome == "LOSS":  losses += 1
    else:                    timeouts += 1

    print(f"{sym:<6} {side:<6} {entry_t:<6} {entry_px:>8.2f} {outcome:<8} {exit_t:>6} {max_move*100:>+6.2f}%")

total = wins + losses + timeouts
wr = wins/total*100 if total else 0
print("-" * 55)
print(f"Total: {total}  Wins: {wins}  Losses: {losses}  Timeouts: {timeouts}")
print(f"Stock Win Rate: {wr:.1f}%")
