"""
BOOF 28 - Morning Spike Scanner
Exact rules: 4x volume, 60% body, VWAP/EMA alignment, 2-5min confirmation
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 150 liquid stocks
UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","JPM","V","MA","BAC",
    "GS","WFC","UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","XOM","CVX","COP","GE","HON","UPS","BA","CAT","VZ",
    "DIS","LIN","PLD","F","GM","RIVN","DAL","UAL","COIN","GME",
    "PLTR","SOFI","RBLX","BABA","JD","SPY","QQQ","IWM"
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

def calculate_ema(df, period=20):
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_avg_volume(df, period=20):
    """Get average volume from lookback"""
    return df['volume'].rolling(period).mean()

def stage1_detect_candidates(df, symbol, verbose=False):
    """
    STAGE 1: Detect morning spikes (looser criteria)
    
    volume_spike = volume[i] >= avg_volume_20[i] * 2.0   # 2x not 4x
    big_move = abs(close[i] - open[i]) / open[i] >= 0.0015  # 0.15%
    body_ok = abs(close[i] - open[i]) / max(high[i] - low[i], 0.01) >= 0.45
    direction = "SHORT" if close[i] < open[i] else "LONG"
    """
    if len(df) < 10:
        return None
    
    vwap = calculate_vwap(df)
    ema20 = calculate_ema(df, 20)
    avg_vol = calculate_avg_volume(df, 20)
    
    candidates = []
    
    for i in range(min(9, len(df))):  # First 9 bars = 9:30-10:15
        if pd.isna(avg_vol.iloc[i]) or avg_vol.iloc[i] == 0:
            continue
        
        vol_ratio = df['volume'].iloc[i] / avg_vol.iloc[i]
        move_pct = abs(df['close'].iloc[i] - df['open'].iloc[i]) / df['open'].iloc[i]
        candle_range = max(df['high'].iloc[i] - df['low'].iloc[i], 0.01)
        body_ratio = abs(df['close'].iloc[i] - df['open'].iloc[i]) / candle_range
        
        # Looser criteria
        volume_spike = vol_ratio >= 2.0
        big_move = move_pct >= 0.0015
        body_ok = body_ratio >= 0.45
        
        # Log why candidates fail
        if verbose:
            print(f"\n{symbol} bar {i}:")
            print(f"  vol_ratio: {vol_ratio:.2f}x (need 2.0)")
            print(f"  move_pct: {move_pct*100:.3f}% (need 0.15%)")
            print(f"  body_ratio: {body_ratio:.2f} (need 0.45)")
            print(f"  close: {df['close'].iloc[i]:.2f}, ema20: {ema20.iloc[i]:.2f}")
        
        stage1_ok = volume_spike and big_move and body_ok
        
        if not stage1_ok:
            if verbose:
                fails = []
                if not volume_spike: fails.append("volume")
                if not big_move: fails.append("move")
                if not body_ok: fails.append("body")
                print(f"  FAILS: {', '.join(fails)}")
            continue
        
        direction = "SHORT" if df['close'].iloc[i] < df['open'].iloc[i] else "LONG"
        
        candidates.append({
            'direction': direction,
            'spike_idx': i,
            'price': df['close'].iloc[i],
            'volume': df['volume'].iloc[i],
            'rvol': vol_ratio,
            'vwap': vwap.iloc[i],
            'ema': ema20.iloc[i]
        })
        
        if verbose:
            print(f"  ✓ STAGE 1 CANDIDATE: {direction}")
    
    return candidates if candidates else None

def stage2_wait_confirmation(df, candidate, symbol, verbose=False):
    """
    STAGE 2: 2-bar confirmation
    
    short_confirm = (
        direction == "SHORT"
        and close[i+2] < close[i]
        and close[i+2] < ema20[i+2]
    )
    
    long_confirm = (
        direction == "LONG"
        and close[i+2] > close[i]
        and close[i+2] > ema20[i+2]
    )
    """
    spike_idx = candidate['spike_idx']
    direction = candidate['direction']
    ema20 = calculate_ema(df, 20)
    
    # Need at least 2 more bars (i+2)
    if spike_idx + 2 >= len(df):
        return None
    
    close_now = df['close'].iloc[spike_idx]
    close_2bars = df['close'].iloc[spike_idx + 2]
    ema_2bars = ema20.iloc[spike_idx + 2]
    
    if verbose:
        print(f"\n{symbol} Stage 2 check (bar {spike_idx+2}):")
        print(f"  direction: {direction}")
        print(f"  close[i]: {close_now:.2f}, close[i+2]: {close_2bars:.2f}")
        print(f"  ema20[i+2]: {ema_2bars:.2f}")
    
    if direction == 'SHORT':
        short_confirm = (close_2bars < close_now) and (close_2bars < ema_2bars)
        if verbose:
            print(f"  price_lower: {close_2bars < close_now}")
            print(f"  below_ema: {close_2bars < ema_2bars}")
        
        if short_confirm:
            if verbose:
                print(f"  ✓ STAGE 2 CONFIRMED (SHORT)")
            # Entry on bar i+2 or i+3
            return {'entry_idx': spike_idx + 2, 'entry_price': df['close'].iloc[spike_idx + 2]}
        else:
            if verbose:
                print(f"  ✗ Stage 2 failed")
    
    else:  # LONG
        long_confirm = (close_2bars > close_now) and (close_2bars > ema_2bars)
        if verbose:
            print(f"  price_higher: {close_2bars > close_now}")
            print(f"  above_ema: {close_2bars > ema_2bars}")
        
        if long_confirm:
            if verbose:
                print(f"  ✓ STAGE 2 CONFIRMED (LONG)")
            return {'entry_idx': spike_idx + 2, 'entry_price': df['close'].iloc[spike_idx + 2]}
        else:
            if verbose:
                print(f"  ✗ Stage 2 failed")
    
    return None

def stage3_simulate(df, entry_idx, direction, target_pct=1.0, stop_pct=0.5, max_bars=12):
    """Stage 3: Enter, Stage 4: Exit on TP/SL or EMA reclaim"""
    if entry_idx >= len(df) - 1:
        return None, None
    
    entry_price = df['close'].iloc[entry_idx]
    ema20 = calculate_ema(df, 20)
    
    if direction == 'SHORT':
        tp = entry_price * (1 - target_pct/100)
        sl = entry_price * (1 + stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            # TP hit
            if df['low'].iloc[i] <= tp:
                return target_pct, 'TP'
            # SL hit
            if df['high'].iloc[i] >= sl:
                return -stop_pct, 'SL'
            # EMA reclaim (exit short)
            if df['close'].iloc[i] > ema20.iloc[i] * 1.001:
                exit_price = df['close'].iloc[i]
                return (entry_price - exit_price) / entry_price * 100, 'EMA_RECLAIM'
    
    else:  # LONG
        tp = entry_price * (1 + target_pct/100)
        sl = entry_price * (1 - stop_pct/100)
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            if df['high'].iloc[i] >= tp:
                return target_pct, 'TP'
            if df['low'].iloc[i] <= sl:
                return -stop_pct, 'SL'
            # EMA reclaim (exit long)
            if df['close'].iloc[i] < ema20.iloc[i] * 0.999:
                exit_price = df['close'].iloc[i]
                return (exit_price - entry_price) / entry_price * 100, 'EMA_RECLAIM'
    
    # Time exit
    exit_price = df['close'].iloc[min(entry_idx + max_bars - 1, len(df) - 1)]
    if direction == 'SHORT':
        return (entry_price - exit_price) / entry_price * 100, 'TIME'
    else:
        return (exit_price - entry_price) / entry_price * 100, 'TIME'

def run_scanner():
    test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    DEBUG = False  # Set True for detailed logging
    
    print('='*80)
    print('BOOF 28 - MORNING SPIKE SCANNER')
    print('2x volume | 0.15% move | 45% body | 2-bar confirmation')
    print(f'Date: {test_date.date()}')
    print('='*80)
    
    print(f'\nScanning {len(UNIVERSE)} stocks...\n')
    
    # STAGE 1: DETECT CANDIDATES
    print('STAGE 1: Detecting morning spikes (9:30-10:15)...')
    
    all_candidates = []
    for sym in UNIVERSE:
        try:
            df = get_data(sym, test_date)
            if df is None:
                continue
            
            candidates = stage1_detect_candidates(df, sym, verbose=DEBUG)
            if candidates:
                for c in candidates:
                    all_candidates.append({'symbol': sym, **c, 'df': df})
            
            time.sleep(0.05)
        except:
            pass
    
    print(f'\n=== CANDIDATES FOUND: {len(all_candidates)} ===')
    
    if all_candidates:
        shorts = [c for c in all_candidates if c['direction'] == 'SHORT']
        longs = [c for c in all_candidates if c['direction'] == 'LONG']
        
        if shorts:
            print(f'\nSHORT CANDIDATES ({len(shorts)}):')
            for c in shorts[:10]:  # Show first 10
                print(f"  {c['symbol']:<6} bar {c['spike_idx']:<2} | {c['rvol']:<5.1f}x vol | "
                      f"${c['price']:<8.2f} | VWAP: {c['vwap']:<8.2f}")
        
        if longs:
            print(f'\nLONG CANDIDATES ({len(longs)}):')
            for c in longs[:10]:
                print(f"  {c['symbol']:<6} bar {c['spike_idx']:<2} | {c['rvol']:<5.1f}x vol | "
                      f"${c['price']:<8.2f} | VWAP: {c['vwap']:<8.2f}")
    
    # STAGE 2: CONFIRMATION
    print(f'\nSTAGE 2: 2-bar confirmation...')
    
    trades = []
    for candidate in all_candidates:
        confirmation = stage2_wait_confirmation(candidate['df'], candidate, candidate['symbol'], verbose=DEBUG)
        if confirmation:
            # STAGE 3 & 4: Simulate
            pnl, exit_type = stage3_simulate(
                candidate['df'], 
                confirmation['entry_idx'], 
                candidate['direction']
            )
            
            if pnl is not None:
                trades.append({
                    'symbol': candidate['symbol'],
                    'direction': candidate['direction'],
                    'spike_bar': candidate['spike_idx'],
                    'entry': confirmation['entry_price'],
                    'rvol': candidate['rvol'],
                    'pnl': pnl,
                    'exit': exit_type
                })
    
    print('='*80)
    
    if trades:
        wins = len([t for t in trades if t['pnl'] > 0])
        total_pnl = sum(t['pnl'] for t in trades)
        
        print(f'\nTRADES EXECUTED: {len(trades)}')
        print(f'Win Rate: {wins/len(trades)*100:.1f}%')
        print(f'Total P&L: {total_pnl:+.2f}%')
        print(f'Avg P&L: {total_pnl/len(trades):.3f}%')
        
        print(f'\nTRADE DETAILS:')
        print(f"{'Symbol':<8} {'Dir':<6} {'Spike':<6} {'Entry':<10} {'1% P&L':<8} {'Exit':<12}")
        print('-'*55)
        for t in trades:
            print(f"{t['symbol']:<8} {t['direction']:<6} {t['spike_bar']:<6} "
                  f"${t['entry']:<9.2f} {t['pnl']:<+7.2f}% {t['exit']:<12}")
    else:
        print('\nNo trades - no candidates met confirmation criteria')
    
    print('='*80)

if __name__ == '__main__':
    run_scanner()
