import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('SYMBOL HOLDOUT - TRAIN/TEST GENERALIZATION')
print('='*80)
print()

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

# TRAIN SET
train_symbols = ['UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT']

# TEST SET (completely held out)
test_symbols = ['PLTR', 'SOFI', 'HOOD', 'RBLX', 'CRWD', 'SHOP']

# Algorithm parameters
RVOL_THRESH = 7
BODY_THRESH = 0.9
TP_1 = 1.0
TP_2 = 1.75
SL = 1.0

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

def analyze_symbol_set(symbols, label):
    """Analyze a set of symbols using the algorithm"""
    trades = []
    
    print(f'{label} Set: {symbols}')
    print()
    
    for symbol in symbols:
        try:
            print(f'  {symbol}: ', end='', flush=True)
            
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
            
            count = 0
            
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
                    
                    # 2-bar long ignition
                    if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                        b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                        
                        # Calculate Score
                        score = 0
                        if b1['rvol'] > RVOL_THRESH: score += 1
                        if b1['body'] * 100 > BODY_THRESH: score += 1
                        if b1['vwap_slope'] > 0.25: score += 1
                        if b2['body'] * 100 > 0.5: score += 1
                        
                        if score >= 3:
                            entry = b2['close']
                            tp1_level = entry * (1 + TP_1/100)
                            tp2_level = entry * (1 + TP_2/100)
                            sl_level = entry * (1 - SL/100)
                            
                            future = pm_data.iloc[i+2:i+32]
                            
                            # First-touch logic
                            tp1_bar = None
                            tp2_bar = None
                            sl_bar = None
                            
                            for j, (_, bar) in enumerate(future.iterrows()):
                                if tp1_bar is None and bar['high'] >= tp1_level:
                                    tp1_bar = j + 1
                                if tp2_bar is None and bar['high'] >= tp2_level:
                                    tp2_bar = j + 1
                                if sl_bar is None and bar['low'] <= sl_level:
                                    sl_bar = j + 1
                                if sl_bar and tp1_bar:
                                    break
                            
                            # Calculate P&L
                            if sl_bar and tp1_bar is None:
                                pnl = -SL
                                outcome = 'SL_FULL'
                            elif sl_bar and tp1_bar and sl_bar < tp1_bar:
                                pnl = -SL
                                outcome = 'SL_FULL'
                            elif tp1_bar and sl_bar is None:
                                if tp2_bar:
                                    pnl = 0.5 * TP_1 + 0.5 * TP_2
                                    outcome = 'TP1_TP2'
                                else:
                                    final_price = future.iloc[-1]['close']
                                    trail_pnl = (final_price - entry) / entry * 100
                                    pnl = 0.5 * TP_1 + 0.5 * trail_pnl
                                    outcome = 'TP1_TRAIL'
                            elif tp1_bar and sl_bar and tp1_bar < sl_bar:
                                if tp2_bar and tp2_bar < sl_bar:
                                    pnl = 0.5 * TP_1 + 0.5 * TP_2
                                    outcome = 'TP1_TP2'
                                else:
                                    pnl = 0.5 * TP_1 + 0.5 * (-SL)
                                    outcome = 'TP1_SL'
                            else:
                                final_price = future.iloc[-1]['close']
                                pnl = (final_price - entry) / entry * 100
                                outcome = 'NO_HIT'
                            
                            trades.append({
                                'symbol': symbol,
                                'date': str(date),
                                'pnl': pnl,
                                'outcome': outcome,
                                'score': score
                            })
                            count += 1
            
            print(f'{count} trades')
            
        except Exception as e:
            print(f'ERROR: {str(e)[:40]}')
    
    return trades

# Analyze TRAIN set
print('='*80)
print('TRAINING SET ANALYSIS')
print('='*80)
train_trades = analyze_symbol_set(train_symbols, 'TRAIN')

print()
print('TRAIN Results:')
if train_trades:
    train_df = pd.DataFrame(train_trades)
    train_pnl = train_df['pnl'].values
    
    print(f'  Total trades: {len(train_df)}')
    print(f'  Avg P&L: {np.mean(train_pnl):+.2f}%')
    print(f'  Median P&L: {np.median(train_pnl):+.2f}%')
    print(f'  Win rate: {sum(train_pnl > 0)/len(train_pnl)*100:.1f}%')
    print(f'  Std dev: {np.std(train_pnl):.2f}%')
    print()
    
    # Per symbol
    print('  Per symbol:')
    for sym in train_symbols:
        sym_trades = train_df[train_df['symbol'] == sym]
        if len(sym_trades) > 0:
            avg_pnl = sym_trades['pnl'].mean()
            print(f'    {sym}: {len(sym_trades)} trades, {avg_pnl:+.2f}% avg')

# Analyze TEST set
print()
print('='*80)
print('TEST SET ANALYSIS (Held Out)')
print('='*80)
test_trades = analyze_symbol_set(test_symbols, 'TEST')

print()
print('TEST Results:')
if test_trades:
    test_df = pd.DataFrame(test_trades)
    test_pnl = test_df['pnl'].values
    
    print(f'  Total trades: {len(test_df)}')
    print(f'  Avg P&L: {np.mean(test_pnl):+.2f}%')
    print(f'  Median P&L: {np.median(test_pnl):+.2f}%')
    print(f'  Win rate: {sum(test_pnl > 0)/len(test_pnl)*100:.1f}%')
    print(f'  Std dev: {np.std(test_pnl):.2f}%')
    print()
    
    # Per symbol
    print('  Per symbol:')
    for sym in test_symbols:
        sym_trades = test_df[test_df['symbol'] == sym]
        if len(sym_trades) > 0:
            avg_pnl = sym_trades['pnl'].mean()
            print(f'    {sym}: {len(sym_trades)} trades, {avg_pnl:+.2f}% avg')

# Compare
print()
print('='*80)
print('GENERALIZATION COMPARISON')
print('='*80)
print()

if train_trades and test_trades:
    print(f'                    TRAIN          TEST')
    print(f'                    -----          ----')
    print(f'Symbols:            {len(train_symbols)}              {len(test_symbols)}')
    print(f'Trades:             {len(train_df)}             {len(test_df)}')
    print(f'Avg P&L:            {np.mean(train_pnl):+.2f}%         {np.mean(test_pnl):+.2f}%')
    print(f'Median P&L:         {np.median(train_pnl):+.2f}%         {np.median(test_pnl):+.2f}%')
    print(f'Win rate:           {sum(train_pnl > 0)/len(train_pnl)*100:.1f}%           {sum(test_pnl > 0)/len(test_pnl)*100:.1f}%')
    print()
    
    # Statistical comparison
    pnl_diff = abs(np.mean(train_pnl) - np.mean(test_pnl))
    wr_diff = abs(sum(train_pnl > 0)/len(train_pnl) - sum(test_pnl > 0)/len(test_pnl)) * 100
    
    print(f'Difference in Avg P&L: {pnl_diff:.2f}%')
    print(f'Difference in Win Rate: {wr_diff:.1f}%')
    print()
    
    if pnl_diff < 1.0 and wr_diff < 15:
        print('✓ GENERALIZES: Test set performs similarly to train set')
        print('  Algorithm is not overfitted to specific symbols')
    else:
        print('⚠ PERFORMANCE GAP: Test set underperforms train set')
        print('  May need symbol-specific tuning or larger train set')

print()
print('='*80)
print('SYMBOL HOLDOUT TEST COMPLETE')
print('='*80)
