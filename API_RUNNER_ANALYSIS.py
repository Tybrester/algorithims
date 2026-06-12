import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 RUNNER ANALYSIS - API CALLS - 6 MONTHS - 20 STOCKS')
print('='*80)

API_KEY = 'AKXYPKTGTYKE2PN2GPP4U5VJHU'
API_SECRET = '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

symbols = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX',
           'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR']

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)  # 6 months

print(f'Symbols ({len(symbols)}): {symbols}')
print(f'Date range: {start.date()} to {end.date()}')
print('='*80)
print()

runners_9_11 = []
runners_2_30 = []
all_signals_am = []
all_signals_pm = []

for symbol in symbols:
    try:
        print(f'Fetching {symbol}... ', end='', flush=True)
        
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
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
        
        am_sig = 0
        pm_sig = 0
        am_run = 0
        pm_run = 0
        
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
            am_data = day[mask_am].reset_index(drop=True)
            
            for i in range(min(len(am_data) - 30, 40)):
                b1 = am_data.iloc[i]
                b2 = am_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    am_sig += 1
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        all_signals_am.append({'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                               'mfe': round(mfe*100,2), 'entry': round(b2['close'],2)})
                        if mfe <= -0.02:
                            runners_9_11.append({'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                                 'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                                 'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)})
                            am_run += 1
            
            # 2:30-4 PM Window
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            for i in range(min(len(pm_data) - 30, 40)):
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    pm_sig += 1
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        all_signals_pm.append({'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                               'mfe': round(mfe*100,2), 'entry': round(b2['close'],2)})
                        if mfe <= -0.02:
                            runners_2_30.append({'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                                 'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                                 'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)})
                            pm_run += 1
        
        print(f'{len(df):,} bars | Signals: AM={am_sig}, PM={pm_sig} | Runners: AM={am_run}, PM={pm_run}')
    except Exception as e:
        print(f'ERROR: {str(e)[:60]}')

print()
print('='*80)
print('FINAL RESULTS')
print('='*80)
print(f'9:30-11 AM: {len(all_signals_am)} total signals, {len(runners_9_11)} runners (MFE >= 2%)')
print(f'2:30-4 PM: {len(all_signals_pm)} total signals, {len(runners_2_30)} runners (MFE >= 2%)')
print('='*80)

if runners_9_11:
    print()
    print('MORNING RUNNERS (9:30-11 AM) - MFE >= 2%:')
    for r in runners_9_11[:20]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_2_30:
    print()
    print('AFTERNOON RUNNERS (2:30-4 PM) - MFE >= 2%:')
    for r in runners_2_30[:20]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

# Save
if runners_9_11:
    pd.DataFrame(runners_9_11).to_csv('boof30_runners_9_11am.csv', index=False)
if runners_2_30:
    pd.DataFrame(runners_2_30).to_csv('boof30_runners_2_30_4pm.csv', index=False)

if all_signals_am:
    pd.DataFrame(all_signals_am).to_csv('boof30_all_signals_9_11am.csv', index=False)
if all_signals_pm:
    pd.DataFrame(all_signals_pm).to_csv('boof30_all_signals_2_30_4pm.csv', index=False)

print()
print('FILES SAVED:')
if runners_9_11:
    print('  - boof30_runners_9_11am.csv')
if runners_2_30:
    print('  - boof30_runners_2_30_4pm.csv')
if all_signals_am:
    print('  - boof30_all_signals_9_11am.csv')
if all_signals_pm:
    print('  - boof30_all_signals_2_30_4pm.csv')
print('='*80)
print('COMPLETE')
print('='*80)
