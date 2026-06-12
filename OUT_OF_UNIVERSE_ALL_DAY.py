import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('OUT-OF-UNIVERSE TEST - ALL DAY WINDOW')
print('='*80)
print('9:30 AM - 4:00 PM EST')
print()

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

OUT_OF_UNIVERSE = [
    'NOW', 'HUBS', 'MDB', 'ESTC', 'ZS', 'OKTA', 'TEAM', 'PANW',
    'AMAT', 'LRCX', 'KLAC', 'ASML', 'ON', 'MPWR',
    'MELI', 'DUOL', 'SPOT', 'ETSY', 'PINS', 'RDDT',
    'CAT', 'DE', 'URI', 'PWR', 'GE', 'VRT',
    'GS', 'MS', 'SCHW', 'IBKR', 'CBOE',
    'ISRG', 'ABBV', 'UNH', 'HCA', 'VEEV',
    'COST', 'WMT', 'TGT', 'TJX'
]

PARAMS = {
    'rvol': 7,
    'bar1_body': 0.9,
    'vwap_slope': 0.25,
    'bar2_body': 0.5
}

TP_1 = 1.0
TP_2 = 1.75
SL = 1.0

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

def is_trading_window(hour, minute):
    """Check if within trading hours 9:30 AM - 4:00 PM"""
    # Morning: 9:30-11:00 AM
    # Afternoon: 2:30-4:00 PM
    # OR full day: just check market hours
    if hour < 9 or hour > 15:
        return False
    if hour == 9 and minute < 30:
        return False
    return True

def run_analysis(symbols, score_thresh, label):
    trades = []
    
    print(f'{label} (Score >= {score_thresh})')
    print('-' * 60)
    
    for symbol in symbols:
        try:
            print(f'  {symbol}: ', end='', flush=True)
            
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
                
                # ALL DAY WINDOW
                mask = day.apply(lambda r: is_trading_window(r['hour'], r['minute']), axis=1)
                trade_data = day[mask].reset_index(drop=True)
                
                if len(trade_data) < 35:
                    continue
                
                for i in range(len(trade_data) - 30):
                    if i + 1 >= len(trade_data):
                        continue
                    
                    b1 = trade_data.iloc[i]
                    b2 = trade_data.iloc[i+1]
                    
                    # 2-bar long ignition
                    if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                        b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                        
                        # Calculate Score
                        score = 0
                        if b1['rvol'] > PARAMS['rvol']: score += 1
                        if b1['body'] * 100 > PARAMS['bar1_body']: score += 1
                        if b1['vwap_slope'] > PARAMS['vwap_slope']: score += 1
                        if b2['body'] * 100 > PARAMS['bar2_body']: score += 1
                        
                        if score >= score_thresh:
                            entry = b2['close']
                            tp1_level = entry * (1 + TP_1/100)
                            tp2_level = entry * (1 + TP_2/100)
                            sl_level = entry * (1 - SL/100)
                            
                            future = trade_data.iloc[i+2:i+32]
                            
                            # First-touch logic
                            tp1_bar = None
                            tp2_bar = None
                            sl_bar = None
                            
                            for j, (_, bar) in enumerate(future.iterrows()):
                                if tp1_bar is None and bar['high'] >= tp1_level:
                                    tp1_bar = j + 1
                                if tp2_bar is None and bar['high'] >= tp2_level:
                                    tp2_bar = j + 1
                                if sl_bar is None and bar['low'] <= sl_level:
                                    sl_bar = j + 1
                                if sl_bar and tp1_bar:
                                    break
                            
                            # Calculate P&L
                            if sl_bar and tp1_bar is None:
                                pnl = -SL
                            elif sl_bar and tp1_bar and sl_bar < tp1_bar:
                                pnl = -SL
                            elif tp1_bar and sl_bar is None:
                                if tp2_bar:
                                    pnl = 0.5 * TP_1 + 0.5 * TP_2
                                else:
                                    final_price = future.iloc[-1]['close']
                                    trail_pnl = (final_price - entry) / entry * 100
                                    pnl = 0.5 * TP_1 + 0.5 * trail_pnl
                            elif tp1_bar and sl_bar and tp1_bar < sl_bar:
                                if tp2_bar and tp2_bar < sl_bar:
                                    pnl = 0.5 * TP_1 + 0.5 * TP_2
                                else:
                                    pnl = 0.5 * TP_1 + 0.5 * (-SL)
                            else:
                                final_price = future.iloc[-1]['close']
                                pnl = (final_price - entry) / entry * 100
                            
                            trades.append({
                                'symbol': symbol,
                                'date': str(date),
                                'pnl': pnl,
                                'score': score,
                                'hour': b1['hour'],
                                'minute': b1['minute']
                            })
                            count += 1
            
            print(f'{count} trades')
            
        except Exception as e:
            print(f'ERROR: {str(e)[:40]}')
    
    print()
    return trades

# Run both score thresholds
print('='*80)
trades_score3 = run_analysis(OUT_OF_UNIVERSE, 3, 'SCORE 3 - ALL DAY')

trades_score6 = run_analysis(OUT_OF_UNIVERSE, 6, 'SCORE 6 - ALL DAY')

# Results
print('='*80)
print('ALL DAY RESULTS COMPARISON')
print('='*80)
print()

if trades_score3:
    df3 = pd.DataFrame(trades_score3)
    pnl3 = df3['pnl'].values
    print(f'Score >= 3:')
    print(f'  Total trades: {len(df3)}')
    print(f'  Avg P&L: {np.mean(pnl3):+.2f}%')
    print(f'  Median P&L: {np.median(pnl3):+.2f}%')
    print(f'  Win rate: {sum(pnl3 > 0)/len(pnl3)*100:.1f}%')
    print(f'  Std dev: {np.std(pnl3):.2f}%')
    print()
    
    # Time of day distribution
    morning = df3[(df3['hour'] == 9) | ((df3['hour'] == 10) & (df3['minute'] <= 30))]
    midday = df3[(df3['hour'] == 10) & (df3['minute'] > 30)] | (df3['hour'] == 11) | (df3['hour'] == 12) | (df3['hour'] == 13) | ((df3['hour'] == 14) & (df3['minute'] < 30))
    afternoon = ((df3['hour'] == 14) & (df3['minute'] >= 30)) | (df3['hour'] == 15)
    
    print('Time distribution:')
    print(f'  9:30-10:30 AM: {len(morning)} trades')
    print(f'  10:30-2:30 PM: {len(midday)} trades')
    print(f'  2:30-4:00 PM: {len(afternoon)} trades')
    print()
else:
    print('Score >= 3: No trades found')
    print()

if trades_score6:
    df6 = pd.DataFrame(trades_score6)
    pnl6 = df6['pnl'].values
    print(f'Score >= 6:')
    print(f'  Total trades: {len(df6)}')
    print(f'  Avg P&L: {np.mean(pnl6):+.2f}%')
    print(f'  Median P&L: {np.median(pnl6):+.2f}%')
    print(f'  Win rate: {sum(pnl6 > 0)/len(pnl6)*100:.1f}%')
    print(f'  Std dev: {np.std(pnl6):.2f}%')
else:
    print('Score >= 6: No trades found')

print()
print('='*80)
print('CONCLUSION')
print('='*80)

if trades_score3 and trades_score6:
    print(f'All-day window: {len(df3)} Score 3 signals vs {len(df6)} Score 6 signals')
    if np.mean(pnl3) > 0:
        print(f'✓ Score 3 produces profitable out-of-universe trades')
    if np.mean(pnl6) > np.mean(pnl3):
        print(f'✓ Score 6 improves performance but with fewer signals')
else:
    print('Pattern may be specific to high-beta momentum stocks')

print('='*80)
