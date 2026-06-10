"""
BOOF 28 - Quick 1-Month Backtest (2-hour window, 9:30-11:30)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 50 stocks for speed
UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","JPM","V","MA","BAC","UNH","JNJ","LLY",
    "WMT","COST","HD","PG","KO","XOM","CVX","GE","DIS","COIN",
    "GME","PLTR","SOFI","RBLX","BABA","JD","SPY","QQQ","IWM"
]

def get_5m_data(symbol, start_date, end_date):
    df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df

def calculate_same_time_avg_volume(df, lookback_days=20):
    df['time'] = df['timestamp'].dt.time
    df['date'] = df['timestamp'].dt.date
    
    dates = sorted(df['date'].unique())
    if len(dates) > lookback_days:
        recent_dates = dates[-lookback_days:]
    else:
        recent_dates = dates
    
    hist_df = df[df['date'].isin(recent_dates[:-1])]
    if len(hist_df) == 0:
        return pd.Series(df['volume'].mean(), index=df.index)
    
    time_groups = hist_df.groupby('time')['volume'].mean()
    
    avg_volumes = []
    for idx, row in df.iterrows():
        t = row['time']
        if t in time_groups:
            avg_volumes.append(time_groups[t])
        else:
            avg_volumes.append(row['volume'])
    
    return pd.Series(avg_volumes, index=df.index)

def run_backtest():
    # 1 month: January 2026
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 31, tzinfo=timezone.utc)
    
    # Fetch extra for volume calc
    fetch_start = start_date - timedelta(days=25)
    fetch_end = end_date + timedelta(days=1)
    
    print('='*80)
    print('BOOF 28 - 1 MONTH BACKTEST (Jan 2026)')
    print('2-hour window: 9:30-11:30 AM')
    print('Target: 1% profit on stock movement')
    print(f'Stocks: {len(UNIVERSE)}')
    print('='*80)
    
    # Trading days
    trading_days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)
    
    print(f'\nScanning {len(trading_days)} days...\n')
    
    all_trades = []
    
    for trade_date in trading_days:
        day_trades = []
        
        for sym in UNIVERSE:
            try:
                df = get_5m_data(sym, fetch_start, fetch_end)
                if df is None or len(df) < 20:
                    continue
                
                # Calculate seasonal average
                avg_vol = calculate_same_time_avg_volume(df, lookback_days=20)
                
                # Get today's data
                today_mask = df['timestamp'].dt.date == trade_date.date()
                today_df = df[today_mask].reset_index(drop=True)
                today_avg = avg_vol[today_mask].reset_index(drop=True)
                
                if len(today_df) < 24:  # Need 2 hours (24 bars)
                    continue
                
                # Only check first 24 bars (9:30-11:30 = 2 hours)
                for i in range(min(19, len(today_df) - 5)):  # Up to 10:55, need 5 bars after
                    if pd.isna(today_avg.iloc[i]) or today_avg.iloc[i] == 0:
                        continue
                    
                    vol_ratio = today_df['volume'].iloc[i] / today_avg.iloc[i]
                    
                    # Volume spike >= 3.0x
                    if vol_ratio < 3.0:
                        continue
                    
                    # Clean continuation check (5 bars = 25 min)
                    close_i = today_df['close'].iloc[i]
                    close_i5 = today_df['close'].iloc[i + 5]
                    
                    five_min_move = (close_i5 - close_i) / close_i
                    
                    # Need at least 1% move for target
                    if abs(five_min_move) < 0.01:  # 1% minimum move
                        continue
                    
                    # Trend efficiency
                    range_high = today_df['high'].iloc[i+1:i+6].max()
                    range_low = today_df['low'].iloc[i+1:i+6].min()
                    range_chop = range_high - range_low
                    net_move = abs(close_i5 - close_i)
                    trend_efficiency = net_move / range_chop if range_chop > 0 else 0
                    
                    if trend_efficiency < 0.45:
                        continue
                    
                    # Direction
                    direction = 'LONG' if five_min_move > 0 else 'SHORT'
                    
                    # Entry at i+5
                    entry_idx = i + 5
                    entry_price = close_i5
                    
                    # Target: 1% profit (not 0.5% stop)
                    pnl = None
                    if direction == 'SHORT':
                        tp = entry_price * 0.99  # 1% down
                        sl = entry_price * 1.005  # 0.5% up stop
                        for j in range(entry_idx + 1, min(entry_idx + 12, len(today_df))):  # 1 hour max
                            if today_df['low'].iloc[j] <= tp:
                                pnl = 1.0
                                break
                            if today_df['high'].iloc[j] >= sl:
                                pnl = -0.5
                                break
                    else:
                        tp = entry_price * 1.01  # 1% up
                        sl = entry_price * 0.995  # 0.5% down stop
                        for j in range(entry_idx + 1, min(entry_idx + 12, len(today_df))):
                            if today_df['high'].iloc[j] >= tp:
                                pnl = 1.0
                                break
                            if today_df['low'].iloc[j] <= sl:
                                pnl = -0.5
                                break
                    
                    if pnl is None:
                        exit_price = today_df['close'].iloc[min(entry_idx + 11, len(today_df) - 1)]
                        if direction == 'SHORT':
                            pnl = (entry_price - exit_price) / entry_price * 100
                        else:
                            pnl = (exit_price - entry_price) / entry_price * 100
                    
                    if pnl is not None:
                        day_trades.append({
                            'date': trade_date,
                            'symbol': sym,
                            'direction': direction,
                            'entry': entry_price,
                            'move_pct': five_min_move * 100,
                            'pnl': pnl
                        })
                
                time.sleep(0.02)
                
            except Exception as e:
                pass
        
        if day_trades:
            day_pnl = sum(t['pnl'] for t in day_trades)
            print(f"{trade_date.date()}: {len(day_trades)} trades, P&L: {day_pnl:+.2f}%")
            all_trades.extend(day_trades)
    
    print('='*80)
    
    if all_trades:
        df_results = pd.DataFrame(all_trades)
        wins = len(df_results[df_results['pnl'] > 0])
        total_pnl = df_results['pnl'].sum()
        
        print(f'\nFINAL RESULTS - JANUARY 2026:')
        print(f'Total Trades: {len(df_results)}')
        print(f'Win Rate: {wins/len(df_results)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(df_results):.3f}%')
        
        # Filter for 1%+ profit moves
        big_moves = df_results[abs(df_results['move_pct']) >= 1.0]
        if len(big_moves) > 0:
            print(f'\nTrades with 1%+ initial move: {len(big_moves)}')
            print(f'Those trades P&L: {big_moves["pnl"].sum():+.2f}%')
        
        print(f'\nTop Symbols:')
        sym_pnl = df_results.groupby('symbol')['pnl'].sum().sort_values(ascending=False).head(10)
        for sym, pnl in sym_pnl.items():
            count = len(df_results[df_results['symbol'] == sym])
            print(f'  {sym}: {count} trades, {pnl:+.2f}%')
    else:
        print('\nNo trades generated')
    
    print('='*80)

if __name__ == '__main__':
    run_backtest()
