"""
BOOF 28 - Detailed Trade Analysis
Fields: Date, Symbol, Opening Move %, Direction, Gap %, RVOL, Opening Range %, Market Direction
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

SYMBOLS = ['AAPL', 'NVDA', 'AMZN', 'META', 'AVGO', 'GOOGL', 'TSLA']
SPY_SYMBOL = 'SPY'

def calculate_same_time_avg_volume(df, lookback_days=20):
    df['time_of_day'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    hist_df = df[df['date'].isin(recent_dates[:-1])]
    if len(hist_df) == 0:
        return pd.Series(df['volume'].mean(), index=df.index)
    
    time_groups = hist_df.groupby('time_of_day')['volume'].mean()
    
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time_of_day']
        if t in time_groups and time_groups[t] > 0:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def get_spy_data(start_date, end_date):
    """Fetch SPY data for market direction"""
    try:
        df = fetch_alpaca_bars(SPY_SYMBOL, start_date, end_date, '5Min',
                               creds['api_key'], creds['secret_key'])
        if df is None or len(df) == 0:
            return None
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        df['date'] = df['timestamp'].dt.date
        return df
    except:
        return None

def analyze_symbol(symbol, start_date, end_date, spy_df):
    try:
        df = fetch_alpaca_bars(symbol, start_date - timedelta(days=25), end_date + timedelta(days=1), '5Min',
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) < 50:
            return []
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        # Calculate volume ratio
        avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
        df['vol_ratio'] = df['volume'] / avg_vol
        
        # Time in ET
        df['hour_et'] = (df['timestamp'].dt.hour - 5) % 24
        df['minute'] = df['timestamp'].dt.minute
        df['time_et'] = df['hour_et'] * 100 + df['minute']
        df['date'] = df['timestamp'].dt.date
        
        trades = []
        dates = sorted(df['date'].unique())
        
        for trade_date in dates:
            day_df = df[df['date'] == trade_date].copy()
            
            # Find 9:30 AM bar
            open_bar = day_df[day_df['time_et'] == 930]
            if len(open_bar) == 0:
                continue
            
            bar = open_bar.iloc[0]
            open_price = bar['open']
            close_price = bar['close']
            bar_high = bar['high']
            bar_low = bar['low']
            rvol = bar['vol_ratio'] if pd.notna(bar['vol_ratio']) else 0
            
            # Calculate metrics
            opening_move = (close_price - open_price) / open_price * 100
            opening_range = (bar_high - bar_low) / open_price * 100
            
            # Direction
            if close_price > open_price:
                direction = 'LONG'
            elif close_price < open_price:
                direction = 'SHORT'
            else:
                continue
            
            # Calculate gap from previous day close
            prev_day = day_df[day_df['time_et'] < 930]
            if len(prev_day) > 0:
                prev_close = prev_day.iloc[-1]['close']
                gap_pct = (open_price - prev_close) / prev_close * 100
            else:
                gap_pct = 0
            
            # Get SPY direction for market context
            market_direction = 'NEUTRAL'
            if spy_df is not None:
                spy_day = spy_df[spy_df['date'] == trade_date]
                if len(spy_day) > 0:
                    spy_open = spy_day[spy_day['time_et'] == 930]
                    if len(spy_open) > 0:
                        spy_bar = spy_open.iloc[0]
                        spy_move = (spy_bar['close'] - spy_bar['open']) / spy_bar['open'] * 100
                        if spy_move > 0.1:
                            market_direction = 'UP'
                        elif spy_move < -0.1:
                            market_direction = 'DOWN'
            
            # Apply the filter logic
            abs_move = abs(opening_move)
            if abs_move < 0.25:
                continue  # Skip small moves
            
            # Determine if trade qualifies
            trade_type = ""
            if 0.25 <= abs_move < 0.75:
                trade_type = "0.25-0.75%"
            elif abs_move >= 0.75:
                if opening_move < 0:  # Red bar
                    trade_type = ">=0.75% red"
                else:
                    trade_type = ">=0.75% green"
            
            trades.append({
                'date': trade_date,
                'symbol': symbol,
                'opening_move': round(opening_move, 2),
                'direction': direction,
                'gap_pct': round(gap_pct, 2),
                'rvol': round(rvol, 2),
                'opening_range': round(opening_range, 2),
                'market_direction': market_direction,
                'trade_type': trade_type
            })
        
        return trades
    except Exception as e:
        print(f"  {symbol}: {str(e)[:50]}")
        return []

def run_study():
    start_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*120)
    print('DETAILED TRADE ANALYSIS')
    print(f'Stocks: {", ".join(SYMBOLS)}')
    print(f'Period: {start_date.date()} to {end_date.date()} (3 months)')
    print('='*120)
    
    # Get SPY data first
    print('\nFetching SPY data for market direction...')
    spy_df = get_spy_data(start_date - timedelta(days=25), end_date + timedelta(days=1))
    if spy_df is not None:
        print(f'  SPY data loaded: {len(spy_df)} bars')
    
    all_trades = []
    
    for sym in SYMBOLS:
        print(f'\nAnalyzing {sym}...', end=' ')
        trades = analyze_symbol(sym, start_date, end_date, spy_df)
        print(f'{len(trades)} trades')
        all_trades.extend(trades)
        time.sleep(0.3)
    
    if not all_trades:
        print('\nNo trades found')
        return
    
    df = pd.DataFrame(all_trades)
    
    print('\n' + '='*120)
    print(f'TOTAL TRADES: {len(df)}')
    print('='*120)
    
    # Print header
    print(f"\n{'Date':12} {'Symbol':8} {'Move%':8} {'Dir':6} {'Gap%':8} {'RVOL':6} {'Range%':8} {'MktDir':8} {'Type':15}")
    print('-'*120)
    
    # Print all trades sorted by date
    df_sorted = df.sort_values('date')
    for _, row in df_sorted.iterrows():
        print(f"{row['date']!s:12} {row['symbol']:8} {row['opening_move']:+7.2f}% {row['direction']:6} "
              f"{row['gap_pct']:+7.2f}% {row['rvol']:6.2f} {row['opening_range']:7.2f}% {row['market_direction']:8} {row['trade_type']:15}")
    
    # Summary by trade type
    print('\n' + '='*120)
    print('SUMMARY BY TRADE TYPE:')
    print('='*120)
    print(f"{'Type':20} {'Count':8} {'Avg Move':10} {'Avg Gap':10} {'Avg RVOL':10} {'Avg Range':10}")
    print('-'*120)
    
    for trade_type in ['0.25-0.75%', '>=0.75% red', '>=0.75% green']:
        type_data = df[df['trade_type'] == trade_type]
        if len(type_data) == 0:
            continue
        
        avg_move = type_data['opening_move'].mean()
        avg_gap = type_data['gap_pct'].mean()
        avg_rvol = type_data['rvol'].mean()
        avg_range = type_data['opening_range'].mean()
        
        print(f"{trade_type:20} {len(type_data):8} {avg_move:+9.2f}% {avg_gap:+9.2f}% {avg_rvol:9.2f} {avg_range:9.2f}%")
    
    # Summary by market direction
    print('\n' + '='*120)
    print('SUMMARY BY MARKET DIRECTION:')
    print('='*120)
    print(f"{'Mkt Dir':12} {'Count':8} {'Avg Move':10} {'Symbols':30}")
    print('-'*120)
    
    for mkt_dir in ['UP', 'DOWN', 'NEUTRAL']:
        mkt_data = df[df['market_direction'] == mkt_dir]
        if len(mkt_data) == 0:
            continue
        
        symbols_list = ', '.join(mkt_data['symbol'].unique()[:5])
        if len(mkt_data['symbol'].unique()) > 5:
            symbols_list += '...'
        
        print(f"{mkt_dir:12} {len(mkt_data):8} {mkt_data['opening_move'].mean():+9.2f}% {symbols_list:30}")
    
    print('='*120)

if __name__ == '__main__':
    run_study()
