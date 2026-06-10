"""
6-Month Backtest: Boof 22 & 23 with +0.05% Target
Using exact current algorithm parameters
"""

import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# =============================================================================
# CONFIGURATION - Matching Current Live Bot Parameters
# =============================================================================

# Date range: 6 months
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=180)

# TP/SL targeting +0.05% wins (0.0005 = 0.05%)
TP_PCT = 0.0005  # +0.05% take profit
SL_PCT = 0.0003  # -0.03% stop loss (tighter for better R:R)

# Boof 22 Config (from boof22.ts)
BOOF22_CFG = {
    'ATR_LEN': 14,
    'VOL_LEN': 50,
    'VOL_MULT': 1.3,
    'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6,
    'CLUSTER_MERGE': 0.5,
    'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0,
    'RVOL_MIN': 0.8,
}

# Boof 23 Config (from boof23.ts)
BOOF23_CFG = {
    'ATR_LEN': 14,
    'VOL_LEN': 50,
    'FRACTAL_BARS': 3,
    'ATR_MULT': 0.4,  # Tighter than Boof 22
    'CLUSTER_MERGE': 0.5,
    'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0,
    'RVOL_MIN': 0.8,
    'ZZ_PROX_BARS': 30,
    'USE_ENGULF': False,
}

# 10 Stock Universe
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'AMZN', 'MSFT', 'NFLX', 'CRM']

# Symbol-specific parameters
SYMBOL_PARAMS = {
    'NVDA': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'META': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AAPL': {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0},
    'GOOGL': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AMD': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
}

# Alpaca credentials
ALPACA_KEY = os.getenv('ALPACA_KEY', '')
ALPACA_SECRET = os.getenv('ALPACA_SECRET', '')

# =============================================================================
# DATA FETCHING
# =============================================================================

def fetch_alpaca_data(symbol: str, start: datetime, end: datetime, timeframe='1Min') -> pd.DataFrame:
    """Fetch historical bars from Alpaca."""
    if not ALPACA_KEY or not ALPACA_SECRET:
        print(f"[ERROR] Alpaca credentials not set. Set ALPACA_KEY and ALPACA_SECRET env vars.")
        return pd.DataFrame()
    
    all_bars = []
    current_start = start
    
    while current_start < end:
        current_end = min(current_start + timedelta(days=30), end)
        
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
        params = {
            'timeframe': timeframe,
            'start': current_start.isoformat() + 'Z',
            'end': current_end.isoformat() + 'Z',
            'limit': 10000,
            'adjustment': 'raw',
            'feed': 'iex'
        }
        
        headers = {
            'APCA-API-KEY-ID': ALPACA_KEY,
            'APCA-API-SECRET-KEY': ALPACA_SECRET,
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                bars = data.get('bars', [])
                all_bars.extend(bars)
                print(f"[Fetch] {symbol}: Got {len(bars)} bars from {current_start.date()} to {current_end.date()}")
            else:
                print(f"[ERROR] {symbol}: HTTP {response.status_code} - {response.text}")
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")
        
        current_start = current_end + timedelta(minutes=1)
    
    if not all_bars:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_bars)
    df['t'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'t': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
    df = df.sort_values('time').reset_index(drop=True)
    
    return df

# =============================================================================
# INDICATORS
# =============================================================================

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_vol_sma(df: pd.DataFrame, period: int = 50) -> pd.Series:
    """Compute volume SMA."""
    return df['volume'].rolling(period).mean()

def compute_session_rvol(df: pd.DataFrame, vol_len: int = 50) -> pd.Series:
    """Compute relative volume vs session average."""
    vol_sma = compute_vol_sma(df, vol_len)
    return df['volume'] / vol_sma

def build_cluster_array(df: pd.DataFrame, atr_series: pd.Series, vol_mult: float, cfg: Dict) -> Tuple[List, List]:
    """Build volume-weighted price cluster array."""
    vol_sma = compute_vol_sma(df, cfg['VOL_LEN'])
    hi_vol = df['volume'] > vol_sma * vol_mult
    
    avg_atr = atr_series.median()
    if avg_atr == 0 or pd.isna(avg_atr):
        return [], []
    
    merge_tol = avg_atr * cfg['CLUSTER_MERGE']
    buckets = []
    
    for i in range(len(df)):
        if not hi_vol.iloc[i]:
            continue
        price = (df['high'].iloc[i] + df['low'].iloc[i]) / 2
        merged = False
        for b in buckets:
            if abs(b[0] - price) <= merge_tol:
                b[0] = (b[0] * b[1] + price) / (b[1] + 1)
                b[1] += 1
                merged = True
                break
        if not merged:
            buckets.append([price, 1])
    
    buckets = [b for b in buckets if b[1] >= cfg['SR_STRENGTH_MIN']]
    buckets.sort(key=lambda x: -x[1])
    
    cluster_prices = [b[0] for b in buckets]
    cluster_strengths = [b[1] for b in buckets]
    return cluster_prices, cluster_strengths

def nearest_sr_distance(price: float, cluster_prices: List, atr: float) -> float:
    """Distance to nearest SR level in ATR units."""
    if not cluster_prices or atr == 0:
        return float('inf')
    dists = [abs(price - cp) / atr for cp in cluster_prices]
    return min(dists)

def build_zigzag(df: pd.DataFrame) -> Tuple[List, List, List, List, List]:
    """Build ZigZag state machine (from boof23.ts)."""
    n = len(df)
    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    closes = df['close'].values
    
    trend = [''] * n
    zz_high = [None] * n
    zz_high_bar = [-1] * n
    zz_low = [None] * n
    zz_low_bar = [-1] * n
    
    t = ''
    last_high = highs[0]
    last_low = lows[0]
    higher_pt = highs[0]
    higher_bar = 0
    lower_pt = lows[0]
    lower_bar = 0
    cur_zz_high = highs[0]
    cur_zz_high_bar = 0
    cur_zz_low = lows[0]
    cur_zz_low_bar = 0
    
    for i in range(1, n):
        if highs[i] > higher_pt:
            higher_pt = highs[i]
            higher_bar = i
        if lows[i] < lower_pt:
            lower_pt = lows[i]
            lower_bar = i
        
        if closes[i] > last_high or opens[i] > last_high:
            if t == 'down':
                cur_zz_low = lower_pt
                cur_zz_low_bar = lower_bar
                higher_pt = highs[i]
                higher_bar = i
            t = 'up'
            last_high = highs[i]
            last_low = lows[i]
        elif closes[i] < last_low or opens[i] < last_low:
            if t == 'up':
                cur_zz_high = higher_pt
                cur_zz_high_bar = higher_bar
                lower_pt = lows[i]
                lower_bar = i
            t = 'down'
            last_high = highs[i]
            last_low = lows[i]
        
        trend[i] = t
        zz_high[i] = cur_zz_high
        zz_high_bar[i] = cur_zz_high_bar
        zz_low[i] = cur_zz_low
        zz_low_bar[i] = cur_zz_low_bar
    
    return trend, zz_high, zz_high_bar, zz_low, zz_low_bar

# =============================================================================
# BOOF 22 BACKTEST
# =============================================================================

def backtest_boof22(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Run Boof 22.0 backtest with exact current parameters."""
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0})
    atr_mult = params['atr_mult']
    vol_mult = params['vol_mult']
    sr_dist_max = params['sr_dist']
    
    cfg = BOOF22_CFG
    df = df.copy().reset_index(drop=True)
    
    if len(df) < max(cfg['VOL_LEN'], cfg['ATR_LEN']) + cfg['FRACTAL_BARS'] * 2 + 10:
        return []
    
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    
    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult, cfg)
    
    F = cfg['FRACTAL_BARS']
    trades = []
    in_trade = False
    entry_price = direction = None
    entry_bar = 0
    entry_slack = 0.0
    tp_price = sl_price = 0.0
    
    for i in range(cfg['VOL_LEN'] + cfg['ATR_LEN'] + F, len(df) - F - 1):
        row = df.iloc[i]
        
        # Exit logic
        if in_trade:
            nxt = df.iloc[i + 1]
            exit_price = None
            exit_type = None
            
            if direction == 'long':
                if nxt['high'] >= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['low'] <= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
            else:
                if nxt['low'] <= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['high'] >= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
            
            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price
                if direction == 'short':
                    pnl_pct = -pnl_pct
                trades.append({
                    'symbol': symbol,
                    'direction': direction,
                    'entry': entry_price,
                    'exit': exit_price,
                    'exit_type': exit_type,
                    'pnl_pct': pnl_pct,
                    'bar': i,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= 1.4 else 'expanded',
                    'strategy': 'boof22'
                })
                in_trade = False
            continue
        
        # Entry filters
        if row['rvol'] < cfg['RVOL_MIN']:
            continue
        
        atr = row['atr']
        if pd.isna(atr) or atr == 0:
            continue
        
        # Check volume
        vol_sma = row['vol_sma']
        if row['volume'] < vol_sma * vol_mult:
            continue
        
        # Fractal detection
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        
        left_highs = highs[i - F:i]
        right_highs = highs[i + 1:i + F + 1]
        left_lows = lows[i - F:i]
        right_lows = lows[i + 1:i + F + 1]
        
        fractal_peak = (highs[i] > left_highs.max()) and (highs[i] > right_highs.max())
        fractal_trough = (lows[i] < left_lows.min()) and (lows[i] < right_lows.min())
        
        # ATR confirmation
        atr_rejected_peak = closes[i] < highs[i] - atr * atr_mult
        atr_bounced_trough = closes[i] > lows[i] + atr * atr_mult
        
        # Slack
        peak_slack = (highs[i] - closes[i]) / atr if atr > 0 else 0
        trough_slack = (closes[i] - lows[i]) / atr if atr > 0 else 0
        
        # SR distance filter
        dist_to_sr = nearest_sr_distance(row['close'], cluster_prices, atr)
        if dist_to_sr > sr_dist_max:
            continue
        
        is_peak = fractal_peak and atr_rejected_peak
        is_trough = fractal_trough and atr_bounced_trough
        
        if is_peak:
            entry_price = df.iloc[i + 1]['open']
            direction = 'short'
            tp_price = entry_price * (1 - TP_PCT)
            sl_price = entry_price * (1 + SL_PCT)
            entry_bar = i + 1
            entry_slack = peak_slack
            in_trade = True
        elif is_trough:
            entry_price = df.iloc[i + 1]['open']
            direction = 'long'
            tp_price = entry_price * (1 + TP_PCT)
            sl_price = entry_price * (1 - SL_PCT)
            entry_bar = i + 1
            entry_slack = trough_slack
            in_trade = True
    
    return trades

# =============================================================================
# BOOF 23 BACKTEST
# =============================================================================

def backtest_boof23(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Run Boof 23.0 backtest with exact current parameters."""
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.4, 'vol_mult': 1.3, 'sr_dist': 1.0})
    atr_mult = params['atr_mult']
    vol_mult = params['vol_mult']
    sr_dist_max = params['sr_dist']
    
    cfg = BOOF23_CFG
    df = df.copy().reset_index(drop=True)
    
    if len(df) < max(cfg['VOL_LEN'], cfg['ATR_LEN']) + cfg['FRACTAL_BARS'] * 2 + 10:
        return []
    
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    
    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult, cfg)
    
    # Build ZigZag
    trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = build_zigzag(df)
    
    F = cfg['FRACTAL_BARS']
    trades = []
    in_trade = False
    entry_price = direction = None
    entry_bar = 0
    entry_slack = 0.0
    tp_price = sl_price = 0.0
    
    warmup = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F
    
    for i in range(warmup, len(df) - F - 1):
        row = df.iloc[i]
        
        # Exit logic
        if in_trade:
            nxt = df.iloc[i + 1]
            exit_price = None
            exit_type = None
            
            if direction == 'long':
                if nxt['high'] >= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['low'] <= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
            else:
                if nxt['low'] <= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['high'] >= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
            
            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price
                if direction == 'short':
                    pnl_pct = -pnl_pct
                trades.append({
                    'symbol': symbol,
                    'direction': direction,
                    'entry': entry_price,
                    'exit': exit_price,
                    'exit_type': exit_type,
                    'pnl_pct': pnl_pct,
                    'bar': i,
                    'slack': entry_slack,
                    'tier': 'core' if entry_slack >= 0.8 else 'expanded',
                    'strategy': 'boof23',
                    'zz_trend': trend_arr[i]
                })
                in_trade = False
            continue
        
        # Entry filters
        if row['rvol'] < cfg['RVOL_MIN']:
            continue
        
        atr = row['atr']
        if pd.isna(atr) or atr == 0:
            continue
        
        vol_sma = row['vol_sma']
        if row['volume'] < vol_sma * vol_mult:
            continue
        
        trend = trend_arr[i]
        if trend == '':
            continue
        
        # SR distance
        dist_to_sr = nearest_sr_distance(row['close'], cluster_prices, atr)
        if dist_to_sr > sr_dist_max:
            continue
        
        # Fractal detection
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values
        
        left_highs = highs[i - F:i]
        right_highs = highs[i + 1:i + F + 1]
        left_lows = lows[i - F:i]
        right_lows = lows[i + 1:i + F + 1]
        
        fractal_peak = (highs[i] > left_highs.max()) and (highs[i] > right_highs.max())
        fractal_trough = (lows[i] < left_lows.min()) and (lows[i] < right_lows.min())
        
        peak_slack = (highs[i] - closes[i]) / atr if atr > 0 else 0
        trough_slack = (closes[i] - lows[i]) / atr if atr > 0 else 0
        
        # SHORT signal: fractal peak + ZZ up trend + proximity to ZZ high
        if fractal_peak and peak_slack >= atr_mult and trend == 'up':
            zz_h_bar = int(zz_high_bar[i])
            if zz_h_bar >= 0 and abs(i - zz_h_bar) <= cfg['ZZ_PROX_BARS']:
                engulf_ok = not cfg['USE_ENGULF'] or closes[i] < opens[i]
                if engulf_ok:
                    entry_price = df.iloc[i + 1]['open']
                    direction = 'short'
                    tp_price = entry_price * (1 - TP_PCT)
                    sl_price = entry_price * (1 + SL_PCT)
                    entry_bar = i + 1
                    entry_slack = peak_slack
                    in_trade = True
        
        # LONG signal: fractal trough + ZZ down trend + proximity to ZZ low
        elif fractal_trough and trough_slack >= atr_mult and trend == 'down':
            zz_l_bar = int(zz_low_bar[i])
            if zz_l_bar >= 0 and abs(i - zz_l_bar) <= cfg['ZZ_PROX_BARS']:
                engulf_ok = not cfg['USE_ENGULF'] or closes[i] > opens[i]
                if engulf_ok:
                    entry_price = df.iloc[i + 1]['open']
                    direction = 'long'
                    tp_price = entry_price * (1 + TP_PCT)
                    sl_price = entry_price * (1 - SL_PCT)
                    entry_bar = i + 1
                    entry_slack = trough_slack
                    in_trade = True
    
    return trades

# =============================================================================
# ANALYSIS & REPORTING
# =============================================================================

def analyze_trades(trades: List[Dict], strategy_name: str) -> Dict:
    """Calculate comprehensive statistics."""
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'profit_factor': 0, 'total_return': 0}
    
    df = pd.DataFrame(trades)
    
    total_trades = len(df)
    wins = df[df['pnl_pct'] > 0]
    losses = df[df['pnl_pct'] <= 0]
    
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    
    gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    total_return = df['pnl_pct'].sum()
    avg_trade = df['pnl_pct'].mean()
    
    # By direction
    longs = df[df['direction'] == 'long']
    shorts = df[df['direction'] == 'short']
    
    # By exit type
    tp_exits = df[df['exit_type'] == 'tp']
    sl_exits = df[df['exit_type'] == 'sl']
    
    # By tier
    core = df[df['tier'] == 'core']
    expanded = df[df['tier'] == 'expanded']
    
    return {
        'strategy': strategy_name,
        'trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_return': total_return,
        'avg_trade': avg_trade,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'longs': len(longs),
        'shorts': len(shorts),
        'long_wr': longs['pnl_pct'].gt(0).mean() if len(longs) > 0 else 0,
        'short_wr': shorts['pnl_pct'].gt(0).mean() if len(shorts) > 0 else 0,
        'tp_rate': len(tp_exits) / total_trades if total_trades > 0 else 0,
        'sl_rate': len(sl_exits) / total_trades if total_trades > 0 else 0,
        'core_trades': len(core),
        'core_wr': core['pnl_pct'].gt(0).mean() if len(core) > 0 else 0,
        'expanded_trades': len(expanded),
        'expanded_wr': expanded['pnl_pct'].gt(0).mean() if len(expanded) > 0 else 0,
    }

def print_report(stats: Dict):
    """Print formatted statistics."""
    print(f"\n{'='*60}")
    print(f"  {stats['strategy']} - 6 MONTH BACKTEST RESULTS")
    print(f"  TP: +{TP_PCT*100:.3f}% | SL: -{SL_PCT*100:.3f}%")
    print(f"{'='*60}")
    print(f"  Total Trades:      {stats['trades']}")
    print(f"  Win Rate:          {stats['win_rate']*100:.1f}%")
    print(f"  Profit Factor:     {stats['profit_factor']:.2f}")
    print(f"  Total Return:      {stats['total_return']*100:.2f}%")
    print(f"  Avg Trade:         {stats['avg_trade']*100:.3f}%")
    print(f"  Gross Profit:      {stats['gross_profit']*100:.2f}%")
    print(f"  Gross Loss:        {stats['gross_loss']*100:.2f}%")
    print(f"\n  --- By Direction ---")
    print(f"  Longs: {stats['longs']} (WR: {stats['long_wr']*100:.1f}%)")
    print(f"  Shorts: {stats['shorts']} (WR: {stats['short_wr']*100:.1f}%)")
    print(f"\n  --- By Tier ---")
    print(f"  Core: {stats['core_trades']} (WR: {stats['core_wr']*100:.1f}%)")
    print(f"  Expanded: {stats['expanded_trades']} (WR: {stats['expanded_wr']*100:.1f}%)")
    print(f"\n  --- Exit Analysis ---")
    print(f"  TP Rate: {stats['tp_rate']*100:.1f}%")
    print(f"  SL Rate: {stats['sl_rate']*100:.1f}%")
    print(f"{'='*60}\n")

# =============================================================================
# MAIN
# =============================================================================

def run_backtest():
    """Run the full 6-month backtest."""
    print(f"\n{'#'*70}")
    print(f"# 6-MONTH BACKTEST: Boof 22 & 23")
    print(f"# Target: +{TP_PCT*100:.3f}% wins")
    print(f"# Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"# Symbols: {', '.join(SYMBOLS)}")
    print(f"{'#'*70}\n")
    
    all_boof22_trades = []
    all_boof23_trades = []
    
    for symbol in SYMBOLS:
        print(f"\n[Processing {symbol}...]")
        
        # Fetch data
        df = fetch_alpaca_data(symbol, START_DATE, END_DATE)
        
        if df.empty:
            print(f"[SKIP] No data for {symbol}")
            continue
        
        print(f"[Data] {symbol}: {len(df)} 1-min bars")
        
        # Run Boof 22
        trades22 = backtest_boof22(df, symbol)
        all_boof22_trades.extend(trades22)
        print(f"[Boof 22] {symbol}: {len(trades22)} trades")
        
        # Run Boof 23
        trades23 = backtest_boof23(df, symbol)
        all_boof23_trades.extend(trades23)
        print(f"[Boof 23] {symbol}: {len(trades23)} trades")
    
    # Analyze results
    print("\n" + "="*70)
    print(" FINAL RESULTS")
    print("="*70)
    
    stats22 = analyze_trades(all_boof22_trades, "Boof 22.0")
    print_report(stats22)
    
    stats23 = analyze_trades(all_boof23_trades, "Boof 23.0")
    print_report(stats23)
    
    # Combined
    combined = all_boof22_trades + all_boof23_trades
    if combined:
        print(f"\n{'='*60}")
        print(f"  COMBINED (Boof 22 + 23)")
        print(f"{'='*60}")
        print(f"  Total Trades: {len(combined)}")
        print(f"  Boof 22: {len(all_boof22_trades)} ({len(all_boof22_trades)/len(combined)*100:.1f}%)")
        print(f"  Boof 23: {len(all_boof23_trades)} ({len(all_boof23_trades)/len(combined)*100:.1f}%)")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if all_boof22_trades:
        df22 = pd.DataFrame(all_boof22_trades)
        df22.to_csv(f'6mo_backtest_boof22_{TP_PCT*10000:.0f}bp_{timestamp}.csv', index=False)
        print(f"[Saved] Boof 22 trades to 6mo_backtest_boof22_{TP_PCT*10000:.0f}bp_{timestamp}.csv")
    
    if all_boof23_trades:
        df23 = pd.DataFrame(all_boof23_trades)
        df23.to_csv(f'6mo_backtest_boof23_{TP_PCT*10000:.0f}bp_{timestamp}.csv', index=False)
        print(f"[Saved] Boof 23 trades to 6mo_backtest_boof23_{TP_PCT*10000:.0f}bp_{timestamp}.csv")
    
    return stats22, stats23

if __name__ == '__main__':
    # Check for credentials
    if not ALPACA_KEY or not ALPACA_SECRET:
        print("[WARNING] Alpaca credentials not set.")
        print("Set environment variables:")
        print("  export ALPACA_KEY='your_key'")
        print("  export ALPACA_SECRET='your_secret'")
        print("\nContinuing with example data (results will be empty)...")
    
    run_backtest()
