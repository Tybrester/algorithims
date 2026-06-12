import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import glob
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 COMPREHENSIVE RUNNER ANALYSIS - BOTH TIME FRAMES')
print('='*80)

# API Setup
API_KEY = 'AKXYPKTGTYKE2PN2GPP4U5VJHU'
API_SECRET = '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

# 20 high-volume symbols
symbols = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX',
           'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR']

# 10 months of data
end_date = datetime(2025, 6, 30)
start_date = end_date - timedelta(days=300)

print(f'Symbols: {len(symbols)}')
print(f'Date range: {start_date.date()} to {end_date.date()}')
print()

runners_9_11 = []
runners_2_30 = []

for symbol in symbols:
    try:
        print(f'Processing {symbol}...', end=' ')
        
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start_date,
            end=end_date
        )
        bars = client.get_stock_bars(request)
        df = bars.df.reset_index()
        
        if len(df) < 1000:
            print(f'insufficient data ({len(df)} bars)')
            continue
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        df['date'] = df['timestamp'].dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['tp'] * df['volume']
        
        am_count = 0
        pm_count = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            
            # 9:30-11 AM Window
            mask_am = ((day['hour'] == 9) & (day['minute'] >= 30)) | (day['hour'] == 10)
            am_data = day[mask_am]
            
            for i in range(min(len(am_data) - 30, 30)):
                b1 = am_data.iloc[i]
                b2 = am_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            runners_9_11.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                            })
                            am_count += 1
            
            # 2:30-4 PM Window
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm]
            
            for i in range(min(len(pm_data) - 30, 30)):
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            runners_2_30.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                            })
                            pm_count += 1
        
        print(f'{len(df):,} bars, AM runners: {am_count}, PM runners: {pm_count}')
    except Exception as e:
        print(f'ERROR: {str(e)[:50]}')

print()
print('='*80)
print(f'FINAL RESULTS:')
print(f'9:30-11 AM: {len(runners_9_11)} runners (MFE >= 2%)')
print(f'2:30-4 PM: {len(runners_2_30)} runners (MFE >= 2%)')
print('='*80)

if runners_9_11:
    print()
    print('MORNING RUNNERS (9:30-11 AM):')
    for r in runners_9_11[:20]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_2_30:
    print()
    print('AFTERNOON RUNNERS (2:30-4 PM):')
    for r in runners_2_30[:20]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

# Save
if runners_9_11:
    pd.DataFrame(runners_9_11).to_csv('boof30_runners_9_11am.csv', index=False)
if runners_2_30:
    pd.DataFrame(runners_2_30).to_csv('boof30_runners_2_30_4pm.csv', index=False)

print()
print('CSV FILES SAVED:')
print('  - boof30_runners_9_11am.csv')
print('  - boof30_runners_2_30_4pm.csv')
print('='*80)
print('ANALYSIS COMPLETE')
print('='*80)
