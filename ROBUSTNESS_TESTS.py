import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('ROBUSTNESS TESTING SUITE')
print('='*80)

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

# =============================================================================
# TEST 1: PARAMETER STABILITY
# =============================================================================
print()
print('='*80)
print('TEST 1: PARAMETER STABILITY')
print('='*80)
print('Testing RVOL and Body thresholds')
print()

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

# Parameter combinations to test
rvol_thresholds = [7, 8, 9]
body_thresholds = [0.8, 0.9, 1.0]

param_results = []

for rvol_thresh in rvol_thresholds:
    for body_thresh in body_thresholds:
        signals = []
        
        for symbol in CORE_UNIVERSE[:7]:  # Sample for speed
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
                            if b1['rvol'] > rvol_thresh: score += 1
                            if b1['body'] * 100 > body_thresh: score += 1
                            if b1['vwap_slope'] > 0.25: score += 1
                            if b2['body'] * 100 > 0.5: score += 1
                            
                            if score >= 3:
                                future = pm_data.iloc[i+2:i+32]
                                mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                                
                                signals.append({
                                    'mfe': mfe,
                                    'score': score,
                                    'rvol': b1['rvol'],
                                    'body': b1['body']
                                })
            except:
                pass
        
        if signals:
            mfe_vals = [s['mfe'] for s in signals]
            runners = sum(m >= 2.0 for m in mfe_vals)
            
            param_results.append({
                'RVOL': f'>{rvol_thresh}',
                'Body': f'>{body_thresh}%',
                'Signals': len(signals),
                'WinRate_2pct': round(runners/len(signals)*100, 1),
                'Avg_MFE': round(np.mean(mfe_vals), 2),
                'Median_MFE': round(np.median(mfe_vals), 2)
            })

results_df = pd.DataFrame(param_results)
print(results_df.to_string(index=False))

print()
print('Stability Assessment:')
win_rates = results_df['WinRate_2pct'].values
print(f'  Win rate range: {win_rates.min():.1f}% - {win_rates.max():.1f}%')
print(f'  Std deviation: {np.std(win_rates):.2f}%')
if np.std(win_rates) < 10:
    print('  ✓ EDGE IS STABLE across parameter variations')
else:
    print('  ⚠ Edge varies significantly with parameters')

# =============================================================================
# TEST 2: 1-BAR DELAY
# =============================================================================
print()
print('='*80)
print('TEST 2: 1-BAR DELAY')
print('='*80)
print('Comparing: Enter immediately vs Enter 1 minute later')
print()

immediate_signals = []
delayed_signals = []

for symbol in CORE_UNIVERSE[:5]:
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
            
            for i in range(len(pm_data) - 31):  # Extra bar for delay
                if i + 2 >= len(pm_data):
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
                        # Immediate entry
                        entry_immediate = b2['close']
                        future_immediate = pm_data.iloc[i+2:i+32]
                        mfe_immediate = (future_immediate['high'].max() - entry_immediate) / entry_immediate * 100
                        
                        immediate_signals.append({
                            'mfe': mfe_immediate,
                            'entry': entry_immediate
                        })
                        
                        # Delayed entry (1 bar later)
                        if i + 3 < len(pm_data):
                            entry_delayed = pm_data.iloc[i+2]['open']  # Enter at open of next bar
                            future_delayed = pm_data.iloc[i+3:i+33]
                            if len(future_delayed) > 0:
                                mfe_delayed = (future_delayed['high'].max() - entry_delayed) / entry_delayed * 100
                                
                                delayed_signals.append({
                                    'mfe': mfe_delayed,
                                    'entry': entry_delayed,
                                    'entry_diff_pct': (entry_delayed - entry_immediate) / entry_immediate * 100
                                })
    except:
        pass

if immediate_signals and delayed_signals:
    imm_mfe = [s['mfe'] for s in immediate_signals]
    del_mfe = [s['mfe'] for s in delayed_signals]
    entry_diffs = [s['entry_diff_pct'] for s in delayed_signals]
    
    print(f'Immediate entry signals: {len(immediate_signals)}')
    print(f'Delayed entry signals: {len(delayed_signals)}')
    print()
    print('Performance Comparison:')
    print(f'  Immediate - Avg MFE: {np.mean(imm_mfe):.2f}%, WinRate: {sum(m >= 2 for m in imm_mfe)/len(imm_mfe)*100:.1f}%')
    print(f'  Delayed   - Avg MFE: {np.mean(del_mfe):.2f}%, WinRate: {sum(m >= 2 for m in del_mfe)/len(del_mfe)*100:.1f}%')
    print()
    print(f'Entry price difference: {np.mean(entry_diffs):.3f}% (delayed vs immediate)')
    
    if abs(np.mean(imm_mfe) - np.mean(del_mfe)) < 0.5:
        print('✓ ROBUST: 1-bar delay produces similar results')
    else:
        print('⚠ Entry timing is sensitive')

# =============================================================================
# TEST 3: SYMBOL HOLDOUT
# =============================================================================
print()
print('='*80)
print('TEST 3: SYMBOL HOLDOUT - GENERALIZATION TEST')
print('='*80)
print('Train: UPST, AFRM, RKLB, MRNA')
print('Test:  PLTR, SOFI, HOOD, RBLX, CRWD')
print()

train_symbols = ['UPST', 'AFRM', 'RKLB', 'MRNA']
test_symbols = ['PLTR', 'SOFI', 'HOOD', 'RBLX', 'CRWD']

def analyze_symbols(symbols, label):
    signals = []
    
    for symbol in symbols:
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
                            future = pm_data.iloc[i+2:i+32]
                            mfe = (future['high'].max() - b2['close']) / b2['close'] * 100
                            
                            signals.append({
                                'symbol': symbol,
                                'mfe': mfe,
                                'score': score
                            })
        except:
            pass
    
    if signals:
        mfe_vals = [s['mfe'] for s in signals]
        runners = sum(m >= 2.0 for m in mfe_vals)
        
        print(f'{label} Set ({len(symbols)} symbols):')
        print(f'  Signals: {len(signals)}')
        print(f'  WinRate (2% TP): {runners/len(signals)*100:.1f}%')
        print(f'  Avg MFE: {np.mean(mfe_vals):.2f}%')
        print(f'  Median MFE: {np.median(mfe_vals):.2f}%')
        return len(signals), runners/len(signals)*100, np.mean(mfe_vals)
    else:
        print(f'{label} Set: No signals found')
        return 0, 0, 0

train_count, train_wr, train_mfe = analyze_symbols(train_symbols, 'TRAIN')
test_count, test_wr, test_mfe = analyze_symbols(test_symbols, 'TEST')

print()
print('Generalization Assessment:')
if train_count > 0 and test_count > 0:
    wr_diff = abs(train_wr - test_wr)
    mfe_diff = abs(train_mfe - test_mfe)
    
    print(f'  Win rate difference: {wr_diff:.1f}%')
    print(f'  Avg MFE difference: {mfe_diff:.2f}%')
    
    if wr_diff < 15 and mfe_diff < 1.0:
        print('✓ GENERALIZES: Test set performs similarly to train set')
    else:
        print('⚠ May be overfitted to specific symbols')

print()
print('='*80)
print('ROBUSTNESS TESTING COMPLETE')
print('='*80)
