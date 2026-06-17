import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

print('Testing Alpaca API with paper endpoint...')

# Paper API keys (if you have separate ones)
API_KEY = 'AKXYPKTGTYKE2PN2GPP4U5VJHU'
API_SECRET = '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'

# Try with paper=False (live) or paper=True
for paper in [True, False]:
    try:
        print(f'\nTrying paper={paper}...')
        client = StockHistoricalDataClient(API_KEY, API_SECRET, paper=paper)
        
        end = datetime(2025, 6, 30)
        start = end - timedelta(days=7)
        
        request = StockBarsRequest(
            symbol_or_symbols='AAPL',
            timeframe=TimeFrame.Day,
            start=start,
            end=end
        )
        bars = client.get_stock_bars(request)
        df = bars.df.reset_index()
        print(f'SUCCESS! Got {len(df)} bars')
        print(df.head(2))
        
    except Exception as e:
        print(f'FAILED: {str(e)[:100]}')
