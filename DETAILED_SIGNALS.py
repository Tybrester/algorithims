import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import numpy as np
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF30 DETAILED SIGNAL ANALYSIS - 20 STOCKS - 6 MONTHS')
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

all_signals = []

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
        
        print(f'{len(df):,} bars')
        
        if len(df) < 1000:
            continue
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        df['date'] = df['timestamp'].dt.date
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['tp'] * df['volume']
        
        count = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            # Calculate VWAP and slope
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            
            # VWAP slope (10-bar trend)
            day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
            
            # Distance from close to vwap
            day['close_vs_vwap'] = (day['close'] - day['vwap']) / day['vwap'] * 100
            
            # 9:30-11 AM Window
            mask_am = ((day['hour'] == 9) & (day['minute'] >= 30)) | (day['hour'] == 10)
            am_data = day[mask_am].reset_index(drop=True)
            
            for i in range(len(am_data) - 30):
                if i + 1 >= len(am_data):
                    continue
                b1 = am_data.iloc[i]
                b2 = am_data.iloc[i+1]
                
                # SHORT criteria
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close'] * 100
                        
                        all_signals.append({
                            'symbol': symbol,
                            'date': str(date),
                            'time': str(b1['timestamp'].time())[:8],
                            'window': '9:30-11AM',
                            'direction': 'short',
                            'entry': round(b2['close'], 2),
                            'mfe': round(mfe, 2),
                            'bar1_body_pct': round(b1['body'] * 100, 2),
                            'bar2_body_pct': round(b2['body'] * 100, 2),
                            'bar1_rvol': round(b1['rvol'], 1),
                            'bar2_rvol': round(b2['rvol'], 1),
                            'bar1_close_vs_vwap': round(b1['close_vs_vwap'], 2),
                            'bar2_close_vs_vwap': round(b2['close_vs_vwap'], 2),
                            'vwap_slope': round(b1['vwap_slope'], 3) if not pd.isna(b1['vwap_slope']) else 0,
                            'is_runner': 1 if mfe <= -2.0 else 0
                        })
                        count += 1
                
                # LONG criteria
                elif (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                      b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    future = am_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                        
                        all_signals.append({
                            'symbol': symbol,
                            'date': str(date),
                            'time': str(b1['timestamp'].time())[:8],
                            'window': '9:30-11AM',
                            'direction': 'long',
                            'entry': round(b2['close'], 2),
                            'mfe': round(mfe, 2),
                            'bar1_body_pct': round(b1['body'] * 100, 2),
                            'bar2_body_pct': round(b2['body'] * 100, 2),
                            'bar1_rvol': round(b1['rvol'], 1),
                            'bar2_rvol': round(b2['rvol'], 1),
                            'bar1_close_vs_vwap': round(b1['close_vs_vwap'], 2),
                            'bar2_close_vs_vwap': round(b2['close_vs_vwap'], 2),
                            'vwap_slope': round(b1['vwap_slope'], 3) if not pd.isna(b1['vwap_slope']) else 0,
                            'is_runner': 1 if mfe >= 2.0 else 0
                        })
                        count += 1
            
            # 2:30-4 PM Window
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                # SHORT
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] < b1['vwap'] and b2['close'] < b2['vwap'] and b2['close'] < b1['low']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['low'].min() - b2['close']) / b2['close'] * 100
                        
                        all_signals.append({
                            'symbol': symbol,
                            'date': str(date),
                            'time': str(b1['timestamp'].time())[:8],
                            'window': '2:30-4PM',
                            'direction': 'short',
                            'entry': round(b2['close'], 2),
                            'mfe': round(mfe, 2),
                            'bar1_body_pct': round(b1['body'] * 100, 2),
                            'bar2_body_pct': round(b2['body'] * 100, 2),
                            'bar1_rvol': round(b1['rvol'], 1),
                            'bar2_rvol': round(b2['rvol'], 1),
                            'bar1_close_vs_vwap': round(b1['close_vs_vwap'], 2),
                            'bar2_close_vs_vwap': round(b2['close_vs_vwap'], 2),
                            'vwap_slope': round(b1['vwap_slope'], 3) if not pd.isna(b1['vwap_slope']) else 0,
                            'is_runner': 1 if mfe <= -2.0 else 0
                        })
                        count += 1
                
                # LONG
                elif (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                      b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                        
                        all_signals.append({
                            'symbol': symbol,
                            'date': str(date),
                            'time': str(b1['timestamp'].time())[:8],
                            'window': '2:30-4PM',
                            'direction': 'long',
                            'entry': round(b2['close'], 2),
                            'mfe': round(mfe, 2),
                            'bar1_body_pct': round(b1['body'] * 100, 2),
                            'bar2_body_pct': round(b2['body'] * 100, 2),
                            'bar1_rvol': round(b1['rvol'], 1),
                            'bar2_rvol': round(b2['rvol'], 1),
                            'bar1_close_vs_vwap': round(b1['close_vs_vwap'], 2),
                            'bar2_close_vs_vwap': round(b2['close_vs_vwap'], 2),
                            'vwap_slope': round(b1['vwap_slope'], 3) if not pd.isna(b1['vwap_slope']) else 0,
                            'is_runner': 1 if mfe >= 2.0 else 0
                        })
                        count += 1
        
        if count > 0:
            print(f'  -> {count} signals captured')
        
    except Exception as e:
        print(f'  -> ERROR: {str(e)[:60]}')

print()
print('='*80)
print(f'TOTAL SIGNALS: {len(all_signals)}')
print('='*80)

if all_signals:
    df_out = pd.DataFrame(all_signals)
    df_out.to_csv('boof30_all_signals_detailed.csv', index=False)
    
    runners = df_out[df_out['is_runner'] == 1]
    print(f'RUNNERS (MFE >= 2%): {len(runners)}')
    
    # Summary stats
    print()
    print('SUMMARY BY WINDOW/DIRECTION:')
    summary = df_out.groupby(['window', 'direction']).agg({
        'is_runner': 'sum',
        'bar1_body_pct': 'mean',
        'bar2_body_pct': 'mean',
        'bar1_rvol': 'mean',
        'vwap_slope': 'mean'
    }).round(2)
    print(summary)
    
    print()
    print('RUNNERS ONLY - AVG METRICS:')
    if len(runners) > 0:
        runner_stats = runners.groupby(['window', 'direction']).agg({
            'bar1_body_pct': 'mean',
            'bar2_body_pct': 'mean',
            'bar1_rvol': 'mean',
            'bar2_rvol': 'mean',
            'bar1_close_vs_vwap': 'mean',
            'vwap_slope': 'mean'
        }).round(2)
        print(runner_stats)
    
    print()
    print('Saved: boof30_all_signals_detailed.csv')

print('='*80)
print('COMPLETE')
print('='*80)
