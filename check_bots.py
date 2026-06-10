from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import datetime, pytz

ET = pytz.timezone("America/New_York")
now   = datetime.datetime.now(ET)
start = now - datetime.timedelta(days=3)

bots = [
    ("Boof23", "PKAJ7LELQVQMPJPEJTGZDRT3XP", "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ"),
    ("Boof29", "PKU37C3QZHELGN2IDQLNYAEFJR", "CTcQtRqgC5SkKxo9q7sAn8iwTZt5CWWtvueiPjvbC22w"),
]

for label, key, secret in bots:
    print(f"\n{'='*40}")
    print(f"  {label}")
    try:
        tc   = TradingClient(key, secret, paper=True)
        dc   = StockHistoricalDataClient(key, secret)
        acct = tc.get_account()
        print(f"  Account:  OK  equity=${float(acct.equity):,.2f}  bp=${float(acct.buying_power):,.2f}")

        req  = StockBarsRequest(symbol_or_symbols="NVDA",
                                timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                                start=start, end=now, limit=10)
        bars = dc.get_stock_bars(req).df
        last = float(bars["close"].iloc[-1])
        print(f"  Bar feed: OK  NVDA 5-min bars={len(bars)}  last_close=${last:.2f}")
        print(f"  STATUS:   READY")
    except Exception as e:
        print(f"  ERROR: {e}")
