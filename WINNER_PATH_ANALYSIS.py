import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('WINNER PATH ANALYSIS - Do they hit 1% / 1.5% before 2%?')
print('='*80)

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

winners_data = []

print(f'Analyzing path for 79 winners from {len(CORE_UNIVERSE)} symbols...')
print()

for symbol in CORE_UNIVERSE:
    try:
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
                        tp2_level = entry * 1.02
                        tp1_5_level = entry * 1.015
                        tp1_level = entry * 1.01
                        sl_level = entry * 0.98
                        
                        future = pm_data.iloc[i+2:i+32]
                        
                        # Check what happens first
                        tp1_bar = None
                        tp1_5_bar = None
                        tp2_bar = None
                        sl_bar = None
                        
                        for j, (_, bar) in enumerate(future.iterrows()):
                            bar_num = j + 1
                            
                            if tp1_bar is None and bar['high'] >= tp1_level:
                                tp1_bar = bar_num
                            if tp1_5_bar is None and bar['high'] >= tp1_5_level:
                                tp1_5_bar = bar_num
                            if tp2_bar is None and bar['high'] >= tp2_level:
                                tp2_bar = bar_num
                            if sl_bar is None and bar['low'] <= sl_level:
                                sl_bar = bar_num
                            
                            # Stop checking once all found
                            if tp2_bar and sl_bar:
                                break
                        
                        # Only analyze winners (TP2 hit before SL)
                        if tp2_bar and (sl_bar is None or tp2_bar <= sl_bar):
                            winners_data.append({
                                'symbol': symbol,
                                'date': str(date),
                                'entry': entry,
                                'tp1_bar': tp1_bar,
                                'tp1_5_bar': tp1_5_bar,
                                'tp2_bar': tp2_bar,
                                'tp1_before_tp2': tp1_bar is not None and tp1_bar < tp2_bar if tp1_bar else False,
                                'tp1_5_before_tp2': tp1_5_bar is not None and tp1_5_bar < tp2_bar if tp1_5_bar else False,
                            })
        
    except Exception as e:
        pass

print(f'Analyzed {len(winners_data)} winners')
print()

# Calculate stats
hit_1pct_before = sum(1 for w in winners_data if w['tp1_before_tp2'])
hit_1_5pct_before = sum(1 for w in winners_data if w['tp1_5_before_tp2'])
total_winners = len(winners_data)

print('='*80)
print('WINNER PATH RESULTS')
print('='*80)
print()
print(f'Total winners (hit 2% TP): {total_winners}')
print()
print('Intermediate targets hit BEFORE 2%:')
print(f'  Hit +1% before +2%: {hit_1pct_before}/{total_winners} ({hit_1pct_before/total_winners*100:.1f}%)')
print(f'  Hit +1.5% before +2%: {hit_1_5pct_before}/{total_winners} ({hit_1_5pct_before/total_winners*100:.1f}%)')
print()

# Time analysis
print('Timing of intermediate hits:')
tp1_bars = [w['tp1_bar'] for w in winners_data if w['tp1_bar']]
tp1_5_bars = [w['tp1_5_bar'] for w in winners_data if w['tp1_5_bar']]
tp2_bars = [w['tp2_bar'] for w in winners_data]

if tp1_bars:
    print(f'  Avg bars to +1%: {sum(tp1_bars)/len(tp1_bars):.1f}')
if tp1_5_bars:
    print(f'  Avg bars to +1.5%: {sum(tp1_5_bars)/len(tp1_5_bars):.1f}')
print(f'  Avg bars to +2%: {sum(tp2_bars)/len(tp2_bars):.1f}')
print()

# Distribution of 1% hits within 2% time
print('Path characteristics:')
hit_1pct_very_early = sum(1 for w in winners_data if w['tp1_bar'] and w['tp1_bar'] <= 2)
print(f'  Hit 1% within 2 bars: {hit_1pct_very_early}/{total_winners} ({hit_1pct_very_early/total_winners*100:.1f}%)')

hit_1_5pct_very_early = sum(1 for w in winners_data if w['tp1_5_bar'] and w['tp1_5_bar'] <= 3)
print(f'  Hit 1.5% within 3 bars: {hit_1_5pct_very_early}/{total_winners} ({hit_1_5pct_very_early/total_winners*100:.1f}%)')

print()
print('='*80)
print('IMPLICATIONS FOR PARTIAL PROFIT TAKING')
print('='*80)
print(f'{hit_1pct_before/total_winners*100:.0f}% of winners pass through +1% first')
print(f'{hit_1_5pct_before/total_winners*100:.0f}% of winners pass through +1.5% first')
print()
print('Strategy options:')
print('  1. Scale out 50% at 1%, move stop to breakeven, let 50% run to 2%')
print('  2. Trail stop: Once +1.5% hit, move stop to +0.5% to lock gains')
print('  3. All-in to 2% (current): Simple, but misses intermediate profit capture')
print('='*80)
