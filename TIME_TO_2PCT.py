import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('TIME TO 2% TARGET ANALYSIS')
print('='*80)

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

tp_times = []  # Bars to hit 2% TP
sl_times = []  # Bars to hit 2% SL
no_tp = []     # Never hit 2% TP

print(f'Analyzing time-to-target for {len(CORE_UNIVERSE)} symbols...')
print()

for symbol in CORE_UNIVERSE:
    try:
        print(f'{symbol}: ', end='', flush=True)
        
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
        )
        bars = client.get_stock_bars(request)
        df = bars.df.reset_index()
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        df['date'] = df['timestamp'].dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['tp'] * df['volume']
        
        signals = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
            
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            if len(pm_data) < 35:
                continue
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    score = 0
                    if b1['rvol'] > 8: score += 1
                    if b1['body'] * 100 > 0.9: score += 1
                    if b1['vwap_slope'] > 0.25: score += 1
                    if b2['body'] * 100 > 0.5: score += 1
                    
                    if score >= 3:
                        entry = b2['close']
                        tp_level = entry * 1.02
                        sl_level = entry * 0.98
                        
                        future = pm_data.iloc[i+2:i+32]  # Next 30 bars
                        
                        tp_bar = None
                        sl_bar = None
                        
                        for j, (_, bar) in enumerate(future.iterrows()):
                            if tp_bar is None and bar['high'] >= tp_level:
                                tp_bar = j + 1
                            if sl_bar is None and bar['low'] <= sl_level:
                                sl_bar = j + 1
                            if tp_bar is not None and sl_bar is not None:
                                break
                        
                        if tp_bar is not None and (sl_bar is None or tp_bar <= sl_bar):
                            tp_times.append(tp_bar)
                        elif sl_bar is not None and (tp_bar is None or sl_bar < tp_bar):
                            sl_times.append(sl_bar)
                        else:
                            no_tp.append(30)  # Max bars, didn't hit
                        
                        signals += 1
        
        print(f'{signals} signals')
        
    except Exception as e:
        print(f'ERROR: {str(e)[:40]}')

print()
print('='*80)
print('TIME TO 2% TARGET RESULTS')
print('='*80)

total = len(tp_times) + len(sl_times) + len(no_tp)
print(f'Total trades: {total}')
print()

if tp_times:
    print(f'2% TP Hit: {len(tp_times)} trades ({len(tp_times)/total*100:.1f}%)')
    print(f'  Fastest: {min(tp_times)} bar')
    print(f'  Avg time: {sum(tp_times)/len(tp_times):.1f} bars ({sum(tp_times)/len(tp_times):.1f} min)')
    print(f'  Median: {sorted(tp_times)[len(tp_times)//2]} bars')
    print(f'  Slowest: {max(tp_times)} bars')
    print()
    print('TP Distribution:')
    for t in [1, 2, 3, 5, 10, 15, 20, 30]:
        count = sum(1 for x in tp_times if x <= t)
        pct = count / len(tp_times) * 100
        print(f'  Within {t} bars: {count}/{len(tp_times)} ({pct:.1f}%)')
    print()

if sl_times:
    print(f'2% SL Hit: {len(sl_times)} trades ({len(sl_times)/total*100:.1f}%)')
    print(f'  Fastest: {min(sl_times)} bar')
    print(f'  Avg time: {sum(sl_times)/len(sl_times):.1f} bars ({sum(sl_times)/len(sl_times):.1f} min)')
    print(f'  Median: {sorted(sl_times)[len(sl_times)//2]} bars')
    print(f'  Slowest: {max(sl_times)} bars')
    print()
    print('SL Distribution:')
    for t in [1, 2, 3, 5, 10, 15]:
        count = sum(1 for x in sl_times if x <= t)
        pct = count / len(sl_times) * 100
        print(f'  Within {t} bars: {count}/{len(sl_times)} ({pct:.1f}%)')
    print()

if no_tp:
    print(f'Neither hit in 30 bars: {len(no_tp)} trades ({len(no_tp)/total*100:.1f}%)')
    
print('='*80)
print('SUMMARY')
print('='*80)
win_rate = len(tp_times) / total * 100
print(f'Win rate to 2%: {win_rate:.1f}%')
if tp_times:
    print(f'Avg winner time: {sum(tp_times)/len(tp_times):.1f} min')
if sl_times:
    print(f'Avg loser time: {sum(sl_times)/len(sl_times):.1f} min')
print('='*80)
