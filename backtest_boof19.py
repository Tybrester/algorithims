import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, ema, vwap, atr, get_alpaca_credentials

# =========================================================
# BOOF 19.0 - 0DTE SCALPING FOR SPY/QQQ
# Event-Driven High-Quality System (Redesigned)
# =========================================================

# Target symbols
SYMBOLS = ['SPY', 'QQQ']

# Timeframe
TIMEFRAME = '1Min'  # 1-minute candles for scalping

# =========================================================
# LAYER 1 — MARKET REGIME FILTER
# =========================================================

# EXPANSION DAY requirements
ATR_EXPANSION_MULTIPLIER = 1.0  # ATR_today > ATR_20d * 1.0 (relaxed)
ORB_RANGE_THRESHOLD = 0.8  # ORB_range > 0.8 * avg_ORB_range (relaxed)
VWAP_DISTANCE_THRESHOLD = 0.001  # abs(price - VWAP) > 0.1% (relaxed)

# =========================================================
# LAYER 2 — PRIMARY ORB ENTRY
# =========================================================

# Opening Range parameters
OR_MINUTES = 15  # First 15 minutes

# Compression parameters
COMPRESSION_LOOKBACK = 5
COMPRESSION_THRESHOLD = 0.9
RANGE_ROLLING_PERIOD = 20

# Expansion parameters
VOLUME_SPIKE_MULTIPLIER = 1.1
ATR_EXPANSION_MULTIPLIER_ORB = 1.0
MIN_BODY_MULTIPLIER = 1.1

# =========================================================
# LAYER 3 — CONTINUATION ENTRIES
# =========================================================

# A. Pullback Continuation
EMA9_PERIOD = 9
PULLBACK_THRESHOLD = 0.001  # 0.1% from EMA9/VWAP
REJECTION_BODY_RATIO = 0.6  # Body > 60% of range

# B. Re-compression Break
RECOMPRESSION_ATR_THRESHOLD = 0.8  # ATR < 80% of average
RECOMPRESSION_LOOKBACK = 10

# C. VWAP Reclaim
VWAP_RECLAIM_THRESHOLD = 0.001  # 0.1% reclaim
VWAP_LOSS_THRESHOLD = 0.001  # 0.1% loss before reclaim

# =========================================================
# TREND FILTER
# =========================================================

EMA_PERIOD = 9  # 9-minute EMA for trend
EMA_SLOPE_THRESHOLD = 0.0001  # Minimum slope for trend
VWAP_TREND_OFFSET = 0.0005  # Price must be 0.05% from VWAP

# =========================================================
# EXIT ENGINE
# =========================================================

# Underlying-based exits (Priority #3)
UNDERLYING_TP_PCT = 0.012  # 1.2% move on underlying (increased from 0.8%)
UNDERLYING_SL_PCT = -0.004  # -0.4% move on underlying (tightened)
VWAP_STOP_LOSS = True  # Stop if underlying loses VWAP

# ATR-based exits (Priority #2)
ATR_TP_MULTIPLIER = 0.5  # TP at 0.5x ATR
ATR_SL_MULTIPLIER = 0.3  # SL at 0.3x ATR

# Reduced hold time (Priority #4)
MAX_HOLD_MINUTES = 5  # Reduced from 10 to 5 minutes
FAST_STOP_MINUTES = 2  # Check for fast stop after 2 minutes

# =========================================================
# TRADE WINDOWS
# =========================================================

# Trade only during high-liquidity hours
TRADE_WINDOWS = [
    ("13:35", "15:00"),  # Morning session (9:35-11:00 AM ET)
    ("17:30", "19:00"),  # Afternoon session (1:30-3:00 PM ET)
]

# =========================================================
# OPTIONS PARAMETERS
# =========================================================

EXPIRATION = "0DTE"
DELTA_MIN = 0.45
DELTA_MAX = 0.60
BID_ASK_SPREAD_PCT = 0.01  # Reduced from 2% to 1% spread
SLIPPAGE_PCT = 0.002  # Reduced from 0.5% to 0.2% slippage

# Theta decay (per minute for 0DTE)
THETA_DECAY_PER_MINUTE = 0.0002  # Reduced from 0.05% to 0.02% decay per minute

# =========================================================
# OPTIONS SIMULATION (Priority #1)
# =========================================================

def calculate_option_price(underlying_price, strike, delta, days_to_expiry=0, iv=0.2):
    """Simplified Black-Scholes for option pricing"""
    # For 0DTE, use delta approximation
    intrinsic = max(0, underlying_price - strike) if delta > 0.5 else max(0, strike - underlying_price)
    time_value = underlying_price * iv * delta * 0.1  # Simplified time value
    return intrinsic + time_value

def calculate_delta(underlying_price, strike, days_to_expiry=0, iv=0.2):
    """Calculate option delta based on moneyness"""
    moneyness = (underlying_price - strike) / underlying_price
    # Approximate delta for 0DTE
    if moneyness > 0.02:
        return min(0.6, 0.5 + moneyness * 5)
    elif moneyness < -0.02:
        return max(0.4, 0.5 + moneyness * 5)
    else:
        return 0.5

def simulate_option_trade(entry_underlying, exit_underlying, direction, hold_minutes, iv=0.2):
    """Simulate option trade with realistic costs"""
    # Select ATM strike
    strike = round(entry_underlying / 0.5) * 0.5  # Round to nearest $0.50
    
    # Calculate entry delta
    entry_delta = calculate_delta(entry_underlying, strike, 0, iv)
    
    # Calculate entry option price (mid)
    entry_option_mid = calculate_option_price(entry_underlying, strike, entry_delta, 0, iv)
    
    # Apply bid/ask spread (Priority #1)
    entry_option_ask = entry_option_mid * (1 + BID_ASK_SPREAD_PCT / 2)
    
    # Apply slippage (Priority #1)
    entry_price = entry_option_ask * (1 + SLIPPAGE_PCT)
    
    # Calculate exit delta (dynamic delta - Priority #1)
    exit_delta = calculate_delta(exit_underlying, strike, 0, iv)
    
    # Calculate exit option price (mid)
    exit_option_mid = calculate_option_price(exit_underlying, strike, exit_delta, 0, iv)
    
    # Apply theta decay (Priority #1)
    theta_decay = exit_option_mid * THETA_DECAY_PER_MINUTE * hold_minutes
    exit_option_mid -= theta_decay
    
    # Apply bid/ask spread on exit
    exit_option_bid = exit_option_mid * (1 - BID_ASK_SPREAD_PCT / 2)
    
    # Apply slippage on exit
    exit_price = exit_option_bid * (1 - SLIPPAGE_PCT)
    
    # Calculate option PnL
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
# INDICATOR CALCULATIONS
# =========================================================

def calculate_or(df, minutes=15):
    """Calculate Opening Range high and low for each day"""
    df = df.copy()
    
    # Group by date
    df['date'] = df.index.date
    
    or_high = {}
    or_low = {}
    or_range = {}
    
    for date, group in df.groupby('date'):
        # Get first N minutes of trading
        group_sorted = group.sort_index()
        or_candles = group_sorted.head(minutes)
        
        if len(or_candles) > 0:
            or_high[date] = or_candles['high'].max()
            or_low[date] = or_candles['low'].min()
            or_range[date] = or_high[date] - or_low[date]
        else:
            or_high[date] = group['high'].iloc[0]
            or_low[date] = group['low'].iloc[0]
            or_range[date] = group['high'].iloc[0] - group['low'].iloc[0]
    
    return or_high, or_low, or_range

def calculate_avg_orb_range(df, or_range, period=20):
    """Calculate rolling average ORB range"""
    dates = sorted(or_range.keys())
    avg_orb_range = {}
    
    for i, date in enumerate(dates):
        if i < period - 1:
            avg_orb_range[date] = or_range[date]
        else:
            recent_ranges = [or_range[d] for d in dates[i-period+1:i+1]]
            avg_orb_range[date] = sum(recent_ranges) / len(recent_ranges)
    
    return avg_orb_range

def detect_compression(df, lookback=5, threshold=0.9):
    """Detect compression (low volatility before expansion)"""
    df = df.copy()
    
    # Calculate candle ranges
    df['range'] = df['high'] - df['low']
    
    # Rolling average of ranges
    df['range_avg'] = df['range'].rolling(lookback).mean()
    
    # Compression: current range < threshold * average
    df['compression'] = df['range'] < df['range_avg'] * threshold
    
    return df

def detect_orb_breakout(df, or_high, or_low, threshold=0.002):
    """Detect ORB breakout"""
    df = df.copy()
    df['date'] = df.index.date
    
    df['orb_breakout_long'] = False
    df['orb_breakout_short'] = False
    
    for idx, row in df.iterrows():
        date = row['date']
        if date in or_high and date in or_low:
            orb_high = or_high[date]
            orb_low = or_low[date]
            
            # Breakout long
            if row['close'] > orb_high * (1 + threshold):
                df.loc[idx, 'orb_breakout_long'] = True
            
            # Breakout short
            if row['close'] < orb_low * (1 - threshold):
                df.loc[idx, 'orb_breakout_short'] = True
    
    return df

def detect_pullback_continuation(df, ema_period=9, pullback_threshold=0.001, rejection_ratio=0.6):
    """Detect pullback continuation entries"""
    df = df.copy()
    
    # Calculate EMA9
    df['ema9'] = ema(df['close'], ema_period)
    
    # Calculate VWAP
    df['vwap'] = vwap(df)
    
    # Detect pullback to EMA9/VWAP
    df['pullback_ema'] = (df['close'] - df['ema9']).abs() / df['ema9'] < pullback_threshold
    df['pullback_vwap'] = (df['close'] - df['vwap']).abs() / df['vwap'] < pullback_threshold
    
    # Detect rejection candle (bullish body > 60% of range)
    df['body'] = (df['close'] - df['open']).abs()
    df['range'] = df['high'] - df['low']
    df['bullish_rejection'] = (df['body'] / df['range'] > rejection_ratio) & (df['close'] > df['open'])
    
    # Pullback continuation signal
    df['pullback_continuation_long'] = df['pullback_ema'] & df['bullish_rejection']
    df['pullback_continuation_short'] = df['pullback_ema'] & ((df['body'] / df['range'] > rejection_ratio) & (df['close'] < df['open']))
    
    return df

def detect_recompression_break(df, atr_threshold=0.8, lookback=10):
    """Detect re-compression break (low ATR consolidation after breakout)"""
    df = df.copy()
    
    # Calculate ATR
    df['atr'] = atr(df, 14)
    df['atr_avg'] = df['atr'].rolling(20).mean()
    
    # Re-compression: ATR < threshold * average
    df['recompression'] = df['atr'] < df['atr_avg'] * atr_threshold
    
    # Check if we had a breakout recently (within lookback candles)
    df['recent_breakout'] = df['high'].rolling(lookback).max().shift(1) < df['high']
    
    # Re-compression break: re-compression ends with breakout
    df['recompression_break_long'] = df['recompression'].shift(1) & df['recent_breakout'] & (df['close'] > df['open'])
    df['recompression_break_short'] = df['recompression'].shift(1) & df['recent_breakout'] & (df['close'] < df['open'])
    
    return df

def detect_vwap_reclaim(df, reclaim_threshold=0.001, loss_threshold=0.001):
    """Detect VWAP reclaim after temporary loss"""
    df = df.copy()
    
    # Calculate VWAP
    df['vwap'] = vwap(df)
    
    # Calculate distance from VWAP
    df['vwap_distance'] = (df['close'] - df['vwap']) / df['vwap']
    
    # Determine if above/below VWAP
    df['above_vwap'] = (df['vwap_distance'] > 0).astype(bool)
    
    # Detect VWAP loss (cross from above to below)
    df['vwap_loss'] = (~df['above_vwap']) & (df['above_vwap'].shift(1).fillna(False))
    
    # Detect VWAP reclaim (cross back above after loss)
    df['vwap_reclaim'] = df['above_vwap'] & (~df['above_vwap'].shift(1).fillna(False)) & (df['vwap_loss'].shift(1).fillna(False))
    
    return df

def calculate_ema_slope(df, period=9):
    """Calculate EMA slope for trend filter"""
    df = df.copy()
    df['ema'] = ema(df['close'], period)
    df['ema_slope'] = df['ema'].diff()
    return df

def is_in_trade_window(timestamp):
    """Check if timestamp is within trade windows"""
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute
    
    for start, end in TRADE_WINDOWS:
        start_hour, start_min = map(int, start.split(':'))
        end_hour, end_min = map(int, end.split(':'))
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min
        
        if start_minutes <= time_minutes < end_minutes:
            return True
    
    return False

def check_expansion_day(df, idx, or_range, avg_orb_range):
    """Layer 1: Check if it's an expansion day (directional market)"""
    if idx < 20:
        return False, 'Not enough data for regime check'
    
    row = df.iloc[idx]
    date = row['date'] if 'date' in row else df.index[idx].date
    
    # ATR expansion
    atr_values = atr(df, 14)
    atr_avg = atr_values.rolling(20).mean()
    atr_expansion = atr_values.iloc[idx] > atr_avg.iloc[idx] * ATR_EXPANSION_MULTIPLIER
    
    # ORB range expansion
    orb_expansion = or_range.get(date, 0) > avg_orb_range.get(date, 0) * ORB_RANGE_THRESHOLD
    
    # VWAP distance
    vwap_values = vwap(df)
    vwap_distance = abs(row['close'] - vwap_values.iloc[idx]) / vwap_values.iloc[idx]
    vwap_expansion = vwap_distance > VWAP_DISTANCE_THRESHOLD
    
    # All conditions must be true
    is_expansion = atr_expansion and orb_expansion and vwap_expansion
    
    reason = f"ATR_exp={atr_expansion}, ORB_exp={orb_expansion}, VWAP_exp={vwap_expansion}"
    
    return is_expansion, reason

# =========================================================
# SIGNAL GENERATION (LAYERED APPROACH)
# =========================================================

def generate_signal(df, idx, or_high, or_low, or_range, avg_orb_range):
    """Generate trading signal using layered approach"""
    if idx < 10:
        return 'none', 0, 'Not enough data'
    
    row = df.iloc[idx]
    
    # Check trade window
    if not is_in_trade_window(df.index[idx]):
        return 'none', 0, 'Outside trade window'
    
    # LAYER 1: Market Regime Filter (DISABLED FOR TESTING)
    # is_expansion, regime_reason = check_expansion_day(df, idx, or_range, avg_orb_range)
    # if not is_expansion:
    #     return 'none', 0, f'Layer 1: Not expansion day ({regime_reason})'
    
    # Skip Layer 1 for now to test signal quality
    
    # LAYER 2: Primary ORB Entry
    if row.get('orb_breakout_long', False) and row.get('compression', False):
        volume_avg = df['volume'].rolling(5).mean()
        volume_expansion = row['volume'] > volume_avg.iloc[idx] * VOLUME_SPIKE_MULTIPLIER
        
        if volume_expansion:
            return 'buy', row['close'], 'Layer 2: ORB breakout with compression and volume'
    
    if row.get('orb_breakout_short', False) and row.get('compression', False):
        volume_avg = df['volume'].rolling(5).mean()
        volume_expansion = row['volume'] > volume_avg.iloc[idx] * VOLUME_SPIKE_MULTIPLIER
        
        if volume_expansion:
            return 'sell', row['close'], 'Layer 2: ORB breakout with compression and volume'
    
    # LAYER 3: Continuation Entries
    
    # A. Pullback Continuation
    if row.get('pullback_continuation_long', False):
        return 'buy', row['close'], 'Layer 3A: Pullback continuation long'
    
    if row.get('pullback_continuation_short', False):
        return 'sell', row['close'], 'Layer 3A: Pullback continuation short'
    
    # B. Re-compression Break
    if row.get('recompression_break_long', False):
        return 'buy', row['close'], 'Layer 3B: Re-compression break long'
    
    if row.get('recompression_break_short', False):
        return 'sell', row['close'], 'Layer 3B: Re-compression break short'
    
    # C. VWAP Reclaim
    if row.get('vwap_reclaim', False):
        # Check trend alignment
        ema_slope = calculate_ema_slope(df, EMA_PERIOD)
        if ema_slope['ema_slope'].iloc[idx] > EMA_SLOPE_THRESHOLD:
            return 'buy', row['close'], 'Layer 3C: VWAP reclaim with bullish trend'
        elif ema_slope['ema_slope'].iloc[idx] < -EMA_SLOPE_THRESHOLD:
            return 'sell', row['close'], 'Layer 3C: VWAP reclaim with bearish trend'
    
    return 'none', 0, 'No signal (all layers checked)'

# =========================================================
# BACKTEST ENGINE
# =========================================================

def backtest_boof19(symbol, start_date, end_date):
    """Run backtest for Boof 19.0"""
    print(f"\n{'='*60}")
    print(f"BOOF 19.0 BACKTEST: {symbol}")
    print(f"{'='*60}")
    
    # Get credentials
    creds = get_alpaca_credentials()
    
    # Fetch data
    df = fetch_alpaca_bars(symbol, start_date, end_date, TIMEFRAME, api_key=creds['api_key'], secret_key=creds['secret_key'])
    if df is None or len(df) < 100:
        print(f"Insufficient data for {symbol}")
        return None
    
    print(f"Fetched {len(df)} candles")
    
    # Calculate indicators
    df['date'] = df.index.date
    
    # Calculate ORB
    or_high, or_low, or_range = calculate_or(df, OR_MINUTES)
    avg_orb_range = calculate_avg_orb_range(df, or_range, 20)
    
    # Calculate compression
    df = detect_compression(df, COMPRESSION_LOOKBACK, COMPRESSION_THRESHOLD)
    
    # Calculate ORB breakout
    df = detect_orb_breakout(df, or_high, or_low, threshold=0.002)
    
    # Calculate continuation signals
    df = detect_pullback_continuation(df, EMA9_PERIOD, PULLBACK_THRESHOLD, REJECTION_BODY_RATIO)
    df = detect_recompression_break(df, RECOMPRESSION_ATR_THRESHOLD, RECOMPRESSION_LOOKBACK)
    df = detect_vwap_reclaim(df, VWAP_RECLAIM_THRESHOLD, VWAP_LOSS_THRESHOLD)
    
    # Generate signals
    signals = []
    for idx in range(len(df)):
        signal, price, reason = generate_signal(df, idx, or_high, or_low, or_range, avg_orb_range)
        if signal != 'none':
            signals.append({
                'timestamp': df.index[idx],
                'signal': signal,
                'price': price,
                'reason': reason
            })
    
    print(f"Generated {len(signals)} signals")
    
    # Simulate trades - check exit conditions on every candle
    trades = []
    entry_time = None
    entry_price = None
    direction = None
    
    # Create a signal lookup map
    signal_map = {sig['timestamp']: sig for sig in signals}
    
    for idx in range(len(df)):
        candle_time = df.index[idx]
        candle_price = df.iloc[idx]['close']
        
        # Check if we should enter a trade
        if entry_time is None and candle_time in signal_map:
            sig = signal_map[candle_time]
            if sig['signal'] != 'none':
                entry_time = candle_time
                entry_price = sig['price']
                direction = sig['signal']
                continue
        
        # Check exit conditions if in a trade
        if entry_time is not None:
            hold_minutes = (candle_time - entry_time).total_seconds() / 60
            
            exit_reason = None
            exit_price = candle_price
            
            # Calculate underlying move
            underlying_move = (exit_price - entry_price) / entry_price
            
            # Calculate VWAP for stop loss
            vwap_values = vwap(df)
            current_vwap = vwap_values.iloc[idx]
            vwap_distance = (exit_price - current_vwap) / current_vwap
            
            # Calculate ATR for dynamic exits
            atr_values = atr(df, 14)
            current_atr = atr_values.iloc[idx]
            
            # Time exit (Priority #4 - reduced hold time)
            if hold_minutes >= MAX_HOLD_MINUTES:
                exit_reason = f'Time exit ({hold_minutes:.1f} min)'
            # Underlying-based take profit (Priority #3)
            elif direction == 'buy' and underlying_move >= UNDERLYING_TP_PCT:
                exit_reason = f'Underlying TP ({underlying_move * 100:.2f}%)'
            elif direction == 'sell' and abs(underlying_move) >= UNDERLYING_TP_PCT:
                exit_reason = f'Underlying TP ({abs(underlying_move) * 100:.2f}%)'
            # Underlying-based stop loss (Priority #3)
            elif direction == 'buy' and underlying_move <= UNDERLYING_SL_PCT:
                exit_reason = f'Underlying SL ({underlying_move * 100:.2f}%)'
            elif direction == 'sell' and abs(underlying_move) <= abs(UNDERLYING_SL_PCT):
                exit_reason = f'Underlying SL ({abs(underlying_move) * 100:.2f}%)'
            # VWAP stop loss (Priority #3)
            elif VWAP_STOP_LOSS and direction == 'buy' and vwap_distance < 0:
                exit_reason = f'VWAP SL (below VWAP)'
            elif VWAP_STOP_LOSS and direction == 'sell' and vwap_distance > 0:
                exit_reason = f'VWAP SL (above VWAP)'
            # ATR-based take profit (Priority #2)
            elif direction == 'buy' and underlying_move >= (current_atr / entry_price) * ATR_TP_MULTIPLIER:
                exit_reason = f'ATR TP ({(current_atr / entry_price) * ATR_TP_MULTIPLIER * 100:.2f}%)'
            elif direction == 'sell' and abs(underlying_move) >= (current_atr / entry_price) * ATR_TP_MULTIPLIER:
                exit_reason = f'ATR TP ({(current_atr / entry_price) * ATR_TP_MULTIPLIER * 100:.2f}%)'
            # ATR-based stop loss (Priority #2)
            elif direction == 'buy' and underlying_move <= -(current_atr / entry_price) * ATR_SL_MULTIPLIER:
                exit_reason = f'ATR SL ({-(current_atr / entry_price) * ATR_SL_MULTIPLIER * 100:.2f}%)'
            elif direction == 'sell' and abs(underlying_move) <= (current_atr / entry_price) * ATR_SL_MULTIPLIER:
                exit_reason = f'ATR SL ({(current_atr / entry_price) * ATR_SL_MULTIPLIER * 100:.2f}%)'
            # Fast stop recognition (Priority #4)
            elif hold_minutes >= FAST_STOP_MINUTES and abs(underlying_move) < 0.0005:
                exit_reason = f'Fast stop (no momentum after {hold_minutes:.1f} min)'
            
            if exit_reason:
                # Simulate option trade with realistic costs (Priority #1)
                option_result = simulate_option_trade(entry_price, exit_price, direction, hold_minutes)
                
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': candle_time,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'direction': direction,
                    'underlying_pnl': underlying_move,  # Track underlying move for analysis
                    'option_pnl': option_result['option_pnl'],  # Use option PnL with costs
                    'entry_option_price': option_result['entry_option_price'],
                    'exit_option_price': option_result['exit_option_price'],
                    'entry_delta': option_result['entry_delta'],
                    'exit_delta': option_result['exit_delta'],
                    'theta_decay': option_result['theta_decay'],
                    'strike': option_result['strike'],
                    'hold_minutes': hold_minutes,
                    'exit_reason': exit_reason
                })
                entry_time = None
                entry_price = None
                direction = None
    
    # Close any remaining trade
    if entry_time is not None:
        exit_price = df.iloc[-1]['close']
        hold_minutes = (df.index[-1] - entry_time).total_seconds() / 60
        underlying_move = (exit_price - entry_price) / entry_price
        
        # Simulate option trade with realistic costs
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
            'exit_reason': 'End of data'
        })
    
    # Calculate statistics
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
    
    # Calculate drawdown
    cumulative = np.cumsum([t['option_pnl'] for t in trades])
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (running_max - cumulative) / (running_max + 1e-6)
    max_drawdown = drawdown.max() if len(drawdown) > 0 else 0
    
    # Calculate average theta decay
    avg_theta = sum(t['theta_decay'] for t in trades) / total_trades if total_trades > 0 else 0
    
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

# =========================================================
# MAIN
# =========================================================

if __name__ == '__main__':
    # Backtest for last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    results = []
    for symbol in SYMBOLS:
        result = backtest_boof19(symbol, start_date, end_date)
        if result:
            results.append(result)
    
    # Summary
    if results:
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        for r in results:
            print(f"{r['symbol']}: {r['total_trades']} trades, {r['win_rate']*100:.1f}% win rate, {r['total_pnl']*100:.1f}% total PnL")
