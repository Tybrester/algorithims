"""
BOOF 28 - Volume Persistence Test
bar1_rvol = vol_930 / avg_vol_930
bar2_rvol = vol_935 / avg_vol_935  
bar3_rvol = vol_940 / avg_vol_940
decay_ratio = bar3_rvol / bar1_rvol
volume_persistent = bar1_rvol > 2.0 AND bar2_rvol > 1.5 AND bar3_rvol > 1.5
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
from datetime import datetime
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL", "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER", "SMCI", "ANET", "DELL", "HPE", "STM",
    "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "CRM", "ADBE", "INTU", "NOW", "SHOP", "ORCL", "IBM", "CSCO",
    "PLTR", "SNOW", "DDOG", "MDB", "NET", "CRWD", "PANW", "ZS", "ESTC", "S",
    "AI", "PATH", "DOCN", "FSLY", "AKAM",
    "PYPL", "SQ", "HOOD", "COIN", "ADP", "FIS", "FI", "GPN", "JKHY",
    "UBER", "ABNB", "DASH", "RBLX", "APP",
    "TTD", "DUOL", "CELH", "CAVA", "RKLB",
    "LLY", "NVO", "ABBV", "JNJ", "MRK", "AMGN", "GILD", "REGN", "VRTX", "ISRG",
    "BIIB", "BMY", "PFE", "MRNA", "NBIX",
    "GE", "CAT", "ETN", "PH", "TT", "DE", "HON", "EMR", "ROP", "URI"
]

MIN_MOVE = 0.0050
MAX_MOVE = 0.0080

def load_cached(symbol):
    cache_file = f"boof_cache/{symbol}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def calculate_time_of_day_avg_volume(all_data, symbol, time_str):
    """Calculate average volume at specific time across all days"""
    if symbol not in all_data:
        return None
    df = all_data[symbol]
    df['date'] = df.index.date
    unique_dates = df['date'].unique()
    volumes = []
    for date in unique_dates:
        day_df = df[df['date'] == date]
        bar = day_df.between_time(time_str, time_str)
        if len(bar) > 0:
            volumes.append(bar.iloc[0]['volume'])
    return np.mean(volumes) if volumes else 1

def get_bar_volume(df, time_str):
    bar = df.between_time(time_str, time_str)
    if len(bar) == 0:
        return 0
    return bar.iloc[0]['volume']

def run_test():
    print('='*100)
    print('BOOF 28 - VOLUME PERSISTENCE TEST')
    print('='*100)
    
    # Load data
    print("\nLoading cached data...")
    all_data = {}
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
    
    print(f"Loaded {len(all_data)} symbols")
    
    # Pre-calculate time-of-day averages
    print("\nCalculating time-of-day average volumes...")
    time_avgs = {}
    for sym in SYMBOLS:
        if sym not in all_data:
            continue
        time_avgs[sym] = {
            '09:30': calculate_time_of_day_avg_volume(all_data, sym, '09:30'),
            '09:35': calculate_time_of_day_avg_volume(all_data, sym, '09:35'),
            '09:40': calculate_time_of_day_avg_volume(all_data, sym, '09:40')
        }
    
    # Date range: 2025 full year
    start_date = pd.to_datetime('2025-01-01').tz_localize('UTC')
    end_date = pd.to_datetime('2025-12-31').tz_localize('UTC')
    
    trades = []
    
    qqq_df = all_data['QQQ'].copy()
    qqq_df = qqq_df[(qqq_df.index >= start_date) & (qqq_df.index <= end_date)]
    qqq_df['date'] = qqq_df.index.date
    dates = sorted(qqq_df['date'].unique())
    
    print(f"\nAnalyzing {len(dates)} trading days...")
    
    for trade_date in dates:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = qqq_day.between_time('09:30', '09:34')
        if len(qqq_open) == 0:
            continue
        
        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        if qqq_move <= 0:
            continue
        
        for sym in SYMBOLS:
            if sym not in all_data or sym not in time_avgs:
                continue
            
            df = all_data[sym].copy()
            df = df[(df.index >= start_date) & (df.index <= end_date)]
            day = df[df.index.date == trade_date]
            if len(day) == 0:
                continue
            
            # Opening move
            stock_open = day.between_time('09:30', '09:34')
            if len(stock_open) == 0:
                continue
            
            open_p = stock_open.iloc[0]['open']
            close_p = stock_open.iloc[-1]['close']
            stock_move = (close_p - open_p) / open_p
            
            if not (MIN_MOVE <= stock_move <= MAX_MOVE):
                continue
            
            # Get volumes and calculate RVOL
            vol_930 = get_bar_volume(day, '09:30')
            vol_935 = get_bar_volume(day, '09:35')
            vol_940 = get_bar_volume(day, '09:40')
            
            avg_930 = time_avgs[sym]['09:30']
            avg_935 = time_avgs[sym]['09:35']
            avg_940 = time_avgs[sym]['09:40']
            
            bar1_rvol = vol_930 / avg_930 if avg_930 > 0 else 0
            bar2_rvol = vol_935 / avg_935 if avg_935 > 0 else 0
            bar3_rvol = vol_940 / avg_940 if avg_940 > 0 else 0
            
            # Decay ratio
            decay_ratio = bar3_rvol / bar1_rvol if bar1_rvol > 0 else 0
            
            # Volume persistence check
            volume_persistent = (bar1_rvol > 2.0 and bar2_rvol > 1.5 and bar3_rvol > 1.5)
            
            # Entry/exit
            entry_data = day.between_time('09:35', '09:35')
            exit_data = day.between_time('10:15', '10:15')
            if len(entry_data) == 0 or len(exit_data) == 0:
                continue
            
            entry_price = entry_data.iloc[0]['close']
            exit_price = exit_data.iloc[0]['close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': sym,
                'pnl': pnl,
                'bar1_rvol': bar1_rvol,
                'bar2_rvol': bar2_rvol,
                'bar3_rvol': bar3_rvol,
                'decay_ratio': decay_ratio,
                'volume_persistent': volume_persistent,
                'qqq_move': qqq_move,
                'stock_move': stock_move
            })
    
    if not trades:
        print("No trades found")
        return
    
    df = pd.DataFrame(trades)
    
    print(f"\n{'='*100}")
    print(f"TOTAL TRADES: {len(df)}")
    print(f"{'='*100}")
    
    # Split by volume persistence
    persistent = df[df['volume_persistent'] == True]
    non_persistent = df[df['volume_persistent'] == False]
    
    # Calculate metrics
    def calc_metrics(data, label):
        if len(data) == 0:
            return {
                'trade_count': 0,
                'win_rate': 0,
                'avg_pnl': 0,
                'total_pnl': 0,
                'avg_decay': 0
            }
        
        wins = len(data[data['pnl'] > 0])
        return {
            'trade_count': len(data),
            'win_rate': wins / len(data) * 100,
            'avg_pnl': data['pnl'].mean(),
            'total_pnl': data['pnl'].sum(),
            'avg_decay': data['decay_ratio'].mean()
        }
    
    p_metrics = calc_metrics(persistent, 'Persistent')
    np_metrics = calc_metrics(non_persistent, 'Non-Persistent')
    
    # Print comparison
    print(f"\n{'='*100}")
    print("VOLUME PERSISTENCE COMPARISON")
    print(f"{'='*100}")
    print(f"{'Metric':25} {'Persistent':15} {'Non-Persistent':15} {'Diff':15}")
    print('-'*100)
    print(f"{'Trade Count':25} {p_metrics['trade_count']:15.0f} {np_metrics['trade_count']:15.0f} {p_metrics['trade_count']-np_metrics['trade_count']:+.0f}")
    print(f"{'Win Rate (%)':25} {p_metrics['win_rate']:14.1f}% {np_metrics['win_rate']:14.1f}% {p_metrics['win_rate']-np_metrics['win_rate']:+.1f}%")
    print(f"{'Avg P&L (%)':25} {p_metrics['avg_pnl']:14.2f}% {np_metrics['avg_pnl']:14.2f}% {p_metrics['avg_pnl']-np_metrics['avg_pnl']:+.2f}%")
    print(f"{'Total P&L (%)':25} {p_metrics['total_pnl']:14.2f}% {np_metrics['total_pnl']:14.2f}% {p_metrics['total_pnl']-np_metrics['total_pnl']:+.2f}%")
    print(f"{'Avg Decay Ratio':25} {p_metrics['avg_decay']:15.2f} {np_metrics['avg_decay']:15.2f} {p_metrics['avg_decay']-np_metrics['avg_decay']:+.2f}")
    
    # Decay ratio analysis for winners vs losers
    print(f"\n{'='*100}")
    print("DECAY RATIO: WINNERS vs LOSERS")
    print(f"{'='*100}")
    
    winners = df[df['pnl'] > 0]
    losers = df[df['pnl'] <= 0]
    
    print(f"Winners ({len(winners)} trades):")
    print(f"  Avg Decay Ratio: {winners['decay_ratio'].mean():.3f}")
    print(f"  Median Decay: {winners['decay_ratio'].median():.3f}")
    print(f"  Std Dev: {winners['decay_ratio'].std():.3f}")
    
    print(f"\nLosers ({len(losers)} trades):")
    print(f"  Avg Decay Ratio: {losers['decay_ratio'].mean():.3f}")
    print(f"  Median Decay: {losers['decay_ratio'].median():.3f}")
    print(f"  Std Dev: {losers['decay_ratio'].std():.3f}")
    
    # Correlation
    corr_decay_pnl = df['decay_ratio'].corr(df['pnl'])
    print(f"\nCorrelation (decay_ratio vs pnl): {corr_decay_pnl:.3f}")
    
    # Insight
    print(f"\n{'='*100}")
    print("KEY INSIGHT")
    print(f"{'='*100}")
    
    if p_metrics['win_rate'] > np_metrics['win_rate']:
        print(f"✓ Persistent volume IMPROVES win rate by {p_metrics['win_rate']-np_metrics['win_rate']:.1f}%")
    else:
        print(f"✗ Persistent volume HURTS win rate by {np_metrics['win_rate']-p_metrics['win_rate']:.1f}%")
    
    if winners['decay_ratio'].mean() < losers['decay_ratio'].mean():
        print(f"✓ Lower decay ratio (volume holding up) correlates with WINS")
        print(f"  Winners decay: {winners['decay_ratio'].mean():.2f}x")
        print(f"  Losers decay: {losers['decay_ratio'].mean():.2f}x")
    else:
        print(f"✗ Higher decay ratio (volume dropping off) correlates with wins")
    
    print(f"{'='*100}")

if __name__ == '__main__':
    run_test()
