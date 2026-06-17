from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
tc = TradingClient('PK7QIKE4PJOJMAG23KEIZ2P6JF','AaiSUex556PSJGXagrSLkF7Ykti6qSZbYDBs2Ctd4uy8', paper=True)
for exp in ['2026-06-16','2026-06-17','2026-06-18','2026-06-19','2026-06-20']:
    req = GetOptionContractsRequest(underlying_symbols=['TSLA'], expiration_date=exp, type='put', limit=5)
    r = tc.get_option_contracts(req)
    n = len(r.option_contracts)
    print(f"{exp}: {n} contracts")
