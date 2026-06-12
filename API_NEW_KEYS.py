import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 RUNNER ANALYSIS - NEW API KEYS - 20 STOCKS - 6 MONTHS')
print('='*80)

# NEW API credentials
API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

symbols = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX',
           'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR']

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

print(f'Symbols: {len(symbols)}')
print(f'Date range: {start.date()} to {end.date()}')
print('='*80)
print()

# Test connection first
print('Testing API connection...')
try:
    test_req = StockBarsRequest(symbol_or_symbols='AAPL', timeframe=TimeFrame.Day, 
                                start=end-timedelta(days=5), end=end)
    test_bars = client.get_stock_bars(test_req)
    print(f'API connection: SUCCESS ({len(test_bars.df)} test bars)')
except Exception as e:
    print(f'API connection: FAILED - {str(e)[:80]}')
    exit(1)

print()

runners_am = []
runners_pm = []

for symbol in symbols:
    try:
        print(f'{symbol}: Fetching... ', end='', flush=True)
        
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
        )
        bars = client.get_stock_bars(request)
        df = bars.df.reset_index()
        
        print(f'{len(df):,} bars | Processing...')
        
        if len(df) < 1000:
            print(f'  -> Insufficient data')
            continue
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        df['date'] = df['timestamp'].dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['tp'] * df['volume']
        
        am_sig = am_run = pm_sig = pm_run = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            
            # 9:30-11 AM
            mask_am = ((day['hour'] == 9) & (day['minute'] >= 30)) | (day['hour'] == 10)
            am_data = day[mask_am].reset_index(drop=True)
            
            for i in range(len(am_data) - 30):
                if i + 1 >= len(am_data):
                    continue
                b1 = am_data.iloc[i]
                b2 = am_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    am_sig += 1
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            runners_am.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                            })
                            am_run += 1
            
            # 2:30-4 PM
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    pm_sig += 1
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            runners_pm.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                            })
                            pm_run += 1
        
        print(f'  -> AM: {am_sig} signals, {am_run} runners | PM: {pm_sig} signals, {pm_run} runners')
        
    except Exception as e:
        print(f'  -> ERROR: {str(e)[:50]}')

print()
print('='*80)
print('FINAL RESULTS')
print('='*80)
print(f'9:30-11 AM: {len(runners_am)} runners (MFE >= 2%)')
print(f'2:30-4 PM: {len(runners_pm)} runners (MFE >= 2%)')
print('='*80)

if runners_am:
    print()
    print('MORNING RUNNERS (9:30-11 AM):')
    for r in runners_am[:20]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_pm:
    print()
    print('AFTERNOON RUNNERS (2:30-4 PM):')
    for r in runners_pm[:20]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_am:
    pd.DataFrame(runners_am).to_csv('boof30_runners_9_11am.csv', index=False)
    print('\nSaved: boof30_runners_9_11am.csv')
if runners_pm:
    pd.DataFrame(runners_pm).to_csv('boof30_runners_2_30_4pm.csv', index=False)
    print('Saved: boof30_runners_2_30_4pm.csv')

print('='*80)
print('COMPLETE')
print('='*80)
