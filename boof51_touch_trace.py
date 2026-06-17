"""
Trace boof51 state machine for each missed trade to determine:
- Was it a fresh 1st touch (IDLE→IN→FIRED)?
- Or a re-touch after DEAD reset (DEAD→IDLE→IN→FIRED)?
"""
import alpaca_trade_api as t
import pytz
from datetime import datetime

api = t.REST('PKWKMWREJIGNRMBOQWORXFRMDS','7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW','https://paper-api.alpaca.markets')
ET  = pytz.timezone('America/New_York')

NEAR_PCT = 0.001   # 0.1% near zone
BOUNCE   = 0.0015  # 0.15% bounce required

def trace_sm(bars, level, sym, signal_time_str):
    """Replay state machine on bars up to signal time, show path."""
    sm = {"state": "IDLE", "extreme": None, "touch_num": 0, "was_below": False}
    resets = 0
    path = []

    for ts, row in bars.iterrows():
        t_str = ts.strftime("%H:%M")
        high  = row['high']; low = row['low']; close = row['close']

        prev_state = sm['state']
        touching   = sm['was_below'] and high >= level * (1 - NEAR_PCT)

        if close < level:
            sm['was_below'] = True

        if sm['state'] == 'IDLE':
            if touching:
                sm['state']    = 'IN'
                sm['extreme']  = close
                sm['touch_num'] += 1
                path.append(f"  {t_str} IDLE→IN  (h={high:.2f} c={close:.2f} touch#{sm['touch_num']})")

        elif sm['state'] == 'IN':
            if high >= level * (1 - NEAR_PCT):
                sm['extreme'] = min(sm['extreme'], close)
                path.append(f"  {t_str} IN→IN    (h={high:.2f} c={close:.2f} extreme={sm['extreme']:.2f})")
            else:
                bounce_pct = (level - sm['extreme']) / level if sm['extreme'] else 0
                bounced = bounce_pct >= BOUNCE
                if bounced and sm['touch_num'] == 1:
                    path.append(f"  {t_str} IN→FIRED (bounce={bounce_pct*100:.2f}%) *** SIGNAL ***")
                    sm['state'] = 'FIRED'
                    break
                else:
                    path.append(f"  {t_str} IN→DEAD  (bounce={bounce_pct*100:.2f}% needed 0.15%, touch#{sm['touch_num']})")
                    sm['state']     = 'DEAD'
                    sm['was_below'] = False

        elif sm['state'] == 'DEAD':
            if sm['was_below']:
                path.append(f"  {t_str} DEAD→IDLE (price went below {level:.2f} again — re-armed, reset #{resets+1})")
                sm['state']    = 'IDLE'
                sm['extreme']  = None
                sm['touch_num'] = 0
                resets += 1

        if t_str == signal_time_str:
            break

    return path, resets

TRADES = [
    ("CLSK", 17.2125, "11:11"),
    ("MU",   1076.42, "11:12"),
    ("MRVL", 294.277, "11:12"),
    ("TSLA", None,    "11:27"),  # need to find level
    ("HOOD", None,    "11:56"),
    ("AMD",  None,    "12:05"),
    ("ADBE", None,    "12:07"),
]

# Get levels from log
import subprocess
result = subprocess.run(
    ['ssh', '-i', r'C:\Users\tybre\Downloads\Boof Capital.pem',
     '-o', 'StrictHostKeyChecking=no',
     'ec2-user@3.16.45.99',
     "grep 'SIGNAL.*level=' ~/boof51.log | head -40"],
    capture_output=True, text=True
)
print("Signal levels from log:")
print(result.stdout)
