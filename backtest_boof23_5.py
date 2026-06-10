import pandas as pd
import numpy as np
from backtest_boof23 import run_boof23, SYMBOL_PARAMS as B23_SYMBOL_PARAMS, DEFAULT_PARAMS as B23_DEFAULT_PARAMS

# =============================================================================
# BOOF 23.5 — ZigZag + Chop Detection (ADX + VWAP + RSI2)
# =============================================================================
# LIVE BOT ALIGNED — June 2026
#   Chop detection: ADX(14) < 20
#   Chop entries: VWAP mean-reversion + RSI2 extremes
#   Chop TP/SL: 8% / 6% (tighter than normal mode)
#   Normal mode: Falls back to Boof 23.0 logic (ATR-based TP/SL)
# =============================================================================

ADX_LEN = 14
ADX_CHOP_THRESHOLD = 20.0  # ADX < 20 = chop mode
RSI2_PERIOD = 2
RSI2_OVERSOLD = 10   # Buy CALL when RSI2 < 10
RSI2_OVERBOUGHT = 90 # Buy PUT when RSI2 > 90
CHOP_TP_PCT = 0.08   # 8% take profit in chop
CHOP_SL_PCT = 0.06   # 6% stop loss in chop
MAX_HOLD = 30        # trend mode max hold
CHOP_MAX_HOLD = 20   # chop mode faster exit


def compute_adx(df, period=ADX_LEN):
    """Compute ADX (Average Directional Index) for chop detection."""
    high, low, close = df['high'], df['low'], df['close']
    
    # True Range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    
    # +DM and -DM
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    
    # Smooth TR, +DM, -DM
    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    
    # DX and ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(span=period, adjust=False).mean()
    
    return adx


def compute_vwap(df):
    """Compute VWAP (Volume Weighted Average Price)."""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
    return vwap


def compute_rsi2(df):
    """Compute 2-period RSI (RSI2) for mean-reversion signals."""
    close = df['close']
    delta = close.diff()
    
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # Wilder's smoothing for 2-period RSI
    avg_gain = gain.ewm(alpha=1/2, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/2, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def run_boof23_5(df, symbol='SPY', tp_mult=4.0, sl_mult=2.0, min_rvol=80):
    """
    Run Boof 23.5 backtest with chop detection.
    Returns list of trade dicts.
    """
    params = B23_SYMBOL_PARAMS.get(symbol, B23_DEFAULT_PARAMS)
    atr_mult = params['atr_mult']
    vol_mult = params['vol_mult']
    sr_dist = params['sr_dist']
    
    ATR_LEN = 14
    VOL_LEN = 50
    CLUSTER_MERGE = 0.5
    SR_STRENGTH_MIN = 2
    FRACTAL_BARS = 3
    
    df = df.copy().reset_index(drop=True)
    if len(df) < max(ATR_LEN, VOL_LEN, ADX_LEN, FRACTAL_BARS * 2) + 10:
        return []
    
    # Import from backtest_boof23
    from backtest_boof23 import compute_atr, build_cluster_array, nearest_sr_distance, detect_zz_swing, is_engulf
    
    # Compute indicators
    atr_series = compute_atr(df, ATR_LEN)
    df['atr'] = atr_series
    df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
    df['rvol'] = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol'] = df['volume'] > df['vol_sma'] * vol_mult
    
    # Chop detection indicators
    df['adx'] = compute_adx(df)
    df['vwap'] = compute_vwap(df)
    df['rsi2'] = compute_rsi2(df)
    
    # Build cluster array
    cluster_prices, cluster_strengths = build_cluster_array(df, atr_series, vol_mult, CLUSTER_MERGE, SR_STRENGTH_MIN)
    
    # Pre-calc ZigZag swings for proximity filter
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    swings = []
    
    for i in range(FRACTAL_BARS, len(df) - FRACTAL_BARS):
        swing = detect_zz_swing(highs, lows, closes, i, FRACTAL_BARS, atr_series.iloc[i], atr_mult)
        if swing:
            swings.append(swing)
    
    F = FRACTAL_BARS
    trades = []
    in_trade = False
    entry_price = direction = None
    entry_bar = 0
    entry_slack = 0.0
    entry_mode = 'normal'
    tp_price = sl_price = 0.0
    
    for i in range(VOL_LEN + ATR_LEN + ADX_LEN + F, len(df) - F - 1):
        row = df.iloc[i]
        
        # --- Exit logic ---
        if in_trade:
            nxt = df.iloc[i + 1]
            exit_price = None
            exit_type = None
            bars_held = i - entry_bar
            
            if direction == 'long':
                if nxt['high'] >= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['low'] <= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
                elif bars_held >= (CHOP_MAX_HOLD if entry_mode == 'chop' else MAX_HOLD):
                    exit_price, exit_type = nxt['close'], 'time'
            else:
                if nxt['low'] <= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['high'] >= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
                elif bars_held >= (CHOP_MAX_HOLD if entry_mode == 'chop' else MAX_HOLD):
                    exit_price, exit_type = nxt['close'], 'time'
            
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
                    'mode': entry_mode,
                })
                in_trade = False
            continue
        
        if in_trade:
            continue
        
        # --- Check chop regime ---
        current_adx = row['adx']
        is_chop = current_adx < ADX_CHOP_THRESHOLD
        
        atr = row['atr']
        price = row['close']
        
        if pd.isna(atr) or atr == 0:
            continue
        
        if is_chop:
            # === CHOP MODE: VWAP + RSI2 Mean Reversion ===
            current_vwap = row['vwap']
            current_rsi2 = row['rsi2']
            
            if pd.isna(current_vwap) or pd.isna(current_rsi2):
                continue
            
            # Buy CALL: Price < VWAP and RSI2 < 10 (oversold)
            if price < current_vwap and current_rsi2 < RSI2_OVERSOLD:
                entry_price = df.iloc[i + 1]['open']
                direction = 'long'
                tp_price = entry_price * (1 + CHOP_TP_PCT)
                sl_price = entry_price * (1 - CHOP_SL_PCT)
                entry_bar = i + 1
                entry_slack = (current_vwap - price) / atr if atr > 0 else 0
                entry_mode = 'chop'
                in_trade = True
            
            # Buy PUT: Price > VWAP and RSI2 > 90 (overbought)
            elif price > current_vwap and current_rsi2 > RSI2_OVERBOUGHT:
                entry_price = df.iloc[i + 1]['open']
                direction = 'short'
                tp_price = entry_price * (1 - CHOP_TP_PCT)
                sl_price = entry_price * (1 + CHOP_SL_PCT)
                entry_bar = i + 1
                entry_slack = (price - current_vwap) / atr if atr > 0 else 0
                entry_mode = 'chop'
                in_trade = True
        
        else:
            # === NORMAL MODE: Use Boof 23.0 logic ===
            if row['rvol'] < min_rvol:
                continue
            
            if not row['hi_vol']:
                continue
            
            left_highs = highs[i - F: i]
            right_highs = highs[i + 1: i + F + 1]
            left_lows = lows[i - F: i]
            right_lows = lows[i + 1: i + F + 1]
            
            fractal_peak = (highs[i] > left_highs.max()) and (highs[i] > right_highs.max())
            fractal_trough = (lows[i] < left_lows.min()) and (lows[i] < right_lows.min())
            
            atr_rejected_peak = closes[i] < highs[i] - atr * atr_mult
            atr_bounced_trough = closes[i] > lows[i] + atr * atr_mult
            
            dist_to_sr = nearest_sr_distance(price, cluster_prices, atr)
            if dist_to_sr > sr_dist:
                continue
            
            # ZigZag proximity filter (within 30 bars of last swing)
            recent_swings = [s for s in swings if 0 <= i - s['bar'] <= 30]
            if not recent_swings:
                continue
            
            peak_slack = (highs[i] - closes[i]) / atr if atr > 0 else 0
            trough_slack = (closes[i] - lows[i]) / atr if atr > 0 else 0
            
            is_peak = fractal_peak and atr_rejected_peak
            is_trough = fractal_trough and atr_bounced_trough
            
            if is_peak:
                entry_price = df.iloc[i + 1]['open']
                direction = 'short'
                tp_price = entry_price - atr * tp_mult
                sl_price = entry_price + atr * sl_mult
                entry_bar = i + 1
                entry_slack = peak_slack
                entry_mode = 'normal'
                in_trade = True
            
            elif is_trough:
                entry_price = df.iloc[i + 1]['open']
                direction = 'long'
                tp_price = entry_price + atr * tp_mult
                sl_price = entry_price - atr * sl_mult
                entry_bar = i + 1
                entry_slack = trough_slack
                entry_mode = 'normal'
                in_trade = True
    
    return trades


if __name__ == '__main__':
    print("Boof 23.5 (ZigZag + Chop Detection) backtest module loaded")
    print(f"ADX threshold: {ADX_CHOP_THRESHOLD} (< = chop mode)")
    print(f"Chop TP/SL: {CHOP_TP_PCT*100:.0f}% / {CHOP_SL_PCT*100:.0f}%")
    print(f"RSI2 levels: {RSI2_OVERSOLD} (oversold) / {RSI2_OVERBOUGHT} (overbought)")
