from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

API_KEY = 'AKXYPKTGTYKE2PN2GPP4U5VJHU'
API_SECRET = '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'

print('Testing basic connection...')
print(f'Key prefix: {API_KEY[:8]}...')

try:
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    # Simple 5-day test
    end = datetime(2025, 6, 30)
    start = end - timedelta(days=5)
    
    request = StockBarsRequest(
        symbol_or_symbols='AAPL',
        timeframe=TimeFrame.Day,
        start=start,
        end=end
    )
    
    bars = client.get_stock_bars(request)
    df = bars.df.reset_index()
    print(f'SUCCESS: {len(df)} bars retrieved')
    print(df)
    
except Exception as e:
    print(f'ERROR: {e}')
    print(f'Error type: {type(e).__name__}')
