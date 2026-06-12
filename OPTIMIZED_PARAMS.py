import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print('='*80)
print('OPTIMIZED PARAMETERS: RVOL > 7, Body > 0.9%')
print('='*80)
print()
print('Core Universe + Relaxed Parameters')
print()

API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
client = StockHistoricalDataClient(API_KEY, API_SECRET)

CORE_UNIVERSE = ['UPST','AFRM','RKLB','MRNA','RIOT','CHPT','ARM','HIMS','TEM','ASTS','LUNR','CLSK','APP','SMCI','RDW','IREN','MSTR']

# RELAXED PARAMETERS
RVOL_THRESH = 7      # Was 8
BODY_THRESH = 0.9    # Was 0.9 (same)
SCORE_THRESH = 3

TP_1 = 1.0
TP_2 = 1.75
SL = 1.0

end = datetime(2025, 6, 30)
start = end - timedelta(days=180)

all_signals = []

print(f'Analyzing {len(CORE_UNIVERSE)} core symbols...')
print(f'Score criteria: RVOL>{RVOL_THRESH}, Body>{BODY_THRESH}%, VWAP_slope>0.25, Bar2_body>0.5%')
print(f'Targets: +{TP_1}% (50%), +{TP_2}% (50%), SL: -{SL}%')
print()

for symbol in CORE_UNIVERSE:
    try:
        print(f'{symbol}: ', end='', flush=True)
        
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
        
        signals = 0
        
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
                    if b1['rvol'] > RVOL_THRESH: score += 1
                    if b1['body'] * 100 > BODY_THRESH: score += 1
                    if b1['vwap_slope'] > 0.25: score += 1
                    if b2['body'] * 100 > 0.5: score += 1
                    
                    if score >= SCORE_THRESH:
                        entry = b2['close']
                        tp1_level = entry * (1 + TP_1/100)
                        tp2_level = entry * (1 + TP_2/100)
                        sl_level = entry * (1 - SL/100)
                        
                        future = pm_data.iloc[i+2:i+32]
                        
                        # Track first touch
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
                        
                        # Determine P&L
                        if sl_bar and tp1_bar is None:
                            pnl = -SL
                            outcome = 'SL_FULL'
                        elif sl_bar and tp1_bar and sl_bar < tp1_bar:
                            pnl = -SL
                            outcome = 'SL_FULL'
                        elif tp1_bar and sl_bar is None:
                            # Hit TP1, check for TP2
                            if tp2_bar:
                                pnl = 0.5 * TP_1 + 0.5 * TP_2
                                outcome = 'TP1_TP2'
                            else:
                                # Only TP1 hit, exit at end
                                final_price = future.iloc[-1]['close']
                                exit_pnl = (final_price - entry) / entry * 100
                                pnl = 0.5 * TP_1 + 0.5 * exit_pnl
                                outcome = 'TP1_TRAIL'
                        elif tp1_bar and sl_bar and tp1_bar < sl_bar:
                            # Hit TP1 first, check for TP2
                            if tp2_bar and tp2_bar < sl_bar:
                                pnl = 0.5 * TP_1 + 0.5 * TP_2
                                outcome = 'TP1_TP2'
                            else:
                                # TP1 then SL
                                pnl = 0.5 * TP_1 + 0.5 * (-SL)
                                outcome = 'TP1_SL'
                        else:
                            # Neither hit
                            final_price = future.iloc[-1]['close']
                            pnl = (final_price - entry) / entry * 100
                            outcome = 'NO_HIT'
                        
                        all_signals.append({
                            'symbol': symbol,
                            'date': str(date),
                            'entry': entry,
                            'score': score,
                            'rvol': b1['rvol'],
                            'body': b1['body'],
                            'pnl': pnl,
                            'outcome': outcome,
                            'tp1_bar': tp1_bar,
                            'tp2_bar': tp2_bar,
                            'sl_bar': sl_bar
                        })
                        signals += 1
        
        print(f'{signals} signals')
        
    except Exception as e:
        print(f'ERROR: {str(e)[:40]}')

print()
print('='*80)
print('OPTIMIZED PARAMETERS RESULTS')
print('='*80)
print()

df_out = pd.DataFrame(all_signals)
print(f'Total signals: {len(df_out)}')
print()

# Performance
pnl_vals = df_out['pnl'].values
print('Performance Summary:')
print(f'  Avg P&L per trade: {np.mean(pnl_vals):+.2f}%')
print(f'  Median P&L: {np.median(pnl_vals):+.2f}%')
print(f'  Std dev: {np.std(pnl_vals):.2f}%')
print(f'  Best trade: {np.max(pnl_vals):+.2f}%')
print(f'  Worst trade: {np.min(pnl_vals):+.2f}%')
print()

# Win rate
wins = sum(pnl_vals > 0)
losses = sum(pnl_vals < 0)
scratches = sum(pnl_vals == 0)
print(f'Win rate: {wins}/{len(df_out)} ({wins/len(df_out)*100:.1f}%)')
print(f'Loss rate: {losses}/{len(df_out)} ({losses/len(df_out)*100:.1f}%)')
print(f'Scratch rate: {scratches}/{len(df_out)} ({scratches/len(df_out)*100:.1f}%)')
print()

# Outcome breakdown
print('Outcome Distribution:')
outcome_counts = df_out['outcome'].value_counts()
for outcome, count in outcome_counts.items():
    avg_pnl = df_out[df_out['outcome'] == outcome]['pnl'].mean()
    print(f'  {outcome}: {count} ({count/len(df_out)*100:.1f}%) | Avg P&L: {avg_pnl:+.2f}%')

print()

# Per symbol
print('Per Symbol Performance:')
sym_stats = df_out.groupby('symbol').agg({
    'pnl': ['count', 'mean', lambda x: sum(x > 0)]
}).round(2)
sym_stats.columns = ['Signals', 'Avg_PnL', 'Wins']
sym_stats['WinRate'] = (sym_stats['Wins'] / sym_stats['Signals'] * 100).round(1)
sym_stats = sym_stats.sort_values('Avg_PnL', ascending=False)
print(sym_stats.to_string())

print()
print('='*80)
print('ALGORITHM CONFIGURATION')
print('='*80)
print()
print('CORE_UNIVERSE = [')
for sym in CORE_UNIVERSE:
    print(f"    '{sym}',")
print(']')
print()
print('ENTRY CRITERIA:')
print(f'    if symbol in CORE_UNIVERSE and score >= 3:')
print(f'        enter()')
print()
print('SCORING (4 factors, need 3+):')
print(f'    +1 if bar1_rvol > {RVOL_THRESH}')
print(f'    +1 if bar1_body > {BODY_THRESH}%')
print(f'    +1 if vwap_slope > 0.25%')
print(f'    +1 if bar2_body > 0.5%')
print()
print('EXIT STRATEGY (Partial):')
print(f'    exit 50% at +{TP_1}%')
print(f'    exit 50% at +{TP_2}%')
print(f'    stop loss at -{SL}%')
print()
print(f'Expected value: {np.mean(pnl_vals):+.2f}% per trade')
print('='*80)

# Save results
df_out.to_csv('optimized_core_signals.csv', index=False)
print('\nSaved: optimized_core_signals.csv')
