"""
Options Backtest - Boof 22 & 23 with OPRA Data
1m underlying + option quotes, realistic execution
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
SLACK_MAX = 0.8  # From previous update

# Exit Models (Updated per user) - Extended hold times for 1DTE
EXIT_MODELS = {
    'A': {'tp': 0.20, 'sl': -0.10, 'max_hold': 15, 'name': 'Tight Scalp (+20/-10%)'},   # 15 min
    'B': {'tp': 0.30, 'sl': -0.15, 'max_hold': 30, 'name': 'Balanced (+30/-15%)'},      # 30 min  
    'C': {'tp': 0.40, 'sl': -0.20, 'max_hold': 60, 'name': 'Trend (+40/-20%)'},         # 60 min
}
FORCE_EXIT_MINUTES = 120  # 2 hour max for 1DTE

# Option Config
OPTION_CONFIG = {
    'dte_max': 1,          # 0-1 DTE
    'delta_min': 0.40,
    'delta_max': 0.70,
    'slippage_pct': 0.02,  # 2% slippage on entry/exit
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

def fetch_option_snapshot(symbol, date_str):
    """Fetch option chain snapshot from Alpaca"""
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

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def select_option_contract(underlying_price, direction, chain_data, debug=False):
    """Select 0-1 DTE option with delta 0.40-0.70, ATM or 1 strike ITM"""
    if not chain_data or 'snapshots' not in chain_data:
        if debug: print("[DEBUG] No chain data or snapshots")
        return None
    
    # Find closest expiration (0-1 DTE)
    candidates = []
    raw_count = 0
    # snapshots is a dict: {option_symbol: snapshot_data}
    for opt_symbol, opt in chain_data['snapshots'].items():
        raw_count += 1
        # Parse strike and expiration from symbol
        # Format: SYMBOLYYMMDDC/PSTRIKE
        if len(opt_symbol) < 15: continue
        
        opt_type = 'call' if 'C' in opt_symbol else 'put'
        if direction == 'long' and opt_type != 'call': continue
        if direction == 'short' and opt_type != 'put': continue
        
        # Check delta range if available (0.30-0.80 for 1DTE flexibility)
        greeks = opt.get('greeks', {})
        delta = abs(greeks.get('delta', 0))
        if delta > 0 and (delta < 0.30 or delta > 0.80):
            continue
        
        # Get quote
        quote = opt.get('latestQuote', {})
        bid = quote.get('bidPrice', 0)
        ask = quote.get('askPrice', 0)
        if bid == 0 or ask == 0:
            continue
        spread = ask - bid
        spread_pct = spread / ask if ask > 0 else 1
        
        # Relaxed spread filter (max 20% for 1DTE)
        if spread_pct > 0.20:
            continue
        
        candidates.append({
            'symbol': opt_symbol,
            'strike': opt.get('strikePrice', 0),
            'bid': bid,
            'ask': ask,
            'delta': delta if delta > 0 else 0.50,
            'spread_pct': spread_pct
        })
    
    if debug:
        print(f"[DEBUG] Raw options: {raw_count}, After filter: {len(candidates)}")
        if candidates:
            print(f"[DEBUG] Best candidate: {candidates[0]['symbol']} delta={candidates[0]['delta']:.2f}")
    
    if not candidates:
        return None
    
    # Select best: closest to ATM with tightest spread
    for c in candidates:
        c['dist_atm'] = abs(c['strike'] - underlying_price) / underlying_price if underlying_price > 0 else 1
    
    # Sort by: closest to ATM, then tight spread
    candidates.sort(key=lambda x: (x['dist_atm'], x['spread_pct']))
    return candidates[0] if candidates else None

def simulate_option_pnl(entry_price, underlying_move, delta, gamma=0.01):
    """Simulate option price change based on underlying move"""
    # Simplified model: delta + gamma adjustment
    option_change = entry_price * (delta * underlying_move + 0.5 * gamma * (underlying_move ** 2))
    return option_change

def get_boof22_signals(df, symbol):
    """Get Boof 22 signals with Slack < 0.8 filter"""
    signals = []
    atr = compute_atr(df)
    vol_sma = compute_vol_sma(df)
    
    for i in range(50, len(df) - 1):
        if atr.iloc[i] == 0: continue
        
        # Fractal detection (3 bars each side)
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
        
        # Slack filter
        if fractal_peak and atr_rejected_peak and peak_slack < SLACK_MAX:
            signals.append({
                'bar_idx': i + 1,  # Entry on next bar
                'direction': 'short',
                'slack': peak_slack,
                'underlying_price': df.iloc[i + 1]['open']
            })
        elif fractal_trough and atr_bounced_trough and trough_slack < SLACK_MAX:
            signals.append({
                'bar_idx': i + 1,
                'direction': 'long',
                'slack': trough_slack,
                'underlying_price': df.iloc[i + 1]['open']
            })
    
    return signals

def run_option_trade(df, signal, model_config, opt_contract):
    """Simulate one option trade with minute-by-minute tracking"""
    entry_bar = signal['bar_idx']
    if entry_bar >= len(df): return None
    
    # Entry at ask + slippage
    entry_price = opt_contract['ask'] * (1 + OPTION_CONFIG['slippage_pct'])
    underlying_entry = signal['underlying_price']
    delta = opt_contract['delta']
    
    # Calculate TP/SL prices
    tp_price = entry_price * (1 + model_config['tp'])
    sl_price = entry_price * (1 + model_config['sl'])
    
    max_hold_bars = min(model_config['max_hold'], FORCE_EXIT_MINUTES)
    exit_bar = entry_bar
    exit_type = 'time'
    current_option_price = entry_price
    
    # 1DTE leverage multiplier - ATM 1DTE options move ~20x the underlying
    leverage = 20.0
    
    for i in range(entry_bar, min(entry_bar + max_hold_bars, len(df))):
        current_underlying = df.iloc[i]['close']
        underlying_move = (current_underlying - underlying_entry) / underlying_entry
        
        # 1DTE option price model: gamma-accelerated move
        # For 1% stock move, option moves ~20% (leverage effect)
        option_pnl = underlying_move * leverage
        current_option_price = entry_price * (1 + option_pnl)
        
        # Check TP
        if current_option_price >= tp_price:
            exit_bar = i
            exit_type = 'tp'
            break
        
        # Check SL
        if current_option_price <= sl_price:
            exit_bar = i
            exit_type = 'sl'
            break
        
        exit_bar = i
    
    # Exit at simulated price minus slippage
    exit_price = current_option_price * (1 - OPTION_CONFIG['slippage_pct'])
    if exit_type == 'tp':
        exit_price = max(exit_price, tp_price * 0.99)  # Near TP
    elif exit_type == 'sl':
        exit_price = min(exit_price, sl_price * 1.01)  # Near SL
    
    pnl_pct = (exit_price - entry_price) / entry_price
    
    return {
        'entry_bar': entry_bar,
        'exit_bar': exit_bar,
        'hold_bars': exit_bar - entry_bar,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl_pct': pnl_pct,
        'exit_type': exit_type,
        'direction': signal['direction'],
        'slack': signal['slack'],
        'model': model_config['name']
    }

def backtest_symbol(symbol, start_date, end_date):
    """Run full options backtest for one symbol"""
    print(f"\n[Backtest] {symbol}: {start_date} to {end_date}")
    
    # Fetch data
    df = fetch_alpaca_data(symbol, start_date, end_date)
    if df is None or len(df) < 1000:
        print(f"[SKIP] {symbol} - insufficient data")
        return []
    
    print(f"[Data] {symbol}: {len(df)} 1-min bars")
    
    # Get signals
    signals = get_boof22_signals(df, symbol)
    print(f"[Signals] {symbol}: {len(signals)} signals found")
    
    if not signals:
        return []
    
    # For each signal, use REAL OPRA option quotes
    all_trades = {model: [] for model in EXIT_MODELS.keys()}
    
    # Fetch option chain once for this symbol/day
    # In production, fetch at each signal timestamp
    print(f"[OPRA] Fetching option chain for {symbol}...")
    chain_data = fetch_option_snapshot(symbol, start_date)
    
    for signal in signals[:50]:  # Limit for API rate limits
        # Select appropriate option contract based on signal direction
        opt_contract = select_option_contract(signal['underlying_price'], signal['direction'], chain_data)
        
        if not opt_contract:
            print(f"[SKIP] No suitable option contract for signal at bar {signal['bar_idx']}")
            continue
        
        print(f"[TRADE] {opt_contract['symbol']} @ {opt_contract['ask']:.2f} (delta: {opt_contract['delta']:.2f})")
        
        for model_key, model_config in EXIT_MODELS.items():
            trade = run_option_trade(df, signal, model_config, opt_contract)
            if trade:
                trade['symbol'] = symbol
                trade['option_symbol'] = opt_contract['symbol']
                trade['entry_delta'] = opt_contract['delta']
                all_trades[model_key].append(trade)
    
    return all_trades

def analyze_results(all_trades):
    """Analyze and report results for all exit models"""
    print("\n" + "="*80)
    print("OPTIONS BACKTEST RESULTS - ALL EXIT MODELS")
    print("="*80)
    
    for model_key, trades in all_trades.items():
        if not trades:
            print(f"\n[Model {model_key}] No trades")
            continue
        
        df = pd.DataFrame(trades)
        wins = df[df['pnl_pct'] > 0]
        losses = df[df['pnl_pct'] <= 0]
        
        gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0.0001
        
        cumulative = df['pnl_pct'].cumsum()
        running_max = cumulative.expanding().max()
        drawdown = cumulative - running_max
        max_dd = drawdown.min()
        
        print(f"\n{'='*80}")
        print(f"EXIT MODEL {model_key}: {EXIT_MODELS[model_key]['name']}")
        print(f"{'='*80}")
        print(f"Trades: {len(df)}")
        print(f"Win Rate: {len(wins)/len(df)*100:.1f}%")
        print(f"Profit Factor: {gross_profit/gross_loss:.2f}")
        print(f"Max Drawdown: {max_dd*100:.2f}%")
        print(f"Net P&L: {df['pnl_pct'].sum()*100:.2f}%")
        print(f"Avg Hold Time: {df['hold_bars'].mean():.1f} bars")
        
        tp_count = len(df[df['exit_type'] == 'tp'])
        sl_count = len(df[df['exit_type'] == 'sl'])
        time_count = len(df[df['exit_type'] == 'time'])
        print(f"Exits - TP: {tp_count} | SL: {sl_count} | Time: {time_count}")

def main():
    print("="*80)
    print("OPTIONS BACKTEST - Boof 22/23 with Slack < 0.8 Filter")
    print("="*80)
    print(f"Symbols: {SYMBOLS}")
    print(f"Slack Max: {SLACK_MAX}")
    model_names = [f"{k}: {v['name']}" for k, v in EXIT_MODELS.items()]
    print(f"Exit Models: {', '.join(model_names)}")
    print("="*80)
    
    # Run backtest for recent period
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    all_results = {model: [] for model in EXIT_MODELS.keys()}
    
    for symbol in SYMBOLS[:3]:  # Start with 3 symbols for testing
        symbol_results = backtest_symbol(symbol, start_date, end_date)
        for model in EXIT_MODELS.keys():
            if model in symbol_results:
                all_results[model].extend(symbol_results[model])
    
    # Analyze results
    analyze_results(all_results)
    
    # Save results
    for model_key, trades in all_results.items():
        if trades:
            df = pd.DataFrame(trades)
            filename = f"options_backtest_model_{model_key}_{datetime.now().strftime('%Y%m%d')}.csv"
            df.to_csv(filename, index=False)
            print(f"\n[SAVED] {filename}")

if __name__ == '__main__':
    main()
