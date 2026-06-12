import pandas as pd
import glob
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 RUNNER ANALYSIS - FIXED FOR CACHE STRUCTURE')
print('='*80)

# Test one file to see structure
test_files = glob.glob('boof_cache/TSLA_*.pkl')
if test_files:
    test_df = pd.read_pickle(test_files[0])
    print(f'Cache file structure: {list(test_df.columns)}')
    print(f'Sample data:')
    print(test_df.head(2))
    print()

# Get available symbols
all_files = glob.glob('boof_cache/*_2024-01-01_2026-12-31.pkl')
available_symbols = sorted(list(set([f.split('\\')[-1].split('_')[0] for f in all_files])))

# Top 20
top_20 = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX', 
          'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR']

symbols = [s for s in top_20 if s in available_symbols][:20]
if len(symbols) < 20:
    symbols = available_symbols[:20]

print(f'Processing {len(symbols)} symbols: {symbols}')
print('='*80)
print()

runners_am = []
runners_pm = []
signals_am = []
signals_pm = []

for symbol in symbols:
    try:
        files = glob.glob(f'boof_cache/{symbol}_2024-01-01_2026-12-31.pkl')
        if not files:
            print(f'{symbol}: No cache file')
            continue
        
        df = pd.read_pickle(files[0])
        
        # Cache files have timestamp in index named 't'
        df = df.reset_index()
        df.rename(columns={'t': 'timestamp'}, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Last 6 months
        cutoff = df['timestamp'].max() - pd.DateOffset(months=6)
        df = df[df['timestamp'] >= cutoff]
        
        if len(df) == 0:
            print(f'{symbol}: No recent data')
            continue
        
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
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        am_sig += 1
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
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        pm_sig += 1
                        if mfe <= -0.02:
                            runners_pm.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                            })
                            pm_run += 1
        
        signals_am.append({'symbol': symbol, 'count': am_sig})
        signals_pm.append({'symbol': symbol, 'count': pm_sig})
        
        if am_run > 0 or pm_run > 0:
            print(f'{symbol}: AM {am_sig} sig/{am_run} run | PM {pm_sig} sig/{pm_run} run')
        
    except Exception as e:
        print(f'{symbol}: ERROR - {str(e)[:60]}')

print()
print('='*80)
print('FINAL RESULTS')
print('='*80)
total_am_sig = sum(s['count'] for s in signals_am)
total_pm_sig = sum(s['count'] for s in signals_pm)
print(f'9:30-11 AM: {total_am_sig} signals | {len(runners_am)} runners (MFE >= 2%)')
print(f'2:30-4 PM: {total_pm_sig} signals | {len(runners_pm)} runners (MFE >= 2%)')
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

# Save
if runners_am:
    pd.DataFrame(runners_am).to_csv('boof30_runners_9_11am.csv', index=False)
    print('\nSaved: boof30_runners_9_11am.csv')

if runners_pm:
    pd.DataFrame(runners_pm).to_csv('boof30_runners_2_30_4pm.csv', index=False)
    print('Saved: boof30_runners_2_30_4pm.csv')

print('='*80)
print('COMPLETE')
print('='*80)
