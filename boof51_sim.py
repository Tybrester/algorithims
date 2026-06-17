"""
Simulate boof51 missed trades using actual 1-min bar data from Alpaca.
Each trade: entry at open of signal bar+1, exit when stock hits TP (-0.50%) or SL (+0.25%), max 60 bars.
"""
import alpaca_trade_api as t
import pandas as pd
from datetime import datetime
import pytz

API_KEY    = "PKWKMWREJIGNRMBOQWORXFRMDS"
API_SECRET = "7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW"
BASE_URL   = "https://paper-api.alpaca.markets"
ET         = pytz.timezone("America/New_York")

api = t.REST(API_KEY, API_SECRET, BASE_URL)

TRADES = [
    ("CLSK",  "11:12", 17.17,   17.0842, 17.2129),
    ("MU",    "11:13", 1070.98, 1065.6251, 1073.6574),
    ("MRVL",  "11:13", 293.41,  291.9429, 294.1435),
    ("ADBE",  "11:20", 209.485, 208.4376, 210.0087),
    ("TSLA",  "11:28", 409.94,  407.8903, 410.9648),
    ("MU",    "11:28", 1071.89, 1066.5306, 1074.5697),
    ("MU",    "11:35", 1072.44, 1067.0778, 1075.1211),
    ("TSLA",  "11:36", 409.815, 407.7659, 410.8395),
    ("TSLA",  "11:47", 408.765, 406.7212, 409.7869),
    ("HOOD",  "11:57", 100.52,  100.0174, 100.7713),
    ("AMD",   "12:06", 547.17,  544.4341, 548.5379),
    ("ADBE",  "12:08", 209.925, 208.8754, 210.4498),
    ("TSLA",  "12:09", 409.26,  407.2137, 410.2831),
    ("CLSK",  "12:18", 17.415,  17.3279,  17.4585),
    ("HOOD",  "12:18", 100.45,  99.9477,  100.7011),
    ("NVDA",  "12:18", 212.23,  211.1688, 212.7606),
    ("AVGO",  "12:27", 393.34,  391.3733, 394.3233),
    ("ADBE",  "12:35", 209.72,  208.6714, 210.2443),
    ("AMD",   "12:36", 549.89,  547.1405, 551.2647),
    ("PLTR",  "12:37", 134.65,  133.9768, 134.9866),
    ("TSLA",  "12:41", 410.07,  408.0197, 411.0952),
    ("NVDA",  "12:42", 212.18,  211.1191, 212.7105),
    ("MU",    "12:48", 1075.965,1070.5852, 1078.6549),
    ("NVDA",  "12:48", 212.12,  211.0594, 212.6503),
    ("MRVL",  "12:49", 301.00,  299.4950, 301.7525),
    ("CLSK",  "12:55", 17.44,   17.3528,  17.4836),
]

# Fetch today's 1-min bars for all unique symbols
syms = list(set(t[0] for t in TRADES))
print("Fetching bars...")
bars = {}
for sym in syms:
    df = api.get_bars(sym, "1Min", start="2026-06-15", feed="iex", limit=400).df
    df = df.tz_convert(ET)
    bars[sym] = df

print(f"\n{'Sym':<6} {'Entry ET':<8} {'Entry $':>9} {'TP $':>9} {'SL $':>9} {'Result':<8} {'Exit $':>9} {'Stock %':>8} {'Bars':>5}")
print("-" * 80)

wins = losses = timeouts = 0
total_pct = 0.0

for sym, entry_time_str, entry, tp, sl in TRADES:
    df = bars.get(sym)
    if df is None or df.empty:
        print(f"{sym:<6} {entry_time_str:<8} — no data")
        continue

    # Find bar at or after entry time
    h, m = map(int, entry_time_str.split(":"))
    entry_dt = ET.localize(datetime(2026, 6, 15, h, m, 0))

    # Get bars from entry onward
    future = df[df.index >= entry_dt].head(61)
    if future.empty:
        print(f"{sym:<6} {entry_time_str:<8} — no bars after entry")
        continue

    result = "TIMEOUT"
    exit_price = future.iloc[-1]["close"]
    exit_bar = len(future)

    for i, (ts, row) in enumerate(future.iterrows()):
        if row["low"] <= tp:
            result = "TP WIN"
            exit_price = tp
            exit_bar = i + 1
            break
        if row["high"] >= sl:
            result = "SL LOSS"
            exit_price = sl
            exit_bar = i + 1
            break

    pct = (entry - exit_price) / entry * 100  # put gains when stock drops
    total_pct += pct
    if result == "TP WIN": wins += 1
    elif result == "SL LOSS": losses += 1
    else: timeouts += 1

    print(f"{sym:<6} {entry_time_str:<8} {entry:>9.2f} {tp:>9.2f} {sl:>9.2f} {result:<8} {exit_price:>9.2f} {pct:>+7.2f}% {exit_bar:>5}")

total = wins + losses + timeouts
print("-" * 80)
print(f"Wins: {wins}  Losses: {losses}  Timeouts: {timeouts}  Total: {total}")
print(f"Win Rate: {wins/total*100:.1f}%")
print(f"Avg stock move: {total_pct/total:+.3f}% per trade")
print()
print("Note: positive % = stock dropped (put gains), negative % = stock rose (put loses)")
