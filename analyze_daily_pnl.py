"""
Analyze daily P&L from backtest results
"""
import pandas as pd
from datetime import datetime

def analyze_daily(trades_file, name):
    df = pd.read_csv(trades_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['date'] = df['entry_time'].dt.date
    
    daily = df.groupby('date').agg({
        'pnl': ['sum', 'count', 'mean'],
        'result': lambda x: (x == 'win').mean()
    }).reset_index()
    
    daily.columns = ['date', 'total_pnl', 'trades', 'avg_pnl', 'win_rate']
    
    print(f"\n{'='*60}")
    print(f"{name} DAILY METRICS")
    print(f"{'='*60}")
    print(f"Trading days: {len(daily)}")
    print(f"Trades per day: {daily['trades'].mean():.1f} (range: {daily['trades'].min()}-{daily['trades'].max()})")
    print(f"\nDaily P&L:")
    print(f"  Average: ${daily['total_pnl'].mean():.2f}")
    print(f"  Median:  ${daily['total_pnl'].median():.2f}")
    print(f"  Min:     ${daily['total_pnl'].min():.2f}")
    print(f"  Max:     ${daily['total_pnl'].max():.2f}")
    print(f"  Std Dev: ${daily['total_pnl'].std():.2f}")
    
    print(f"\nDaily Win Rate: {daily['win_rate'].mean()*100:.1f}%")
    
    # Worst and best days
    print(f"\nBest day:  {daily.loc[daily['total_pnl'].idxmax(), 'date']} = ${daily['total_pnl'].max():.2f}")
    print(f"Worst day: {daily.loc[daily['total_pnl'].idxmin(), 'date']} = ${daily['total_pnl'].min():.2f}")
    
    # Consecutive loss days
    daily_sorted = daily.sort_values('date')
    loss_days = (daily_sorted['total_pnl'] < 0).astype(int)
    consecutive_losses = []
    current_streak = 0
    for is_loss in loss_days:
        if is_loss:
            current_streak += 1
        else:
            if current_streak > 0:
                consecutive_losses.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        consecutive_losses.append(current_streak)
    
    print(f"\nRed days: {len(daily[daily['total_pnl'] < 0])}/{len(daily)} ({len(daily[daily['total_pnl'] < 0])/len(daily)*100:.1f}%)")
    print(f"Green days: {len(daily[daily['total_pnl'] > 0])}/{len(daily)} ({len(daily[daily['total_pnl'] > 0])/len(daily)*100:.1f}%)")
    if consecutive_losses:
        print(f"Max consecutive red days: {max(consecutive_losses)}")
    
    return daily

# Analyze the latest results
import glob
import os

# Find latest CSV files
files_22 = sorted(glob.glob('backtest_boof22_results_*.csv'))
files_23 = sorted(glob.glob('backtest_boof23_results_*.csv'))

if files_22:
    daily_22 = analyze_daily(files_22[-1], 'BOOF 22')
if files_23:
    daily_23 = analyze_daily(files_23[-1], 'BOOF 23')

# Combined
if files_22 and files_23:
    df_22 = pd.read_csv(files_22[-1])
    df_23 = pd.read_csv(files_23[-1])
    df_combined = pd.concat([df_22, df_23])
    df_combined['entry_time'] = pd.to_datetime(df_combined['entry_time'])
    df_combined['date'] = df_combined['entry_time'].dt.date
    
    daily_combined = df_combined.groupby('date')['pnl'].sum().reset_index()
    daily_combined.columns = ['date', 'total_pnl']
    
    print(f"\n{'='*60}")
    print(f"BOOF 22 + 23 COMBINED DAILY")
    print(f"{'='*60}")
    print(f"Trading days: {len(daily_combined)}")
    print(f"Daily P&L:")
    print(f"  Average: ${daily_combined['total_pnl'].mean():.2f}")
    print(f"  Median:  ${daily_combined['total_pnl'].median():.2f}")
    print(f"  Min:     ${daily_combined['total_pnl'].min():.2f}")
    print(f"  Max:     ${daily_combined['total_pnl'].max():.2f}")
    print(f"  Std Dev: ${daily_combined['total_pnl'].std():.2f}")
    print(f"\nBest day:  ${daily_combined['total_pnl'].max():.2f}")
    print(f"Worst day: ${daily_combined['total_pnl'].min():.2f}")
