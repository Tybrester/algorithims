import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('TOP 100 VOLATILE STOCKS - BOOF30 SCORE TEST')
print('='*80)

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

# Top 100 volatile stocks (high beta, meme stocks, crypto, biotech, EV, etc.)
volatile_100 = [
    # Original 20
    'TSLA', 'NVDA', 'AAPL', 'AMZN', 'QQQ', 'SPY', 'MSFT', 'META', 'GOOGL', 'NFLX',
    'AMD', 'CRM', 'AVGO', 'SHOP', 'UBER', 'COIN', 'PLTR', 'HOOD', 'RKLB', 'MSTR',
    # Meme / Retail Favorites
    'GME', 'AMC', 'BB', 'NOK', 'EXPR', 'KOSS', 'BBBY', 'SPCE', 'TLRY', 'SNDL',
    # Crypto / Blockchain
    'MARA', 'RIOT', 'HUT', 'BITF', 'CLSK', 'ARBK', 'BTBT', 'SDIG', 'WGMI', 'TYDE',
    # High Beta Tech / Growth
    'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'FSR', 'GOEV', 'WKHS', 'BLNK', 'CHPT',
    # Biotech Volatility
    'MRNA', 'BNTX', 'PFE', 'AZN', 'GILD', 'BIIB', 'REGN', 'VRTX', 'SRPT', 'KPTI',
    # China / Emerging
    'BABA', 'JD', 'PDD', 'NIO', 'DIDI', 'TME', 'BILI', 'IQ', 'FUTU', 'LU',
    # Semiconductors / Hardware
    'INTC', 'QCOM', 'TXN', 'MU', 'LRCX', 'KLAC', 'AMAT', 'SNPS', 'CDNS', 'ASML',
    # Fintech / Disruptors
    'SQ', 'PYPL', 'SOFI', 'UPST', 'AFRM', 'LMND', 'ROOT', 'RBLX', 'DOCU', 'ZM',
    # Energy / Commodities Volatile
    'XOM', 'CVX', 'OXY', 'MRO', 'DVN', 'FANG', 'COP', 'SLB', 'HAL', 'BKR',
    # Airlines / Travel / Cyclical
    'UAL', 'DAL', 'AAL', 'LUV', 'CCL', 'RCL', 'NCLH', 'MAR', 'HLT', 'ABNB'
]

# Remove duplicates
volatile_100 = list(dict.fromkeys(volatile_100))

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

print(f'Stocks: {len(volatile_100)}')
print(f'Date range: {start.date()} to {end.date()}')
print('='*80)
print()

all_signals = []

for symbol in volatile_100:
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
            
            # Check both windows
            for window, mask in [
                ('9:30-11AM', ((day['hour'] == 9) & (day['minute'] >= 30)) | (day['hour'] == 10)),
                ('2:30-4PM', ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15))
            ]:
                window_data = day[mask].reset_index(drop=True)
                
                if len(window_data) < 35:  # Need at least 35 bars for 2-bar pattern + 30 future
                    continue
                
                for i in range(len(window_data) - 30):
                    if i + 1 >= len(window_data):
                        continue
                    b1 = window_data.iloc[i]
                    b2 = window_data.iloc[i+1]
                    
                    # LONG criteria
                    if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                        b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                        
                        future = window_data.iloc[i+2:i+30]
                        if len(future) >= 20:
                            mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                            
                            # Calculate LONG_SCORE
                            score = 0
                            if b1['rvol'] > 8: score += 1
                            if b1['body'] * 100 > 0.9: score += 1
                            if b1['vwap_slope'] > 0.25: score += 1
                            if b2['body'] * 100 > 0.5: score += 1
                            
                            all_signals.append({
                                'symbol': symbol, 'date': str(date), 'time': str(b1['timestamp'].time())[:8],
                                'window': window, 'direction': 'long', 'mfe': round(mfe, 2),
                                'entry': round(b2['close'], 2), 'LONG_SCORE': score,
                                'bar1_rvol': round(b1['rvol'], 1), 'bar1_body_pct': round(b1['body']*100, 2),
                                'bar2_body_pct': round(b2['body']*100, 2), 'vwap_slope': round(b1['vwap_slope'], 3),
                                'is_runner': 1 if mfe >= 2.0 else 0
                            })
                            count += 1
        
        if count > 0:
            print(f' -> {count} signals')
        else:
            print(' -> 0')
        
    except Exception as e:
        print(f' -> ERROR: {str(e)[:40]}')

print()
print('='*80)
print(f'TOTAL SIGNALS: {len(all_signals)}')
print('='*80)

if all_signals:
    df = pd.DataFrame(all_signals)
    df.to_csv('boof30_top100_signals.csv', index=False)
    
    # Score >= 3 analysis
    high_score = df[df['LONG_SCORE'] >= 3]
    low_score = df[df['LONG_SCORE'] < 3]
    
    hs_runners = high_score['is_runner'].sum()
    hs_total = len(high_score)
    hs_rate = hs_runners / hs_total * 100 if hs_total > 0 else 0
    
    ls_runners = low_score['is_runner'].sum()
    ls_total = len(low_score)
    ls_rate = ls_runners / ls_total * 100 if ls_total > 0 else 0
    
    print()
    print('SCORE >= 3 RESULTS:')
    print(f'  Signals: {hs_total}')
    print(f'  Runners: {hs_runners}/{hs_total} ({hs_rate:.1f}%)')
    print()
    print('SCORE < 3 RESULTS:')
    print(f'  Signals: {ls_total}')
    print(f'  Runners: {ls_runners}/{ls_total} ({ls_rate:.1f}%)')
    print()
    
    if hs_total > 0 and ls_total > 0:
        print(f'LIFT: {hs_rate/ls_rate:.2f}x better with Score >= 3')
    
    # Score breakdown
    print()
    print('SCORE BREAKDOWN:')
    for score in sorted(df['LONG_SCORE'].unique(), reverse=True):
        subset = df[df['LONG_SCORE'] == score]
        rate = subset['is_runner'].mean() * 100
        print(f'  Score {score}: {len(subset)} signals, {subset["is_runner"].sum()} runners ({rate:.1f}%)')
    
    # Show high-score runners
    hs_runner_list = high_score[high_score['is_runner'] == 1]
    print()
    print(f'HIGH-SCORE RUNNERS (Score >= 3):')
    for _, r in hs_runner_list.iterrows():
        print(f"  {r['symbol']} {r['date']} {r['window']} | Score: {r['LONG_SCORE']} | MFE: {r['mfe']}%")
    
    print()
    print('Saved: boof30_top100_signals.csv')

print('='*80)
print('COMPLETE')
print('='*80)
