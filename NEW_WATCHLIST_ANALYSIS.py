import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('NEW WATCHLIST - SCORE >= 3 ANALYSIS')
print('='*80)

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

# New watchlist
watchlist = [
    # Fintech / Growth
    'UPST', 'AFRM', 'PLTR', 'RBLX', 'LMND', 'ROOT', 'SOFI', 'HOOD', 'DASH', 'SNOW', 'NET', 'DDOG', 'CRWD', 'CFLT', 'SHOP',
    # AI / High Beta Tech
    'NVDA', 'AMD', 'AVGO', 'ARM', 'SMCI', 'MU', 'TSM', 'MRVL', 'ANET',
    # Crypto / Fintech
    'COIN', 'MSTR', 'RIOT', 'MARA', 'HUT', 'CLSK', 'BTBT', 'BITF', 'IREN',
    # Space / Speculative Growth
    'RKLB', 'LUNR', 'ASTS', 'RDW', 'SPIR',
    # EV / Transportation
    'TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI',
    # Biotech / Healthcare Momentum
    'MRNA', 'BNTX', 'SRPT', 'VKTX', 'HIMS', 'TEM',
    # China Momentum
    'BABA', 'PDD', 'JD', 'BILI', 'TME', 'FUTU', 'IQ',
    # Volatile Mid Caps
    'CELH', 'APP', 'DUOL', 'CAVA', 'APPF'
]

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

print(f'Symbols: {len(watchlist)}')
print(f'Date range: {start.date()} to {end.date()}')
print('='*80)
print()

all_signals = []

for symbol in watchlist:
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
        
        print(f'{len(df):,} bars', end='')
        
        if len(df) < 1000:
            print(' -> skip')
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
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
            day['close_vs_vwap'] = (day['close'] - day['vwap']) / day['vwap'] * 100
            
            # 2:30-4 PM Window only (best performance)
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            if len(pm_data) < 35:
                continue
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                # LONG criteria
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    future = pm_data.iloc[i+2:i+30]
                    if len(future) >= 20:
                        mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                        
                        # Calculate LONG_SCORE
                        score = 0
                        if b1['rvol'] > 8: score += 1
                        if b1['body'] * 100 > 0.9: score += 1
                        if b1['vwap_slope'] > 0.25: score += 1
                        if b2['body'] * 100 > 0.5: score += 1
                        
                        if score >= 3:
                            all_signals.append({
                                'symbol': symbol,
                                'date': str(date),
                                'time': str(b1['timestamp'].time())[:8],
                                'entry': round(b2['close'], 2),
                                'mfe': round(mfe, 2),
                                'LONG_SCORE': score,
                                'bar1_rvol': round(b1['rvol'], 1),
                                'bar1_body_pct': round(b1['body']*100, 2),
                                'vwap_slope': round(b1['vwap_slope'], 3),
                                'is_runner': 1 if mfe >= 2.0 else 0
                            })
                            count += 1
        
        if count > 0:
            print(f' -> {count} Score 3+ signals')
        else:
            print(' -> 0')
        
    except Exception as e:
        print(f' -> ERROR: {str(e)[:40]}')

print()
print('='*80)
print(f'TOTAL SCORE 3+ SIGNALS: {len(all_signals)}')
print('='*80)

if all_signals:
    df_out = pd.DataFrame(all_signals)
    df_out.to_csv('new_watchlist_score3.csv', index=False)
    
    runners = df_out[df_out['is_runner'] == 1]
    
    print()
    print('OVERALL PERFORMANCE:')
    print(f'  Signals: {len(df_out)}')
    print(f'  Runners (MFE >= 2%): {len(runners)} ({len(runners)/len(df_out)*100:.1f}%)')
    print(f'  Avg MFE: {df_out["mfe"].mean():.2f}%')
    print(f'  Median MFE: {df_out["mfe"].median():.2f}%')
    print()
    
    # Per symbol
    print('PER SYMBOL (with Score 3+ signals):')
    sym_stats = df_out.groupby('symbol').agg({
        'mfe': ['count', 'mean', lambda x: sum(x >= 2)]
    }).round(2)
    sym_stats.columns = ['Signals', 'Avg MFE', 'Runners']
    sym_stats = sym_stats.sort_values('Avg MFE', ascending=False)
    print(sym_stats.to_string())
    
    print()
    print('Saved: new_watchlist_score3.csv')

print('='*80)
print('COMPLETE')
print('='*80)
