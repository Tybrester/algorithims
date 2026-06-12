import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('CALCULATING MAE FOR SCORE 3 SIGNALS')
print('='*80)

# Load existing score 3 signals
df = pd.read_csv('boof30_top100_signals.csv')
score3 = df[df['LONG_SCORE'] == 3].copy()

print(f'Score 3 signals: {len(score3)}')
print()

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

mae_results = []

for idx, row in score3.iterrows():
    try:
        symbol = row['symbol']
        date_str = row['date']
        entry_time = row['time']
        entry_price = row['entry']
        
        # Parse date and get day data
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start = date.replace(hour=9, minute=30)
        end = date.replace(hour=16, minute=0)
        
        # Fetch data
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
        )
        bars = client.get_stock_bars(request)
        day_df = bars.df.reset_index()
        
        if len(day_df) < 50:
            continue
        
        day_df['timestamp'] = pd.to_datetime(day_df['timestamp']).dt.tz_localize(None)
        
        # Find entry bar
        entry_ts = pd.to_datetime(f"{date_str} {entry_time}")
        mask = day_df['timestamp'] > entry_ts
        future = day_df[mask].head(30)  # Next 30 bars
        
        if len(future) < 20:
            continue
        
        # Calculate MAE (adverse move against position)
        # For longs: MAE = (low - entry) / entry (most negative = worst drawdown)
        mae = (future['low'].min() - entry_price) / entry_price * 100
        
        mae_results.append({
            'symbol': symbol,
            'date': date_str,
            'time': entry_time,
            'entry': entry_price,
            'mfe': row['mfe'],
            'mae': round(mae, 2),
            'window': row['window'],
            'bar1_rvol': row['bar1_rvol'],
            'bar1_body_pct': row['bar1_body_pct']
        })
        
        print(f'{symbol} {date_str} {entry_time} | MFE: {row["mfe"]}% | MAE: {round(mae, 2)}%')
        
    except Exception as e:
        print(f'{symbol} {date_str}: ERROR - {str(e)[:40]}')

print()
print('='*80)
print(f'Calculated MAE for {len(mae_results)} signals')
print('='*80)

if mae_results:
    mae_df = pd.DataFrame(mae_results)
    mae_df.to_csv('score3_mae_analysis.csv', index=False)
    
    # Calculate stats
    mae_values = mae_df['mae'].values
    mfe_values = mae_df['mfe'].values
    
    avg_mae = mae_values.mean()
    median_mae = pd.Series(mae_values).median()
    p90_mae = pd.Series(mae_values).quantile(0.90)
    
    # MFE > MAE rate
    wins = sum(mfe_values > abs(mae_values))
    win_rate = wins / len(mae_df) * 100
    
    print()
    print('SCORE 3 MAE STATISTICS:')
    print(f'  Avg MAE:     {avg_mae:.2f}%')
    print(f'  Median MAE:  {median_mae:.2f}%')
    print(f'  P90 MAE:     {p90_mae:.2f}%')
    print()
    print(f'  MFE > |MAE| Rate: {wins}/{len(mae_df)} ({win_rate:.1f}%)')
    print()
    
    # Risk/Reward
    avg_mfe = mfe_values.mean()
    rr_ratio = avg_mfe / abs(avg_mae) if avg_mae != 0 else 0
    print(f'  Avg MFE: {avg_mfe:.2f}%')
    print(f'  Risk/Reward Ratio: 1:{rr_ratio:.2f}')
    
    # Worst MAE cases
    print()
    print('Worst MAE (biggest drawdowns):')
    worst = mae_df.nsmallest(5, 'mae')
    for _, r in worst.iterrows():
        print(f"  {r['symbol']} {r['date']} | MAE: {r['mae']}% | MFE: {r['mfe']}%")
    
    # Best Risk/Reward
    mae_df['rr'] = mae_df['mfe'] / abs(mae_df['mae'])
    print()
    print('Best Risk/Reward trades:')
    best_rr = mae_df.nlargest(5, 'rr')
    for _, r in best_rr.iterrows():
        print(f"  {r['symbol']} {r['date']} | RR: 1:{r['rr']:.1f} | MAE: {r['mae']}% | MFE: {r['mfe']}%")
    
    print()
    print('Saved: score3_mae_analysis.csv')

print('='*80)
print('COMPLETE')
print('='*80)
