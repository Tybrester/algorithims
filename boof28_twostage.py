"""
BOOF 28 - Two Stage System
Stage 1: Detection (fast scan) → Watchlist
Stage 2: Confirmation (slow filter) → Trades
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Large universe - 200 stocks
UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","JPM","V","MA","BAC",
    "GS","WFC","UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","XOM","CVX","COP","GE","HON","UPS","BA","CAT","VZ",
    "DIS","LIN","PLD","F","GM","RIVN","LCID","DAL","UAL","AAL",
    "COIN","GME","AMC","PLTR","SOFI","RBLX","BABA","JD","PDD","SPY"
]

def get_data(symbol, date, lookback=20):
    """Get 5m data"""
    start = date - timedelta(days=lookback)
    end = date + timedelta(days=1)
    df = fetch_alpaca_bars(symbol, start, end, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df[df['timestamp'].dt.date == date.date()].reset_index(drop=True)

def calculate_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    return (typical * df['volume']).cumsum() / df['volume'].cumsum()

def stage1_detection(df):
    """
    STAGE 1: FAST SCAN
    Goal: Find "something is happening" stocks
    
    Conditions (ANY of these):
    - RVOL > 2.0
    - Price vs VWAP distance > 0.3%
    - First 15m range expansion
    
    Returns: True/False (add to watchlist or not)
    """
    if len(df) < 3:
        return False
    
    vwap = calculate_vwap(df)
    
    # Condition 1: RVOL > 2.0
    avg_vol = df['volume'].mean()
    current_vol = df['volume'].iloc[:3].sum()  # First 3 bars
    rvol = current_vol / (avg_vol * 3) if avg_vol > 0 else 0
    
    # Condition 2: Price vs VWAP distance > 0.3%
    price = df['close'].iloc[2]  # 9:40 price
    vwap_val = vwap.iloc[2]
    vwap_dist = abs(price - vwap_val) / vwap_val
    
    # Condition 3: First 15m range expansion (3 bars)
    first_3 = df.iloc[:3]
    range_3 = (first_3['high'].max() - first_3['low'].min()) / first_3['open'].iloc[0]
    
    # ANY condition triggers watchlist
    if rvol > 2.0:
        return True
    if vwap_dist > 0.003:
        return True
    if range_3 > 0.005:  # 0.5% range in 15m
        return True
    
    return False

def stage2_confirmation(df):
    """
    STAGE 2: SLOW FILTER (only runs on watchlist stocks)
    
    Step 2A: Wait for structure (3-6 bars)
    Step 2B: Classify move type
    Step 2C: Entry trigger (only if continuation)
    
    Returns: {'direction': 'LONG'/'SHORT', 'entry_idx': int, 'type': str} or None
    """
    if len(df) < 8:  # Need at least 8 bars for confirmation
        return None
    
    vwap = calculate_vwap(df)
    
    # Check first 3 bars for initial direction
    first_3 = df.iloc[:3]
    first_3_vwap = vwap.iloc[:3]
    
    price_9_40 = first_3['close'].iloc[-1]
    vwap_9_40 = first_3_vwap.iloc[-1]
    
    # Determine initial bias
    if price_9_40 > vwap_9_40:
        bias = 'LONG'
    elif price_9_40 < vwap_9_40:
        bias = 'SHORT'
    else:
        return None
    
    # Step 2A: Wait for next 3-6 bars (bars 3-8)
    confirm_window = df.iloc[3:9]
    confirm_vwap = vwap.iloc[3:9]
    
    if len(confirm_window) < 4:
        return None
    
    # Score each factor (2-of-3 rule)
    score = 0
    details = {}
    
    if bias == 'LONG':
        # Factor 1: Momentum confirmation (>0.25% displacement)
        momentum_ok = (confirm_window['close'].iloc[-1] - confirm_window['close'].iloc[0]) / confirm_window['close'].iloc[0] > 0.0025
        if momentum_ok:
            score += 1
        details['momentum'] = momentum_ok
        
        # Factor 2: Structure (higher highs forming)
        highs = confirm_window['high'].values
        structure_ok = all(highs[i] >= highs[i-1] * 0.998 for i in range(1, len(highs)))
        if structure_ok:
            score += 1
        details['structure'] = structure_ok
        
        # Factor 3: VWAP hold
        vwap_ok = all(confirm_window['close'].iloc[i] > confirm_vwap.iloc[i] * 0.999 
                     for i in range(len(confirm_window)))
        if vwap_ok:
            score += 1
        details['vwap'] = vwap_ok
        
        # 2-OF-3 RULE: Need at least 2 factors
        if score >= 2:
            # Entry trigger - break of consolidation high
            consolidation_high = confirm_window['high'].max()
            for i in range(6, min(9, len(df))):
                if df['high'].iloc[i] > consolidation_high * 0.999:
                    return {'direction': 'LONG', 'entry_idx': i, 'type': f'2of3_{score}', 'details': details}
    
    else:  # SHORT bias
        # Factor 1: Momentum confirmation
        momentum_ok = (confirm_window['close'].iloc[0] - confirm_window['close'].iloc[-1]) / confirm_window['close'].iloc[0] > 0.0025
        if momentum_ok:
            score += 1
        details['momentum'] = momentum_ok
        
        # Factor 2: Structure (lower lows forming)
        lows = confirm_window['low'].values
        structure_ok = all(lows[i] <= lows[i-1] * 1.002 for i in range(1, len(lows)))
        if structure_ok:
            score += 1
        details['structure'] = structure_ok
        
        # Factor 3: VWAP hold
        vwap_ok = all(confirm_window['close'].iloc[i] < confirm_vwap.iloc[i] * 1.001 
                     for i in range(len(confirm_window)))
        if vwap_ok:
            score += 1
        details['vwap'] = vwap_ok
        
        # 2-OF-3 RULE
        if score >= 2:
            consolidation_low = confirm_window['low'].min()
            for i in range(6, min(9, len(df))):
                if df['low'].iloc[i] < consolidation_low * 1.001:
                    return {'direction': 'SHORT', 'entry_idx': i, 'type': f'2of3_{score}', 'details': details}
    
    return None

def simulate_trade(df, entry_idx, direction, target_pct=1.0, stop_pct=0.5, max_bars=10):
    """Simulate trade"""
    if entry_idx >= len(df) - 1:
        return None, None
    
    entry_price = df['close'].iloc[entry_idx]
    
    if direction == 'LONG':
        tp = entry_price * (1 + target_pct/100)
        sl = entry_price * (1 - stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['high'].iloc[i] >= tp:
                return target_pct, 'TP'
            if df['low'].iloc[i] <= sl:
                return -stop_pct, 'SL'
    else:
        tp = entry_price * (1 - target_pct/100)
        sl = entry_price * (1 + stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['low'].iloc[i] <= tp:
                return target_pct, 'TP'
            if df['high'].iloc[i] >= sl:
                return -stop_pct, 'SL'
    
    exit_price = df['close'].iloc[min(entry_idx + max_bars - 1, len(df) - 1)]
    if direction == 'LONG':
        return (exit_price - entry_price) / entry_price * 100, 'TIME'
    else:
        return (entry_price - exit_price) / entry_price * 100, 'TIME'

def run_backtest():
    test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    
    print('='*80)
    print('BOOF 28 - TWO STAGE SYSTEM')
    print('Stage 1: Detection → Watchlist')
    print('Stage 2: Confirmation → Trades')
    print(f'Date: {test_date.date()}')
    print('='*80)
    
    print(f'\nScanning {len(UNIVERSE)} stocks...\n')
    
    # STAGE 1: DETECTION
    print('STAGE 1: Building watchlist...')
    watchlist = []
    
    for sym in UNIVERSE:
        try:
            df = get_data(sym, test_date)
            if df is None:
                continue
            
            if stage1_detection(df):
                watchlist.append({'symbol': sym, 'df': df})
            
            time.sleep(0.05)
        except:
            pass
    
    print(f'\nWATCHLIST ({len(watchlist)} stocks):')
    for item in watchlist:
        print(f'  {item["symbol"]}')
    
    # STAGE 2: CONFIRMATION
    print(f'\nSTAGE 2: Confirmation filter...')
    print(f'{"Symbol":<8} {"Direction":<8} {"Type":<15} {"Entry":<8} {"1% P&L":<8} {"Exit":<6}')
    print('-'*60)
    
    trades = []
    total_pnl = 0
    
    for item in watchlist:
        sym = item['symbol']
        df = item['df']
        
        # Run confirmation
        signal = stage2_confirmation(df)
        if not signal:
            continue
        
        # Simulate
        pnl, exit_type = simulate_trade(df, signal['entry_idx'], signal['direction'], 1.0, 0.5)
        
        if pnl is not None:
            trades.append({
                'symbol': sym,
                'direction': signal['direction'],
                'type': signal['type'],
                'pnl': pnl,
                'exit': exit_type
            })
            total_pnl += pnl
            
            entry_price = df['close'].iloc[signal['entry_idx']]
            print(f"{sym:<8} {signal['direction']:<8} {signal['type']:<15} {entry_price:<8.2f} {pnl:<+7.2f}% {exit_type:<6}")
    
    print('='*60)
    
    if trades:
        wins = len([t for t in trades if t['pnl'] > 0])
        print(f'\nSUMMARY:')
        print(f'Watchlist: {len(watchlist)} stocks')
        print(f'Trades: {len(trades)}')
        print(f'Win Rate: {wins/len(trades)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(trades):.3f}%')
        
        # By direction
        longs = [t for t in trades if t['direction'] == 'LONG']
        shorts = [t for t in trades if t['direction'] == 'SHORT']
        
        if longs:
            long_pnl = sum(t['pnl'] for t in longs)
            print(f'\nLongs: {len(longs)} trades, {long_pnl:+.2f}%')
        if shorts:
            short_pnl = sum(t['pnl'] for t in shorts)
            print(f'Shorts: {len(shorts)} trades, {short_pnl:+.2f}%')
    else:
        print(f'\nNo trades from {len(watchlist)} watchlist stocks')
    
    print('='*60)

if __name__ == '__main__':
    run_backtest()
