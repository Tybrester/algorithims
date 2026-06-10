"""
BOOF 28 - Structure Confirmation Model
Spike → Wait for structure → Enter second wave
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 100 liquid stocks
STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","JPM","V","MA","BAC",
    "GS","WFC","UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","XOM","CVX","COP","GE","HON","UPS","BA","CAT","VZ",
    "DIS","LIN","PLD","F","GM","DAL","UAL","COIN","GME","AMC",
    "PLTR","SOFI","RBLX","BABA","JD","PDD","SPY","QQQ","IWM"
]

def get_data(symbol, date, lookback=20):
    """Get 5m data for a date"""
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

def detect_spike(df, vwap, min_rvol=2.0):
    """STEP 1: Detect volume spike with VWAP interaction"""
    if len(df) < 3:
        return None
    
    avg_vol = df['volume'].mean()
    
    for i in range(1, min(6, len(df))):  # Check first 6 bars (30 min)
        current_vol = df['volume'].iloc[i]
        rvol = current_vol / avg_vol if avg_vol > 0 else 0
        
        if rvol >= min_rvol:
            price = df['close'].iloc[i]
            vwap_val = vwap.iloc[i]
            
            # Above or below VWAP
            if price > vwap_val:
                return {'idx': i, 'direction': 'LONG', 'rvol': rvol, 'price': price, 'vwap': vwap_val}
            elif price < vwap_val:
                return {'idx': i, 'direction': 'SHORT', 'rvol': rvol, 'price': price, 'vwap': vwap_val}
    
    return None

def check_structure_confirmation(df, vwap, spike, max_lookforward=8):
    """
    STEP 2: Wait for structure confirmation
    
    For LONG:
    - 2-3 consecutive higher highs after spike
    - OR VWAP hold after pullback
    - OR breakout → retest → hold
    
    For SHORT:
    - 2-3 consecutive lower lows after spike
    - OR VWAP hold below after pullback
    - OR breakdown → retest → hold
    """
    spike_idx = spike['idx']
    direction = spike['direction']
    spike_price = spike['price']
    spike_vwap = spike['vwap']
    
    if spike_idx + max_lookforward >= len(df):
        return None
    
    window = df.iloc[spike_idx+1:spike_idx+max_lookforward+1]
    window_vwap = vwap.iloc[spike_idx+1:spike_idx+max_lookforward+1]
    
    if len(window) < 3:
        return None
    
    if direction == 'LONG':
        # Check 1: 2-3 consecutive higher highs
        highs = window['high'].values
        higher_highs_count = 0
        for i in range(1, min(4, len(highs))):
            if highs[i] > highs[i-1]:
                higher_highs_count += 1
            else:
                break
        
        if higher_highs_count >= 2:
            # Entry on break of most recent high
            entry_idx = spike_idx + higher_highs_count
            return {'idx': entry_idx, 'price': df['close'].iloc[entry_idx], 'type': 'higher_highs'}
        
        # Check 2: VWAP hold after pullback
        pullback = False
        hold_vwap = False
        
        for i in range(len(window)):
            if window['low'].iloc[i] < spike_price * 0.995:  # Pullback from spike
                pullback = True
            if pullback and window['close'].iloc[i] > window_vwap.iloc[i]:
                # Found hold above VWAP after pullback
                if i >= 2:  # Need at least 2 bars of structure
                    return {'idx': spike_idx + i, 'price': df['close'].iloc[spike_idx + i], 'type': 'vwap_hold'}
        
        # Check 3: Breakout → retest → hold
        if len(window) >= 4:
            breakout_high = window['high'].iloc[0]
            for i in range(2, len(window)):
                # Retest near breakout level
                if window['low'].iloc[i] > breakout_high * 0.997:  # Held above
                    if window['close'].iloc[i] > window['open'].iloc[i]:  # Bullish close
                        return {'idx': spike_idx + i, 'price': df['close'].iloc[spike_idx + i], 'type': 'retest_hold'}
    
    else:  # SHORT
        # Check 1: 2-3 consecutive lower lows
        lows = window['low'].values
        lower_lows_count = 0
        for i in range(1, min(4, len(lows))):
            if lows[i] < lows[i-1]:
                lower_lows_count += 1
            else:
                break
        
        if lower_lows_count >= 2:
            entry_idx = spike_idx + lower_lows_count
            return {'idx': entry_idx, 'price': df['close'].iloc[entry_idx], 'type': 'lower_lows'}
        
        # Check 2: VWAP hold below after pullback
        pullback = False
        for i in range(len(window)):
            if window['high'].iloc[i] > spike_price * 1.005:  # Pullback up
                pullback = True
            if pullback and window['close'].iloc[i] < window_vwap.iloc[i]:
                if i >= 2:
                    return {'idx': spike_idx + i, 'price': df['close'].iloc[spike_idx + i], 'type': 'vwap_hold_short'}
        
        # Check 3: Breakdown → retest → hold
        if len(window) >= 4:
            breakdown_low = window['low'].iloc[0]
            for i in range(2, len(window)):
                if window['high'].iloc[i] < breakdown_low * 1.003:  # Held below
                    if window['close'].iloc[i] < window['open'].iloc[i]:  # Bearish close
                        return {'idx': spike_idx + i, 'price': df['close'].iloc[spike_idx + i], 'type': 'retest_hold_short'}
    
    return None

def simulate_trade(df, entry_idx, direction, target_pct=1.0, stop_pct=0.5, max_bars=10):
    """Simulate with 1% target, 0.5% stop"""
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
    print('BOOF 28 - STRUCTURE CONFIRMATION')
    print('Spike → Wait for structure → Enter second wave')
    print(f'Date: {test_date.date()}')
    print('='*80)
    
    print(f'\nScanning {len(STOCKS)} stocks...\n')
    print(f'{"Symbol":<6} {"Spike":>6} {"RVOL":>5} {"Structure":>12} {"Entry":>8} {"1% P&L":>8} {"Exit":>6}')
    print('-'*80)
    
    results = []
    total_pnl = 0
    
    for sym in STOCKS:
        try:
            df = get_data(sym, test_date)
            if df is None or len(df) < 5:
                continue
            
            vwap = calculate_vwap(df)
            
            # STEP 1: Detect spike
            spike = detect_spike(df, vwap)
            if not spike:
                continue
            
            # STEP 2: Wait for structure confirmation
            confirmation = check_structure_confirmation(df, vwap, spike)
            if not confirmation:
                continue
            
            # STEP 3: Simulate trade
            pnl, exit_type = simulate_trade(df, confirmation['idx'], spike['direction'], 1.0, 0.5)
            
            if pnl is not None:
                results.append({
                    'sym': sym,
                    'spike_rvol': spike['rvol'],
                    'structure': confirmation['type'],
                    'entry': confirmation['price'],
                    'pnl': pnl,
                    'exit': exit_type
                })
                total_pnl += pnl
                
                print(f"{sym:<6} {spike['idx']:>6} {spike['rvol']:>5.1f} {confirmation['type']:>12} "
                      f"{confirmation['price']:>8.2f} {pnl:>+7.2f}% {exit_type:>6}")
            
            time.sleep(0.05)
            
        except Exception as e:
            pass
    
    print('='*80)
    
    if results:
        wins = len([r for r in results if r['pnl'] > 0])
        total = len(results)
        
        print(f'\nSUMMARY:')
        print(f'Total Trades: {total}')
        print(f'Win Rate: {wins/total*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/total:.3f}%')
        
        print(f'\nBy Structure Type:')
        by_type = {}
        for r in results:
            t = r['structure']
            if t not in by_type:
                by_type[t] = {'count': 0, 'pnl': 0}
            by_type[t]['count'] += 1
            by_type[t]['pnl'] += r['pnl']
        
        for t, data in by_type.items():
            print(f'  {t}: {data["count"]} trades, {data["pnl"]:+.2f}%')
        
        print(f'\nTop 5 Trades:')
        top = sorted(results, key=lambda x: x['pnl'], reverse=True)[:5]
        for r in top:
            print(f"  {r['sym']}: {r['pnl']:+.2f}% ({r['structure']})")
        
        print(f'\nWorst 5 Trades:')
        bottom = sorted(results, key=lambda x: x['pnl'])[:5]
        for r in bottom:
            print(f"  {r['sym']}: {r['pnl']:+.2f}% ({r['structure']})")
    else:
        print('No trades generated')
    
    print('='*80)

if __name__ == '__main__':
    run_backtest()
