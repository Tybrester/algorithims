import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('TIME SEGMENT ANALYSIS - CORE UNIVERSE')
print('='*80)
print()
print('Splitting ALL DAY into 3 windows:')
print('  1. 9:30-11:00 AM (Morning)')
print('  2. 11:00-2:30 PM (Midday)')  
print('  3. 2:30-4:00 PM (Afternoon)')
print()

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

PARAMS = {'rvol': 7, 'bar1_body': 0.9, 'vwap_slope': 0.25, 'bar2_body': 0.5}
TP_1, TP_2, SL = 1.0, 1.75, 1.0

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

def get_time_segment(hour, minute):
    """Return time segment: morning, midday, afternoon"""
    total_min = hour * 60 + minute
    morning_start = 9 * 60 + 30  # 570
    morning_end = 11 * 60        # 660
    midday_end = 14 * 60 + 30    # 870
    afternoon_end = 16 * 60      # 960
    
    if total_min < morning_start or total_min > afternoon_end:
        return None
    if total_min < morning_end:
        return 'morning'
    if total_min < midday_end:
        return 'midday'
    return 'afternoon'

trades = []  # Collect all trades with segment info

print('Analyzing Core Universe...')
print('-'*60)

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
        
        count = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50: continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
            
            for i in range(len(day) - 30):
                if i + 1 >= len(day): continue
                
                b1 = day.iloc[i]
                b2 = day.iloc[i+1]
                
                # Time segment check
                segment = get_time_segment(b1['hour'], b1['minute'])
                if not segment: continue
                
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
                        
                        future = day.iloc[i+2:i+32]
                        
                        # Track MFE and MAE
                        mfe = 0
                        mae = 0
                        for _, bar in future.iterrows():
                            price_high = (bar['high'] - entry) / entry * 100
                            price_low = (entry - bar['low']) / entry * 100
                            mfe = max(mfe, price_high)
                            mae = max(mae, price_low)
                        
                        # First-touch TP/SL logic
                        tp1_bar = tp2_bar = sl_bar = None
                        for j, (_, bar) in enumerate(future.iterrows()):
                            if tp1_bar is None and bar['high'] >= tp1_level: tp1_bar = j + 1
                            if tp2_bar is None and bar['high'] >= tp2_level: tp2_bar = j + 1
                            if sl_bar is None and bar['low'] <= sl_level: sl_bar = j + 1
                            if sl_bar and tp1_bar: break
                        
                        # Calculate P&L
                        if sl_bar and tp1_bar is None:
                            pnl = -SL
                        elif sl_bar and tp1_bar and sl_bar < tp1_bar:
                            pnl = -SL
                        elif tp1_bar and sl_bar is None:
                            if tp2_bar: pnl = 0.5 * TP_1 + 0.5 * TP_2
                            else:
                                final_price = future.iloc[-1]['close']
                                trail_pnl = (final_price - entry) / entry * 100
                                pnl = 0.5 * TP_1 + 0.5 * trail_pnl
                        elif tp1_bar and sl_bar and tp1_bar < sl_bar:
                            if tp2_bar and tp2_bar < sl_bar: pnl = 0.5 * TP_1 + 0.5 * TP_2
                            else: pnl = 0.5 * TP_1 + 0.5 * (-SL)
                        else:
                            final_price = future.iloc[-1]['close']
                            pnl = (final_price - entry) / entry * 100
                        
                        trades.append({
                            'symbol': symbol,
                            'date': str(date),
                            'segment': segment,
                            'pnl': pnl,
                            'mfe': mfe,
                            'mae': mae,
                            'score': score
                        })
                        count += 1
        
        print(f'{count} trades')
        
    except Exception as e:
        print(f'ERROR: {str(e)[:40]}')

print()
print('='*80)
print('TIME SEGMENT RESULTS')
print('='*80)
print()

if trades:
    df = pd.DataFrame(trades)
    
    # Overall stats
    segments = ['morning', 'midday', 'afternoon']
    segment_names = ['9:30-11:00 AM', '11:00-2:30 PM', '2:30-4:00 PM']
    
    print(f"{'Segment':<15} {'Signals':>8} {'EV %':>8} {'Win %':>8} {'Avg MFE':>10} {'Avg MAE':>10}")
    print('-'*65)
    
    for seg, name in zip(segments, segment_names):
        seg_data = df[df['segment'] == seg]
        if len(seg_data) > 0:
            pnl = seg_data['pnl'].values
            ev = np.mean(pnl)
            win_rate = sum(pnl > 0) / len(pnl) * 100
            avg_mfe = seg_data['mfe'].mean()
            avg_mae = seg_data['mae'].mean()
            
            print(f"{name:<15} {len(seg_data):>8} {ev:>+7.2f}% {win_rate:>7.1f}% {avg_mfe:>9.2f}% {avg_mae:>9.2f}%")
        else:
            print(f"{name:<15} {0:>8} {'N/A':>8} {'N/A':>8} {'N/A':>10} {'N/A':>10}")
    
    print()
    
    # Full breakdown with percentiles
    for seg, name in zip(segments, segment_names):
        seg_data = df[df['segment'] == seg]
        if len(seg_data) == 0:
            continue
        
        print(f'{name} BREAKDOWN:')
        print(f'  Signals: {len(seg_data)}')
        print(f'  EV: {seg_data["pnl"].mean():+.2f}%')
        print(f'  Median P&L: {seg_data["pnl"].median():+.2f}%')
        print(f'  Win Rate: {sum(seg_data["pnl"] > 0) / len(seg_data) * 100:.1f}%')
        print(f'  Std Dev: {seg_data["pnl"].std():.2f}%')
        print()
        print(f'  MFE (Avg): {seg_data["mfe"].mean():.2f}%')
        print(f'  MFE (P50): {seg_data["mfe"].median():.2f}%')
        print(f'  MFE (P90): {np.percentile(seg_data["mfe"], 90):.2f}%')
        print()
        print(f'  MAE (Avg): {seg_data["mae"].mean():.2f}%')
        print(f'  MAE (P50): {seg_data["mae"].median():.2f}%')
        print(f'  MAE (P90): {np.percentile(seg_data["mae"], 90):.2f}%')
        print()
        
        # Top performers by symbol in this segment
        by_sym = seg_data.groupby('symbol')['pnl'].agg(['count', 'mean']).sort_values('mean', ascending=False)
        top_3 = by_sym.head(3)
        print('  Top 3 symbols:')
        for sym, row in top_3.iterrows():
            print(f'    {sym}: {int(row["count"])} trades, {row["mean"]:+.2f}% avg')
        print()

    # Combined comparison
    total = len(df)
    print('='*80)
    print('SUMMARY COMPARISON')
    print('='*80)
    print(f'Total signals across all segments: {total}')
    print()
    print(f"{'Segment':<20} {'% of Total':>12} {'EV':>10} {'MFE/MAE Ratio':>15}")
    print('-'*55)
    
    for seg, name in zip(segments, segment_names):
        seg_data = df[df['segment'] == seg]
        if len(seg_data) > 0:
            pct = len(seg_data) / total * 100
            ev = seg_data['pnl'].mean()
            ratio = seg_data['mfe'].mean() / seg_data['mae'].mean() if seg_data['mae'].mean() > 0 else 0
            print(f"{name:<20} {pct:>11.1f}% {ev:>+9.2f}% {ratio:>14.2f}x")
else:
    print('No trades found')

print()
print('='*80)
print('RECOMMENDATION')
print('='*80)
if trades:
    best_seg = df.groupby('segment')['pnl'].mean().idxmax()
    seg_map = {'morning': '9:30-11:00 AM', 'midday': '11:00-2:30 PM', 'afternoon': '2:30-4:00 PM'}
    print(f'Best performing time segment: {seg_map.get(best_seg, best_seg)}')
    print()
    print('Suggested trading focus:')
    for seg, name in zip(segments, segment_names):
        seg_data = df[df['segment'] == seg]
        if len(seg_data) > 0 and seg_data['pnl'].mean() > 0:
            print(f'  ✓ {name}: +EV segment ({seg_data["pnl"].mean():+.2f}%)')
        elif len(seg_data) > 0:
            print(f'  ✗ {name}: Negative EV ({seg_data["pnl"].mean():+.2f}%)')
print('='*80)
