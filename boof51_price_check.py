import alpaca_trade_api as t
import pytz
from datetime import datetime

api = t.REST('PKWKMWREJIGNRMBOQWORXFRMDS','7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW','https://paper-api.alpaca.markets')
ET = pytz.timezone('America/New_York')

checks = [
    ('CLSK',  11, 12, 17.17,   17.08, 17.21, "SL 4 bars"),
    ('MU',    11, 13, 1070.98, 1065.63, 1073.66, "SL 2 bars"),
    ('TSLA',  11, 28, 409.94,  407.89, 410.96, "SL 5 bars"),
    ('HOOD',  11, 57, 100.52,  100.02, 100.77, "SL 1 bar"),
    ('ADBE',  12,  8, 209.93,  208.88, 210.45, "TP 32 bars"),
    ('HOOD',  12, 18, 100.45,   99.95, 100.70, "TP 18 bars"),
]

for sym, h, m, entry, tp, sl, result in checks:
    df = api.get_bars(sym, '1Min', start='2026-06-15', feed='iex', limit=400).df.tz_convert(ET)
    entry_dt = ET.localize(datetime(2026, 6, 15, h, m, 0))
    window = df[df.index >= entry_dt].head(6)
    print(f"{sym} {h}:{m:02d}  entry={entry}  TP={tp}  SL={sl}  -> {result}")
    print(f"  {'Time':<6} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8}")
    for ts, row in window.iterrows():
        marker = ""
        if row['high'] >= sl: marker = " <- SL HIT"
        if row['low'] <= tp:  marker = " <- TP HIT"
        print(f"  {ts.strftime('%H:%M'):<6} {row['open']:>8.2f} {row['high']:>8.2f} {row['low']:>8.2f} {row['close']:>8.2f}{marker}")
    print()
