import pandas as pd
import glob
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 CACHED DATA ANALYSIS - 20 STOCKS, 10 MONTHS')
print('='*80)

# Get available symbols from cache
all_files = glob.glob('boof_cache/*_2024-01-01_2026-12-31.pkl')
symbols = sorted(list(set([f.split('\\')[-1].split('_')[0] for f in all_files])))

# Top 20 liquid stocks
top_symbols = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX', 
               'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR']

# Use available symbols
symbols_to_use = [s for s in top_symbols if s in symbols][:20]
if len(symbols_to_use) < 20:
    symbols_to_use = symbols[:20]

print(f'Processing {len(symbols_to_use)} symbols: {symbols_to_use}')
print()

runners_9_11 = []
runners_2_30 = []

for symbol in symbols_to_use:
    try:
        files = glob.glob(f'boof_cache/{symbol}_2024-01-01_2026-12-31.pkl')
        if not files:
            print(f'{symbol}: No cache file')
            continue
        
        df = pd.read_pickle(files[0])
        
        # Last 10 months
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        cutoff = df['timestamp'].max() - pd.DateOffset(months=10)
        df = df[df['timestamp'] >= cutoff]
        
        print(f'{symbol}: {len(df):,} bars', end=' -> ')
        
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
            
            # 9:30-11 AM
            mask_am = ((day['hour'] == 9) & (day['minute'] >= 30)) | (day['hour'] == 10)
            am_data = day[mask_am]
            for i in range(min(len(am_data) - 30, 30)):
                b1, b2 = am_data.iloc[i], am_data.iloc[i+1]
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            runners_9_11.append({'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                                 'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                                 'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)})
                            am_count += 1
            
            # 2:30-4 PM
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm]
            for i in range(min(len(pm_data) - 30, 30)):
                b1, b2 = pm_data.iloc[i], pm_data.iloc[i+1]
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        if mfe <= -0.02:
                            runners_2_30.append({'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                                 'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                                                 'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)})
                            pm_count += 1
        
        print(f'AM: {am_count}, PM: {pm_count}')
    except Exception as e:
        print(f'{symbol}: {str(e)[:30]}')

print()
print('='*80)
print(f'RESULTS: 9:30-11 AM = {len(runners_9_11)} runners | 2:30-4 PM = {len(runners_2_30)} runners')
print('='*80)

if runners_9_11:
    print('\nMORNING RUNNERS (9:30-11 AM):')
    for r in runners_9_11[:15]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_2_30:
    print('\nAFTERNOON RUNNERS (2:30-4 PM):')
    for r in runners_2_30[:15]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_9_11:
    pd.DataFrame(runners_9_11).to_csv('boof30_runners_9_11am.csv', index=False)
if runners_2_30:
    pd.DataFrame(runners_2_30).to_csv('boof30_runners_2_30_4pm.csv', index=False)

print()
print('FILES SAVED: boof30_runners_9_11am.csv, boof30_runners_2_30_4pm.csv')
print('='*80)
