"""
BOOF30 FINAL TRADING ALGORITHM
================================
Core Universe: Relaxed thresholds
Out-of-Universe: Strict thresholds (extreme setups only)
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

CORE_UNIVERSE = [
    'UPST', 'AFRM', 'RKLB', 'MRNA', 'RIOT', 'CHPT',
    'ARM', 'HIMS', 'TEM', 'ASTS', 'LUNR', 'CLSK',
    'APP', 'SMCI', 'RDW', 'IREN', 'MSTR'
]

# CORE UNIVERSE THRESHOLDS (Relaxed)
CORE_THRESHOLDS = {
    'rvol': 7,          # Was 8
    'bar1_body': 0.9,   # %
    'vwap_slope': 0.25, # %
    'bar2_body': 0.5,   # %
    'score_to_trade': 3
}

# OUT-OF-UNIVERSE THRESHOLDS (Strict - extreme setups only)
EXTENDED_THRESHOLDS = {
    'rvol': 9,          # Higher volume requirement
    'bar1_body': 1.0,   # Larger body required
    'vwap_slope': 0.3,  # Stronger trend
    'bar2_body': 0.7,   # Stronger continuation
    'score_to_trade': 6 # Perfect score required
}

# EXIT STRATEGY (Partial)
TP_1 = 1.0      # First target
TP_2 = 1.75     # Second target
SL = 1.0        # Stop loss

# TIME WINDOW
TRADE_WINDOW_START = '14:30'  # 2:30 PM
TRADE_WINDOW_END = '16:00'    # 4:00 PM

# =============================================================================
# ENTRY LOGIC
# =============================================================================

def should_trade(symbol, bar1, bar2, vwap_slope):
    """
    Determine if we should trade based on symbol and score
    """
    if symbol in CORE_UNIVERSE:
        thresh = CORE_THRESHOLDS
    else:
        thresh = EXTENDED_THRESHOLDS
    
    # Calculate score
    score = 0
    if bar1['rvol'] > thresh['rvol']:
        score += 1
    if bar1['body'] * 100 > thresh['bar1_body']:
        score += 1
    if vwap_slope > thresh['vwap_slope']:
        score += 1
    if bar2['body'] * 100 > thresh['bar2_body']:
        score += 1
    
    return score >= thresh['score_to_trade'], score, thresh['score_to_trade']

# =============================================================================
# 2-BAR IGNITION PATTERN DETECTION
# =============================================================================

def detect_long_ignition(df, i):
    """
    Detect 2-bar long ignition pattern at index i
    """
    if i + 1 >= len(df):
        return False, None, None
    
    bar1 = df.iloc[i]
    bar2 = df.iloc[i+1]
    
    # Pattern criteria
    bar1_body_ok = bar1['body'] >= 0.004  # 0.4% minimum
    bar1_rvol_ok = bar1['rvol'] >= 2.0
    bar2_rvol_ok = bar2['rvol'] >= 1.5
    bar1_above_vwap = bar1['close'] > bar1['vwap']
    bar2_above_vwap = bar2['close'] > bar2['vwap']
    bar2_breaks_high = bar2['close'] > bar1['high']
    
    pattern_ok = (bar1_body_ok and bar1_rvol_ok and bar2_rvol_ok and 
                  bar1_above_vwap and bar2_above_vwap and bar2_breaks_high)
    
    if pattern_ok:
        return True, bar1, bar2
    
    return False, None, None

# =============================================================================
# FIRST-TOUCH TP/SL LOGIC (Realistic P&L)
# =============================================================================

def calculate_pnl(entry, future_bars, tp1, tp2, sl):
    """
    Calculate realistic P&L using first-touch logic
    """
    tp1_level = entry * (1 + tp1/100)
    tp2_level = entry * (1 + tp2/100)
    sl_level = entry * (1 - sl/100)
    
    tp1_bar = None
    tp2_bar = None
    sl_bar = None
    
    for j, bar in enumerate(future_bars):
        bar_num = j + 1  # 1-indexed
        
        if tp1_bar is None and bar['high'] >= tp1_level:
            tp1_bar = bar_num
        if tp2_bar is None and bar['high'] >= tp2_level:
            tp2_bar = bar_num
        if sl_bar is None and bar['low'] <= sl_level:
            sl_bar = bar_num
        
        # Stop checking once we have all
        if sl_bar and tp1_bar:
            break
    
    # Determine outcome based on first touch
    if sl_bar and tp1_bar is None:
        # SL hit, never hit TP1
        return -sl, 'SL_FULL'
    
    elif sl_bar and tp1_bar and sl_bar < tp1_bar:
        # SL hit before TP1
        return -sl, 'SL_FULL'
    
    elif tp1_bar and sl_bar is None:
        # Hit TP1, no SL
        if tp2_bar:
            # Hit both targets
            pnl = 0.5 * tp1 + 0.5 * tp2
            return pnl, 'TP1_TP2'
        else:
            # TP1 only, trail out
            final_price = future_bars[-1]['close']
            trail_pnl = (final_price - entry) / entry * 100
            pnl = 0.5 * tp1 + 0.5 * trail_pnl
            return pnl, 'TP1_TRAIL'
    
    elif tp1_bar and sl_bar and tp1_bar < sl_bar:
        # Hit TP1 first
        if tp2_bar and tp2_bar < sl_bar:
            # TP2 hit before SL
            pnl = 0.5 * tp1 + 0.5 * tp2
            return pnl, 'TP1_TP2'
        else:
            # TP1 then SL
            pnl = 0.5 * tp1 + 0.5 * (-sl)
            return pnl, 'TP1_SL'
    
    else:
        # Neither hit - time exit
        final_price = future_bars[-1]['close']
        pnl = (final_price - entry) / entry * 100
        return pnl, 'NO_HIT'

# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from datetime import datetime, timedelta
    
    API_KEY = 'AKABAAKCEGGUJNSKQC26JLGHM2'
    API_SECRET = 'DzFh27xAvWgSsDsyytoHY9hcCw4J3oqB3HSf9c3KG67C'
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    
    end = datetime(2025, 6, 30)
    start = end - timedelta(days=180)
    
    all_trades = []
    
    for symbol in CORE_UNIVERSE:
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end
            )
            bars = client.get_stock_bars(request)
            df = bars.df.reset_index()
            
            # Process data
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
                
                # Calculate indicators
                day['vwap'] = day['tpv'].cumsum() / day['volume'].cumsum()
                day['avg_vol'] = day['volume'].rolling(20, min_periods=1).mean()
                day['rvol'] = day['volume'] / day['avg_vol']
                day['body'] = abs(day['close'] - day['open']) / day['open']
                day['vwap_slope'] = day['vwap'].diff(10) / day['vwap'].shift(10) * 100
                
                # Filter to trading window
                mask_pm = ((day['hour'] == 14) & (day['minute'] >= 30)) | (day['hour'] == 15)
                pm_data = day[mask_pm].reset_index(drop=True)
                
                if len(pm_data) < 35:
                    continue
                
                for i in range(len(pm_data) - 30):
                    pattern_ok, bar1, bar2 = detect_long_ignition(pm_data, i)
                    
                    if pattern_ok:
                        vwap_slope = bar1['vwap_slope']
                        trade_ok, score, thresh = should_trade(symbol, bar1, bar2, vwap_slope)
                        
                        if trade_ok:
                            entry = bar2['close']
                            future = pm_data.iloc[i+2:i+32].to_dict('records')
                            
                            pnl, outcome = calculate_pnl(
                                entry, future, TP_1, TP_2, SL
                            )
                            
                            all_trades.append({
                                'symbol': symbol,
                                'date': str(date),
                                'entry': entry,
                                'score': score,
                                'threshold_used': thresh,
                                'rvol': bar1['rvol'],
                                'body': bar1['body'],
                                'pnl': pnl,
                                'outcome': outcome
                            })
        
        except Exception as e:
            print(f'{symbol}: ERROR - {str(e)[:40]}')
    
    # Report results
    print('='*80)
    print('FINAL ALGORITHM RESULTS')
    print('='*80)
    print()
    
    trades_df = pd.DataFrame(all_trades)
    print(f'Total trades: {len(trades_df)}')
    print()
    
    # Performance
    pnl_vals = trades_df['pnl'].values
    print('Performance:')
    print(f'  Avg P&L: {np.mean(pnl_vals):+.2f}%')
    print(f'  Median P&L: {np.median(pnl_vals):+.2f}%')
    print(f'  Win rate: {sum(pnl_vals > 0)/len(pnl_vals)*100:.1f}%')
    print(f'  Sharpe (est): {np.mean(pnl_vals)/np.std(pnl_vals):.2f}')
    print()
    
    # Outcomes
    print('Outcome breakdown:')
    print(trades_df['outcome'].value_counts())
    print()
    
    # Save
    trades_df.to_csv('final_algorithm_trades.csv', index=False)
    print('Saved: final_algorithm_trades.csv')

if __name__ == '__main__':
    import pandas as pd
    import numpy as np
    main()
