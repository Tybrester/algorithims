import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, ema, vwap, atr, get_alpaca_credentials

# =========================================================
# BOOF 19.0 - 0DTE SCALPING FOR SPY/QQQ
# Event-Driven High-Quality System (Redesigned)
# =========================================================

# Target symbols
# =========================================================
# SYMBOL-SPECIFIC PROFILES
# =========================================================

SPY_PROFILE = {
  "mode": "mean_reversion",
  "orbBreakoutPct": 0.0035,       # 0.35% (original - better quality)
  "liquidityGrabPct": 0.0035,    # 0.35% (original - better quality)
  "vwapDistance": 0.016,          # 1.6% (original - better quality)
  "takeProfitPct": 0.20,          # 20%
  "stopLossPct": -0.10,           # -10%
  "maxHoldMin": 6,                # 6 min (critical for 0DTE)
  "requireChopRegime": True,
  "trendTradesAllowed": False,
  "name": "SPY_CHOP_ENGINE",
  "exitLogic": "quick_scalp"
}

QQQ_PROFILE = {
  "mode": "mean_reversion",       # Changed from momentum to mean reversion
  "orbBreakoutPct": 0.0028,       # 0.28% (original - better quality)
  "liquidityGrabPct": 0.0028,    # 0.28% (original - better quality)
  "vwapDistance": 0.019,          # 1.9% (original - better quality)
  "takeProfitPct": 0.20,          # 20%
  "stopLossPct": -0.10,           # -10%
  "maxHoldMin": 6,                # 6 min (critical for 0DTE)
  "requireChopRegime": True,      # Chop-only
  "trendTradesAllowed": False,    # No trend trades
  "name": "QQQ_CHOP_ENGINE",
  "exitLogic": "quick_scalp"      # Quick scalp like SPY
}

def get_profile(symbol):
    return SPY_PROFILE if symbol == 'SPY' else QQQ_PROFILE

SYMBOLS = ['SPY', 'QQQ']
TIMEFRAME = '1Min'

# =========================================================
# REGIME DETECTION (Chop vs Trend)
# =========================================================

# VWAP slope threshold
VWAP_SLOPE_STRONG = 0.0001  # Relaxed for trend
VWAP_SLOPE_FLAT = 0.00002  # Relaxed for chop

# EMA separation
EMA9_PERIOD = 9
EMA21_PERIOD = 21
EMA_SPREAD_EXPANDING = 0.0005  # Relaxed
EMA_SPREAD_COMPRESSING = 0.0001  # Relaxed

# ADX proxy
ADX_PROXY_PERIOD = 14
ADX_PROXY_HIGH = 0.002  # Relaxed
ADX_PROXY_LOW = 0.0005  # Relaxed

# Higher timeframe alignment
HTF_VWAP_DISTANCE = 0.001  # Relaxed

# Dynamic TP based on regime (Chop Specialist - restored to original)
TP_CHOP = 0.20  # 20% TP in chop
TP_TREND = 0.20  # Same as chop since we only trade chop

# =========================================================
# MULTI-CANDLE ACCEPTANCE (Priority #2)
# =========================================================

CONTINUATION_CANDLES = 0  # No continuation requirement
CONTINUATION_THRESHOLD = 0.0001  # Reduced threshold

# =========================================================
# STRUCTURAL LEVELS (Priority #3)
# =========================================================

USE_PREV_DAY_LEVELS = True
USE_PREMARKET_LEVELS = True
USE_OVERNIGHT_MIDPOINT = True

# =========================================================
# DISTANCE FILTERS (Priority #4)
# =========================================================

MAX_DISTANCE_FROM_VWAP = 0.015  # Increased from 0.8% to 1.5%
MAX_DISTANCE_FROM_EMA = 0.012  # Increased from 0.6% to 1.2%
MAX_DISTANCE_FROM_ORB = 0.025  # Increased from 1.5% to 2.5%

# =========================================================
# SESSION-AWARE BEHAVIOR (Priority #5)
# =========================================================

SESSION_OPEN_END = "10:00"
SESSION_MIDDAY_END = "15:00"

SESSION_OPEN_TP_MULTIPLIER = 1.5
SESSION_OPEN_SL_MULTIPLIER = 0.8
SESSION_MIDDAY_TP_MULTIPLIER = 1.0
SESSION_MIDDAY_SL_MULTIPLIER = 1.2
SESSION_POWER_TP_MULTIPLIER = 1.3
SESSION_POWER_SL_MULTIPLIER = 0.9

# =========================================================
# REVERSAL-BASED LOGIC (Priority #6)
# =========================================================

FAILED_BREAKDOWN_THRESHOLD = 0.002  # Relaxed for 10 trades/day
FAILED_BREAKOUT_THRESHOLD = 0.002  # Relaxed for 10 trades/day
LIQUIDITY_GRAB_THRESHOLD = 0.003  # Relaxed for 10 trades/day
VWAP_RECLAIM_REVERSAL = True

# =========================================================
# EXIT ENGINE
# =========================================================

UNDERLYING_TP_PCT = 0.012
UNDERLYING_SL_PCT = -0.004
VWAP_STOP_LOSS = True
ATR_TP_MULTIPLIER = 0.5
ATR_SL_MULTIPLIER = 0.3
MAX_HOLD_MINUTES = 15  # Increased from 5 to 15 for structural moves
FAST_STOP_MINUTES = 5  # Increased from 2 to 5

# =========================================================
# OPTIONS PARAMETERS
# =========================================================

EXPIRATION = "0DTE"
DELTA_MIN = 0.45
DELTA_MAX = 0.60

# =========================================================
# REALISM LAYER (Slippage, Spread, Fill, Delay)
# =========================================================

# Slippage model
SLIPPAGE_MODEL = 'percentage'  # 'percentage' or 'fixed'
SLIPPAGE_PCT = 0.0  # Disabled for backtest
SLIPPAGE_FIXED = 0.0  # Disabled

# Spread model
SPREAD_MODEL = 'percentage'  # 'percentage' or 'fixed'
BID_ASK_SPREAD_PCT = 0.0  # Disabled for backtest
BID_ASK_SPREAD_FIXED = 0.0  # Disabled

# Worst-case fill assumption
WORST_CASE_FILL = False  # Disabled

# Delayed execution simulation
EXECUTION_DELAY_SECONDS = 0  # No delay
EXECUTION_DELAY_CANDLES = 0  # No delay

# Theta decay
THETA_DECAY_PER_MINUTE = 0.0002  # 0.02% theta decay per minute

# =========================================================
# TRADE WINDOWS
# =========================================================

TRADE_WINDOWS = [
    ("13:35", "15:00"),
    ("17:30", "19:00"),
]

# =========================================================
# REGIME DETECTION FUNCTIONS
# =========================================================

def detect_regime(df, idx):
    """Detect if current market is chop or trend using multiple factors"""
    if idx < 30:
        return 'chop', 0, "Not enough data"
    
    trend_score = 0
    
    # 1. VWAP slope
    vwap_values = vwap(df)
    vwap_slope = (vwap_values.iloc[idx] - vwap_values.iloc[idx-10]) / vwap_values.iloc[idx-10]
    if abs(vwap_slope) >= VWAP_SLOPE_STRONG:
        trend_score += 30
    elif abs(vwap_slope) <= VWAP_SLOPE_FLAT:
        trend_score -= 10
    
    # 2. EMA separation
    ema9_values = ema(df['close'], EMA9_PERIOD)
    ema21_values = ema(df['close'], EMA21_PERIOD)
    ema_spread = abs(ema9_values.iloc[idx] - ema21_values.iloc[idx]) / ema21_values.iloc[idx]
    
    # Check if spread is expanding
    ema_spread_prev = abs(ema9_values.iloc[idx-5] - ema21_values.iloc[idx-5]) / ema21_values.iloc[idx-5]
    if ema_spread > ema_spread_prev * 1.1 and ema_spread > EMA_SPREAD_EXPANDING:
        trend_score += 25
    elif ema_spread < EMA_SPREAD_COMPRESSING:
        trend_score -= 10
    
    # 3. ADX proxy (simple version)
    recent_candles = df.iloc[idx-ADX_PROXY_PERIOD:idx]
    total_move = sum(abs(recent_candles['close'] - recent_candles['open']) for _, recent_candles in recent_candles.iterrows())
    total_range = sum(recent_candles['high'] - recent_candles['low'] for _, recent_candles in recent_candles.iterrows())
    adx_proxy = total_move / total_range if total_range > 0 else 0
    
    if adx_proxy >= ADX_PROXY_HIGH:
        trend_score += 25
    elif adx_proxy <= ADX_PROXY_LOW:
        trend_score -= 10
    
    # 4. Higher timeframe alignment
    price_vs_vwap = (df.iloc[idx]['close'] - vwap_values.iloc[idx]) / vwap_values.iloc[idx]
    ema9_slope = (ema9_values.iloc[idx] - ema9_values.iloc[idx-5]) / ema9_values.iloc[idx-5]
    
    # Bullish regime: price above VWAP and EMA rising
    if price_vs_vwap > HTF_VWAP_DISTANCE and ema9_slope > 0:
        trend_score += 20
    # Bearish regime: price below VWAP and EMA falling
    elif price_vs_vwap < -HTF_VWAP_DISTANCE and ema9_slope < 0:
        trend_score += 20
    # Crossing/chop
    elif abs(price_vs_vwap) < HTF_VWAP_DISTANCE:
        trend_score -= 10
    
    # Classify regime
    if trend_score >= 70:
        regime = 'strong_trend'
    elif trend_score >= 40:
        regime = 'weak_trend'
    else:
        regime = 'chop'
    
    reason = f"Score={trend_score}, VWAP_slope={vwap_slope:.5f}, EMA_spread={ema_spread:.4f}, ADX_proxy={adx_proxy:.3f}"
    
    return regime, trend_score, reason

# =========================================================
# MULTI-CANDLE ACCEPTANCE
# =========================================================

def check_multi_candle_continuation(df, idx, direction, num_candles=0, threshold=0.0001):
    """Check for multi-candle continuation after breakout (disabled for more trades)"""
    if num_candles == 0:
        return True  # Always return true if no continuation required
    
    if idx < num_candles:
        return False
    
    for i in range(1, num_candles + 1):
        candle = df.iloc[idx - i]
        prev_candle = df.iloc[idx - i - 1]
        
        if direction == 'buy':
            if candle['close'] <= prev_candle['close']:
                return False
            if (candle['close'] - prev_candle['close']) / prev_candle['close'] < threshold:
                return False
        else:
            if candle['close'] >= prev_candle['close']:
                return False
            if (prev_candle['close'] - candle['close']) / prev_candle['close'] < threshold:
                return False
    
    return True

# =========================================================
# STRUCTURAL LEVELS
# =========================================================

def calculate_structural_levels(df, idx):
    """Calculate key structural levels"""
    if idx < 100:
        return {}
    
    # Previous day high/low
    prev_day = df.iloc[idx-1].date if 'date' in df.iloc[idx-1] else df.index[idx-1].date
    prev_day_candles = df[df.index.date == prev_day]
    
    if len(prev_day_candles) > 0:
        prev_high = prev_day_candles['high'].max()
        prev_low = prev_day_candles['low'].min()
    else:
        prev_high = df.iloc[idx-100:idx]['high'].max()
        prev_low = df.iloc[idx-100:idx]['low'].min()
    
    # Opening range (first 15 min of current day)
    current_day = df.iloc[idx].date if 'date' in df.iloc[idx] else df.index[idx].date
    day_candles = df[df.index.date == current_day]
    
    if len(day_candles) >= 15:
        or_high = day_candles.iloc[:15]['high'].max()
        or_low = day_candles.iloc[:15]['low'].min()
    else:
        or_high = day_candles['high'].max()
        or_low = day_candles['low'].min()
    
    return {
        'prev_high': prev_high,
        'prev_low': prev_low,
        'or_high': or_high,
        'or_low': or_low
    }

# =========================================================
# DISTANCE FILTERS
# =========================================================

def check_distance_filters(df, idx, levels, max_distance_vwap=MAX_DISTANCE_FROM_VWAP):
    """Check if price is too far from key levels"""
    candle = df.iloc[idx]
    vwap_values = vwap(df)
    ema_values = ema(df['close'], 9)
    
    # Distance from VWAP
    vwap_distance = abs(candle['close'] - vwap_values.iloc[idx]) / vwap_values.iloc[idx]
    if vwap_distance > max_distance_vwap:
        return False, f"Too far from VWAP ({vwap_distance*100:.2f}%)"
    
    # Distance from EMA
    ema_distance = abs(candle['close'] - ema_values.iloc[idx]) / ema_values.iloc[idx]
    if ema_distance > MAX_DISTANCE_FROM_EMA:
        return False, f"Too far from EMA ({ema_distance*100:.2f}%)"
    
    # Distance from ORB
    or_distance = abs(candle['close'] - levels.get('or_high', candle['close'])) / levels.get('or_high', candle['close'])
    if or_distance > MAX_DISTANCE_FROM_ORB:
        return False, f"Too far from ORB ({or_distance*100:.2f}%)"
    
    return True, "Distance filters passed"

# =========================================================
# SESSION-AWARE BEHAVIOR
# =========================================================

def get_session_type(timestamp):
    """Determine current session type"""
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute
    
    # Open session: 9:30-10:00 ET (13:30-14:00 UTC)
    if 13*60+30 <= time_minutes < 14*60:
        return 'open'
    # Midday session: 10:00-3:00 ET (14:00-19:00 UTC)
    elif 14*60 <= time_minutes < 19*60:
        return 'midday'
    # Power hour: 3:00-4:00 ET (19:00-20:00 UTC)
    elif 19*60 <= time_minutes < 20*60:
        return 'power'
    else:
        return 'other'

def get_session_multipliers(session_type):
    """Get TP/SL multipliers based on session"""
    if session_type == 'open':
        return SESSION_OPEN_TP_MULTIPLIER, SESSION_OPEN_SL_MULTIPLIER
    elif session_type == 'midday':
        return SESSION_MIDDAY_TP_MULTIPLIER, SESSION_MIDDAY_SL_MULTIPLIER
    elif session_type == 'power':
        return SESSION_POWER_TP_MULTIPLIER, SESSION_POWER_SL_MULTIPLIER
    else:
        return 1.0, 1.0

# =========================================================
# REVERSAL-BASED LOGIC
# =========================================================

def detect_failed_breakdown(df, idx, level, threshold=FAILED_BREAKDOWN_THRESHOLD):
    """Detect failed breakdown (price broke below level then reclaimed)"""
    if idx < 5:
        return False
    
    recent_low = df.iloc[idx-5:idx]['low'].min()
    if recent_low < level * (1 - threshold):
        if df.iloc[idx]['close'] > level:
            return True
    return False

def detect_failed_breakout(df, idx, level, threshold=FAILED_BREAKOUT_THRESHOLD):
    """Detect failed breakout (price broke above level then rejected)"""
    if idx < 5:
        return False
    
    recent_high = df.iloc[idx-5:idx]['high'].max()
    if recent_high > level * (1 + threshold):
        if df.iloc[idx]['close'] < level:
            return True
    return False

def detect_liquidity_grab(df, idx, level, threshold=LIQUIDITY_GRAB_THRESHOLD):
    """Detect liquidity grab (price swept beyond level then reversed)"""
    if idx < 3:
        return False
    
    # Check if price swept beyond level
    if df.iloc[idx-1]['high'] > level * (1 + threshold):
        if df.iloc[idx]['close'] < level:
            return True
    if df.iloc[idx-1]['low'] < level * (1 - threshold):
        if df.iloc[idx]['close'] > level:
            return True
    
    return False

# =========================================================
# OPTIONS SIMULATION
# =========================================================

def apply_realism(price, direction, is_entry=True):
    """Apply slippage, spread, and worst-case fill to price"""
    if SPREAD_MODEL == 'percentage':
        spread = price * BID_ASK_SPREAD_PCT / 2
    else:
        spread = BID_ASK_SPREAD_FIXED
    
    if SLIPPAGE_MODEL == 'percentage':
        slippage = price * SLIPPAGE_PCT
    else:
        slippage = SLIPPAGE_FIXED
    
    if is_entry:
        # Entry: buy at ask + slippage, sell at bid - slippage
        if direction == 'buy':
            adjusted_price = price + spread + slippage
        else:
            adjusted_price = price - spread - slippage
    else:
        # Exit: sell at bid - slippage, buy at ask + slippage
        if direction == 'buy':
            adjusted_price = price - spread - slippage
        else:
            adjusted_price = price + spread + slippage
    
    return adjusted_price

def calculate_option_price(underlying_price, strike, delta, days_to_expiry=0, iv=0.2):
    intrinsic = max(0, underlying_price - strike) if delta > 0.5 else max(0, strike - underlying_price)
    time_value = underlying_price * iv * delta * 0.1
    return intrinsic + time_value

def calculate_delta(underlying_price, strike, days_to_expiry=0, iv=0.2):
    moneyness = (underlying_price - strike) / underlying_price
    if moneyness > 0.02:
        return min(0.6, 0.5 + moneyness * 5)
    elif moneyness < -0.02:
        return max(0.4, 0.5 + moneyness * 5)
    else:
        return 0.5

def simulate_option_trade(entry_underlying, exit_underlying, direction, hold_minutes, iv=0.2):
    """Simulate option trade with realism layer"""
    strike = round(entry_underlying / 0.5) * 0.5
    entry_delta = calculate_delta(entry_underlying, strike, 0, iv)
    entry_option_mid = calculate_option_price(entry_underlying, strike, entry_delta, 0, iv)
    
    # Apply realism to entry price
    entry_price = apply_realism(entry_option_mid, direction, is_entry=True)
    
    exit_delta = calculate_delta(exit_underlying, strike, 0, iv)
    exit_option_mid = calculate_option_price(exit_underlying, strike, exit_delta, 0, iv)
    theta_decay = exit_option_mid * THETA_DECAY_PER_MINUTE * hold_minutes
    exit_option_mid -= theta_decay
    
    # Apply realism to exit price
    exit_price = apply_realism(exit_option_mid, direction, is_entry=False)
    
    if direction == 'buy':
        option_pnl = (exit_price - entry_price) / entry_price
    else:
        option_pnl = (entry_price - exit_price) / entry_price
    
    return {
        'entry_option_price': entry_price,
        'exit_option_price': exit_price,
        'option_pnl': option_pnl,
        'entry_delta': entry_delta,
        'exit_delta': exit_delta,
        'theta_decay': theta_decay,
        'strike': strike
    }

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def is_in_trade_window(timestamp):
    date = datetime.fromtimestamp(timestamp) if isinstance(timestamp, (int, float)) else timestamp
    hour = date.hour
    minute = date.minute
    time_minutes = hour * 60 + minute
    
    for window in TRADE_WINDOWS:
        start_h, start_m = map(int, window[0].split(':'))
        end_h, end_m = map(int, window[1].split(':'))
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m
        
        if start_minutes <= time_minutes < end_minutes:
            return True
    
    return False

# =========================================================
# SIGNAL GENERATION (Event-Driven)
# =========================================================

def generate_signal(df, idx, profile):
    """Generate signals with profile-driven logic (single function for all symbols)"""
    if idx < 50:
        return 'none', 0, 'Not enough data', 'chop'
    
    row = df.iloc[idx]
    
    if not is_in_trade_window(df.index[idx]):
        return 'none', 0, 'Outside trade window', 'chop'
    
    # Detect regime
    regime, trend_score, regime_reason = detect_regime(df, idx)
    
    # Symbol-specific regime filter
    if profile["requireChopRegime"] and regime != 'chop':
        return 'none', 0, f'Filter: {regime} regime (chop only)', regime
    if not profile["trendTradesAllowed"] and regime in ['strong_trend', 'weak_trend']:
        return 'none', 0, f'Filter: {regime} regime (trend disabled)', regime
    
    # Calculate structural levels
    levels = calculate_structural_levels(df, idx)
    
    # Distance Filters (profile-driven)
    distance_ok, distance_reason = check_distance_filters(df, idx, levels, profile["vwapDistance"])
    if not distance_ok:
        return 'none', 0, distance_reason, regime
    
    # Reversal-Based Logic (profile-driven thresholds)
    vwap_values = vwap(df)
    current_vwap = vwap_values.iloc[idx]
    
    # Failed breakdown reversal (long)
    if detect_failed_breakdown(df, idx, levels['prev_low'], profile["liquidityGrabPct"]):
        if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'buy', row['close'], f'Failed breakdown reversal - {regime}', regime
    
    # Failed breakout reversal (short)
    if detect_failed_breakout(df, idx, levels['prev_high'], profile["liquidityGrabPct"]):
        if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'sell', row['close'], f'Failed breakout reversal - {regime}', regime
    
    # Liquidity grab reversal
    if detect_liquidity_grab(df, idx, levels['or_high'], profile["liquidityGrabPct"]):
        if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'sell', row['close'], f'Liquidity grab reversal - {regime}', regime
    
    if detect_liquidity_grab(df, idx, levels['or_low'], profile["liquidityGrabPct"]):
        if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'buy', row['close'], f'Liquidity grab reversal - {regime}', regime
    
    # VWAP reclaim reversal (SPY/mean reversion only)
    if profile["mode"] == "mean_reversion" and VWAP_RECLAIM_REVERSAL:
        vwap_distance = (row['close'] - current_vwap) / current_vwap
        if abs(vwap_distance) < 0.001 and vwap_distance > 0:
            if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
                return 'buy', row['close'], f'VWAP reclaim reversal - {regime}', regime
        elif abs(vwap_distance) < 0.001 and vwap_distance < 0:
            if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
                return 'sell', row['close'], f'VWAP reclaim reversal - {regime}', regime
    
    # Structural level breakout (profile-driven threshold)
    if row['close'] > levels['or_high'] * (1 + profile["orbBreakoutPct"]):
        if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'buy', row['close'], f'OR breakout - {regime}', regime
    
    if row['close'] < levels['or_low'] * (1 - profile["orbBreakoutPct"]):
        if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'sell', row['close'], f'OR breakdown - {regime}', regime
    
    return 'none', 0, 'No high-quality setup', regime

# =========================================================
# BACKTEST ENGINE
# =========================================================

def backtest_boof19_v2(symbol, start_date, end_date):
    print(f"\n{'='*60}")
    print(f"BOOF 19.0 V2 BACKTEST: {symbol}")
    print(f"{'='*60}")
    
    creds = get_alpaca_credentials()
    df = fetch_alpaca_bars(symbol, start_date, end_date, TIMEFRAME, api_key=creds['api_key'], secret_key=creds['secret_key'])
    if df is None or len(df) < 100:
        print(f"Insufficient data for {symbol}")
        return None
    
    print(f"Fetched {len(df)} candles")
    df['date'] = df.index.date
    
    # Generate signals
    signals = []
    profile = get_profile(symbol)
    for idx in range(len(df)):
        signal, price, reason, regime = generate_signal(df, idx, profile)
        if signal != 'none':
            signals.append({
                'timestamp': df.index[idx],
                'signal': signal,
                'price': price,
                'reason': reason,
                'regime': regime
            })
    
    print(f"Generated {len(signals)} signals")
    
    # Simulate trades with delayed execution
    trades = []
    entry_time = None
    entry_price = None
    direction = None
    entry_regime = None
    pending_signal = None  # Store pending signal for delayed execution
    signal_map = {sig['timestamp']: sig for sig in signals}
    
    for idx in range(len(df)):
        candle_time = df.index[idx]
        candle_price = df.iloc[idx]['close']
        
        # Check for new signal
        if entry_time is None and candle_time in signal_map:
            sig = signal_map[candle_time]
            if sig['signal'] != 'none':
                # Calculate delay in candles
                if EXECUTION_DELAY_CANDLES > 0:
                    delay_candles = EXECUTION_DELAY_CANDLES
                elif EXECUTION_DELAY_SECONDS > 0:
                    # Convert seconds to candles (assuming 1-min candles)
                    delay_candles = max(1, int(EXECUTION_DELAY_SECONDS / 60))
                else:
                    # No delay - execute immediately
                    entry_time = candle_time
                    entry_price = candle_price
                    direction = sig['signal']
                    entry_regime = sig['regime']
                    max_favorable_move = 0  # Reset for new trade
                    continue
                
                # If delay > 0, store pending signal
                pending_signal = sig
                pending_signal['delay_remaining'] = delay_candles
                continue
        
        # Process pending signal with delay
        if pending_signal is not None and entry_time is None:
            pending_signal['delay_remaining'] -= 1
            if pending_signal['delay_remaining'] <= 0:
                # Execute entry with delayed price
                entry_time = candle_time
                entry_price = candle_price
                direction = pending_signal['signal']
                entry_regime = pending_signal['regime']
                max_favorable_move = 0  # Reset for new trade
                pending_signal = None
                continue
        
        if entry_time is not None:
            hold_minutes = (candle_time - entry_time).total_seconds() / 60
            exit_reason = None
            exit_price = candle_price
            underlying_move = (exit_price - entry_price) / entry_price
            
            # Profile-driven exit logic
            if profile["exitLogic"] == "quick_scalp":
                # SPY: quick profit or time exit
                if direction == 'buy' and underlying_move >= profile["takeProfitPct"]:
                    exit_reason = f'Quick TP ({underlying_move * 100:.2f}%)'
                elif direction == 'sell' and abs(underlying_move) >= profile["takeProfitPct"]:
                    exit_reason = f'Quick TP ({abs(underlying_move) * 100:.2f}%)'
                elif hold_minutes >= profile["maxHoldMin"]:
                    exit_reason = f'Time exit ({hold_minutes:.1f} min)'
                elif direction == 'buy' and underlying_move <= profile["stopLossPct"]:
                    exit_reason = f'SL hit ({underlying_move * 100:.2f}%)'
                elif direction == 'sell' and abs(underlying_move) <= abs(profile["stopLossPct"]):
                    exit_reason = f'SL hit ({abs(underlying_move) * 100:.2f}%)'
            elif profile["exitLogic"] == "trend_follow":
                # QQQ: hold if trend valid, exit if momentum breaks
                current_regime, current_trend_score, _ = detect_regime(df, idx)
                
                # Check if trend still valid
                trend_still_valid = current_regime in ['strong_trend', 'weak_trend']
                
                # Track max favorable move for trailing stop
                if direction == 'buy':
                    max_favorable_move = max(max_favorable_move, underlying_move)
                else:
                    max_favorable_move = max(max_favorable_move, abs(underlying_move))
                
                # Trailing stop logic (protect winners)
                if profile.get("useTrailingStop", False) and hold_minutes > 3:
                    trailing_stop_threshold = max_favorable_move - profile.get("trailingStopPct", 0.005)
                    if direction == 'buy' and underlying_move < trailing_stop_threshold:
                        exit_reason = f'Trailing stop ({underlying_move * 100:.2f}%)'
                    elif direction == 'sell' and abs(underlying_move) < trailing_stop_threshold:
                        exit_reason = f'Trailing stop ({abs(underlying_move) * 100:.2f}%)'
                
                # Don't exit on first weakness (min hold time)
                min_hold = profile.get("minHoldBeforeExit", 0)
                
                if direction == 'buy' and underlying_move >= profile["takeProfitPct"]:
                    exit_reason = f'Trend TP ({underlying_move * 100:.2f}%)'
                elif direction == 'sell' and abs(underlying_move) >= profile["takeProfitPct"]:
                    exit_reason = f'Trend TP ({abs(underlying_move) * 100:.2f}%)'
                elif not trend_still_valid and hold_minutes > min_hold:
                    exit_reason = f'Trend broken ({current_regime})'
                elif hold_minutes >= profile["maxHoldMin"]:
                    exit_reason = f'Max time exit ({hold_minutes:.1f} min)'
                elif direction == 'buy' and underlying_move <= profile["stopLossPct"]:
                    exit_reason = f'SL hit ({underlying_move * 100:.2f}%)'
                elif direction == 'sell' and abs(underlying_move) <= abs(profile["stopLossPct"]):
                    exit_reason = f'SL hit ({abs(underlying_move) * 100:.2f}%)'
            else:
                # Fallback to original logic
                if direction == 'buy' and underlying_move >= profile["takeProfitPct"]:
                    exit_reason = f'TP hit ({underlying_move * 100:.2f}%)'
                elif direction == 'sell' and abs(underlying_move) >= profile["takeProfitPct"]:
                    exit_reason = f'TP hit ({abs(underlying_move) * 100:.2f}%)'
                elif hold_minutes >= profile["maxHoldMin"]:
                    exit_reason = f'Time exit ({hold_minutes:.1f} min)'
                elif direction == 'buy' and underlying_move <= profile["stopLossPct"]:
                    exit_reason = f'SL hit ({underlying_move * 100:.2f}%)'
                elif direction == 'sell' and abs(underlying_move) <= abs(profile["stopLossPct"]):
                    exit_reason = f'SL hit ({abs(underlying_move) * 100:.2f}%)'
            
            if exit_reason:
                option_result = simulate_option_trade(entry_price, exit_price, direction, hold_minutes)
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': candle_time,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'direction': direction,
                    'underlying_pnl': underlying_move,
                    'option_pnl': option_result['option_pnl'],
                    'entry_option_price': option_result['entry_option_price'],
                    'exit_option_price': option_result['exit_option_price'],
                    'entry_delta': option_result['entry_delta'],
                    'exit_delta': option_result['exit_delta'],
                    'theta_decay': option_result['theta_decay'],
                    'strike': option_result['strike'],
                    'hold_minutes': hold_minutes,
                    'exit_reason': exit_reason,
                    'regime': entry_regime
                })
                entry_time = None
                entry_price = None
                direction = None
                entry_regime = None
    
    if entry_time is not None:
        exit_price = df.iloc[-1]['close']
        hold_minutes = (df.index[-1] - entry_time).total_seconds() / 60
        underlying_move = (exit_price - entry_price) / entry_price
        option_result = simulate_option_trade(entry_price, exit_price, direction, hold_minutes)
        trades.append({
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'direction': direction,
            'underlying_pnl': underlying_move,
            'option_pnl': option_result['option_pnl'],
            'entry_option_price': option_result['entry_option_price'],
            'exit_option_price': option_result['exit_option_price'],
            'entry_delta': option_result['entry_delta'],
            'exit_delta': option_result['exit_delta'],
            'theta_decay': option_result['theta_decay'],
            'strike': option_result['strike'],
            'hold_minutes': hold_minutes,
            'exit_reason': 'End of data',
            'regime': entry_regime
        })
    
    if len(trades) == 0:
        print("No trades generated")
        return None
    
    total_trades = len(trades)
    winning_trades = len([t for t in trades if t['option_pnl'] > 0])
    losing_trades = len([t for t in trades if t['option_pnl'] < 0])
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    total_pnl = sum(t['option_pnl'] for t in trades)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    avg_hold = sum(t['hold_minutes'] for t in trades) / total_trades if total_trades > 0 else 0
    
    max_profit = max(t['option_pnl'] for t in trades) if trades else 0
    max_loss = min(t['option_pnl'] for t in trades) if trades else 0
    
    cumulative = np.cumsum([t['option_pnl'] for t in trades])
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (running_max - cumulative) / (running_max + 1e-6)
    max_drawdown = drawdown.max() if len(drawdown) > 0 else 0
    
    avg_theta = sum(t['theta_decay'] for t in trades) / total_trades if total_trades > 0 else 0
    
    # Regime breakdown
    trend_trades = [t for t in trades if t['regime'] in ['strong_trend', 'weak_trend']]
    chop_trades = [t for t in trades if t['regime'] == 'chop']
    
    trend_pnl = sum(t['option_pnl'] for t in trend_trades) if trend_trades else 0
    chop_pnl = sum(t['option_pnl'] for t in chop_trades) if chop_trades else 0
    
    # Exit reason breakdown
    tp_trades = [t for t in trades if 'TP' in t.get('exit_reason', '')]
    sl_trades = [t for t in trades if 'SL' in t.get('exit_reason', '')]
    time_trades = [t for t in trades if 'Time' in t.get('exit_reason', '')]
    trend_break_trades = [t for t in trades if 'Trend' in t.get('exit_reason', '')]
    
    tp_pnl = sum(t['option_pnl'] for t in tp_trades) if tp_trades else 0
    sl_pnl = sum(t['option_pnl'] for t in sl_trades) if sl_trades else 0
    time_pnl = sum(t['option_pnl'] for t in time_trades) if time_trades else 0
    trend_break_pnl = sum(t['option_pnl'] for t in trend_break_trades) if trend_break_trades else 0
    
    print(f"\n{'='*60}")
    print(f"RESULTS: {symbol}")
    print(f"{'='*60}")
    print(f"Total Trades: {total_trades}")
    print(f"Winning Trades: {winning_trades}")
    print(f"Losing Trades: {losing_trades}")
    print(f"Win Rate: {win_rate*100:.1f}%")
    print(f"Total Option PnL: {total_pnl*100:.1f}%")
    print(f"Avg Option PnL per Trade: {avg_pnl*100:.2f}%")
    print(f"Avg Underlying Move: {np.mean([t['underlying_pnl'] for t in trades])*100:.2f}%")
    print(f"Avg Hold Time: {avg_hold:.1f} minutes")
    print(f"Avg Theta Decay: ${avg_theta:.3f}")
    print(f"Max Profit: {max_profit*100:.1f}%")
    print(f"Max Loss: {max_loss*100:.1f}%")
    print(f"Max Drawdown: {max_drawdown*100:.1f}%")
    print(f"\nRegime Breakdown:")
    print(f"  Trend Trades: {len(trend_trades)} (PnL: {trend_pnl*100:.1f}%)")
    print(f"  Chop Trades: {len(chop_trades)} (PnL: {chop_pnl*100:.1f}%)")
    print(f"\nExit Reason Breakdown:")
    print(f"  TP Hits: {len(tp_trades)} (PnL: {tp_pnl*100:.1f}%)")
    print(f"  SL Hits: {len(sl_trades)} (PnL: {sl_pnl*100:.1f}%)")
    print(f"  Time Exits: {len(time_trades)} (PnL: {time_pnl*100:.1f}%)")
    print(f"  Trend Breaks: {len(trend_break_trades)} (PnL: {trend_break_pnl*100:.1f}%)")
    print(f"{'='*60}")
    
    return {
        'symbol': symbol,
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'avg_hold_minutes': avg_hold,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'max_drawdown': max_drawdown,
        'avg_theta': avg_theta,
        'trades': trades
    }

if __name__ == '__main__':
    end_date = datetime(2026, 4, 30)
    start_date = datetime(2026, 4, 1)
    
    results = []
    for symbol in SYMBOLS:
        result = backtest_boof19_v2(symbol, start_date, end_date)
        if result:
            results.append(result)
    
    if results:
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        for r in results:
            trade_capital = r['total_trades'] * 300
            total_pnl_dollars = trade_capital * (r['total_pnl'] / 100)
            print(f"{r['symbol']}: {r['total_trades']} trades, {r['win_rate']*100:.1f}% win rate, {r['total_pnl']*100:.1f}% total PnL")
            print(f"  Trade capital: ${trade_capital:,.0f}")
            print(f"  PnL at $300/trade: ${total_pnl_dollars:,.2f}")
        
        total_trades = sum(r['total_trades'] for r in results)
        total_capital = total_trades * 300
        combined_pnl_pct = sum(r['total_pnl'] for r in results)
        combined_pnl_dollars = total_capital * (combined_pnl_pct / 100)
        print(f"\nCombined: {total_trades} trades, {combined_pnl_pct*100:.1f}% total PnL")
        print(f"  Total trade capital: ${total_capital:,.0f}")
        print(f"  Combined PnL at $300/trade: ${combined_pnl_dollars:,.2f}")
