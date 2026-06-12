import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 LONG & SHORT RUNNER ANALYSIS - 20 STOCKS - 6 MONTHS')
print('='*80)

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

# SHORTS (existing logic)
shorts_am = []
shorts_pm = []
# LONGS (reversed logic)
longs_am = []
longs_pm = []

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
        
        s_am = s_pm = l_am = l_pm = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            
            # 9:30-11 AM Window
            mask_am = ((day['hour'] == 9) & (day['minute'] >= 30)) | (day['hour'] == 10)
            am_data = day[mask_am].reset_index(drop=True)
            
            for i in range(len(am_data) - 30):
                if i + 1 >= len(am_data):
                    continue
                b1 = am_data.iloc[i]
                b2 = am_data.iloc[i+1]
                
                # SHORTS: close < vwap, b2 close < b1 low
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            shorts_am.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1),
                                'side': 'short'
                            })
                            s_am += 1
                
                # LONGS: close > vwap, b2 close > b1 high
                elif (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                      b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['high'].max() - b2['close']) / b2['close']
                        if mfe >= 0.02:
                            longs_am.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1),
                                'side': 'long'
                            })
                            l_am += 1
            
            # 2:30-4 PM Window
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                # SHORTS
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            shorts_pm.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1),
                                'side': 'short'
                            })
                            s_pm += 1
                
                # LONGS
                elif (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                      b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['high'].max() - b2['close']) / b2['close']
                        if mfe >= 0.02:
                            longs_pm.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1),
                                'side': 'long'
                            })
                            l_pm += 1
        
        if s_am or s_pm or l_am or l_pm:
            print(f'  -> AM: {s_am}S/{l_am}L | PM: {s_pm}S/{l_pm}L')
        else:
            print(f'  -> No runners')
        
    except Exception as e:
        print(f'  -> ERROR: {str(e)[:50]}')

print()
print('='*80)
print('FINAL RESULTS')
print('='*80)
print(f'9:30-11 AM: {len(shorts_am)} shorts, {len(longs_am)} longs')
print(f'2:30-4 PM: {len(shorts_pm)} shorts, {len(longs_pm)} longs')
print('='*80)

# Combine all
all_signals = shorts_am + longs_am + shorts_pm + longs_pm

if all_signals:
    df_out = pd.DataFrame(all_signals)
    df_out.to_csv('boof30_long_short_runners.csv', index=False)
    print('\nSaved: boof30_long_short_runners.csv')

print('='*80)
print('COMPLETE')
print('='*80)
