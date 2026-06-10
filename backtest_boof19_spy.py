import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

# =========================================================
# SPY 19.0 - MEAN REVERSION ENGINE
# =========================================================

SPY_PROFILE = {
  "mode": "mean_reversion",
  "orbBreakoutPct": 0.003,        # 0.3% (balanced)
  "liquidityGrabPct": 0.003,     # 0.3% (balanced)
  "vwapDistance": 0.01,           # 1.0% (balanced)
  "allowFadeBreakouts": True,
  "requireReversionSignal": True,
  "takeProfitPct": 0.25,          # 25% (increased)
  "stopLossPct": -0.10,           # -10% (tighter)
  "maxHoldMin": 10,               # 10 min (longer)
  "maxTradesPerDay": 10,
  "requireChopRegime": True,      # Re-enabled for quality
  "trendTradesAllowed": False,
  "name": "SPY_CHOP_ENGINE"
}

# =========================================================
# PARAMETERS
# =========================================================

SYMBOL = 'SPY'
TIMEFRAME = '1m'

# Regime Detection
VWAP_SLOPE_STRONG = 0.0001
VWAP_SLOPE_FLAT = 0.00002
EMA9_PERIOD = 9
EMA21_PERIOD = 21
EMA_SPREAD_EXPANDING = 0.0005
EMA_SPREAD_COMPRESSING = 0.0001
ADX_PROXY_PERIOD = 14
ADX_PROXY_HIGH = 0.002
ADX_PROXY_LOW = 0.0005
HTF_VWAP_DISTANCE = 0.001

# Dynamic TP
TP_CHOP = SPY_PROFILE["takeProfitPct"]
TP_TREND = SPY_PROFILE["takeProfitPct"]

# Multi-Candle Acceptance
CONTINUATION_CANDLES = 0
CONTINUATION_THRESHOLD = 0.0001

# Structural Levels
USE_PREV_DAY_LEVELS = True
USE_PREMARKET_LEVELS = True
USE_OVERNIGHT_MIDPOINT = True

# Distance Filters
MAX_DISTANCE_FROM_VWAP = SPY_PROFILE["vwapDistance"]
MAX_DISTANCE_FROM_EMA = 0.012
MAX_DISTANCE_FROM_ORB = 0.025

# Reversal Logic
FAILED_BREAKDOWN_THRESHOLD = SPY_PROFILE["liquidityGrabPct"]
FAILED_BREAKOUT_THRESHOLD = SPY_PROFILE["liquidityGrabPct"]
LIQUIDITY_GRAB_THRESHOLD = SPY_PROFILE["liquidityGrabPct"]
VWAP_RECLAIM_REVERSAL = True

# Exit Engine
UNDERLYING_TP_PCT = SPY_PROFILE["takeProfitPct"]
UNDERLYING_SL_PCT = SPY_PROFILE["stopLossPct"]
VWAP_STOP_LOSS = True
ATR_TP_MULTIPLIER = 0.5
ATR_SL_MULTIPLIER = 0.3
MAX_HOLD_MINUTES = SPY_PROFILE["maxHoldMin"]
FAST_STOP_MINUTES = 2

# Options Parameters
EXPIRATION = "0DTE"
DELTA_MIN = 0.45
DELTA_MAX = 0.60

# Realism Layer (disabled)
SLIPPAGE_PCT = 0.0
BID_ASK_SPREAD_PCT = 0.0
THETA_DECAY_PER_MINUTE = 0.0002

# Trade Windows (US Eastern time - assuming data is in ET)
TRADE_WINDOWS = [
    ("09:30", "16:00"),  # Regular session
]

# Session Behavior
SESSION_OPEN_END = "10:00"
SESSION_MIDDAY_END = "15:00"
SESSION_OPEN_TP_MULTIPLIER = 1.5
SESSION_OPEN_SL_MULTIPLIER = 0.8
SESSION_MIDDAY_TP_MULTIPLIER = 1.0
SESSION_MIDDAY_SL_MULTIPLIER = 1.2
SESSION_POWER_TP_MULTIPLIER = 1.3
SESSION_POWER_SL_MULTIPLIER = 0.9

# =========================================================
# DATA FETCHING
# =========================================================

def fetch_data(symbol, start_date, end_date):
    """Fetch 1-minute data from yfinance"""
    ticker = yf.Ticker(symbol)
    data = ticker.history(start=start_date, end=end_date, interval=TIMEFRAME)
    return data

# =========================================================
# INDICATORS
# =========================================================

def vwap(df):
    """Calculate VWAP"""
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    cumulative_volume = df['Volume'].cumsum()
    cumulative_tp_volume = (typical_price * df['Volume']).cumsum()
    vwap = cumulative_tp_volume / cumulative_volume
    return vwap

def ema(data, period):
    """Calculate EMA"""
    return data.ewm(span=period, adjust=False).mean()

def atr(df, period=14):
    """Calculate ATR"""
    high_low = df['High'] - df['Low']
    high_close = abs(df['High'] - df['Close'].shift())
    low_close = abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

# =========================================================
# REGIME DETECTION
# =========================================================

def detect_regime(df, idx):
    if idx < 30:
        return 'chop', 0, 'Not enough data'
    
    trend_score = 0
    
    # VWAP slope
    vwap_values = vwap(df)
    vwap_slope = (vwap_values.iloc[idx] - vwap_values.iloc[idx - 10]) / vwap_values.iloc[idx - 10]
    if abs(vwap_slope) >= VWAP_SLOPE_STRONG:
        trend_score += 30
    elif abs(vwap_slope) <= VWAP_SLOPE_FLAT:
        trend_score -= 10
    
    # EMA separation
    ema9_values = ema(df['Close'], EMA9_PERIOD)
    ema21_values = ema(df['Close'], EMA21_PERIOD)
    ema_spread = abs(ema9_values.iloc[idx] - ema21_values.iloc[idx]) / ema21_values.iloc[idx]
    ema_spread_prev = abs(ema9_values.iloc[idx - 5] - ema21_values.iloc[idx - 5]) / ema21_values.iloc[idx - 5]
    if ema_spread > ema_spread_prev * 1.1 and ema_spread > EMA_SPREAD_EXPANDING:
        trend_score += 25
    elif ema_spread < EMA_SPREAD_COMPRESSING:
        trend_score -= 10
    
    # ADX proxy
    total_move = 0
    total_range = 0
    for i in range(idx - ADX_PROXY_PERIOD, idx):
        if i >= 0:
            total_move += abs(df.iloc[i]['Close'] - df.iloc[i]['Open'])
            total_range += df.iloc[i]['High'] - df.iloc[i]['Low']
    adx_proxy = total_move / total_range if total_range > 0 else 0
    if adx_proxy >= ADX_PROXY_HIGH:
        trend_score += 25
    elif adx_proxy <= ADX_PROXY_LOW:
        trend_score -= 10
    
    # HTF alignment
    price_vs_vwap = (df.iloc[idx]['Close'] - vwap_values.iloc[idx]) / vwap_values.iloc[idx]
    ema9_slope = (ema9_values.iloc[idx] - ema9_values.iloc[idx - 5]) / ema9_values.iloc[idx - 5]
    if price_vs_vwap > HTF_VWAP_DISTANCE and ema9_slope > 0:
        trend_score += 20
    elif price_vs_vwap < -HTF_VWAP_DISTANCE and ema9_slope < 0:
        trend_score += 20
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
# STRUCTURAL LEVELS
# =========================================================

def calculate_structural_levels(df, idx):
    """Calculate key structural levels"""
    if idx < 30:
        return {'prev_high': df.iloc[idx]['High'], 'prev_low': df.iloc[idx]['Low'], 'or_high': df.iloc[idx]['High'], 'or_low': df.iloc[idx]['Low']}
    
    # Previous day high/low
    prev_day = df.iloc[idx-30:idx]
    prev_high = prev_day['High'].max()
    prev_low = prev_day['Low'].min()
    
    # Opening range (first 30 candles = 30 minutes)
    or_candles = df.iloc[max(0, idx-30):idx]
    or_high = or_candles['High'].max()
    or_low = or_candles['Low'].min()
    
    return {
        'prev_high': prev_high,
        'prev_low': prev_low,
        'or_high': or_high,
        'or_low': or_low
    }

# =========================================================
# DISTANCE FILTERS
# =========================================================

def check_distance_filters(df, idx, levels):
    """Check if price is too far from key levels"""
    current_price = df.iloc[idx]['Close']
    vwap_values = vwap(df)
    current_vwap = vwap_values.iloc[idx]
    
    # Distance from VWAP
    vwap_distance = abs(current_price - current_vwap) / current_vwap
    if vwap_distance > MAX_DISTANCE_FROM_VWAP:
        return False, f"Too far from VWAP ({vwap_distance*100:.2f}%)"
    
    # Distance from ORB
    or_distance = abs(current_price - levels['or_high']) / levels['or_high']
    if or_distance > MAX_DISTANCE_FROM_ORB:
        return False, f"Too far from ORB ({or_distance*100:.2f}%)"
    
    return True, "Distance filters passed"

# =========================================================
# MULTI-CANDLE ACCEPTANCE
# =========================================================

def check_multi_candle_continuation(df, idx, direction, num_candles=0, threshold=0.0001):
    if num_candles == 0:
        return True
    
    if idx < num_candles:
        return False
    
    for i in range(1, num_candles + 1):
        candle = df.iloc[idx - i]
        prev_candle = df.iloc[idx - i - 1]
        
        if direction == 'buy':
            if candle['Close'] <= prev_candle['Close']:
                return False
            if (candle['Close'] - prev_candle['Close']) / prev_candle['Close'] < threshold:
                return False
        else:
            if candle['Close'] >= prev_candle['Close']:
                return False
            if (prev_candle['Close'] - candle['Close']) / prev_candle['Close'] < threshold:
                return False
    
    return True

# =========================================================
# REVERSAL DETECTION
# =========================================================

def detect_failed_breakdown(df, idx, level):
    """Detect failed breakdown (dip below level then reclaim)"""
    if idx < 5:
        return False
    
    recent_low = df.iloc[idx-5:idx]['Low'].min()
    if recent_low < level * (1 - FAILED_BREAKDOWN_THRESHOLD):
        if df.iloc[idx]['Close'] > level:
            return True
    return False

def detect_failed_breakout(df, idx, level):
    """Detect failed breakout (break above level then reject)"""
    if idx < 5:
        return False
    
    recent_high = df.iloc[idx-5:idx]['High'].max()
    if recent_high > level * (1 + FAILED_BREAKOUT_THRESHOLD):
        if df.iloc[idx]['Close'] < level:
            return True
    return False

def detect_liquidity_grab(df, idx, level):
    """Detect liquidity grab (wick through level then close back)"""
    if idx < 3:
        return False
    
    if df.iloc[idx-1]['High'] > level * (1 + LIQUIDITY_GRAB_THRESHOLD):
        if df.iloc[idx]['Close'] < level:
            return True
    
    if df.iloc[idx-1]['Low'] < level * (1 - LIQUIDITY_GRAB_THRESHOLD):
        if df.iloc[idx]['Close'] > level:
            return True
    
    return False

# =========================================================
# TRADE WINDOW
# =========================================================

def is_in_trade_window(timestamp):
    """Check if timestamp is within trade window"""
    time_str = timestamp.strftime("%H:%M")
    
    for start, end in TRADE_WINDOWS:
        start_minutes = int(start.split(":")[0]) * 60 + int(start.split(":")[1])
        end_minutes = int(end.split(":")[0]) * 60 + int(end.split(":")[1])
        time_minutes = int(time_str.split(":")[0]) * 60 + int(time_str.split(":")[1])
        
        if start_minutes <= time_minutes < end_minutes:
            return True
    
    return False

# =========================================================
# OPTIONS SIMULATION
# =========================================================

def apply_realism(price, direction, is_entry=True):
    """Apply slippage and spread (disabled for SPY)"""
    return price

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
    """Simulate option trade"""
    strike = round(entry_underlying / 0.5) * 0.5
    entry_delta = calculate_delta(entry_underlying, strike, 0, iv)
    entry_option_mid = calculate_option_price(entry_underlying, strike, entry_delta, 0, iv)
    entry_price = apply_realism(entry_option_mid, direction, is_entry=True)
    
    exit_delta = calculate_delta(exit_underlying, strike, 0, iv)
    exit_option_mid = calculate_option_price(exit_underlying, strike, exit_delta, 0, iv)
    theta_decay = exit_option_mid * THETA_DECAY_PER_MINUTE * hold_minutes
    exit_option_mid -= theta_decay
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
# SIGNAL GENERATION
# =========================================================

def generate_signal(df, idx):
    """Generate mean reversion signals for SPY"""
    if idx < 50:
        return 'none', 0, 'Not enough data', 'chop'
    
    row = df.iloc[idx]
    
    if not is_in_trade_window(df.index[idx]):
        return 'none', 0, 'Outside trade window', 'chop'
    
    # Detect regime
    regime, trend_score, regime_reason = detect_regime(df, idx)
    
    # SPY: Only trade in chop
    if SPY_PROFILE["requireChopRegime"] and regime != 'chop':
        return 'none', 0, f'Filter: {regime} regime (chop only)', regime
    
    # Calculate structural levels
    levels = calculate_structural_levels(df, idx)
    
    # Distance Filters
    distance_ok, distance_reason = check_distance_filters(df, idx, levels)
    if not distance_ok:
        return 'none', 0, distance_reason, regime
    
    # Reversal-Based Logic
    vwap_values = vwap(df)
    current_vwap = vwap_values.iloc[idx]
    
    # Failed breakdown reversal (long)
    if detect_failed_breakdown(df, idx, levels['prev_low']):
        if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'buy', row['Close'], f'Failed breakdown reversal (prev low) - {regime}', regime
    
    # Failed breakout reversal (short)
    if detect_failed_breakout(df, idx, levels['prev_high']):
        if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'sell', row['Close'], f'Failed breakout reversal (prev high) - {regime}', regime
    
    # Liquidity grab reversal
    if detect_liquidity_grab(df, idx, levels['or_high']):
        if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'sell', row['Close'], f'Liquidity grab reversal (OR high) - {regime}', regime
    
    if detect_liquidity_grab(df, idx, levels['or_low']):
        if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'buy', row['Close'], f'Liquidity grab reversal (OR low) - {regime}', regime
    
    # VWAP reclaim reversal
    if VWAP_RECLAIM_REVERSAL:
        vwap_distance = (row['Close'] - current_vwap) / current_vwap
        if abs(vwap_distance) < 0.001 and vwap_distance > 0:
            if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
                return 'buy', row['Close'], f'VWAP reclaim reversal - {regime}', regime
        elif abs(vwap_distance) < 0.001 and vwap_distance < 0:
            if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
                return 'sell', row['Close'], f'VWAP reclaim reversal - {regime}', regime
    
    # ORB breakout with continuation (SPY tight threshold)
    if row['Close'] > levels['or_high'] * (1 + SPY_PROFILE["orbBreakoutPct"]):
        if check_multi_candle_continuation(df, idx, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'buy', row['Close'], f'OR breakout - {regime}', regime
    
    if row['Close'] < levels['or_low'] * (1 - SPY_PROFILE["orbBreakoutPct"]):
        if check_multi_candle_continuation(df, idx, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD):
            return 'sell', row['Close'], f'OR breakdown - {regime}', regime
    
    return 'none', 0, 'No high-quality setup', regime

# =========================================================
# BACKTEST ENGINE
# =========================================================

def backtest_spy19(symbol, start_date, end_date):
    """Run SPY 19.0 backtest"""
    print(f"\n{'='*50}")
    print(f"BOOF 19.0 SPY: {SPY_PROFILE['name']}")
    print(f"{'='*50}\n")
    
    df = fetch_data(symbol, start_date, end_date)
    print(f"Fetched {len(df)} candles")
    
    # Generate signals
    signals = []
    for idx in range(len(df)):
        signal, price, reason, regime = generate_signal(df, idx)
        if signal != 'none':
            signals.append({
                'timestamp': df.index[idx],
                'signal': signal,
                'price': price,
                'reason': reason,
                'regime': regime
            })
    
    print(f"Generated {len(signals)} signals")
    
    # Simulate trades
    trades = []
    entry_time = None
    entry_price = None
    direction = None
    entry_regime = None
    signal_map = {sig['timestamp']: sig for sig in signals}
    
    for idx in range(len(df)):
        candle_time = df.index[idx]
        candle_price = df.iloc[idx]['Close']
        
        # Check for new signal
        if entry_time is None and candle_time in signal_map:
            sig = signal_map[candle_time]
            if sig['signal'] != 'none':
                entry_time = candle_time
                entry_price = candle_price
                direction = sig['signal']
                entry_regime = sig['regime']
                continue
        
        if entry_time is not None:
            hold_minutes = (candle_time - entry_time).total_seconds() / 60
            exit_reason = None
            exit_price = candle_price
            underlying_move = (exit_price - entry_price) / entry_price
            
            # Dynamic TP based on regime
            dynamic_tp = TP_CHOP
            
            # TP/SL exit
            if direction == 'buy':
                if underlying_move >= dynamic_tp:
                    exit_reason = f'TP hit ({underlying_move*100:.2f}%)'
                elif underlying_move <= UNDERLYING_SL_PCT:
                    exit_reason = f'SL hit ({underlying_move*100:.2f}%)'
            else:
                if underlying_move <= -dynamic_tp:
                    exit_reason = f'TP hit ({underlying_move*100:.2f}%)'
                elif underlying_move >= -UNDERLYING_SL_PCT:
                    exit_reason = f'SL hit ({underlying_move*100:.2f}%)'
            
            # Time exit
            if hold_minutes >= MAX_HOLD_MINUTES:
                exit_reason = f'Time exit ({hold_minutes:.1f} min)'
            
            # VWAP stop loss
            if VWAP_STOP_LOSS and exit_reason is None:
                vwap_values = vwap(df)
                current_vwap = vwap_values.iloc[idx]
                if direction == 'buy' and candle_price < current_vwap:
                    exit_reason = 'VWAP stop loss'
                elif direction == 'sell' and candle_price > current_vwap:
                    exit_reason = 'VWAP stop loss'
            
            if exit_reason:
                trade_result = simulate_option_trade(entry_price, exit_price, direction, hold_minutes)
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': candle_time,
                    'direction': direction,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'underlying_move': underlying_move,
                    'hold_minutes': hold_minutes,
                    'exit_reason': exit_reason,
                    'option_pnl': trade_result['option_pnl'],
                    'entry_option_price': trade_result['entry_option_price'],
                    'exit_option_price': trade_result['exit_option_price'],
                    'theta_decay': trade_result['theta_decay'],
                    'regime': entry_regime
                })
                entry_time = None
                entry_price = None
                direction = None
                entry_regime = None
    
    # Close remaining trade at end
    if entry_time is not None:
        exit_price = df.iloc[-1]['Close']
        hold_minutes = (df.index[-1] - entry_time).total_seconds() / 60
        underlying_move = (exit_price - entry_price) / entry_price
        trade_result = simulate_option_trade(entry_price, exit_price, direction, hold_minutes)
        trades.append({
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'underlying_move': underlying_move,
            'hold_minutes': hold_minutes,
            'exit_reason': 'End of data',
            'option_pnl': trade_result['option_pnl'],
            'entry_option_price': trade_result['entry_option_price'],
            'exit_option_price': trade_result['exit_option_price'],
            'theta_decay': trade_result['theta_decay'],
            'regime': entry_regime
        })
    
    # Calculate results
    if not trades:
        print("No trades executed")
        return
    
    winning_trades = [t for t in trades if t['option_pnl'] > 0]
    losing_trades = [t for t in trades if t['option_pnl'] <= 0]
    
    total_pnl = sum(t['option_pnl'] for t in trades)
    avg_pnl = total_pnl / len(trades) if trades else 0
    avg_hold = sum(t['hold_minutes'] for t in trades) / len(trades) if trades else 0
    avg_theta = sum(t['theta_decay'] for t in trades) / len(trades) if trades else 0
    avg_underlying_move = sum(t['underlying_move'] for t in trades) / len(trades) if trades else 0
    
    max_profit = max(t['option_pnl'] for t in trades) if trades else 0
    max_loss = min(t['option_pnl'] for t in trades) if trades else 0
    
    # Calculate drawdown
    cumulative_pnl = []
    running_pnl = 0
    for t in trades:
        running_pnl += t['option_pnl']
        cumulative_pnl.append(running_pnl)
    
    if cumulative_pnl:
        peak = max(cumulative_pnl)
        trough = min(cumulative_pnl)
        max_drawdown = (trough - peak) / peak if peak != 0 else 0
    else:
        max_drawdown = 0
    
    # Regime breakdown
    trend_trades = [t for t in trades if t['regime'] in ['strong_trend', 'weak_trend']]
    chop_trades = [t for t in trades if t['regime'] == 'chop']
    
    trend_pnl = sum(t['option_pnl'] for t in trend_trades)
    chop_pnl = sum(t['option_pnl'] for t in chop_trades)
    
    print(f"\n{'='*50}")
    print(f"RESULTS: {symbol}")
    print(f"{'='*50}")
    print(f"Total Trades: {len(trades)}")
    print(f"Winning Trades: {len(winning_trades)}")
    print(f"Losing Trades: {len(losing_trades)}")
    print(f"Win Rate: {len(winning_trades)/len(trades)*100:.1f}%")
    print(f"Total Option PnL: {total_pnl*100:.1f}%")
    print(f"Avg Option PnL per Trade: {avg_pnl*100:.2f}%")
    print(f"Avg Underlying Move: {avg_underlying_move*100:.2f}%")
    print(f"Avg Hold Time: {avg_hold:.1f} minutes")
    print(f"Avg Theta Decay: ${avg_theta:.3f}")
    print(f"Max Profit: {max_profit*100:.1f}%")
    print(f"Max Loss: {max_loss*100:.1f}%")
    print(f"Max Drawdown: {max_drawdown*100:.1f}%")
    print(f"\nRegime Breakdown:")
    print(f"  Trend Trades: {len(trend_trades)} (PnL: {trend_pnl*100:.1f}%)")
    print(f"  Chop Trades: {len(chop_trades)} (PnL: {chop_pnl*100:.1f}%)")
    print(f"{'='*50}\n")

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    end_date = datetime.now(pytz.UTC)
    start_date = end_date - timedelta(days=7)  # 7 days for 1m data limit
    
    backtest_spy19(SYMBOL, start_date, end_date)
