"""
Replay today's boof51 entries on actual 1-min stock bars.
For each ENTRY logged, find when stock price hit TP or SL level first.
"""
import alpaca_trade_api as t
import pytz
from datetime import datetime
import re

ET = pytz.timezone("America/New_York")
api = t.REST('PKWKMWREJIGNRMBOQWORXFRMDS','7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW','https://paper-api.alpaca.markets')

LOG_FILE = "/Users/tybre/algorithims/boof51.log"  # will read locally via SSH dump
# Parse trades from log lines provided
raw = """
11:12:06  ENTRY  CLSK  +1bar open=17.1700  TP=17.0842  SL=17.2129
11:13:06  ENTRY  MU  +1bar open=1070.9800  TP=1065.6251  SL=1073.6574
11:13:06  ENTRY  MRVL  +1bar open=293.4100  TP=291.9429  SL=294.1435
11:20:25  ENTRY  ADBE  +1bar open=209.4850  TP=208.4376  SL=210.0087
11:28:08  ENTRY  TSLA  +1bar open=409.9400  TP=407.8903  SL=410.9648
11:28:09  ENTRY  MU  +1bar open=1071.8900  TP=1066.5306  SL=1074.5697
11:35:48  ENTRY  MU  +1bar open=1072.4400  TP=1067.0778  SL=1075.1211
11:36:48  ENTRY  TSLA  +1bar open=409.8150  TP=407.7659  SL=410.8395
11:47:23  ENTRY  TSLA  +1bar open=408.7650  TP=406.7212  SL=409.7869
11:57:34  ENTRY  HOOD  +1bar open=100.5200  TP=100.0174  SL=100.7713
12:06:31  ENTRY  AMD  +1bar open=547.1700  TP=544.4341  SL=548.5379
12:08:32  ENTRY  ADBE  +1bar open=209.9250  TP=208.8754  SL=210.4498
12:09:32  ENTRY  TSLA  +1bar open=409.2600  TP=407.2137  SL=410.2831
12:18:52  ENTRY  CLSK  +1bar open=17.4150  TP=17.3279  SL=17.4585
12:18:52  ENTRY  HOOD  +1bar open=100.4500  TP=99.9477  SL=100.7011
12:18:53  ENTRY  NVDA  +1bar open=212.2300  TP=211.1688  SL=212.7606
12:27:55  ENTRY  AVGO  +1bar open=393.3400  TP=391.3733  SL=394.3233
12:34:59  ENTRY  ADBE  +1bar open=209.7200  TP=208.6714  SL=210.2443
12:35:59  ENTRY  AMD  +1bar open=549.8900  TP=547.1405  SL=551.2647
12:37:00  ENTRY  PLTR  +1bar open=134.6500  TP=133.9768  SL=134.9866
12:41:01  ENTRY  TSLA  +1bar open=410.0700  TP=408.0197  SL=411.0952
12:42:02  ENTRY  NVDA  +1bar open=212.1800  TP=211.1191  SL=212.7105
12:48:00  ENTRY  MU  +1bar open=1075.9650  TP=1070.5852  SL=1078.6549
12:48:00  ENTRY  NVDA  +1bar open=212.1200  TP=211.0594  SL=212.6503
12:49:01  ENTRY  MRVL  +1bar open=301.0000  TP=299.4950  SL=301.7525
12:55:03  ENTRY  CLSK  +1bar open=17.4400  TP=17.3528  SL=17.4836
12:59:38  ENTRY  ADBE  +1bar open=207.4100  TP=206.3730  SL=207.9285
13:00:39  ENTRY  MRVL  +1bar open=300.8100  TP=299.3059  SL=301.5620
13:01:39  ENTRY  HOOD  +1bar open=99.1200  TP=98.6244  SL=99.3678
13:13:05  ENTRY  TSLA  +1bar open=409.2750  TP=407.2286  SL=410.2982
13:16:06  ENTRY  CLSK  +1bar open=17.4500  TP=17.3627  SL=17.4936
13:20:36  ENTRY  MU  +1bar open=1069.7000  TP=1064.3515  SL=1072.3743
13:21:37  ENTRY  MRVL  +1bar open=300.5500  TP=299.0473  SL=301.3014
13:25:06  ENTRY  TSLA  +1bar open=409.2400  TP=407.1938  SL=410.2631
13:25:06  ENTRY  HOOD  +1bar open=99.1400  TP=98.6443  SL=99.3879
13:30:44  ENTRY  CLSK  +1bar open=17.4700  TP=17.3826  SL=17.5137
""".strip().split("\n")

# Parse entries
entries = []
for line in raw:
    m = re.match(r"(\d+:\d+:\d+)\s+ENTRY\s+(\w+)\s+\+1bar open=([\d.]+)\s+TP=([\d.]+)\s+SL=([\d.]+)", line.strip())
    if m:
        t_str, sym, entry, tp, sl = m.groups()
        entries.append({
            "time": t_str,
            "sym": sym,
            "entry": float(entry),
            "tp": float(tp),
            "sl": float(sl),
        })

# Fetch bars for each unique symbol
print(f"Fetching bars for {len(set(e['sym'] for e in entries))} symbols...")
bars_cache = {}
for sym in set(e["sym"] for e in entries):
    try:
        df = api.get_bars(sym, '1Min', start='2026-06-15', feed='iex', limit=500).df.tz_convert(ET)
        bars_cache[sym] = df
        print(f"  {sym}: {len(df)} bars")
    except Exception as ex:
        print(f"  {sym}: FAILED {ex}")

# Replay each trade
wins = losses = timeouts = 0
results = []

for e in entries:
    sym   = e["sym"]
    entry = e["entry"]
    tp    = e["tp"]
    sl    = e["sl"]
    t_str = e["time"]

    if sym not in bars_cache:
        continue

    df = bars_cache[sym]
    # Find entry time
    h, m, s = map(int, t_str.split(":"))
    entry_dt = ET.localize(datetime(2026, 6, 15, h, m, s))

    after = df[df.index >= entry_dt]
    outcome = "TIMEOUT"
    exit_time = None
    bars_held = 0

    for ts, row in after.iterrows():
        bars_held += 1
        if row["low"] <= tp:
            outcome = "WIN"
            exit_time = ts.strftime("%H:%M")
            break
        if row["high"] >= sl:
            outcome = "LOSS"
            exit_time = ts.strftime("%H:%M")
            break
        if bars_held >= 60:
            outcome = "TIMEOUT"
            exit_time = ts.strftime("%H:%M")
            break

    results.append({**e, "outcome": outcome, "exit_time": exit_time, "bars": bars_held})
    if outcome == "WIN":    wins += 1
    elif outcome == "LOSS": losses += 1
    else:                   timeouts += 1

# Print table
print(f"\n{'Time':<8} {'Sym':<6} {'Entry':>8} {'TP':>8} {'SL':>8} {'Result':<8} {'Exit':>6} {'Bars':>5}")
print("-" * 65)
for r in results:
    print(f"{r['time']:<8} {r['sym']:<6} {r['entry']:>8.2f} {r['tp']:>8.2f} {r['sl']:>8.2f} {r['outcome']:<8} {str(r['exit_time']):>6} {r['bars']:>5}")

total = wins + losses + timeouts
wr = wins / total * 100 if total else 0
print(f"\nTotal: {total}  Wins: {wins}  Losses: {losses}  Timeouts: {timeouts}")
print(f"Win Rate (stock): {wr:.1f}%")
print(f"RR ratio: TP={abs(results[0]['entry']-results[0]['tp'])/results[0]['entry']*100:.2f}% / SL={abs(results[0]['sl']-results[0]['entry'])/results[0]['entry']*100:.2f}%")
