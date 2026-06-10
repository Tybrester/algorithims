import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, ema, vwap, atr, get_alpaca_credentials

# =========================================================
# Dynamic 1H Support Resistance Break Strategy
# =========================================================

# Settings
PIVOT_LEN_LONG = 6  # Pivot strength for LONG entries
PIVOT_LEN_SHORT = 9  # Pivot strength for SHORT entries (unused if SHORTs disabled)
LOOKBACK_BARS = 60  # Bars back (60 bars on 1m)
USE_VWAP = True  # Use VWAP filter
ENABLE_SHORTS = False  # Disable SHORT entries - LONG-only is profitable

# Filter settings
VWAP_SLOPE_PERIOD = 10  # Period for VWAP slope calculation
VOLUME_MULTIPLIER = 1.1  # Volume must be > 1.1x average (lowered)
VOLUME_AVG_PERIOD = 20  # Period for average volume
EMA9_PERIOD = 9
EMA20_PERIOD = 20
# ATR_RANGE_PERIOD = 20  # Disabled for now
# MAX_VWAP_DISTANCE = 0.02  # Max distance from VWAP (2% - relaxed further)

# Risk management
RISK_REWARD = 1.5  # 1.5R

# Time stop (for 0DTE)
TIME_STOP_MINUTES = 20  # 20-minute time stop

# Trade windows (in minutes from 9:30 AM)
# 9:35-11:00 = 5-90 minutes
# 2:00-3:30 = 330-390 minutes
TRADE_WINDOWS = [
    (5, 90),    # 9:35-11:00 AM
    (330, 390)  # 2:00-3:30 PM
]

# =========================================================
# INDICATOR CALCULATIONS
# =========================================================

def find_pivots(df, pivot_len=5):
    """Find pivot highs and lows"""
    df = df.copy()
    
    pivot_highs = []
    pivot_lows = []
    
    for i in range(pivot_len, len(df) - pivot_len):
        # Check for pivot high
        is_pivot_high = True
        for j in range(i - pivot_len, i + pivot_len + 1):
            if j != i and df['high'].iloc[j] >= df['high'].iloc[i]:
                is_pivot_high = False
                break
        if is_pivot_high:
            pivot_highs.append((i, df['high'].iloc[i]))
        
        # Check for pivot low
        is_pivot_low = True
        for j in range(i - pivot_len, i + pivot_len + 1):
            if j != i and df['low'].iloc[j] <= df['low'].iloc[i]:
                is_pivot_low = False
                break
        if is_pivot_low:
            pivot_lows.append((i, df['low'].iloc[i]))
    
    return pivot_highs, pivot_lows

def check_lower_high_structure(df, current_idx, lookback=5):
    """Check for lower high structure (bearish)"""
    if current_idx < lookback + 1:
        return False
    
    # Check if recent highs are making lower highs
    recent_highs = []
    for i in range(current_idx - lookback, current_idx + 1):
        recent_highs.append(df['high'].iloc[i])
    
    # Simple check: current high < previous high
    if len(recent_highs) >= 2:
        return recent_highs[-1] < recent_highs[-2]
    
    return False

def check_failed_breakdown(df, current_idx, support_level):
    """Check for failed breakdown of support"""
    if current_idx < 2:
        return False
    
    # Previous candle broke below support
    prev_low = df['low'].iloc[current_idx - 1]
    prev_close = df['close'].iloc[current_idx - 1]
    
    # Current candle rejected and closed back above support
    current_low = df['low'].iloc[current_idx]
    current_close = df['close'].iloc[current_idx]
    
    # Failed breakdown: previous broke below, current touched but closed above
    failed_breakdown = (
        prev_low < support_level and
        current_low <= support_level and
        current_close > support_level
    )
    
    return failed_breakdown

def check_rejection_candle(df, current_idx):
    """Check for rejection candle (long wick, close near high)"""
    if current_idx < 1:
        return False
    
    row = df.iloc[current_idx]
    
    # Calculate wick ratios
    body = abs(row['close'] - row['open'])
    upper_wick = row['high'] - max(row['open'], row['close'])
    lower_wick = min(row['open'], row['close']) - row['low']
    total_range = row['high'] - row['low']
    
    if total_range == 0:
        return False
    
    # Rejection candle: close near high (bullish rejection of lower prices)
    close_position = (row['close'] - row['low']) / total_range
    
    # Close in top 30% of range
    return close_position > 0.7

def check_volatility_after_breakdown(df, current_idx, period=5):
    """Check volatility expansion after potential breakdown"""
    if current_idx < period + 1:
        return False
    
    # Compare recent volatility to previous
    recent_range = (df['high'].iloc[current_idx - period:current_idx] - 
                    df['low'].iloc[current_idx - period:current_idx]).mean()
    prev_range = (df['high'].iloc[current_idx - period - 5:current_idx - period] - 
                  df['low'].iloc[current_idx - period - 5:current_idx - period]).mean()
    
    return recent_range > prev_range

def check_market_bias(df, current_idx):
    """Check if market is bullish (SPY above VWAP)"""
    vwap_values = vwap(df)
    current_vwap = vwap_values.iloc[current_idx]
    current_price = df['close'].iloc[current_idx]
    
    return current_price > current_vwap

def get_recent_levels(pivot_highs, pivot_lows, current_idx, lookback_bars=12):
    """Get recent support and resistance levels"""
    # Find most recent pivot high within lookback
    recent_resistance = None
    for idx, value in reversed(pivot_highs):
        if current_idx - idx <= lookback_bars:
            recent_resistance = value
            break
    
    # Find most recent pivot low within lookback
    recent_support = None
    for idx, value in reversed(pivot_lows):
        if current_idx - idx <= lookback_bars:
            recent_support = value
            break
    
    return recent_resistance, recent_support

def check_vwap_slope(vwap_values, current_idx, period=10):
    """Check if VWAP is rising or falling"""
    if current_idx < period:
        return 0  # Not enough data
    
    current_vwap = vwap_values.iloc[current_idx]
    prev_vwap = vwap_values.iloc[current_idx - period]
    
    slope = (current_vwap - prev_vwap) / prev_vwap
    return slope

def check_volume_expansion(df, current_idx, multiplier=1.5, avg_period=20):
    """Check if current volume > multiplier * average volume"""
    if current_idx < avg_period:
        return False  # Not enough data
    
    current_volume = df['volume'].iloc[current_idx]
    avg_volume = df['volume'].iloc[current_idx - avg_period:current_idx].mean()
    
    return current_volume > (avg_volume * multiplier)

def is_in_trade_window(timestamp):
    """Check if timestamp is within trade windows"""
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute - 570  # 9:30 AM = 570 minutes
    
    for start, end in TRADE_WINDOWS:
        if start <= time_minutes <= end:
            return True
    
    return False

def check_atr_volatility(df, current_idx, period=20):
    """Check if current candle range > average candle range"""
    if current_idx < period:
        return False  # Not enough data
    
    current_range = df['high'].iloc[current_idx] - df['low'].iloc[current_idx]
    avg_range = (df['high'].iloc[current_idx - period:current_idx] - 
                 df['low'].iloc[current_idx - period:current_idx]).mean()
    
    return current_range > avg_range

def check_vwap_distance(price, vwap, max_distance=0.003):
    """Check if price is within max distance from VWAP"""
    distance = abs(price - vwap) / vwap
    return distance < max_distance

def check_retest_confirmation(df, current_idx, level, side='LONG'):
    """Check for retest confirmation after breakout"""
    # Need at least 2 more candles to check retest
    if current_idx + 2 >= len(df):
        return False
    
    # Check if next candle retests the level
    next_candle = df.iloc[current_idx + 1]
    next_next_candle = df.iloc[current_idx + 2]
    
    if side == 'LONG':
        # LONG: resistance broke, close above, next candle retests, holds above
        if next_candle['low'] <= level and next_candle['close'] > level:
            return True
        # Or next_next candle retests and holds
        if next_next_candle['low'] <= level and next_next_candle['close'] > level:
            return True
    else:
        # SHORT: support broke, close below, next candle retests, holds below
        if next_candle['high'] >= level and next_candle['close'] < level:
            return True
        # Or next_next candle retests and holds
        if next_next_candle['high'] >= level and next_next_candle['close'] < level:
            return True
    
    return False

def check_trend_regime(df, current_idx, ema9_period=9, ema20_period=20):
    """Check trend regime using EMA 9/20 and VWAP slope"""
    if current_idx < ema20_period:
        return 'neutral'  # Not enough data
    
    ema9_values = ema(df, ema9_period)
    ema20_values = ema(df, ema20_period)
    vwap_values = vwap(df)
    
    current_ema9 = ema9_values.iloc[current_idx]
    current_ema20 = ema20_values.iloc[current_idx]
    current_vwap = vwap_values.iloc[current_idx]
    current_price = df['close'].iloc[current_idx]
    
    # Ensure scalar values
    if hasattr(current_ema9, 'values'):
        current_ema9 = current_ema9.values[0] if len(current_ema9.values) > 0 else current_ema9
    if hasattr(current_ema20, 'values'):
        current_ema20 = current_ema20.values[0] if len(current_ema20.values) > 0 else current_ema20
    if hasattr(current_vwap, 'values'):
        current_vwap = current_vwap.values[0] if len(current_vwap.values) > 0 else current_vwap
    
    # VWAP slope
    vwap_slope = check_vwap_slope(vwap_values, current_idx, VWAP_SLOPE_PERIOD)
    
    # LONG trend: price > VWAP, VWAP rising, EMA9 > EMA20
    if current_price > current_vwap and vwap_slope > 0 and current_ema9 > current_ema20:
        return 'bullish'
    
    # SHORT trend: price < VWAP, VWAP falling, EMA9 < EMA20
    if current_price < current_vwap and vwap_slope < 0 and current_ema9 < current_ema20:
        return 'bearish'
    
    return 'neutral'

# =========================================================
# SIGNAL GENERATION
# =========================================================

def generate_signals_dynamic_sr(df, symbol="SPY"):
    """Generate signals for Dynamic SR Break strategy"""
    
    # Calculate indicators for LONG and SHORT separately
    pivot_highs_long, pivot_lows_long = find_pivots(df, PIVOT_LEN_LONG)
    pivot_highs_short, pivot_lows_short = find_pivots(df, PIVOT_LEN_SHORT)
    vwap_values = vwap(df)
    
    df = df.copy()
    df['vwap'] = vwap_values
    
    signals = []
    
    # Use the larger pivot length for loop start
    max_pivot_len = max(PIVOT_LEN_LONG, PIVOT_LEN_SHORT)
    
    for i in range(max_pivot_len + LOOKBACK_BARS + VWAP_SLOPE_PERIOD + VOLUME_AVG_PERIOD + EMA20_PERIOD, len(df)):
        row = df.iloc[i]
        current_vwap = row['vwap']
        
        # Time filter
        if not is_in_trade_window(row.name):
            continue
        
        # Market bias filter (only for LONGs)
        market_bullish = check_market_bias(df, i)
        
        # VWAP slope filter
        vwap_slope = check_vwap_slope(vwap_values, i, VWAP_SLOPE_PERIOD)
        
        # Volume expansion filter
        volume_ok = check_volume_expansion(df, i, VOLUME_MULTIPLIER, VOLUME_AVG_PERIOD)
        if not volume_ok:
            continue
        
        # Trend regime filter (calculate EMA for trend alignment)
        ema9_values = ema(df, EMA9_PERIOD)
        ema20_values = ema(df, EMA20_PERIOD)
        current_ema9 = ema9_values.iloc[i]
        current_ema20 = ema20_values.iloc[i]
        
        # Ensure scalar values
        if hasattr(current_ema9, 'values'):
            current_ema9 = current_ema9.values[0] if len(current_ema9.values) > 0 else current_ema9
        if hasattr(current_ema20, 'values'):
            current_ema20 = current_ema20.values[0] if len(current_ema20.values) > 0 else current_ema20
        
        # ATR volatility filter (disabled for now)
        # volatility_ok = check_atr_volatility(df, i, ATR_RANGE_PERIOD)
        # if not volatility_ok:
        #     continue
        
        # Distance from VWAP filter (disabled for now)
        # vwap_distance_ok = check_vwap_distance(row['close'], current_vwap, MAX_VWAP_DISTANCE)
        # if not vwap_distance_ok:
        #     continue
        
        # LONG entries with market bias filter
        if market_bullish:
            # Get recent levels using LONG pivot length
            recent_resistance, recent_support = get_recent_levels(pivot_highs_long, pivot_lows_long, i, LOOKBACK_BARS)
            
            if recent_resistance is not None and recent_support is not None:
                # Breakout conditions with relaxed EMA trend alignment (2 of 3 conditions)
                long_bullish_signals = 0
                if row['close'] > current_vwap:
                    long_bullish_signals += 1
                if vwap_slope > 0:
                    long_bullish_signals += 1
                if current_ema9 > current_ema20:
                    long_bullish_signals += 1
                
                long_cond = (
                    row['close'] > recent_resistance and 
                    long_bullish_signals >= 2
                )
                
                if long_cond:
                    signals.append({
                        'time': row.name,
                        'price': row['close'],
                        'side': 'LONG',
                        'resistance': recent_resistance,
                        'support': recent_support,
                        'vwap': current_vwap,
                        'vwap_slope': vwap_slope,
                        'signal_type': 'resistance_break_long'
                    })
        
        # SHORT entries (simplified - breakout with bearish conditions)
        if ENABLE_SHORTS:
            # Only trade SHORTs when below VWAP regime
            market_bearish = not market_bullish
            
            if market_bearish:
                # Get recent levels using SHORT pivot length
                recent_resistance, recent_support = get_recent_levels(pivot_highs_short, pivot_lows_short, i, LOOKBACK_BARS)
                
                if recent_support is not None:
                    # Breakout conditions with relaxed EMA trend alignment (2 of 3 conditions)
                    short_bearish_signals = 0
                    if row['close'] < current_vwap:
                        short_bearish_signals += 1
                    if vwap_slope < 0:
                        short_bearish_signals += 1
                    if current_ema9 < current_ema20:
                        short_bearish_signals += 1
                    
                    short_cond = (
                        row['close'] < recent_support and 
                        short_bearish_signals >= 2
                    )
                    
                    if short_cond:
                        signals.append({
                            'time': row.name,
                            'price': row['close'],
                            'side': 'SHORT',
                            'resistance': recent_resistance,
                            'support': recent_support,
                            'vwap': current_vwap,
                            'vwap_slope': vwap_slope,
                            'signal_type': 'support_break_short'
                        })
    
    return signals, df

# =========================================================
# BACKTEST ENGINE
# =========================================================

def backtest_dynamic_sr(df_underlying, symbol="SPY"):
    """Backtest Dynamic SR Break with 0DTE options simulation"""
    
    signals, df = generate_signals_dynamic_sr(df_underlying, symbol)
    
    if not signals:
        return {
            'symbol': symbol,
            'total_trades': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'total_pnl': 0,
            'expectancy': 0,
            'profit_factor': 0,
            'max_drawdown': 0,
            'avg_winner_gt_loser': False,
            'trades': [],
            'daily_breakdown': {}
        }
    
    trades = []
    
    for signal in signals:
        entry_time = signal['time']
        entry_price = signal['price']
        side = signal['side']
        support = signal['support']
        resistance = signal['resistance']
        
        if entry_time not in df.index:
            continue
        
        idx = df.index.get_loc(entry_time)
        future = df.iloc[idx + 1: idx + 60]  # Look ahead 60 minutes (1 hour max)
        
        if len(future) == 0:
            continue
        
        # Calculate SL and TP
        if side == 'LONG':
            sl_price = support
            tp_price = entry_price + ((entry_price - sl_price) * RISK_REWARD)
        else:
            sl_price = resistance
            tp_price = entry_price - ((sl_price - entry_price) * RISK_REWARD)
        
        # Simulate options PnL (delta ~0.5 for ATM)
        delta = 0.50
        
        for bar_idx, (_, row) in enumerate(future.iterrows()):
            current_price = row['close']
            
            if side == 'LONG':
                underlying_pnl = (current_price - entry_price) / entry_price
            else:
                underlying_pnl = (entry_price - current_price) / entry_price
            
            options_pnl = underlying_pnl * delta
            
            # Time stop (20 minutes)
            if bar_idx >= TIME_STOP_MINUTES:
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': row.name,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'options_pnl': options_pnl,
                    'exit_reason': 'time_stop'
                })
                break
            
            # Take profit
            if side == 'LONG' and current_price >= tp_price:
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': row.name,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'options_pnl': options_pnl,
                    'exit_reason': 'take_profit'
                })
                break
            elif side == 'SHORT' and current_price <= tp_price:
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': row.name,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'options_pnl': options_pnl,
                    'exit_reason': 'take_profit'
                })
                break
            
            # Stop loss
            if side == 'LONG' and current_price <= sl_price:
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': row.name,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'options_pnl': options_pnl,
                    'exit_reason': 'stop_loss'
                })
                break
            elif side == 'SHORT' and current_price >= sl_price:
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': row.name,
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'options_pnl': options_pnl,
                    'exit_reason': 'stop_loss'
                })
                break
    
    # Calculate statistics
    if trades:
        pnls = [t['options_pnl'] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        # LONG vs SHORT breakdown
        long_trades = [t for t in trades if t['side'] == 'LONG']
        short_trades = [t for t in trades if t['side'] == 'SHORT']
        
        long_pnls = [t['options_pnl'] for t in long_trades]
        short_pnls = [t['options_pnl'] for t in short_trades]
        
        long_win_rate = sum(1 for p in long_pnls if p > 0) / len(long_pnls) if long_pnls else 0
        short_win_rate = sum(1 for p in short_pnls if p > 0) / len(short_pnls) if short_pnls else 0
        long_total_pnl = sum(long_pnls) if long_pnls else 0
        short_total_pnl = sum(short_pnls) if short_pnls else 0
        
        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_pnl = np.mean(pnls) if pnls else 0
        expectancy = avg_pnl
        profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')
        
        avg_winner = np.mean(wins) if wins else 0
        avg_loser = np.mean(losses) if losses else 0
        avg_winner_gt_loser = avg_winner > abs(avg_loser) if wins and losses else False
        
        # Calculate max drawdown
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max)
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0
    else:
        win_rate = 0
        avg_pnl = 0
        expectancy = 0
        profit_factor = 0
        avg_winner_gt_loser = False
        max_drawdown = 0
        long_win_rate = 0
        short_win_rate = 0
        long_total_pnl = 0
        short_total_pnl = 0
        long_trades = []
        short_trades = []
    
    # Group trades by date for daily breakdown
    daily_breakdown = {}
    for trade in trades:
        trade_date = trade['entry_time'].date()
        if trade_date not in daily_breakdown:
            daily_breakdown[trade_date] = {
                'trades': [],
                'pnl': 0,
                'wins': 0,
                'losses': 0
            }
        daily_breakdown[trade_date]['trades'].append(trade)
        daily_breakdown[trade_date]['pnl'] += trade['options_pnl']
        if trade['options_pnl'] > 0:
            daily_breakdown[trade_date]['wins'] += 1
        else:
            daily_breakdown[trade_date]['losses'] += 1
    
    return {
        'symbol': symbol,
        'total_trades': len(trades),
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'total_pnl': sum(pnls) if pnls else 0,
        'expectancy': expectancy,
        'profit_factor': profit_factor,
        'max_drawdown': max_drawdown,
        'avg_winner_gt_loser': avg_winner_gt_loser,
        'trades': trades,
        'daily_breakdown': daily_breakdown,
        'long_trades': len(long_trades),
        'short_trades': len(short_trades),
        'long_win_rate': long_win_rate,
        'short_win_rate': short_win_rate,
        'long_total_pnl': long_total_pnl,
        'short_total_pnl': short_total_pnl
    }

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    # Backtest April 2026
    end_date = datetime(2026, 4, 30)
    start_date = datetime(2026, 4, 1)
    
    print(f"\n{'='*60}")
    print(f"Dynamic 1H Support Resistance Break Strategy")
    print(f"{start_date.date()} to {end_date.date()}")
    print(f"{'='*60}\n")
    
    # Test on SPY only
    symbols = ['SPY']
    
    credentials = get_alpaca_credentials()
    
    all_results = {}
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"BACKTEST: {symbol}")
        print(f"{'='*60}\n")
        
        # Download data
        print(f"  Downloading {symbol} data from Alpaca API...")
        df = fetch_alpaca_bars(symbol, start_date, end_date, '1Min', 
                              api_key=credentials['api_key'], 
                              secret_key=credentials['secret_key'])
        
        if df is None or len(df) == 0:
            print(f"No data found for {symbol}")
            continue
        
        print(f"Downloaded {len(df)} candles\n")
        
        # Run backtest
        print("Running Dynamic SR Break backtest...")
        result = backtest_dynamic_sr(df, symbol)
        
        # Print results
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}\n")
        
        print(f"Total Trades: {result['total_trades']}")
        print(f"Win Rate: {result['win_rate']*100:.1f}%")
        print(f"Avg PnL: {result['avg_pnl']*100:.2f}%")
        print(f"Total PnL: {result['total_pnl']*100:.2f}%")
        print(f"Expectancy: {result['expectancy']*100:.2f}%")
        print(f"Profit Factor: {result['profit_factor']:.2f}")
        print(f"Max Drawdown: {result['max_drawdown']*100:.2f}%")
        print(f"Avg Winner > Avg Loser: {result['avg_winner_gt_loser']}")
        print(f"\nLONG vs SHORT Breakdown:")
        print(f"  LONG: {result['long_trades']} trades, {result['long_win_rate']*100:.1f}% WR, {result['long_total_pnl']*100:.2f}% PnL")
        print(f"  SHORT: {result['short_trades']} trades, {result['short_win_rate']*100:.1f}% WR, {result['short_total_pnl']*100:.2f}% PnL")
        
        all_results[symbol] = result
    
    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}\n")
    
    total_trades = sum(r['total_trades'] for r in all_results.values())
    
    if all_results:
        avg_win_rate = np.mean([r['win_rate'] for r in all_results.values()])
        avg_expectancy = np.mean([r['expectancy'] for r in all_results.values()])
        avg_profit_factor = np.mean([r['profit_factor'] for r in all_results.values()])
        avg_max_drawdown = np.mean([r['max_drawdown'] for r in all_results.values()])
        
        combined_pnl_pct = sum(r['total_pnl'] for r in all_results.values())
    else:
        avg_win_rate = 0
        avg_expectancy = 0
        avg_profit_factor = 0
        avg_max_drawdown = 0
        combined_pnl_pct = 0
    
    print(f"Total Trades: {total_trades}")
    print(f"Average Win Rate: {avg_win_rate*100:.1f}%")
    print(f"Average Expectancy: {avg_expectancy*100:.2f}%")
    print(f"Average Profit Factor: {avg_profit_factor:.2f}")
    print(f"Average Max Drawdown: {avg_max_drawdown*100:.2f}%")
    print(f"Combined PnL: {combined_pnl_pct*100:.2f}%")
    
    print(f"\n{'='*60}")
    print(f"BACKTEST COMPLETE")
    print(f"{'='*60}")
