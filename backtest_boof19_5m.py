import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, ema, vwap, atr, get_alpaca_credentials

# =========================================================
# BOOF 19.0 - 0DTE SCALPING FOR SPY/QQQ (5-MINUTE VERSION)
# Event-Driven High-Quality System
# =========================================================

# Target symbols
# =========================================================
# SYMBOL-SPECIFIC PROFILES (5-MINUTE TUNED)
# =========================================================

SPY_PROFILE = {
  "mode": "mean_reversion",
  "orbBreakoutPct": 0.005,        # 0.5% (adjusted for 5m)
  "liquidityGrabPct": 0.005,     # 0.5% (adjusted for 5m)
  "vwapDistance": 0.02,           # 2.0% (adjusted for 5m)
  "takeProfitPct": 0.20,          # 20%
  "stopLossPct": -0.10,           # -10%
  "maxHoldMin": 30,               # 30 min (6 candles on 5m)
  "requireChopRegime": True,
  "trendTradesAllowed": False,
  "name": "SPY_CHOP_ENGINE_5M",
  "exitLogic": "quick_scalp"
}

QQQ_PROFILE = {
  "mode": "mean_reversion",
  "orbBreakoutPct": 0.004,        # 0.4% (adjusted for 5m)
  "liquidityGrabPct": 0.004,     # 0.4% (adjusted for 5m)
  "vwapDistance": 0.025,          # 2.5% (adjusted for 5m)
  "takeProfitPct": 0.20,          # 20%
  "stopLossPct": -0.10,           # -10%
  "maxHoldMin": 30,               # 30 min (6 candles on 5m)
  "requireChopRegime": True,
  "trendTradesAllowed": False,
  "name": "QQQ_CHOP_ENGINE_5M",
  "exitLogic": "quick_scalp"
}

def get_profile(symbol):
    return SPY_PROFILE if symbol == 'SPY' else QQQ_PROFILE

SYMBOLS = ['SPY', 'QQQ']
TIMEFRAME = '5Min'

# =========================================================
# REGIME DETECTION (Chop vs Trend)
# =========================================================

# VWAP slope threshold (adjusted for 5m)
VWAP_SLOPE_STRONG = 0.0002  # Adjusted for 5m
VWAP_SLOPE_FLAT = 0.00005   # Adjusted for 5m

# EMA separation
EMA9_PERIOD = 9
EMA21_PERIOD = 21
EMA_SPREAD_EXPANDING = 0.001  # Adjusted for 5m
EMA_SPREAD_COMPRESSING = 0.0002  # Adjusted for 5m

# ADX proxy
ADX_PROXY_PERIOD = 14
ADX_PROXY_HIGH = 0.003  # Adjusted for 5m
ADX_PROXY_LOW = 0.001  # Adjusted for 5m

# Higher timeframe alignment
HTF_VWAP_DISTANCE = 0.002  # Adjusted for 5m

# Dynamic TP based on regime
TP_CHOP = 0.20  # 20% TP in chop
TP_TREND = 0.20  # Same as chop since we only trade chop

# =========================================================
# MULTI-CANDLE ACCEPTANCE
# =========================================================

CONTINUATION_CANDLES = 0  # No continuation requirement
CONTINUATION_THRESHOLD = 0.0002  # Adjusted for 5m

# =========================================================
# STRUCTURAL LEVELS
# =========================================================

USE_PREV_DAY_LEVELS = True
USE_PREMARKET_LEVELS = True
USE_OVERNIGHT_MIDPOINT = True

# =========================================================
# DISTANCE FILTERS
# =========================================================

MAX_DISTANCE_FROM_VWAP = 0.02  # Adjusted for 5m
MAX_DISTANCE_FROM_EMA = 0.015  # Adjusted for 5m
MAX_DISTANCE_FROM_ORB = 0.03  # Adjusted for 5m

# =========================================================
# SESSION-AWARE BEHAVIOR
# =========================================================

# Trading windows (in minutes from 9:30 AM)
MARKET_OPEN_MIN = 0
MARKET_CLOSE_MIN = 390  # 4:00 PM

# Early session (9:30-11:00 AM)
EARLY_SESSION_START = 0
EARLY_SESSION_END = 90

# Mid session (11:00 AM-1:00 PM)
MID_SESSION_START = 90
MID_SESSION_END = 210

# Late session (1:00 PM-3:00 PM)
LATE_SESSION_START = 210
LATE_SESSION_END = 330

# Power hour (3:00 PM-4:00 PM)
POWER_HOUR_START = 330
POWER_HOUR_END = 390

# =========================================================
# EXIT LOGIC
# =========================================================

MAX_HOLD_MINUTES = 30  # 30 min for 5m
FAST_STOP_MINUTES = 10  # 10 min for 5m

# Theta decay (adjusted for 5m - less per minute but longer holds)
THETA_DECAY_PER_MINUTE = 0.00015  # 0.015% per minute

# =========================================================
# VWAP RECLAIM REVERSAL
# =========================================================

VWAP_RECLAIM_REVERSAL = True

# =========================================================
# STRUCTURAL LEVEL CALCULATION (5-MINUTE VERSION)
# =========================================================

def calculate_structural_levels_5m(df, idx):
    """Calculate structural levels adapted for 5-minute data"""
    row = df.iloc[idx]
    timestamp = df.index[idx]
    
    # Time in minutes from 9:30 AM
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute - 570  # 9:30 AM = 570 minutes
    
    # Previous day high/low (use first 6 candles of day)
    day_start_idx = max(0, idx - int(time_minutes / 5))
    if day_start_idx < idx:
        prev_day_high = df.iloc[day_start_idx:idx]['high'].max()
        prev_day_low = df.iloc[day_start_idx:idx]['low'].min()
    else:
        prev_day_high = row['high']
        prev_day_low = row['low']
    
    # Premarket levels (first 6 candles = 30 minutes)
    premarket_end_idx = min(idx, 6)
    if premarket_end_idx > 0:
        premarket_high = df.iloc[0:premarket_end_idx]['high'].max()
        premarket_low = df.iloc[0:premarket_end_idx]['low'].min()
    else:
        premarket_high = row['high']
        premarket_low = row['low']
    
    # ORB (Opening Range Breakout) - first 6 candles (30 minutes)
    orb_end_idx = min(idx, 6)
    if orb_end_idx > 0:
        or_high = df.iloc[0:orb_end_idx]['high'].max()
        or_low = df.iloc[0:orb_end_idx]['low'].min()
    else:
        or_high = row['high']
        or_low = row['low']
    
    # Overnight midpoint
    overnight_midpoint = (prev_day_high + prev_day_low) / 2
    
    return {
        'prev_high': prev_day_high,
        'prev_low': prev_day_low,
        'premarket_high': premarket_high,
        'premarket_low': premarket_low,
        'or_high': or_high,
        'or_low': or_low,
        'overnight_midpoint': overnight_midpoint
    }

# =========================================================
# REGIME DETECTION
# =========================================================

def detect_regime(df, idx):
    """Detect if market is in chop or trend regime"""
    if idx < 21:
        return 'chop'
    
    vwap_values = vwap(df)
    ema9_values = ema(df, EMA9_PERIOD)
    ema21_values = ema(df, EMA21_PERIOD)
    
    # Use the same pattern as the working 1m version
    current_vwap = vwap_values.iloc[idx]
    current_ema9 = ema9_values.iloc[idx]
    current_ema21 = ema21_values.iloc[idx]
    
    # Ensure scalar values
    if hasattr(current_vwap, 'values'):
        current_vwap = current_vwap.values[0] if len(current_vwap.values) > 0 else current_vwap
    if hasattr(current_ema9, 'values'):
        current_ema9 = current_ema9.values[0] if len(current_ema9.values) > 0 else current_ema9
    if hasattr(current_ema21, 'values'):
        current_ema21 = current_ema21.values[0] if len(current_ema21.values) > 0 else current_ema21
    
    # VWAP slope
    if idx >= 5:
        vwap_slope = (vwap_values.iloc[idx] - vwap_values.iloc[idx-5]) / vwap_values.iloc[idx-5]
        if hasattr(vwap_slope, 'values'):
            vwap_slope = vwap_slope.values[0] if len(vwap_slope.values) > 0 else vwap_slope
    else:
        vwap_slope = 0
    
    # EMA spread - ensure scalar
    ema_spread = abs(current_ema9 - current_ema21) / current_ema21
    if hasattr(ema_spread, 'values'):
        ema_spread = ema_spread.values[0] if len(ema_spread.values) > 0 else ema_spread
    
    # ADX proxy (ATR-based)
    atr_values = atr(df, ADX_PROXY_PERIOD)
    current_atr = atr_values.iloc[idx] if idx >= ADX_PROXY_PERIOD else 0
    if hasattr(current_atr, 'values'):
        current_atr = current_atr.values[0] if len(current_atr.values) > 0 else current_atr
    adx_proxy = current_atr / df.iloc[idx]['close'] if df.iloc[idx]['close'] > 0 else 0
    
    # Regime determination
    if abs(vwap_slope) > VWAP_SLOPE_STRONG and ema_spread > EMA_SPREAD_EXPANDING:
        return 'strong_trend'
    elif abs(vwap_slope) > VWAP_SLOPE_FLAT and ema_spread > EMA_SPREAD_COMPRESSING:
        return 'weak_trend'
    else:
        return 'chop'

# =========================================================
# DISTANCE FILTERS
# =========================================================

def check_distance_filters(df, idx, levels, vwap_distance_threshold):
    """Check if price is too far from key levels"""
    row = df.iloc[idx]
    vwap_values = vwap(df)
    current_vwap = vwap_values.iloc[idx]
    
    vwap_distance = abs(row['close'] - current_vwap) / current_vwap
    
    if vwap_distance > MAX_DISTANCE_FROM_VWAP:
        return False, f"Too far from VWAP: {vwap_distance:.3f} > {MAX_DISTANCE_FROM_VWAP}"
    
    if vwap_distance > vwap_distance_threshold:
        return False, f"Beyond profile VWAP distance: {vwap_distance:.3f} > {vwap_distance_threshold}"
    
    return True, "Distance OK"

# =========================================================
# SIGNAL GENERATION
# =========================================================

def detect_failed_breakdown(df, idx, level, threshold):
    """Detect failed breakdown at key level"""
    if idx < 2:
        return False
    
    row = df.iloc[idx]
    prev_row = df.iloc[idx-1]
    
    # Price broke below level then reclaimed
    if prev_row['low'] < level * (1 - threshold) and row['close'] > level:
        return True
    
    return False

def detect_failed_breakout(df, idx, level, threshold):
    """Detect failed breakout at key level"""
    if idx < 2:
        return False
    
    row = df.iloc[idx]
    prev_row = df.iloc[idx-1]
    
    # Price broke above level then rejected
    if prev_row['high'] > level * (1 + threshold) and row['close'] < level:
        return True
    
    return False

def detect_liquidity_grab(df, idx, level, threshold):
    """Detect liquidity grab at key level"""
    if idx < 2:
        return False
    
    row = df.iloc[idx]
    prev_row = df.iloc[idx-1]
    
    # Price touched level then reversed
    if abs(prev_row['high'] - level) / level < threshold and row['close'] < level:
        return True
    if abs(prev_row['low'] - level) / level < threshold and row['close'] > level:
        return True
    
    return False

def check_multi_candle_continuation(df, idx, direction, num_candles, threshold):
    """Check for multi-candle continuation (disabled for 5m)"""
    return True  # Always true since CONTINUATION_CANDLES = 0

def generate_signal(df, idx, profile):
    """Generate trading signal based on 5-minute data"""
    if idx < 21:
        return 'none', 0, 'Insufficient data', 'chop'
    
    row = df.iloc[idx]
    timestamp = df.index[idx]
    
    # Time filter
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute - 570
    
    if time_minutes < MARKET_OPEN_MIN or time_minutes >= MARKET_CLOSE_MIN:
        return 'none', 0, 'Outside trading hours', 'chop'
    
    # Regime detection
    regime = detect_regime(df, idx)
    
    # Regime filter
    if profile["requireChopRegime"] and regime != 'chop':
        return 'none', 0, f'Filter: {regime} regime (chop only)', regime
    
    if not profile["trendTradesAllowed"] and regime in ['strong_trend', 'weak_trend']:
        return 'none', 0, f'Filter: {regime} regime (trend disabled)', regime
    
    # Calculate structural levels
    levels = calculate_structural_levels_5m(df, idx)
    
    # Distance Filters
    distance_ok, distance_reason = check_distance_filters(df, idx, levels, profile["vwapDistance"])
    if not distance_ok:
        return 'none', 0, distance_reason, regime
    
    # Reversal-Based Logic
    vwap_values = vwap(df)
    current_vwap = vwap_values.iloc[idx]
    
    # Failed breakdown reversal (long)
    if detect_failed_breakdown(df, idx, levels['prev_low'], profile["liquidityGrabPct"]):
        return 'buy', row['close'], f'Failed breakdown reversal - {regime}', regime
    
    # Failed breakout reversal (short)
    if detect_failed_breakout(df, idx, levels['prev_high'], profile["liquidityGrabPct"]):
        return 'sell', row['close'], f'Failed breakout reversal - {regime}', regime
    
    # Liquidity grab reversal
    if detect_liquidity_grab(df, idx, levels['or_high'], profile["liquidityGrabPct"]):
        return 'sell', row['close'], f'Liquidity grab reversal - {regime}', regime
    
    if detect_liquidity_grab(df, idx, levels['or_low'], profile["liquidityGrabPct"]):
        return 'buy', row['close'], f'Liquidity grab reversal - {regime}', regime
    
    # VWAP reclaim reversal
    if profile["mode"] == "mean_reversion" and VWAP_RECLAIM_REVERSAL:
        vwap_distance = (row['close'] - current_vwap) / current_vwap
        if abs(vwap_distance) < 0.002 and vwap_distance > 0:
            return 'buy', row['close'], f'VWAP reclaim reversal - {regime}', regime
        elif abs(vwap_distance) < 0.002 and vwap_distance < 0:
            return 'sell', row['close'], f'VWAP reclaim reversal - {regime}', regime
    
    # Structural level breakout
    if row['close'] > levels['or_high'] * (1 + profile["orbBreakoutPct"]):
        return 'buy', row['close'], f'OR breakout - {regime}', regime
    
    if row['close'] < levels['or_low'] * (1 - profile["orbBreakoutPct"]):
        return 'sell', row['close'], f'OR breakdown - {regime}', regime
    
    return 'none', 0, 'No signal', regime

# =========================================================
# OPTION SIMULATION
# =========================================================

def calculate_delta(underlying_price, strike, time_to_expiry, iv):
    """Simplified delta calculation"""
    if time_to_expiry <= 0:
        return 1.0 if underlying_price > strike else 0.0
    
    moneyness = (underlying_price - strike) / strike
    delta = 0.5 + 0.4 * moneyness / (iv * np.sqrt(time_to_expiry + 0.01))
    return max(0.0, min(1.0, delta))

def calculate_option_price(underlying_price, strike, delta, time_to_expiry, iv):
    """Simplified option price calculation"""
    intrinsic = max(0, underlying_price - strike)
    time_value = iv * underlying_price * np.sqrt(time_to_expiry + 0.01) * (1 - abs(delta - 0.5) * 0.5)
    return intrinsic + time_value

def apply_realism(option_price, direction, is_entry):
    """Apply slippage and spread"""
    spread = option_price * 0.02  # 2% spread
    slippage = option_price * 0.01  # 1% slippage
    
    if is_entry:
        if direction == 'buy':
            return option_price + spread/2 + slippage
        else:
            return option_price - spread/2 - slippage
    else:
        if direction == 'buy':
            return option_price - spread/2 - slippage
        else:
            return option_price + spread/2 + slippage

def simulate_option_trade(entry_underlying, exit_underlying, direction, hold_minutes, iv=0.2):
    """Simulate option trade with realism layer"""
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
# BACKTEST ENGINE
# =========================================================

def backtest_boof19_5m(symbol, start_date, end_date):
    """Run backtest for 5-minute data"""
    print(f"\n{'='*60}")
    print(f"BOOF 19.0 5-MINUTE BACKTEST: {symbol}")
    print(f"{'='*60}")
    
    credentials = get_alpaca_credentials()
    df = fetch_alpaca_bars(symbol, start_date, end_date, TIMEFRAME, 
                          api_key=credentials['api_key'], 
                          secret_key=credentials['secret_key'])
    
    if df is None or len(df) < 30:
        print(f"Insufficient data for {symbol}")
        return None
    
    print(f"Fetched {len(df)} candles")
    
    profile = get_profile(symbol)
    trades = []
    
    for idx in range(21, len(df)):
        signal, price, reason, regime = generate_signal(df, idx, profile)
        
        if signal == 'none':
            continue
        
        entry_time = df.index[idx]
        entry_price = price
        
        # Simulate trade
        for exit_idx in range(idx + 1, min(idx + 30, len(df))):
            exit_row = df.iloc[exit_idx]
            exit_time = df.index[exit_idx]
            exit_price = exit_row['close']
            
            hold_minutes = (exit_time - entry_time).total_seconds() / 60
            
            underlying_pnl = (exit_price - entry_price) / entry_price if signal == 'buy' else (entry_price - exit_price) / entry_price
            
            # TP check
            if underlying_pnl >= profile["takeProfitPct"]:
                exit_reason = 'TP hit'
                break
            
            # SL check
            if underlying_pnl <= profile["stopLossPct"]:
                exit_reason = 'SL hit'
                break
            
            # Time exit
            if hold_minutes >= profile["maxHoldMin"]:
                exit_reason = f'Time exit ({hold_minutes:.1f} min)'
                break
        else:
            exit_idx = len(df) - 1
            exit_row = df.iloc[exit_idx]
            exit_time = df.index[exit_idx]
            exit_price = exit_row['close']
            hold_minutes = (exit_time - entry_time).total_seconds() / 60
            exit_reason = 'End of data'
        
        underlying_pnl = (exit_price - entry_price) / entry_price if signal == 'buy' else (entry_price - exit_price) / entry_price
        option_result = simulate_option_trade(entry_price, exit_price, signal, hold_minutes)
        
        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'signal': signal,
            'underlying_pnl': underlying_pnl,
            'option_pnl': option_result['option_pnl'],
            'hold_minutes': hold_minutes,
            'exit_reason': exit_reason,
            'regime': regime,
            'theta_decay': option_result['theta_decay']
        })
    
    # Calculate statistics
    total_trades = len(trades)
    if total_trades == 0:
        print("No trades generated")
        return None
    
    winning_trades = sum(1 for t in trades if t['option_pnl'] > 0)
    losing_trades = total_trades - winning_trades
    win_rate = winning_trades / total_trades
    
    total_pnl = sum(t['option_pnl'] for t in trades)
    avg_pnl = total_pnl / total_trades
    
    avg_hold = sum(t['hold_minutes'] for t in trades) / total_trades
    
    max_profit = max(t['option_pnl'] for t in trades)
    max_loss = min(t['option_pnl'] for t in trades)
    
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
        result = backtest_boof19_5m(symbol, start_date, end_date)
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
