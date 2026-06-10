"""
Options Backtest - Simulated 1DTE + Live OPRA Scanner
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

# Alpaca API
ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
BASE_URL = 'https://paper-api.alpaca.markets'
DATA_URL = 'https://data.alpaca.markets'

# Config
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']
SLACK_MAX = 0.8

# Exit Models
EXIT_MODELS = {
    'A': {'tp': 0.20, 'sl': -0.10, 'max_hold': 15, 'name': 'Tight Scalp (+20/-10%)'},
    'B': {'tp': 0.30, 'sl': -0.15, 'max_hold': 30, 'name': 'Balanced (+30/-15%)'},
    'C': {'tp': 0.40, 'sl': -0.20, 'max_hold': 60, 'name': 'Trend (+40/-20%)'},
}
FORCE_EXIT_MINUTES = 120

# 1DTE Simulation Config
SIM_CONFIG = {
    'base_price': 2.00,      # $2.00 average 1DTE ATM option price
    'leverage': 20.0,        # 20x gamma leverage for 1DTE ATM
    'slippage_pct': 0.02,    # 2% slippage
}

def fetch_alpaca_data(symbol, start, end):
    """Fetch 1-min bars from Alpaca"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    current_start = datetime.strptime(start, '%Y-%m-%d')
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    
    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=30), end_dt)
        params = {
            'timeframe': '1Min', 'start': current_start.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d'), 'limit': 10000, 'feed': 'iex'
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                bars = resp.json().get('bars', [])
                if bars: all_bars.extend(bars)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")
        current_start = chunk_end
    
    if not all_bars: return None
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'timestamp'})
    df = df.set_index('timestamp').sort_index()
    return df

def fetch_option_snapshot(symbol):
    """Fetch LIVE option chain snapshot from Alpaca OPRA"""
    url = f"{DATA_URL}/v1beta1/options/snapshots/{symbol}"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    params = {'feed': 'opra'}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[ERROR] Options {symbol}: {e}")
    return None

def select_live_option(underlying_price, direction, chain_data):
    """Select best 1DTE option from LIVE OPRA quotes"""
    if not chain_data or 'snapshots' not in chain_data:
        return None
    
    candidates = []
    for opt_symbol, opt in chain_data['snapshots'].items():
        if len(opt_symbol) < 15: continue
        
        opt_type = 'call' if 'C' in opt_symbol else 'put'
        if direction == 'long' and opt_type != 'call': continue
        if direction == 'short' and opt_type != 'put': continue
        
        # Get quote
        quote = opt.get('latestQuote', {})
        bid = quote.get('bidPrice', 0)
        ask = quote.get('askPrice', 0)
        if bid == 0 or ask == 0:
            continue
        
        spread_pct = (ask - bid) / ask
        if spread_pct > 0.15:  # Max 15% spread
            continue
        
        # Get greeks if available
        greeks = opt.get('greeks', {})
        delta = abs(greeks.get('delta', 0))
        
        # Get strike
        strike = opt.get('strikePrice', 0)
        if strike == 0:
            # Parse from symbol: SYMBOLYYMMDDC/PSTRIKE
            try:
                strike = float(opt_symbol[-8:]) / 1000
            except:
                continue
        
        dist_atm = abs(strike - underlying_price) / underlying_price
        
        candidates.append({
            'symbol': opt_symbol,
            'strike': strike,
            'bid': bid,
            'ask': ask,
            'delta': delta if delta > 0 else 0.50,
            'spread_pct': spread_pct,
            'dist_atm': dist_atm
        })
    
    if not candidates:
        return None
    
    # Sort by: closest to ATM, then tight spread
    candidates.sort(key=lambda x: (x['dist_atm'], x['spread_pct']))
    return candidates[0]

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def get_boof22_signals(df, symbol):
    """Get Boof 22 signals with Slack < 0.8 filter"""
    signals = []
    atr = compute_atr(df)
    
    for i in range(50, len(df) - 1):
        if atr.iloc[i] == 0: continue
        
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        left_highs, right_highs = highs[:3], highs[4:]
        left_lows, right_lows = lows[:3], lows[4:]
        
        fractal_peak = (highs[3] > left_highs.max()) and (highs[3] > right_highs.max())
        fractal_trough = (lows[3] < left_lows.min()) and (lows[3] < right_lows.min())
        
        atr_rejected_peak = closes[3] < highs[3] - atr.iloc[i] * 0.6
        atr_bounced_trough = closes[3] > lows[3] + atr.iloc[i] * 0.6
        
        peak_slack = (highs[3] - closes[3]) / atr.iloc[i] if atr.iloc[i] > 0 else 0
        trough_slack = (closes[3] - lows[3]) / atr.iloc[i] if atr.iloc[i] > 0 else 0
        
        if fractal_peak and atr_rejected_peak and peak_slack < SLACK_MAX:
            signals.append({
                'bar_idx': i + 1,
                'direction': 'short',
                'slack': peak_slack,
                'underlying_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
        elif fractal_trough and atr_bounced_trough and trough_slack < SLACK_MAX:
            signals.append({
                'bar_idx': i + 1,
                'direction': 'long',
                'slack': trough_slack,
                'underlying_price': df.iloc[i + 1]['open'],
                'timestamp': df.index[i + 1]
            })
    
    return signals

def simulate_1dte_trade(df, signal, model_config):
    """Simulate 1DTE option trade with realistic gamma model"""
    entry_bar = signal['bar_idx']
    if entry_bar >= len(df): return None
    
    # Entry price with slippage
    entry_price = SIM_CONFIG['base_price'] * (1 + SIM_CONFIG['slippage_pct'])
    underlying_entry = signal['underlying_price']
    
    # TP/SL prices
    tp_price = entry_price * (1 + model_config['tp'])
    sl_price = entry_price * (1 + model_config['sl'])
    
    max_hold_bars = min(model_config['max_hold'], FORCE_EXIT_MINUTES)
    exit_bar = entry_bar
    exit_type = 'time'
    current_price = entry_price
    
    leverage = SIM_CONFIG['leverage']
    
    for i in range(entry_bar, min(entry_bar + max_hold_bars, len(df))):
        current_underlying = df.iloc[i]['close']
        underlying_move = (current_underlying - underlying_entry) / underlying_entry
        
        # 1DTE gamma model: option moves leverage x underlying
        option_pnl = underlying_move * leverage
        current_price = entry_price * (1 + option_pnl)
        
        if current_price >= tp_price:
            exit_bar = i
            exit_type = 'tp'
            break
        
        if current_price <= sl_price:
            exit_bar = i
            exit_type = 'sl'
            break
        
        exit_bar = i
    
    # Exit with slippage
    exit_price = current_price * (1 - SIM_CONFIG['slippage_pct'])
    pnl_pct = (exit_price - entry_price) / entry_price
    
    return {
        'timestamp': signal['timestamp'],
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl_pct': pnl_pct,
        'exit_type': exit_type,
        'direction': signal['direction'],
        'slack': signal['slack'],
        'hold_bars': exit_bar - entry_bar,
        'model': model_config['name']
    }

def run_backtest_simulated():
    """Run simulated 1DTE backtest"""
    print("\n" + "="*80)
    print("MODE 1: SIMULATED 1DTE BACKTEST")
    print("="*80)
    print(f"Symbols: {SYMBOLS}")
    print(f"Slack Filter: < {SLACK_MAX}")
    print(f"1DTE Leverage: {SIM_CONFIG['leverage']}x")
    print(f"Base Option Price: ${SIM_CONFIG['base_price']}")
    print("="*80)
    
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    all_results = {model: [] for model in EXIT_MODELS.keys()}
    
    for symbol in SYMBOLS[:5]:
        print(f"\n[Backtest] {symbol}...")
        df = fetch_alpaca_data(symbol, start_date, end_date)
        if df is None or len(df) < 1000:
            print(f"[SKIP] {symbol} - insufficient data")
            continue
        
        signals = get_boof22_signals(df, symbol)
        if not signals:
            print(f"[SKIP] {symbol} - no signals")
            continue
        
        print(f"  Data: {len(df)} bars | Signals: {len(signals)}")
        
        for signal in signals[:20]:  # Limit for speed
            for model_key, model_config in EXIT_MODELS.items():
                trade = simulate_1dte_trade(df, signal, model_config)
                if trade:
                    trade['symbol'] = symbol
                    all_results[model_key].append(trade)
    
    # Analyze
    print("\n" + "="*80)
    print("SIMULATED 1DTE RESULTS")
    print("="*80)
    
    for model_key, trades in all_results.items():
        if not trades:
            print(f"\n[Model {model_key}] No trades")
            continue
        
        df = pd.DataFrame(trades)
        wins = df[df['pnl_pct'] > 0]
        losses = df[df['pnl_pct'] <= 0]
        
        gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0.0001
        
        print(f"\n{EXIT_MODELS[model_key]['name']}")
        print(f"  Trades: {len(df)}")
        print(f"  Win Rate: {len(wins)/len(df)*100:.1f}%")
        print(f"  Profit Factor: {gross_profit/gross_loss:.2f}")
        print(f"  Net P&L: ${df['pnl_pct'].sum() * SIM_CONFIG['base_price']:.2f} per contract")
        print(f"  Avg Hold: {df['hold_bars'].mean():.1f} min")
        
        for et in ['tp', 'sl', 'time']:
            cnt = len(df[df['exit_type'] == et])
            if cnt > 0:
                print(f"  {et.upper()} exits: {cnt}")
    
    return all_results

def run_live_scanner():
    """Run live OPRA scanner for current market"""
    print("\n" + "="*80)
    print("MODE 2: LIVE OPRA SCANNER")
    print("="*80)
    print("Fetching real-time option quotes from Alpaca OPRA...")
    print("="*80)
    
    for symbol in SYMBOLS[:5]:
        print(f"\n[{symbol}] Scanning...")
        
        # Get latest underlying price
        df = fetch_alpaca_data(symbol, 
            (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
            datetime.now().strftime('%Y-%m-%d'))
        
        if df is None or len(df) == 0:
            print(f"  [SKIP] No data")
            continue
        
        current_price = df.iloc[-1]['close']
        print(f"  Price: ${current_price:.2f}")
        
        # Get signals
        signals = get_boof22_signals(df, symbol)
        print(f"  Recent signals: {len(signals)}")
        
        if not signals:
            continue
        
        # Check last signal
        last_signal = signals[-1]
        print(f"  Last signal: {last_signal['direction'].upper()} @ ${last_signal['underlying_price']:.2f} (slack: {last_signal['slack']:.3f})")
        
        # Fetch live OPRA chain
        chain = fetch_option_snapshot(symbol)
        if not chain:
            print(f"  [ERROR] No OPRA data")
            continue
        
        opt = select_live_option(current_price, last_signal['direction'], chain)
        if opt:
            print(f"  [LIVE OPTION] {opt['symbol']}")
            print(f"    Strike: ${opt['strike']:.2f}")
            print(f"    Bid: ${opt['bid']:.2f} | Ask: ${opt['ask']:.2f}")
            print(f"    Delta: {opt['delta']:.2f}")
            print(f"    Spread: {opt['spread_pct']*100:.1f}%")
            print(f"    Distance ATM: {opt['dist_atm']*100:.1f}%")
            
            # Calculate trade parameters
            entry = opt['ask'] * 1.02
            print(f"\n    [TRADE SETUP]")
            for model_key, model_config in EXIT_MODELS.items():
                tp = entry * (1 + model_config['tp'])
                sl = entry * (1 + model_config['sl'])
                print(f"    Model {model_key}: Entry ${entry:.2f} -> TP ${tp:.2f} / SL ${sl:.2f}")
        else:
            print(f"  [SKIP] No suitable 1DTE option found")

def main():
    print("="*80)
    print("OPTIONS BACKTEST - Simulated 1DTE + Live OPRA Scanner")
    print("="*80)
    
    # Mode 1: Simulated backtest
    run_backtest_simulated()
    
    # Mode 2: Live scanner
    run_live_scanner()
    
    print("\n" + "="*80)
    print("COMPLETE")
    print("="*80)

if __name__ == '__main__':
    main()
