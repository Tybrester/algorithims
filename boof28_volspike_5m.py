"""
BOOF 28 - 5-Minute Volume Spike Scanner (3 months, 100 stocks)
vol_ratio = current_5m_volume / avg_volume_same_5min_20d
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Top 100 liquid stocks
UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","MRVL","SNPS","CDNS","KLAC",
    "JPM","V","MA","BAC","GS","WFC","C","AXP","BLK","SPGI",
    "UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","BMY",
    "AMGN","GILD","REGN","VRTX","ZTS","ISRG","ELV","CI","HUM","CVS",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","TGT","DG","ROST","BKNG","MAR","HLT","ABNB","DASH","UBER",
    "XOM","CVX","COP","EOG","SLB","OXY","MPC","VLO","PSX","KMI",
    "GE","HON","UPS","BA","CAT","DE","LMT","NOC","RTX","UNP","SPY"
]

def get_5m_data(symbol, start_date, end_date):
    """Get 5m data"""
    df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df

def calculate_same_time_avg_volume(df, lookback_days=20):
    """Calculate average volume for each 5-min time slot across lookback"""
    df['time'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    # Get unique dates and take last N
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    # Calculate average by time across recent dates
    hist_df = df[df['date'].isin(recent_dates[:-1])]  # Exclude most recent day
    time_groups = hist_df.groupby('time')['volume'].mean()
    
    # Map back
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time']
        if t in time_groups:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def run_backtest():
    # 3 months: Dec 2025 - Feb 2026
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 2, 28, tzinfo=timezone.utc)
    
    # Fetch extra for volume calculation
    fetch_start = start_date - timedelta(days=25)
    fetch_end = end_date + timedelta(days=1)
    
    print('='*80)
    print('BOOF 28 - 5-MIN VOLUME SPIKE (3 MONTHS)')
    print('vol_ratio = current_5m_volume / avg_same_5min_20d')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print(f'Stocks: {len(UNIVERSE)}')
    print('='*80)
    
    # Generate trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)
    
    print(f'\nScanning {len(trading_days)} trading days...\n')
    
    all_trades = []
    
    for day_num, trade_date in enumerate(trading_days, 1):
        day_trades = []
        
        for sym in UNIVERSE:
            try:
                # Get data with lookback
                df = get_5m_data(sym, fetch_start, fetch_end)
                if df is None or len(df) < 20:
                    continue
                
                # Calculate seasonal average
                avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
                
                # Get today's data
                today_mask = df['timestamp'].dt.date == trade_date.date()
                today_df = df[today_mask].reset_index(drop=True)
                today_avg = avg_vol[today_mask].reset_index(drop=True)
                
                if len(today_df) < 9:  # Need first 45 min (9 bars)
                    continue
                
                # Check first 9 bars (45 min window) for spikes
                for i in range(min(9, len(today_df))):
                    if pd.isna(today_avg.iloc[i]) or today_avg.iloc[i] == 0:
                        continue
                    
                    vol_ratio = today_df['volume'].iloc[i] / today_avg.iloc[i]
                    
                    # Stage 1: Volume spike >= 3.0x
                    if vol_ratio >= 3.0:
                        spike_price = today_df['close'].iloc[i]
                        
                        # Stage 2: Clean continuation (5 bars = 25 min)
                        if i + 5 >= len(today_df):
                            continue
                        
                        # Calculate clean continuation metrics
                        close_i = today_df['close'].iloc[i]
                        close_i5 = today_df['close'].iloc[i + 5]
                        
                        five_min_move = (close_i5 - close_i) / close_i
                        
                        # Range and chop calculation
                        range_high = today_df['high'].iloc[i+1:i+6].max()
                        range_low = today_df['low'].iloc[i+1:i+6].min()
                        range_chop = range_high - range_low
                        
                        net_move = abs(close_i5 - close_i)
                        
                        # Trend efficiency (0.45 = 45% of range is net movement)
                        trend_efficiency = net_move / range_chop if range_chop > 0 else 0
                        clean_trend = trend_efficiency >= 0.45
                        
                        # Determine direction with clean trend requirement
                        direction = None
                        if clean_trend and five_min_move > 0.002:
                            direction = 'LONG'
                        elif clean_trend and five_min_move < -0.002:
                            direction = 'SHORT'
                        else:
                            continue  # Skip - not clean continuation
                        
                        if direction:
                            # Stage 3-4: Entry at i+5 (after clean trend confirmed)
                            entry_idx = i + 5
                            entry_price = close_i5
                            
                            # Simulate (max 6 bars = 30 min)
                            pnl = None
                            if direction == 'SHORT':
                                tp = entry_price * 0.99
                                sl = entry_price * 1.005
                                for j in range(entry_idx + 1, min(entry_idx + 6, len(today_df))):
                                    if today_df['low'].iloc[j] <= tp:
                                        pnl = 1.0
                                        break
                                    if today_df['high'].iloc[j] >= sl:
                                        pnl = -0.5
                                        break
                            else:  # LONG
                                tp = entry_price * 1.01
                                sl = entry_price * 0.995
                                for j in range(entry_idx + 1, min(entry_idx + 6, len(today_df))):
                                    if today_df['high'].iloc[j] >= tp:
                                        pnl = 1.0
                                        break
                                    if today_df['low'].iloc[j] <= sl:
                                        pnl = -0.5
                                        break
                            
                            if pnl is None:
                                exit_price = today_df['close'].iloc[min(entry_idx + 5, len(today_df) - 1)]
                                if direction == 'SHORT':
                                    pnl = (entry_price - exit_price) / entry_price * 100
                                else:
                                    pnl = (exit_price - entry_price) / entry_price * 100
                            
                            if pnl is not None:
                                day_trades.append({
                                    'date': trade_date,
                                    'symbol': sym,
                                    'spike_bar': i,
                                    'vol_ratio': vol_ratio,
                                    'direction': direction,
                                    'entry': entry_price,
                                    'pnl': pnl
                                })
                
                time.sleep(0.03)
                
            except Exception as e:
                pass
        
        if day_trades:
            day_pnl = sum(t['pnl'] for t in day_trades)
            print(f"{trade_date.date()}: {len(day_trades)} trades, P&L: {day_pnl:+.2f}%")
            all_trades.extend(day_trades)
        elif day_num % 10 == 0:
            print(f"{trade_date.date()}: No trades")
    
    print('='*80)
    
    if all_trades:
        df_results = pd.DataFrame(all_trades)
        wins = len(df_results[df_results['pnl'] > 0])
        total_pnl = df_results['pnl'].sum()
        
        print(f'\nFINAL RESULTS:')
        print(f'Total Trades: {len(df_results)}')
        print(f'Win Rate: {wins/len(df_results)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(df_results):.3f}%')
        
        shorts = df_results[df_results['direction'] == 'SHORT']
        longs = df_results[df_results['direction'] == 'LONG']
        
        if len(shorts) > 0:
            print(f'\nSHORTS: {len(shorts)} trades, {shorts["pnl"].sum():+.2f}%')
        if len(longs) > 0:
            print(f'LONGS: {len(longs)} trades, {longs["pnl"].sum():+.2f}%')
        
        print(f'\nTop 10 Symbols:')
        sym_pnl = df_results.groupby('symbol')['pnl'].sum().sort_values(ascending=False).head(10)
        for sym, pnl in sym_pnl.items():
            count = len(df_results[df_results['symbol'] == sym])
            print(f'  {sym}: {count} trades, {pnl:+.2f}%')
    else:
        print('\nNo trades generated')
    
    print('='*80)

if __name__ == '__main__':
    run_backtest()
