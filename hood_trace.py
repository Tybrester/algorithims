import alpaca_trade_api as t
import pytz
from datetime import datetime

api = t.REST('PKWKMWREJIGNRMBOQWORXFRMDS','7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW','https://paper-api.alpaca.markets')
ET = pytz.timezone('America/New_York')

df = api.get_bars('HOOD','1Min',start='2026-06-15',feed='iex',limit=400).df.tz_convert(ET)
start  = ET.localize(datetime(2026,6,15,11,50,0))
end    = ET.localize(datetime(2026,6,15,12,25,0))
window = df[(df.index >= start) & (df.index <= end)]
level  = 100.795
NEAR   = 0.001
BOUNCE = 0.0015

print(f"HOOD level={level}  signal=12:17  entry=12:18 @ 100.45")
print(f"{'Time':<6} {'Open':>6} {'High':>6} {'Low':>6} {'Close':>6}  State  Note")
print("-"*70)

state    = "IDLE"
was_below = False
extreme  = None
touch_num = 0
broken   = False

for ts, row in window.iterrows():
    h = row['high']; c = row['close']
    prev_state = state

    if c < level:
        was_below = True

    touching = was_below and h >= level * (1 - NEAR)

    if state == "IDLE":
        if touching:
            state = "IN"
            extreme = c
            touch_num += 1

    elif state == "IN":
        if h >= level * (1 - NEAR):
            extreme = min(extreme, c)
        else:
            bounce_pct = (level - extreme) / level if extreme else 0
            req = 2 if broken else 1
            if bounce_pct >= BOUNCE and touch_num == req:
                state = "FIRED"
            else:
                state = "DEAD"
                broken = True
                was_below = False

    elif state == "DEAD":
        if was_below:
            state = "IDLE"
            extreme = None
            touch_num = 0

    note = ""
    if h >= level: note = "TOUCHES LEVEL"
    if state != prev_state: note += f"  {prev_state}->{state}"

    print(f"{ts.strftime('%H:%M'):<6} {row['open']:>6.2f} {h:>6.2f} {row['low']:>6.2f} {c:>6.2f}  {state:<6} {note}")
