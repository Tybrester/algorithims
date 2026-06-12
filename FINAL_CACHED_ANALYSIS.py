import pandas as pd
import glob
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 RUNNER ANALYSIS - CACHED DATA - 20 STOCKS')
print('='*80)

# Get symbols from cache files
all_files = glob.glob('boof_cache/*_2024-01-01_2026-12-31.pkl')
print(f'Found {len(all_files)} cache files')

available_symbols = sorted(list(set([f.split('\\')[-1].split('_')[0] for f in all_files])))
print(f'Available symbols: {len(available_symbols)}')

# Top 20 liquid stocks
top_20 = ['TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX', 
          'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR']

# Use available symbols
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
            print(f'{symbol}: No cache file found')
            continue
        
        df = pd.read_pickle(files[0])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Last 6 months only
        cutoff = df['timestamp'].max() - pd.DateOffset(months=6)
        df = df[df['timestamp'] >= cutoff]
        
        if len(df) == 0:
            print(f'{symbol}: No recent data')
            continue
        
        print(f'{symbol}: {len(df):,} bars | Processing...')
        
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        df['date'] = df['timestamp'].dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['tp'] * df['volume']
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            # Calculate indicators
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
                
                # Boof 30 pattern
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        signal = {
                            'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                            'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                            'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                        }
                        signals_am.append(signal)
                        if mfe <= -0.02:
                            runners_am.append(signal)
            
            # 2:30-4 PM Window
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                # Boof 30 pattern
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close']
                        signal = {
                            'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                            'mfe': round(mfe*100,2), 'entry': round(b2['close'],2),
                            'rvol1': round(b1['rvol'],1), 'rvol2': round(b2['rvol'],1)
                        }
                        signals_pm.append(signal)
                        if mfe <= -0.02:
                            runners_pm.append(signal)
        
        print(f'  -> AM: {len(signals_am)} signals, {len(runners_am)} runners | PM: {len(signals_pm)} signals, {len(runners_pm)} runners')
        
    except Exception as e:
        print(f'{symbol}: ERROR - {str(e)[:50]}')

print()
print('='*80)
print('FINAL RESULTS')
print('='*80)
print(f'9:30-11 AM: {len(signals_am)} signals | {len(runners_am)} runners (MFE >= 2%)')
print(f'2:30-4 PM: {len(signals_pm)} signals | {len(runners_pm)} runners (MFE >= 2%)')
print('='*80)

if runners_am:
    print()
    print('MORNING RUNNERS (9:30-11 AM):')
    for r in runners_am[:15]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

if runners_pm:
    print()
    print('AFTERNOON RUNNERS (2:30-4 PM):')
    for r in runners_pm[:15]:
        print(f"  {r['symbol']} {r['date']} {r['time']} | Entry: {r['entry']} | RVOL: {r['rvol1']}x/{r['rvol2']}x | MFE: {r['mfe']}%")

# Save
if runners_am:
    pd.DataFrame(runners_am).to_csv('boof30_runners_9_11am.csv', index=False)
    print('\nSaved: boof30_runners_9_11am.csv')

if runners_pm:
    pd.DataFrame(runners_pm).to_csv('boof30_runners_2_30_4pm.csv', index=False)
    print('Saved: boof30_runners_2_30_4pm.csv')

if signals_am:
    pd.DataFrame(signals_am).to_csv('boof30_all_signals_9_11am.csv', index=False)
if signals_pm:
    pd.DataFrame(signals_pm).to_csv('boof30_all_signals_2_30_4pm.csv', index=False)

print('='*80)
print('ANALYSIS COMPLETE')
print('='*80)
