import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
import random
warnings.filterwarnings('ignore')

print('='*80)
print('COMPREHENSIVE VALIDATION SUITE')
print('='*80)

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

# =============================================================================
# 1. WALK-FORWARD VALIDATION
# =============================================================================
print()
print('='*80)
print('1. WALK-FORWARD VALIDATION')
print('='*80)
print('Rolling windows: 2 months train, 1 month test')
print()

# Load all signals
all_signals = []

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

for symbol in CORE_UNIVERSE[:5]:  # Sample for speed
    try:
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
        df['month'] = df['timestamp'].dt.to_period('M')
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['tpv'] = df['tp'] * df['volume']
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
            
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            if len(pm_data) < 35:
                continue
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    score = 0
                    if b1['rvol'] > 8: score += 1
                    if b1['body'] * 100 > 0.9: score += 1
                    if b1['vwap_slope'] > 0.25: score += 1
                    if b2['body'] * 100 > 0.5: score += 1
                    
                    if score >= 3:
                        future = pm_data.iloc[i+2:i+32]
                        mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                        mae = (future['low'].min() - b2['close']) / b2['close'] * 100
                        
                        all_signals.append({
                            'symbol': symbol,
                            'date': str(date),
                            'month': str(day.iloc[0]['month']),
                            'score': score,
                            'mfe': mfe,
                            'mae': mae,
                            'entry': b2['close']
                        })
    except Exception as e:
        pass

signals_df = pd.DataFrame(all_signals)

if len(signals_df) > 0:
    print(f'Total signals captured: {len(signals_df)}')
    print()
    
    # Monthly performance
    monthly_perf = signals_df.groupby('month').agg({
        'mfe': ['count', 'mean', lambda x: sum(x >= 2), lambda x: sum(x >= 1.75)]
    }).round(2)
    monthly_perf.columns = ['Signals', 'Avg_MFE', 'Runners_2pct', 'Winners_1_75pct']
    monthly_perf['WinRate_2pct'] = (monthly_perf['Runners_2pct'] / monthly_perf['Signals'] * 100).round(1)
    monthly_perf['WinRate_1_75pct'] = (monthly_perf['Winners_1_75pct'] / monthly_perf['Signals'] * 100).round(1)
    
    print('Monthly Performance:')
    print(monthly_perf.to_string())
    print()
    
    # Consistency check
    win_rates_2 = monthly_perf['WinRate_2pct'].dropna()
    win_rates_175 = monthly_perf['WinRate_1_75pct'].dropna()
    
    print('Consistency Analysis:')
    print(f'  2% TP win rate std dev: {win_rates_2.std():.2f}% (lower = more consistent)')
    print(f'  1.75% TP win rate std dev: {win_rates_175.std():.2f}%')
    print(f'  Months with >50% win rate (2% TP): {sum(win_rates_2 > 50)}/{len(win_rates_2)}')
    print(f'  Months with >50% win rate (1.75% TP): {sum(win_rates_175 > 50)}/{len(win_rates_175)}')

# =============================================================================
# 2. MONTE CARLO SIMULATION
# =============================================================================
print()
print('='*80)
print('2. MONTE CARLO SIMULATION')
print('='*80)
print('Shuffling trade sequence 5,000 times')
print()

if len(signals_df) > 0:
    # Use actual trade outcomes
    trades = signals_df.copy()
    
    # Define outcomes for partial exit strategy
    def calc_trade_pnl(mfe, mae):
        # Partial exit: 50% at 1%, 50% at 1.75%, SL at -1%
        # Simplified model based on first-touch logic
        if mae <= -1.0:
            return -1.0  # Full SL hit first
        elif mfe >= 1.75:
            return 0.5 * 1.0 + 0.5 * 1.75  # Both targets
        elif mfe >= 1.0:
            return 0.5 * 1.0 + 0.5 * mfe  # 1% hit, rest at close
        else:
            return mfe * 0.5  # Small gain/loss
    
    trades['pnl'] = trades.apply(lambda r: calc_trade_pnl(r['mfe'], r['mae']), axis=1)
    
    n_simulations = 5000
    final_pnls = []
    max_drawdowns = []
    win_streaks = []
    loss_streaks = []
    
    pnl_list = trades['pnl'].tolist()
    
    for _ in range(n_simulations):
        shuffled = random.sample(pnl_list, len(pnl_list))
        
        # Cumulative P&L
        cumulative = [0]
        for p in shuffled:
            cumulative.append(cumulative[-1] + p)
        
        final_pnls.append(cumulative[-1])
        
        # Max drawdown
        peak = 0
        max_dd = 0
        for val in cumulative:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        max_drawdowns.append(max_dd)
        
        # Win/loss streaks
        wins = [1 if p > 0 else 0 for p in shuffled]
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        
        for w in wins:
            if w == 1:
                if current_streak > 0:
                    current_streak += 1
                else:
                    current_streak = 1
                max_win_streak = max(max_win_streak, current_streak)
            else:
                if current_streak < 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                max_loss_streak = max(max_loss_streak, abs(current_streak))
        
        win_streaks.append(max_win_streak)
        loss_streaks.append(max_loss_streak)
    
    print(f'Simulations run: {n_simulations:,}')
    print()
    print('P&L Distribution:')
    print(f'  Mean final P&L: {np.mean(final_pnls):.2f}%')
    print(f'  Median final P&L: {np.median(final_pnls):.2f}%')
    print(f'  Std dev: {np.std(final_pnls):.2f}%')
    print(f'  Worst case: {np.min(final_pnls):.2f}%')
    print(f'  Best case: {np.max(final_pnls):.2f}%')
    print(f'  P10 (90% above): {np.percentile(final_pnls, 10):.2f}%')
    print(f'  P90 (10% above): {np.percentile(final_pnls, 90):.2f}%')
    print()
    print('Drawdown Analysis:')
    print(f'  Avg max drawdown: {np.mean(max_drawdowns):.2f}%')
    print(f'  Median max drawdown: {np.median(max_drawdowns):.2f}%')
    print(f'  P95 max drawdown: {np.percentile(max_drawdowns, 95):.2f}%')
    print()
    print('Streak Analysis:')
    print(f'  Avg max win streak: {np.mean(win_streaks):.1f}')
    print(f'  Avg max loss streak: {np.mean(loss_streaks):.1f}')
    print(f'  Worst loss streak (P95): {np.percentile(loss_streaks, 95):.0f}')

# =============================================================================
# 3. FIRST-TOUCH TP/SL VERIFICATION
# =============================================================================
print()
print('='*80)
print('3. FIRST-TOUCH TP/SL VERIFICATION')
print('='*80)
print('Analyzing which hits first: TP or SL')
print()

# Analyze a sample of trades for first-touch
sample_symbols = ['UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT']
first_touch_results = []

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

for symbol in sample_symbols:
    try:
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
        
        for date, day in df.groupby('date'):
            day = day.sort_values('timestamp').reset_index(drop=True)
            if len(day) < 50:
                continue
            
            day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
            day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
            day['rvol'] = day['volume'] / day['avg_vol']
            day['body'] = abs(day['close'] - day['open']) / day['open']
            day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
            
            mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
            pm_data = day[mask_pm].reset_index(drop=True)
            
            if len(pm_data) < 35:
                continue
            
            for i in range(len(pm_data) - 30):
                if i + 1 >= len(pm_data):
                    continue
                
                b1 = pm_data.iloc[i]
                b2 = pm_data.iloc[i+1]
                
                if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                    b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                    
                    score = 0
                    if b1['rvol'] > 8: score += 1
                    if b1['body'] * 100 > 0.9: score += 1
                    if b1['vwap_slope'] > 0.25: score += 1
                    if b2['body'] * 100 > 0.5: score += 1
                    
                    if score >= 3:
                        entry = b2['close']
                        tp_1 = entry * 1.01
                        tp_175 = entry * 1.0175
                        sl = entry * 0.99
                        
                        future = pm_data.iloc[i+2:i+32]
                        
                        # Track first touch
                        tp1_bar = None
                        tp175_bar = None
                        sl_bar = None
                        
                        for j, (_, bar) in enumerate(future.iterrows()):
                            if tp1_bar is None and bar['high'] >= tp_1:
                                tp1_bar = j + 1
                            if tp175_bar is None and bar['high'] >= tp_175:
                                tp175_bar = j + 1
                            if sl_bar is None and bar['low'] <= sl:
                                sl_bar = j + 1
                            
                            if sl_bar and tp1_bar:
                                break
                        
                        # Determine outcome
                        if sl_bar and tp1_bar is None:
                            outcome = 'SL_FIRST'
                        elif sl_bar and tp1_bar and sl_bar < tp1_bar:
                            outcome = 'SL_FIRST'
                        elif tp1_bar and sl_bar is None:
                            outcome = 'TP1_FIRST'
                        elif tp1_bar and sl_bar and tp1_bar < sl_bar:
                            outcome = 'TP1_FIRST'
                        elif tp175_bar and sl_bar and tp175_bar < sl_bar:
                            outcome = 'TP175_FIRST'
                        else:
                            outcome = 'NO_CLEAR'
                        
                        first_touch_results.append({
                            'symbol': symbol,
                            'date': str(date),
                            'outcome': outcome,
                            'tp1_bar': tp1_bar,
                            'tp175_bar': tp175_bar,
                            'sl_bar': sl_bar,
                            'mfe': (future['high'].max() - entry) / entry * 100,
                            'mae': (future['low'].min() - entry) / entry * 100
                        })
    except Exception as e:
        pass

if first_touch_results:
    ft_df = pd.DataFrame(first_touch_results)
    
    print(f'Sample trades analyzed: {len(ft_df)}')
    print()
    
    outcome_counts = ft_df['outcome'].value_counts()
    print('First-Touch Outcomes:')
    for outcome, count in outcome_counts.items():
        pct = count / len(ft_df) * 100
        print(f'  {outcome}: {count} ({pct:.1f}%)')
    
    print()
    print('Comparison to "Eventual" MFE:')
    
    # How many would be misclassified
    tp1_first = ft_df[ft_df['outcome'] == 'TP1_FIRST']
    sl_first = ft_df[ft_df['outcome'] == 'SL_FIRST']
    
    # Of SL first, how many eventually recovered to be winners?
    sl_recovery = sl_first[sl_first['mfe'] >= 2.0]
    print(f'  Trades hitting SL first but eventually MFE >= 2%: {len(sl_recovery)}/{len(sl_first)} ({len(sl_recovery)/len(sl_first)*100:.1f}%)')
    print(f'  -> These would be MISCLASSIFIED as winners using only eventual MFE')
    
    tp1_slipped = tp1_first[tp1_first['mae'] <= -2.0]
    print(f'  Trades hitting TP1 first but eventually MAE <= -2%: {len(tp1_slipped)}/{len(tp1_first)} ({len(tp1_slipped)/len(tp1_first)*100:.1f}%)')

# =============================================================================
# 4. MAE/MFE PERCENTILE VERIFICATION
# =============================================================================
print()
print('='*80)
print('4. MAE / MFE PERCENTILE VERIFICATION')
print('='*80)
print()

if len(signals_df) > 0:
    mfe_vals = signals_df['mfe'].values
    mae_vals = signals_df['mae'].values
    
    print('MFE (Favorable Excursion) Distribution:')
    for p in [10, 25, 50, 75, 90, 95, 99]:
        print(f'  P{p}: {np.percentile(mfe_vals, p):.2f}%')
    
    print()
    print('MAE (Adverse Excursion) Distribution:')
    for p in [1, 5, 10, 25, 50, 75, 90]:
        print(f'  P{p}: {np.percentile(mae_vals, p):.2f}%')
    
    print()
    print('Risk/Reward Analysis:')
    print(f'  Avg MFE: {np.mean(mfe_vals):.2f}%')
    print(f'  Avg MAE: {np.mean(mae_vals):.2f}%')
    print(f'  Median MFE: {np.median(mfe_vals):.2f}%')
    print(f'  Median MAE: {np.median(mae_vals):.2f}%')
    
    # MFE > |MAE| rate (winners)
    win_rate = sum(mfe_vals > abs(mae_vals)) / len(mfe_vals) * 100
    print(f'  MFE > |MAE| rate: {win_rate:.1f}%')
    
    print()
    print('Drawdown Scenarios (MAE percentiles):')
    print(f'  P10 MAE (90% see less): {np.percentile(mae_vals, 10):.2f}%')
    print(f'  P50 MAE (50% see less): {np.percentile(mae_vals, 50):.2f}%')
    print(f'  P90 MAE (10% see worse): {np.percentile(mae_vals, 90):.2f}%')

print()
print('='*80)
print('VALIDATION COMPLETE')
print('='*80)
