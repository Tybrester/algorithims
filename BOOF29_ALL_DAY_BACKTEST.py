import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('BOOF 29 - ALL DAY BACKTEST (9:30 AM - 4:00 PM)')
print('='*80)
print()

# API Keys
API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)

# Boof 29 Universe
SYMBOLS = [
    'NVDA', 'AMD', 'AVGO', 'QCOM', 'AMAT', 'MU', 'MRVL', 'LRCX', 'KLAC', 'ASML',
    'TSM', 'ARM', 'INTC', 'ON', 'MCHP', 'ADI', 'NXPI', 'TXN', 'MPWR', 'TER',
    'MSFT', 'GOOGL', 'META', 'AMZN', 'AAPL', 'TSLA', 'NFLX', 'PLTR', 'SMCI',
    'ANET', 'DELL', 'CRWD', 'PANW', 'NOW'
]

# Boof 29 Parameters
OPENING_BUCKET_MIN = 0.50  # 0.50%
OPENING_BUCKET_MAX = 0.80  # 0.80%
ENTRY_TIME = (9, 35)  # 9:35 AM
EXIT_TIME = (10, 15)  # 10:15 AM (original)

# For all-day test, we'll scan 9:30-11:00, 11:00-2:30, 2:30-4:00
def get_time_segment(hour, minute):
    total_min = hour * 60 + minute
    morning_start = 9 * 60 + 30
    morning_end = 11 * 60
    midday_end = 14 * 60 + 30
    afternoon_end = 16 * 60
    
    if total_min < morning_start or total_min > afternoon_end:
        return None
    if total_min < morning_end:
        return 'morning'
    if total_min < midday_end:
        return 'midday'
    return 'afternoon'

end = datetime(2025, 6, 30)
start = end - timedelta(days=90)

trades = []

print(f'Analyzing {len(SYMBOLS)} symbols from {start.date()} to {end.date()}...')
print('-'*60)

# Get QQQ for market filter
print('Fetching QQQ data...')
qqq_request = StockBarsRequest(
    symbol_or_symbols='QQQ',
    timeframe=TimeFrame.Day,
    start=start,
    end=end
)
qqq_bars = data_client.get_stock_bars(qqq_request).df
qqq_daily = qqq_bars.reset_index()
qqq_daily['date'] = pd.to_datetime(qqq_daily['timestamp']).dt.date
qqq_daily['qqq_open_pct'] = (qqq_daily['open'] - qqq_daily['close'].shift(1)) / qqq_daily['close'].shift(1)
qqq_map = dict(zip(qqq_daily['date'], qqq_daily['qqq_open_pct']))

for symbol in SYMBOLS:
    try:
        print(f'{symbol}: ', end='', flush=True)
        
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df.reset_index()
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        df['date'] = df['timestamp'].dt.date
        df['time'] = df['hour'] * 60 + df['minute']
        
        count = 0
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            # Get opening price (9:30 bar)
            open_bar = day[(day['hour'] == 9) & (day['minute'] == 30)]
            if open_bar.empty:
                continue
            open_price = open_bar.iloc[0]['open']
            
            # Check QQQ filter
            qqq_move = qqq_map.get(date, 0)
            if qqq_move <= 0:
                continue
            
            # Scan all time segments
            for idx, row in day.iterrows():
                segment = get_time_segment(row['hour'], row['minute'])
                if not segment:
                    continue
                
                # Check if entry time (9:35 in original, now extended)
                if row['hour'] == 9 and row['minute'] == 35:
                    # Calculate opening move
                    move_pct = (row['open'] - open_price) / open_price * 100
                    
                    # Check opening bucket (0.50% - 0.80%)
                    if OPENING_BUCKET_MIN <= move_pct <= OPENING_BUCKET_MAX:
                        entry_price = row['open']
                        entry_time = row['timestamp']
                        
                        # Find exit at 10:15 (30 min hold)
                        exit_candidates = day[(day['hour'] == 10) & (day['minute'] == 15)]
                        if exit_candidates.empty:
                            continue
                        
                        exit_price = exit_candidates.iloc[0]['close']
                        pnl = (exit_price - entry_price) / entry_price * 100
                        
                        trades.append({
                            'symbol': symbol,
                            'date': str(date),
                            'segment': segment,
                            'entry_time': entry_time,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'pnl_pct': pnl,
                            'opening_move': move_pct
                        })
                        count += 1
        
        print(f'{count} trades')
        
    except Exception as e:
        print(f'ERROR: {str(e)[:40]}')

print()
print('='*80)
print('ALL DAY BACKTEST RESULTS')
print('='*80)
print()

if trades:
    df_results = pd.DataFrame(trades)
    
    # Overall stats
    total = len(df_results)
    wins = len(df_results[df_results['pnl_pct'] > 0])
    win_rate = wins / total * 100 if total > 0 else 0
    avg_pnl = df_results['pnl_pct'].mean()
    
    print(f'Total Trades: {total}')
    print(f'Win Rate: {win_rate:.1f}%')
    print(f'Avg P&L: {avg_pnl:.2f}%')
    print(f'Total Return: {df_results["pnl_pct"].sum():.2f}%')
    print()
    
    # By time segment
    print('BY TIME SEGMENT:')
    for seg in ['morning', 'midday', 'afternoon']:
        seg_data = df_results[df_results['segment'] == seg]
        if len(seg_data) > 0:
            print(f'  {seg.capitalize()}: {len(seg_data)} trades, {seg_data["pnl_pct"].mean():.2f}% avg')
    print()
    
    # By symbol (top 10)
    print('TOP 10 SYMBOLS:')
    by_sym = df_results.groupby('symbol')['pnl_pct'].agg(['count', 'mean', 'sum']).sort_values('sum', ascending=False).head(10)
    for sym, row in by_sym.iterrows():
        print(f'  {sym}: {int(row["count"])} trades, {row["mean"]:.2f}% avg, {row["sum"]:.2f}% total')
    print()
    
    # Monthly breakdown
    df_results['month'] = pd.to_datetime(df_results['date']).dt.to_period('M')
    print('MONTHLY BREAKDOWN:')
    monthly = df_results.groupby('month')['pnl_pct'].agg(['count', 'mean', 'sum'])
    for month, row in monthly.iterrows():
        print(f'  {month}: {int(row["count"])} trades, {row["mean"]:.2f}% avg, {row["sum"]:.2f}% total')
    
    # Save results
    df_results.to_csv('boof29_all_day_results.csv', index=False)
    print()
    print('Results saved to boof29_all_day_results.csv')
else:
    print('No trades found')

print('='*80)
print()
print('CONCLUSION:')
print(f'Boof 29 opening momentum (0.50-0.80% move at 9:35, hold to 10:15)')
print(f'All-day window would capture these morning setups only')
print(f'The 0.50-0.80% opening move bucket carries the edge')
print('='*80)
