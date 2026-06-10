"""
BOOF 28 - MFE/RVOL Analysis: Winning vs Losing Trades
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

def get_rvol(df, bar_idx, vol_len=50):
    """Calculate RVOL at specific bar index"""
    if bar_idx < vol_len:
        return 0
    vol_sma = df['volume'].iloc[bar_idx-vol_len:bar_idx].mean()
    if vol_sma == 0:
        return 0
    return df['volume'].iloc[bar_idx] / vol_sma

def get_first_3_bars_rvol(df):
    """Get RVOL for bars 9:30, 9:31, 9:32 (first 3 bars)"""
    first_bar = df.between_time('09:30', '09:30')
    if len(first_bar) == 0:
        return None, None, None
    
    first_idx = df.index.get_loc(first_bar.index[0])
    
    # Get RVOL for first 3 bars
    rvol1 = get_rvol(df, first_idx)
    rvol2 = get_rvol(df, first_idx + 1) if first_idx + 1 < len(df) else 0
    rvol3 = get_rvol(df, first_idx + 2) if first_idx + 2 < len(df) else 0
    
    return rvol1, rvol2, rvol3

def get_30min_mfe(day_df, entry_price, direction):
    """Get max favorable excursion in first 30 min after entry (9:35-10:05)"""
    # Get 9:35 to 10:05 bars
    bars_30m = day_df.between_time('09:35', '10:05')
    if len(bars_30m) == 0:
        return 0
    
    if direction == 'long':
        max_price = bars_30m['high'].max()
        mfe = (max_price - entry_price) / entry_price * 100
    else:
        min_price = bars_30m['low'].min()
        mfe = (entry_price - min_price) / entry_price * 100
    
    return mfe

def get_30min_return(day_df, entry_price):
    """Get return at 30 min mark (10:05)"""
    bars_30m = day_df.between_time('10:05', '10:05')
    if len(bars_30m) == 0:
        return 0
    
    exit_price = bars_30m.iloc[0]['close']
    return (exit_price - entry_price) / entry_price * 100

def run_analysis():
    print('='*100)
    print('BOOF 28 - MFE/RVOL ANALYSIS (Winners vs Losers)')
    print('='*100)
    
    # Load data
    print("\nLoading cached data...")
    all_data = {}
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
    
    print(f"Loaded {len(all_data)} symbols")
    
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
            if sym not in all_data:
                continue
            
            df = all_data[sym].copy()
            df = df[(df.index >= start_date) & (df.index <= end_date)]
            day = df[df.index.date == trade_date]
            
            if len(day) == 0:
                continue
            
            # Get opening move
            stock_open = day.between_time('09:30', '09:34')
            if len(stock_open) == 0:
                continue
            
            open_p = stock_open.iloc[0]['open']
            close_p = stock_open.iloc[-1]['close']
            stock_move = (close_p - open_p) / open_p
            
            if not (MIN_MOVE <= stock_move <= MAX_MOVE):
                continue
            
            # Entry at 9:35
            entry_data = day.between_time('09:35', '09:35')
            if len(entry_data) == 0:
                continue
            
            entry_price = entry_data.iloc[0]['close']
            direction = 'long' if stock_move > 0 else 'short'
            
            # Get 30min data
            mfe = get_30min_mfe(day, entry_price, direction)
            ret_30m = get_30min_return(day, entry_price)
            
            # Get RVOL of first 3 bars
            rvol1, rvol2, rvol3 = get_first_3_bars_rvol(day)
            if rvol1 is None:
                continue
            
            # Final P&L (exit at 10:15)
            exit_data = day.between_time('10:15', '10:15')
            if len(exit_data) == 0:
                continue
            
            exit_price = exit_data.iloc[0]['close']
            pnl = (exit_price - entry_price) / entry_price * 100
            
            trades.append({
                'date': trade_date,
                'symbol': sym,
                'pnl': pnl,
                'mfe': mfe,
                'ret_30m': ret_30m,
                'rvol1': rvol1,
                'rvol2': rvol2,
                'rvol3': rvol3,
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
    
    # Split winners and losers
    winners = df[df['pnl'] > 0]
    losers = df[df['pnl'] <= 0]
    
    print(f"\nWinners: {len(winners)} trades")
    print(f"Losers: {len(losers)} trades")
    print(f"Win Rate: {len(winners)/len(df)*100:.1f}%")
    
    # Compare stats
    metrics = ['mfe', 'ret_30m', 'rvol1', 'rvol2', 'rvol3', 'qqq_move', 'stock_move']
    
    print(f"\n{'='*100}")
    print("WINNERS vs LOSERS - STATISTICAL COMPARISON")
    print(f"{'='*100}")
    print(f"{'Metric':15} {'Winners Avg':12} {'Losers Avg':12} {'Diff':12} {'Win Median':12} {'Lose Median':12}")
    print('-'*100)
    
    for metric in metrics:
        w_avg = winners[metric].mean()
        l_avg = losers[metric].mean()
        w_med = winners[metric].median()
        l_med = losers[metric].median()
        diff = w_avg - l_avg
        
        print(f"{metric:15} {w_avg:11.3f} {l_avg:11.3f} {diff:+11.3f} {w_med:11.3f} {l_med:11.3f}")
    
    # Detailed breakdown
    print(f"\n{'='*100}")
    print("DETAILED BREAKDOWN")
    print(f"{'='*100}")
    
    print("\n--- WINNERS ---")
    for metric in metrics:
        vals = winners[metric]
        print(f"{metric:15}: mean={vals.mean():.3f}, std={vals.std():.3f}, min={vals.min():.3f}, max={vals.max():.3f}")
    
    print("\n--- LOSERS ---")
    for metric in metrics:
        vals = losers[metric]
        print(f"{metric:15}: mean={vals.mean():.3f}, std={vals.std():.3f}, min={vals.min():.3f}, max={vals.max():.3f}")
    
    # Correlation with P&L
    print(f"\n{'='*100}")
    print("CORRELATION WITH FINAL P&L")
    print(f"{'='*100}")
    print(f"{'Metric':15} {'Correlation':12}")
    print('-'*30)
    
    for metric in metrics:
        corr = df[metric].corr(df['pnl'])
        print(f"{metric:15} {corr:11.3f}")
    
    # Top insights
    print(f"\n{'='*100}")
    print("KEY INSIGHTS")
    print(f"{'='*100}")
    
    # MFE analysis
    w_mfe_avg = winners['mfe'].mean()
    l_mfe_avg = losers['mfe'].mean()
    print(f"\n1. MFE (30min max favorable move):")
    print(f"   Winners can run: +{w_mfe_avg:.2f}% on average")
    print(f"   Losers only run: +{l_mfe_avg:.2f}% before reversing")
    print(f"   Edge: Winners give {w_mfe_avg - l_mfe_avg:.2f}% more room")
    
    # RVOL analysis
    w_rvol_avg = (winners['rvol1'] + winners['rvol2'] + winners['rvol3']).mean() / 3
    l_rvol_avg = (losers['rvol1'] + losers['rvol2'] + losers['rvol3']).mean() / 3
    print(f"\n2. RVOL (Volume intensity):")
    print(f"   Winning trades avg RVOL: {w_rvol_avg:.2f}x")
    print(f"   Losing trades avg RVOL: {l_rvol_avg:.2f}x")
    
    # 30min return
    w_30m = winners['ret_30m'].mean()
    l_30m = losers['ret_30m'].mean()
    print(f"\n3. 30-Min Return:")
    print(f"   Winners at 30min: {w_30m:+.2f}%")
    print(f"   Losers at 30min: {l_30m:+.2f}%")
    print(f"   30min predicts final outcome: {'YES' if abs(w_30m - l_30m) > 0.1 else 'WEAK'}")
    
    print(f"\n{'='*100}")

if __name__ == '__main__':
    run_analysis()
