"""
6-Month Backtest: A+ and A Grade Trades Only (Score >= 80)
Using composite strength scoring with RVOL 1.2-3.0 sweet spot
"""
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Alpaca API
ALPACA_KEY = os.getenv('ALPACA_KEY', 'PKGA4ZC63QX27XHF22CB6YP547')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q')
BASE_URL = 'https://paper-api.alpaca.markets'
DATA_URL = 'https://data.alpaca.markets'

# Config - A Grade Only
TP_PCT = 0.0005  # +0.05%
SL_PCT = 0.0003  # -0.03%
MIN_SCORE = 80   # A+ and A only

SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']

# Boof 22 & 23 Configs
BOOF22_CONFIG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'MAX_HOLD': 30,
    'CLUSTER_MERGE': 0.5, 'SR_DIST_MAX': 1.0,
    'SR_STRENGTH_MIN': 2, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6, 'RVOL_MIN': 0.8,
}

BOOF23_CONFIG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'MAX_HOLD': 30,
    'CLUSTER_MERGE': 0.5, 'SR_DIST_MAX': 1.0,
    'SR_STRENGTH_MIN': 2, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.4, 'RVOL_MIN': 0.8,
    'ZZ_PROX_BARS': 30, 'USE_ENGULF': False,
}

SYMBOL_PARAMS = {
    'AAPL': {'atr_mult': 0.6, 'vol_mult': 1.2},
    'NVDA': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'META': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'GOOGL': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'AMD': {'atr_mult': 0.6, 'vol_mult': 1.3},
    'TSLA': {'atr_mult': 0.8, 'vol_mult': 1.4},
    'AMZN': {'atr_mult': 0.6, 'vol_mult': 1.2},
    'MSFT': {'atr_mult': 0.6, 'vol_mult': 1.2},
    'NFLX': {'atr_mult': 0.7, 'vol_mult': 1.3},
    'CRM': {'atr_mult': 0.6, 'vol_mult': 1.2},
}

def fetch_alpaca_data(symbol, start, end):
    """Fetch 1-min bars from Alpaca"""
    url = f"{DATA_URL}/v2/stocks/{symbol}/bars"
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    all_bars = []
    current_start = start
    
    while current_start < end:
        chunk_end = min(current_start + timedelta(days=30), end)
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

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def build_cluster_array(df, vol_sma, atr, merge_factor=0.5, min_strength=2):
    bars = df.to_dict('records')
    clusters = []
    for i, bar in enumerate(bars):
        if i < 50: continue
        if bar['volume'] > vol_sma.iloc[i] * 0.8:
            price = round(bar['close'] / (atr.iloc[i] * merge_factor)) * (atr.iloc[i] * merge_factor)
            found = False
            for c in clusters:
                if abs(c['price'] - price) <= atr.iloc[i] * merge_factor:
                    c['strength'] += 1
                    c['volume'] += bar['volume']
                    found = True
                    break
            if not found:
                clusters.append({'price': price, 'strength': 1, 'volume': bar['volume']})
    return [c for c in clusters if c['strength'] >= min_strength]

def calc_rvol(df, idx, vol_sma, lookback=20):
    if idx < lookback or idx >= len(df): return 1.0
    current_vol = df.iloc[idx]['volume']
    return current_vol / vol_sma.iloc[idx] if vol_sma.iloc[idx] > 0 else 1.0

def calc_composite_score(slack, rvol, cluster_strength, tier):
    """Calculate composite strength score (0-100)"""
    score = 0
    
    # SLACK (35 pts) - INVERTED: lower slack = higher score
    if slack < 0.5: score += 35
    elif slack < 0.8: score += 30
    elif slack < 1.2: score += 20
    elif slack < 1.4: score += 10
    else: score += 5
    
    # RVOL (25 pts) - SWEET SPOT 1.2-3.0
    if 1.2 <= rvol <= 3.0: score += 25
    elif 1.0 <= rvol < 1.2: score += 15
    elif 0.8 <= rvol < 1.0: score += 10
    
    # CLUSTER (20 pts)
    if cluster_strength >= 5: score += 20
    elif cluster_strength >= 3: score += 15
    elif cluster_strength >= 2: score += 10
    
    # TIER (15 pts) - EXPANDED PREFERRED
    if tier == 'expanded': score += 15
    else: score += 5
    
    # DIRECTION (5 pts) - assume with-trend
    score += 5
    
    return score

def backtest_boof22(df, symbol, tp_pct=TP_PCT, sl_pct=SL_PCT):
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3})
    atr_mult = params['atr_mult']
    
    df['atr'] = compute_atr(df)
    df['vol_sma'] = compute_vol_sma(df)
    
    clusters = build_cluster_array(df, df['vol_sma'], df['atr'])
    cluster_prices = [c['price'] for c in clusters]
    cluster_strengths = {c['price']: c['strength'] for c in clusters}
    
    trades = []
    in_trade = False
    
    for i in range(50, len(df) - 1):
        if in_trade:
            exit_bar = min(i + BOOF22_CONFIG['MAX_HOLD'], len(df) - 1)
            for j in range(i, exit_bar + 1):
                if direction == 'long':
                    if df.iloc[j]['high'] >= tp_price: exit_type = 'tp'; exit_pnl = tp_pct; break
                    if df.iloc[j]['low'] <= sl_price: exit_type = 'sl'; exit_pnl = -sl_pct; break
                else:
                    if df.iloc[j]['low'] <= tp_price: exit_type = 'tp'; exit_pnl = tp_pct; break
                    if df.iloc[j]['high'] >= sl_price: exit_type = 'sl'; exit_pnl = -sl_pct; break
            else: exit_type = 'time'; exit_pnl = (df.iloc[exit_bar]['close'] - entry_price) / entry_price * (1 if direction == 'long' else -1)
            
            # Calculate metrics for score
            rvol = calc_rvol(df, entry_idx, df['vol_sma'])
            nearest_cluster = min(cluster_prices, key=lambda x: abs(x - entry_price)) if cluster_prices else entry_price
            cluster_strength = cluster_strengths.get(nearest_cluster, 2)
            
            composite_score = calc_composite_score(entry_slack, rvol, cluster_strength, entry_tier)
            
            if composite_score >= MIN_SCORE:  # A+ and A only
                trades.append({
                    'symbol': symbol, 'direction': direction, 'entry': entry_price, 'exit': df.iloc[exit_bar]['close'],
                    'exit_type': exit_type, 'pnl_pct': exit_pnl, 'bar': exit_bar - entry_idx,
                    'slack': entry_slack, 'tier': entry_tier, 'rvol': rvol, 'cluster': cluster_strength,
                    'score': composite_score, 'strategy': 'boof22'
                })
            in_trade = False
            continue
        
        if df.iloc[i]['atr'] == 0: continue
        
        # Fractal detection
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        left_highs, right_highs = highs[:3], highs[4:]
        left_lows, right_lows = lows[:3], lows[4:]
        
        fractal_peak = (highs[3] > left_highs.max()) and (highs[3] > right_highs.max())
        fractal_trough = (lows[3] < left_lows.min()) and (lows[3] < right_lows.min())
        
        atr_rejected_peak = closes[3] < highs[3] - df.iloc[i]['atr'] * atr_mult
        atr_bounced_trough = closes[3] > lows[3] + df.iloc[i]['atr'] * atr_mult
        
        peak_slack = (highs[3] - closes[3]) / df.iloc[i]['atr'] if df.iloc[i]['atr'] > 0 else 0
        trough_slack = (closes[3] - lows[3]) / df.iloc[i]['atr'] if df.iloc[i]['atr'] > 0 else 0
        
        is_peak = fractal_peak and atr_rejected_peak
        is_trough = fractal_trough and atr_bounced_trough
        
        if is_peak:
            entry_price = df.iloc[i + 1]['open']
            direction = 'short'
            tp_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)
            entry_idx = i + 1
            entry_slack = peak_slack
            entry_tier = 'core' if entry_slack >= 1.4 else 'expanded'
            in_trade = True
        elif is_trough:
            entry_price = df.iloc[i + 1]['open']
            direction = 'long'
            tp_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
            entry_idx = i + 1
            entry_slack = trough_slack
            entry_tier = 'core' if entry_slack >= 1.4 else 'expanded'
            in_trade = True
    
    return trades

def backtest_boof23(df, symbol, tp_pct=TP_PCT, sl_pct=SL_PCT):
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3})
    atr_mult = params['atr_mult']
    
    df['atr'] = compute_atr(df)
    df['vol_sma'] = compute_vol_sma(df)
    
    clusters = build_cluster_array(df, df['vol_sma'], df['atr'])
    cluster_prices = [c['price'] for c in clusters]
    cluster_strengths = {c['price']: c['strength'] for c in clusters}
    
    # Simple ZigZag trend
    df['zz_trend'] = 'up'
    for i in range(20, len(df)):
        if df.iloc[i]['close'] > df.iloc[i-10:i]['close'].mean(): df.loc[df.index[i], 'zz_trend'] = 'up'
        else: df.loc[df.index[i], 'zz_trend'] = 'down'
    
    trades = []
    in_trade = False
    
    for i in range(50, len(df) - 1):
        if in_trade:
            exit_bar = min(i + BOOF23_CONFIG['MAX_HOLD'], len(df) - 1)
            for j in range(i, exit_bar + 1):
                if direction == 'long':
                    if df.iloc[j]['high'] >= tp_price: exit_type = 'tp'; exit_pnl = tp_pct; break
                    if df.iloc[j]['low'] <= sl_price: exit_type = 'sl'; exit_pnl = -sl_pct; break
                else:
                    if df.iloc[j]['low'] <= tp_price: exit_type = 'tp'; exit_pnl = tp_pct; break
                    if df.iloc[j]['high'] >= sl_price: exit_type = 'sl'; exit_pnl = -sl_pct; break
            else: exit_type = 'time'; exit_pnl = (df.iloc[exit_bar]['close'] - entry_price) / entry_price * (1 if direction == 'long' else -1)
            
            rvol = calc_rvol(df, entry_idx, df['vol_sma'])
            nearest_cluster = min(cluster_prices, key=lambda x: abs(x - entry_price)) if cluster_prices else entry_price
            cluster_strength = cluster_strengths.get(nearest_cluster, 2)
            
            composite_score = calc_composite_score(entry_slack, rvol, cluster_strength, entry_tier)
            
            if composite_score >= MIN_SCORE:
                trades.append({
                    'symbol': symbol, 'direction': direction, 'entry': entry_price, 'exit': df.iloc[exit_bar]['close'],
                    'exit_type': exit_type, 'pnl_pct': exit_pnl, 'bar': exit_bar - entry_idx,
                    'slack': entry_slack, 'tier': entry_tier, 'rvol': rvol, 'cluster': cluster_strength,
                    'score': composite_score, 'strategy': 'boof23'
                })
            in_trade = False
            continue
        
        if df.iloc[i]['atr'] == 0: continue
        
        trend = df.iloc[i]['zz_trend']
        
        highs = df.iloc[i-3:i+3]['high'].values
        lows = df.iloc[i-3:i+3]['low'].values
        closes = df.iloc[i-3:i+3]['close'].values
        
        left_highs, right_highs = highs[:3], highs[4:]
        left_lows, right_lows = lows[:3], lows[4:]
        
        fractal_peak = (highs[3] > left_highs.max()) and (highs[3] > right_highs.max())
        fractal_trough = (lows[3] < left_lows.min()) and (lows[3] < right_lows.min())
        
        atr_rejected_peak = closes[3] < highs[3] - df.iloc[i]['atr'] * atr_mult
        atr_bounced_trough = closes[3] > lows[3] + df.iloc[i]['atr'] * atr_mult
        
        peak_slack = (highs[3] - closes[3]) / df.iloc[i]['atr'] if df.iloc[i]['atr'] > 0 else 0
        trough_slack = (closes[3] - lows[3]) / df.iloc[i]['atr'] if df.iloc[i]['atr'] > 0 else 0
        
        # Boof 23: Fade trend with fractal + proximity
        if trend == 'up' and fractal_peak and atr_rejected_peak:
            entry_price = df.iloc[i + 1]['open']
            direction = 'short'
            tp_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)
            entry_idx = i + 1
            entry_slack = peak_slack
            entry_tier = 'core' if entry_slack >= 1.4 else 'expanded'
            in_trade = True
        elif trend == 'down' and fractal_trough and atr_bounced_trough:
            entry_price = df.iloc[i + 1]['open']
            direction = 'long'
            tp_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
            entry_idx = i + 1
            entry_slack = trough_slack
            entry_tier = 'core' if entry_slack >= 1.4 else 'expanded'
            in_trade = True
    
    return trades

def analyze_trades(trades):
    if not trades: return None
    df = pd.DataFrame(trades)
    wins = df[df['pnl_pct'] > 0]
    losses = df[df['pnl_pct'] <= 0]
    
    total_return = df['pnl_pct'].sum()
    gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0
    
    # Calculate max drawdown
    cumulative = df['pnl_pct'].cumsum()
    running_max = cumulative.expanding().max()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()
    
    return {
        'trades': len(df),
        'win_rate': len(wins) / len(df) if len(df) > 0 else 0,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
        'total_return': total_return,
        'max_drawdown': max_dd,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'avg_trade': total_return / len(df) if len(df) > 0 else 0,
    }

def run_backtest():
    end = datetime.now()
    start = end - timedelta(days=180)
    
    print("\n" + "#"*70)
    print("# 6-MONTH BACKTEST: A+ & A GRADE ONLY (Score >= 80)")
    print("# Target: +0.050% | SL: -0.030% | Min Score: 80")
    print(f"# Period: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
    print(f"# Symbols: {', '.join(SYMBOLS)}")
    print("#"*70 + "\n")
    
    all_trades_22 = []
    all_trades_23 = []
    
    for symbol in SYMBOLS:
        print(f"[Processing {symbol}...]")
        df = fetch_alpaca_data(symbol, start, end)
        if df is None or len(df) < 1000:
            print(f"[SKIP] Insufficient data for {symbol}")
            continue
        
        print(f"[Data] {symbol}: {len(df)} 1-min bars")
        
        trades22 = backtest_boof22(df, symbol)
        trades23 = backtest_boof23(df, symbol)
        
        all_trades_22.extend(trades22)
        all_trades_23.extend(trades23)
        
        print(f"[A-Grade] Boof 22: {len(trades22)} trades | Boof 23: {len(trades23)} trades")
    
    print("\n" + "="*70)
    print(" FINAL RESULTS - A+ & A GRADE ONLY")
    print("="*70)
    
    stats22 = analyze_trades(all_trades_22)
    stats23 = analyze_trades(all_trades_23)
    
    if stats22:
        print(f"\n{'='*70}")
        print(f"  Boof 22.0 - A-GRADE ONLY (Score >= 80)")
        print(f"  Trades Filtered: {stats22['trades']} from {stats22['trades'] + len([t for t in all_trades_22 if t.get('score', 0) < 80])}")
        print(f"  Win Rate:          {stats22['win_rate']*100:.1f}%")
        print(f"  Profit Factor:     {stats22['profit_factor']:.2f}")
        print(f"  Max Drawdown:      {stats22['max_drawdown']*100:.2f}%")
        print(f"  Net P&L:           {stats22['total_return']*100:.2f}%")
        print(f"{'='*70}")
    
    if stats23:
        print(f"\n{'='*70}")
        print(f"  Boof 23.0 - A-GRADE ONLY (Score >= 80)")
        print(f"  Trades Filtered: {stats23['trades']} from {stats23['trades'] + len([t for t in all_trades_23 if t.get('score', 0) < 80])}")
        print(f"  Win Rate:          {stats23['win_rate']*100:.1f}%")
        print(f"  Profit Factor:     {stats23['profit_factor']:.2f}")
        print(f"  Max Drawdown:      {stats23['max_drawdown']*100:.2f}%")
        print(f"  Net P&L:           {stats23['total_return']*100:.2f}%")
        print(f"{'='*70}")
    
    # Save results
    if all_trades_22:
        pd.DataFrame(all_trades_22).to_csv(f'agrade_boof22_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv', index=False)
    if all_trades_23:
        pd.DataFrame(all_trades_23).to_csv(f'agrade_boof23_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv', index=False)
    
    print("\n[SAVED] A-grade trade files")

if __name__ == '__main__':
    run_backtest()
