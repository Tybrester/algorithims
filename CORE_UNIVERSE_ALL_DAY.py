import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('CORE UNIVERSE - ALL DAY vs 2:30-4 PM COMPARISON')
print('='*80)
print()

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

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

def is_all_day(hour, minute):
    """9:30 AM - 4:00 PM"""
    if hour < 9 or hour > 15:
        return False
    if hour == 9 and minute < 30:
        return False
    return True

def is_afternoon_only(hour, minute):
    """2:30 PM - 4:00 PM only"""
    if hour == 14 and minute >= 30:
        return True
    if hour == 15:
        return True
    return False

def analyze_window(symbols, window_filter, label):
    """Analyze with specific time window"""
    trades = []
    
    print(f'{label}')
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
                
                # Apply window filter
                if window_filter == 'all_day':
                    mask = day.apply(lambda r: is_all_day(r['hour'], r['minute']), axis=1)
                else:
                    mask = day.apply(lambda r: is_afternoon_only(r['hour'], r['minute']), axis=1)
                
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
                        
                        score = 0
                        if b1['rvol'] > PARAMS['rvol']: score += 1
                        if b1['body'] * 100 > PARAMS['bar1_body']: score += 1
                        if b1['vwap_slope'] > PARAMS['vwap_slope']: score += 1
                        if b2['body'] * 100 > PARAMS['bar2_body']: score += 1
                        
                        if score >= 3:
                            entry = b2['close']
                            tp1_level = entry * (1 + TP_1/100)
                            tp2_level = entry * (1 + TP_2/100)
                            sl_level = entry * (1 - SL/100)
                            
                            future = trade_data.iloc[i+2:i+32]
                            
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

# Run BOTH windows
print('='*80)
trades_all_day = analyze_window(CORE_UNIVERSE, 'all_day', 'ALL DAY (9:30 AM - 4:00 PM)')

trades_afternoon = analyze_window(CORE_UNIVERSE, 'afternoon', 'AFTERNOON ONLY (2:30-4:00 PM)')

# Compare results
print('='*80)
print('WINDOW COMPARISON - CORE UNIVERSE')
print('='*80)
print()

if trades_all_day:
    df_all = pd.DataFrame(trades_all_day)
    pnl_all = df_all['pnl'].values
    
    print(f'ALL DAY WINDOW:')
    print(f'  Total trades: {len(df_all)}')
    print(f'  Avg P&L: {np.mean(pnl_all):+.2f}%')
    print(f'  Median P&L: {np.median(pnl_all):+.2f}%')
    print(f'  Win rate: {sum(pnl_all > 0)/len(pnl_all)*100:.1f}%')
    print()
    
    # Time breakdown
    morning = df_all[((df_all['hour'] == 9) | (df_all['hour'] == 10)) & (df_all['minute'] <= 30)]
    midday = df_all[((df_all['hour'] == 10) & (df_all['minute'] > 30)) | (df_all['hour'].between(11, 13)) | ((df_all['hour'] == 14) & (df_all['minute'] < 30))]
    afternoon = df_all[((df_all['hour'] == 14) & (df_all['minute'] >= 30)) | (df_all['hour'] == 15)]
    
    print('  Time of day breakdown:')
    if len(morning) > 0:
        print(f'    9:30-10:30 AM: {len(morning)} trades, {morning["pnl"].mean():+.2f}% avg')
    if len(midday) > 0:
        print(f'    10:30-2:30 PM: {len(midday)} trades, {midday["pnl"].mean():+.2f}% avg')
    if len(afternoon) > 0:
        print(f'    2:30-4:00 PM: {len(afternoon)} trades, {afternoon["pnl"].mean():+.2f}% avg')
    print()

if trades_afternoon:
    df_pm = pd.DataFrame(trades_afternoon)
    pnl_pm = df_pm['pnl'].values
    
    print(f'AFTERNOON ONLY (2:30-4 PM):')
    print(f'  Total trades: {len(df_pm)}')
    print(f'  Avg P&L: {np.mean(pnl_pm):+.2f}%')
    print(f'  Median P&L: {np.median(pnl_pm):+.2f}%')
    print(f'  Win rate: {sum(pnl_pm > 0)/len(pnl_pm)*100:.1f}%')
    print()

# Side-by-side
if trades_all_day and trades_afternoon:
    print('='*80)
    print('HEAD-TO-HEAD COMPARISON')
    print('='*80)
    print()
    print(f'                    ALL DAY       AFTERNOON ONLY')
    print(f'                    -------       --------------')
    print(f'Signals:            {len(df_all):<13} {len(df_pm)}')
    print(f'Avg P&L:            {np.mean(pnl_all):+.2f}%        {np.mean(pnl_pm):+.2f}%')
    print(f'Win rate:           {sum(pnl_all > 0)/len(pnl_all)*100:.1f}%          {sum(pnl_pm > 0)/len(pnl_pm)*100:.1f}%')
    print()
    
    if len(df_all) > len(df_pm) * 1.5:
        print(f'✓ All-day window generates {len(df_all)/len(df_pm):.1f}x more signals')
    
    if np.mean(pnl_all) >= np.mean(pnl_pm) - 0.2:
        print(f'✓ Quality maintained: all-day avg P&L similar to afternoon-only')
    else:
        print(f'⚠ Quality degradation: afternoon-only performs better')

print()
print('='*80)
print('RECOMMENDATION')
print('='*80)
print()
print('For CORE UNIVERSE:')
if trades_all_day and trades_afternoon:
    if len(df_all) > len(df_pm) and np.mean(pnl_all) > 0:
        print(f'  → Use ALL DAY window for more signals with acceptable quality')
    else:
        print(f'  → Stick with AFTERNOON ONLY for higher quality per signal')
print()
print('For OUT-OF-UNIVERSE:')
print(f'  → Use STRICT parameters (Score 6) with ALL DAY window if any signals found')
print('='*80)
