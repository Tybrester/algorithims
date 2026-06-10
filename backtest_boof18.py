import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest_signals import fetch_alpaca_bars, ema, vwap, atr

# =========================================================
# BOOF 18.0 - ORB + COMPRESSION + REGIME FILTER
# Multiple signal types for increased frequency
# =========================================================

# Filter mode: 'orb_only', 'orb_compression', 'multi_signal'
FILTER_MODE = 'multi_signal'

# Opening Range parameters
OR_MINUTES = 15  # First 15 minutes

# Compression parameters
COMPRESSION_LOOKBACK = 5  # Last 5 candles
COMPRESSION_THRESHOLD = 0.9  # Range < 90% of average (relaxed from 0.7)
RANGE_ROLLING_PERIOD = 20  # Rolling average of ranges

# Expansion parameters
VOLUME_SPIKE_MULTIPLIER = 1.1  # Volume > 1.1x average (relaxed from 1.2)
ATR_EXPANSION_MULTIPLIER = 1.0  # ATR > 1.0x average (effectively disabled)
MIN_BODY_MULTIPLIER = 1.1  # Candle body > 1.1x average (relaxed from 1.2)

# Regime filter parameters
ATR_EXPANSION_THRESHOLD = 1.2  # ATR > 1.2x 20-period average
ATR_TRANSITION_THRESHOLD = 1.0  # ATR > 1.0x 20-period average (for transition)
TREND_CONSISTENCY_THRESHOLD = 0.6  # 60% of swings must be in same direction
TREND_TRANSITION_THRESHOLD = 0.4  # 40% for transition days

# Trade quality filter parameters
ORB_BREAKOUT_STRENGTH_THRESHOLD = 0.3  # Minimum breakout strength (as % of ORB range) - relaxed for testing
SYMBOL_SCORE_THRESHOLD = 60  # Minimum symbol score for trading (relaxed for testing)

# Trade windows (market hours in UTC - US market is UTC-4 in May)
# No trades after 12pm MST = 19:00 UTC
TRADE_WINDOWS = [
    ("13:35", "15:00"),  # Morning session (9:35-11:00 AM ET)
    ("17:30", "19:00"),  # Afternoon session (1:30-12:00 PM MST) - CUT OFF AT 12PM MST
]

# Options parameters
EXPIRATION = "0DTE"
DELTA_MIN = 0.45
DELTA_MAX = 0.60

# Risk management
STOP_LOSS = -0.20  # -20%
TIME_STOP_MINUTES = 20  # 20-minute time stop

# Take profit
TP_TARGET = 0.40  # +40% - full exit

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
    
    for date, group in df.groupby('date'):
        # Get first N minutes of trading
        group_sorted = group.sort_index()
        or_candles = group_sorted.head(minutes)
        
        if len(or_candles) > 0:
            or_high[date] = or_candles['high'].max()
            or_low[date] = or_candles['low'].min()
        else:
            or_high[date] = group['high'].iloc[0]
            or_low[date] = group['low'].iloc[0]
    
    return or_high, or_low

def calculate_candle_range(df):
    """Calculate candle range (high - low)"""
    return df['high'] - df['low']

def calculate_candle_body(df):
    """Calculate candle body (abs(close - open))"""
    return (df['close'] - df['open']).abs()

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
        
        if start_minutes <= time_minutes <= end_minutes:
            return True
    return False

def is_lunchtime(timestamp):
    """Check if it's lunchtime (chop) - 12:00-13:00 ET = 16:00-17:00 UTC"""
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute
    return 960 <= time_minutes <= 1020

def detect_regime(df):
    """Detect if it's an EXPANSION, TRANSITION, or CHOP day"""
    df = df.copy()
    df['date'] = df.index.date
    
    # Calculate historical ORB range median
    or_high, or_low = calculate_or(df, OR_MINUTES)
    orb_ranges = []
    
    for date in df['date'].unique():
        if date in or_high and date in or_low:
            orb_range = or_high[date] - or_low[date]
            orb_ranges.append(orb_range)
    
    median_orb_range = np.median(orb_ranges) if orb_ranges else 0
    
    regime_by_date = {}
    
    for date, group in df.groupby('date'):
        group_sorted = group.sort_index()
        
        # Need at least 60 minutes of data
        if len(group_sorted) < 60:
            regime_by_date[date] = 'CHOP'
            continue
        
        # Calculate ATR for the day
        day_atr = atr(group_sorted, period=14).iloc[-1] if len(group_sorted) >= 14 else 0
        
        if len(group_sorted) >= 20:
            avg_atr = atr(group_sorted, period=20).iloc[-1]
        else:
            avg_atr = day_atr
        
        # ATR expansion check
        atr_expansion = day_atr > (avg_atr * ATR_EXPANSION_THRESHOLD) if avg_atr > 0 else False
        atr_transition = day_atr > (avg_atr * ATR_TRANSITION_THRESHOLD) if avg_atr > 0 else False
        
        # ORB range check
        today_orb_range = (or_high.get(date, group_sorted['high'].iloc[0]) - 
                          or_low.get(date, group_sorted['low'].iloc[0]))
        orb_expansion = today_orb_range > median_orb_range if median_orb_range > 0 else False
        
        # Trend consistency check
        first_hour = group_sorted.head(60)
        
        if len(first_hour) >= 10:
            highs = first_hour['high'].values
            lows = first_hour['low'].values
            
            higher_highs = 0
            for i in range(2, len(highs)):
                if highs[i] > highs[i-1] and highs[i-1] > highs[i-2]:
                    higher_highs += 1
            
            lower_lows = 0
            for i in range(2, len(lows)):
                if lows[i] < lows[i-1] and lows[i-1] < lows[i-2]:
                    lower_lows += 1
            
            total_swings = higher_highs + lower_lows
            if total_swings > 0:
                trend_consistency = max(higher_highs, lower_lows) / total_swings
            else:
                trend_consistency = 0
        else:
            trend_consistency = 0
        
        trend_strong = trend_consistency >= TREND_CONSISTENCY_THRESHOLD
        trend_mixed = trend_consistency >= TREND_TRANSITION_THRESHOLD
        
        # VWAP behavior check (mean reversion vs trend)
        vwap_values = vwap(group_sorted).iloc[:60]
        close_values = group_sorted['close'].iloc[:60]
        
        # Check if price crosses VWAP frequently (mean reversion)
        crosses = 0
        for i in range(1, len(vwap_values)):
            if (close_values.iloc[i-1] > vwap_values.iloc[i-1] and close_values.iloc[i] < vwap_values.iloc[i]) or \
               (close_values.iloc[i-1] < vwap_values.iloc[i-1] and close_values.iloc[i] > vwap_values.iloc[i]):
                crosses += 1
        
        vwap_mean_reversion = crosses > 10  # Frequent crosses = mean reversion
        
        # CLASSIFY REGIME
        if atr_expansion and orb_expansion and trend_strong:
            regime_by_date[date] = 'EXPANSION'
        elif atr_transition and trend_mixed and not vwap_mean_reversion:
            regime_by_date[date] = 'TRANSITION'
        else:
            regime_by_date[date] = 'CHOP'
    
    return regime_by_date

def calculate_symbol_score_from_backtest(backtest_result):
    """Calculate symbol score (0-100) based on ACTUAL trade outcomes, not market structure"""
    
    if backtest_result['total_trades'] == 0:
        return 0  # No trades = no score
    
    # COMPONENT 1: Expected Value per Trade (40%)
    # Average return per trade
    avg_return = backtest_result['avg_pnl'] * 100  # Convert to percentage
    ev_score = 50 + (avg_return * 100)  # Scale: 0.1% return = 60 score
    ev_score = max(0, min(100, ev_score))
    
    # COMPONENT 2: Profit Factor (30%)
    # Actual PF from trades
    pf = backtest_result['profit_factor']
    pf_score = min(pf / 2 * 100, 100)  # PF of 2 = 100 score
    pf_score = max(0, min(100, pf_score))
    
    # COMPONENT 3: Win Rate (20%)
    # Actual win rate from trades
    win_rate = backtest_result['win_rate'] * 100
    wr_score = win_rate  # Direct mapping
    wr_score = max(0, min(100, wr_score))
    
    # COMPONENT 4: Drawdown Penalty (10%)
    # Lower drawdown = higher score
    max_dd = abs(backtest_result['max_drawdown']) * 100
    dd_score = max(0, 100 - (max_dd * 2))  # 5% DD = 90 score, 10% DD = 80 score
    dd_score = max(0, min(100, dd_score))
    
    # Calculate final weighted score
    final_score = (
        ev_score * 0.40 +           # Expected Value per Trade (40%)
        pf_score * 0.30 +            # Profit Factor (30%)
        wr_score * 0.20 +            # Win Rate (20%)
        dd_score * 0.10              # Drawdown Penalty (10%)
    )
    
    return max(0, min(100, final_score))

def calculate_symbol_score(df, symbol):
    """Calculate symbol score (0-100) based on 5 components with refined weights"""
    df = df.copy()
    df['date'] = df.index.date
    
    # Need at least 10 days of data
    unique_dates = df['date'].unique()
    if len(unique_dates) < 10:
        return 50  # Neutral score if insufficient data
    
    # Use last 10 trading days for scoring
    recent_dates = sorted(unique_dates)[-10:]
    df_recent = df[df['date'].isin(recent_dates)]
    
    # COMPONENT 1: ORB Follow-Through Rate (40%)
    # Measures % of ORB breakouts that continue ≥ 1 ATR - MOST IMPORTANT
    orb_score = 50  # Base score
    
    or_high, or_low = calculate_or(df_recent, OR_MINUTES)
    orb_breakouts = 0
    orb_followthrough = 0
    
    for date in recent_dates:
        if date in or_high and date in or_low:
            day_data = df_recent[df_recent['date'] == date].sort_index()
            if len(day_data) > 30:  # Need enough data
                orb_h = or_high[date]
                orb_l = or_low[date]
                day_atr = atr(day_data, period=14).iloc[-1] if len(day_data) >= 14 else 0
                
                # Check for ORB breakout
                for i in range(15, len(day_data)):
                    if day_data['close'].iloc[i] > orb_h or day_data['close'].iloc[i] < orb_l:
                        orb_breakouts += 1
                        # Check if it continues for at least 1 ATR
                        if i + 10 < len(day_data):
                            entry_price = day_data['close'].iloc[i]
                            target = day_atr
                            for j in range(i+1, min(i+10, len(day_data))):
                                if abs(day_data['close'].iloc[j] - entry_price) >= target:
                                    orb_followthrough += 1
                                    break
                        break
    
    if orb_breakouts > 0:
        orb_followthrough_pct = (orb_followthrough / orb_breakouts) * 100
        orb_score = orb_followthrough_pct
    orb_score = max(0, min(100, orb_score))
    
    # COMPONENT 2: Boof 18.0 Historical Performance (25%)
    # Uses actual backtest results on this symbol over last 10 days
    # Weight: Win Rate (10%) + Profit Factor (15%)
    boof18_score = 50  # Base score
    
    # Simulate a quick backtest on recent data to get performance metrics
    # This is a simplified version - in production you'd use actual historical results
    daily_returns = df_recent.groupby('date').apply(
        lambda x: (x['close'].iloc[-1] - x['close'].iloc[0]) / x['close'].iloc[0] * 100
    )
    
    if len(daily_returns) > 0:
        win_days = (daily_returns > 0).sum()
        win_rate = (win_days / len(daily_returns)) * 100
        
        # Calculate profit factor (simplified)
        wins = daily_returns[daily_returns > 0].sum()
        losses = abs(daily_returns[daily_returns < 0].sum())
        profit_factor = (wins / losses) if losses > 0 else 100
        
        # Combine win rate (10% weight) and profit factor (15% weight)
        win_rate_component = (win_rate / 100) * 100  # Normalize to 0-100
        pf_component = min(profit_factor / 2 * 100, 100)  # Cap at 100
        boof18_score = (win_rate_component * 0.4 + pf_component * 0.6)
    boof18_score = max(0, min(100, boof18_score))
    
    # COMPONENT 3: Compression Success Rate (20%)
    # Measures how well symbol responds to compression breakouts
    compression_score = 50  # Base score
    
    # Calculate candle ranges
    df_recent['candle_range'] = df_recent['high'] - df_recent['low']
    df_recent['avg_range'] = df_recent['candle_range'].rolling(window=RANGE_ROLLING_PERIOD).mean()
    
    compression_breakouts = 0
    compression_success = 0
    
    for date in recent_dates:
        day_data = df_recent[df_recent['date'] == date].sort_index()
        if len(day_data) > 30:
            # Find compression periods (last 5 candles below average range)
            for i in range(20, len(day_data) - 5):
                last_5_ranges = day_data['candle_range'].iloc[i-5:i]
                avg_range = day_data['avg_range'].iloc[i]
                
                if len(last_5_ranges) >= 5:
                    avg_last_5 = last_5_ranges.mean()
                    if avg_last_5 < (avg_range * COMPRESSION_THRESHOLD):
                        # Compression detected - check if breakout succeeds
                        if i + 15 < len(day_data):
                            entry_price = day_data['close'].iloc[i]
                            # Check if price moves favorably in next 15 candles
                            future_prices = day_data['close'].iloc[i+1:i+16]
                            max_move = max((future_prices - entry_price).max(), (entry_price - future_prices).min())
                            day_atr = atr(day_data, period=14).iloc[i] if i >= 14 else 0
                            
                            if max_move >= day_atr * 0.5:  # At least 0.5 ATR move
                                compression_breakouts += 1
                                # Check if move was in direction of breakout
                                if day_data['close'].iloc[i+15] > entry_price:
                                    compression_success += 1
    
    if compression_breakouts > 0:
        compression_success_pct = (compression_success / compression_breakouts) * 100
        compression_score = compression_success_pct
    compression_score = max(0, min(100, compression_score))
    
    # COMPONENT 4: Volatility Quality (10%)
    # Measures consistent expansion behavior - REDUCED WEIGHT
    vol_score = 50  # Base score
    
    # Calculate ATR expansion days
    df_recent['atr_expansion'] = df_recent['atr'] > (df_recent['avg_atr'] * 1.1)
    atr_expansion_pct = df_recent['atr_expansion'].mean() * 100
    vol_score += (atr_expansion_pct - 20) * 1.5  # More expansion = higher score
    vol_score = max(0, min(100, vol_score))
    
    # COMPONENT 5: Trend Alignment (5%)
    # Measures intraday trend consistency - REDUCED WEIGHT
    trend_score = 50  # Base score
    
    # Count VWAP crosses (fewer crosses = better trend)
    vwap_values = vwap(df_recent)
    close_values = df_recent['close']
    
    crosses = 0
    for i in range(1, len(vwap_values)):
        if (close_values.iloc[i-1] > vwap_values.iloc[i-1] and close_values.iloc[i] < vwap_values.iloc[i]) or \
           (close_values.iloc[i-1] < vwap_values.iloc[i-1] and close_values.iloc[i] > vwap_values.iloc[i]):
            crosses += 1
    
    # Normalize crosses (fewer = better)
    max_expected_crosses = len(vwap_values) * 0.3  # Expect ~30% max crosses
    cross_ratio = 1 - (crosses / max_expected_crosses) if max_expected_crosses > 0 else 0
    trend_score = 50 + (cross_ratio * 50)
    trend_score = max(0, min(100, trend_score))
    
    # Calculate final weighted score with new weights
    final_score = (
        orb_score * 0.40 +           # ORB Follow-Through (40%)
        boof18_score * 0.25 +         # Boof 18.0 Performance (25%)
        compression_score * 0.20 +    # Compression Success (20%)
        vol_score * 0.10 +            # Volatility Quality (10%)
        trend_score * 0.05            # Trend Alignment (5%)
    )
    
    return max(0, min(100, final_score))

# =========================================================
# SIGNAL GENERATION
# =========================================================

def generate_signals_boof18(df, symbol_score=50):
    """Generate Boof 18.0 signals - ORB + Compression + Multiple Signal Types"""
    
    df = df.copy()
    
    # Calculate indicators
    df['vwap'] = vwap(df)
    df['atr'] = atr(df, period=14)
    df['avg_volume'] = df['volume'].rolling(window=20).mean()
    df['avg_atr'] = df['atr'].rolling(window=20).mean()
    df['ema9'] = ema(df['close'], period=9)
    
    # Calculate candle ranges and bodies
    df['candle_range'] = calculate_candle_range(df)
    df['candle_body'] = calculate_candle_body(df)
    df['avg_range'] = df['candle_range'].rolling(window=RANGE_ROLLING_PERIOD).mean()
    df['avg_body'] = df['candle_body'].rolling(window=RANGE_ROLLING_PERIOD).mean()
    
    # Calculate Opening Range
    or_high, or_low = calculate_or(df, OR_MINUTES)
    
    # Detect regime
    regime_by_date = detect_regime(df)
    
    signals = []
    
    # Track trades per day (multiple allowed on expansion days)
    trades_per_day = {}
    
    # Track ORB breakout direction for re-entry logic
    orb_breakout_direction = {}  # {date: 'LONG' or 'SHORT' or None}
    re_entry_used = {}  # {date: True if re-entry already used}
    
    # Debug counters
    total_checks = 0
    window_checks = 0
    or_checks = 0
    breakout_checks = 0
    compression_checks = 0
    reentry_checks = 0
    regime_expansion_count = 0
    regime_transition_count = 0
    regime_chop_count = 0
    all_passed = 0
    
    for i in range(50, len(df)):  # Start after indicators are ready
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        current_date = row.name.date()
        
        total_checks += 1
        
        # Check trade window
        if not is_in_trade_window(row.name):
            continue
        window_checks += 1
        
        # Skip lunchtime
        if is_lunchtime(row.name):
            continue
        
        # Get regime for today
        regime = regime_by_date.get(current_date, 'CHOP')
        
        # Apply regime-based trading rules
        if regime == 'EXPANSION':
            regime_expansion_count += 1
            max_trades_today = 5  # Allow up to 5 trades on expansion days
            allow_re_entry = True  # Allow re-entries
            allow_multiple_signals = True  # Allow all signal types
        elif regime == 'TRANSITION':
            regime_transition_count += 1
            max_trades_today = 2  # Only 2 trades on transition days
            allow_re_entry = False  # No re-entries
            allow_multiple_signals = False  # Only first ORB breakout
        else:  # CHOP - REGIME SWITCH: CHOP overrides everything
            regime_chop_count += 1
            max_trades_today = 0  # No trades on chop days (overrides symbol score)
            allow_re_entry = False
            allow_multiple_signals = False
            continue  # Skip all checks on CHOP days
        
        # Check if we've hit max trades for today
        trades_today = trades_per_day.get(current_date, 0)
        if trades_today >= max_trades_today:
            continue
        
        # Skip if before OR is established (first 15 minutes)
        if row.name.hour < 13 or (row.name.hour == 13 and row.name.minute < 45):
            continue
        or_checks += 1
        
        # Get OR for today
        today_or_high = or_high.get(current_date, row['high'])
        today_or_low = or_low.get(current_date, row['low'])
        
        # Calculate avg_range
        avg_range = df['avg_range'].iloc[i]
        
        # SIGNAL TYPE 1: ORB BREAKOUT (always available)
        breakout_up = row['close'] > today_or_high
        breakout_down = row['close'] < today_or_low
        
        # Calculate ORB breakout strength
        orb_range = today_or_high - today_or_low
        if breakout_up:
            breakout_strength = (row['close'] - today_or_high) / orb_range if orb_range > 0 else 0
        elif breakout_down:
            breakout_strength = (today_or_low - row['close']) / orb_range if orb_range > 0 else 0
        else:
            breakout_strength = 0
        
        if breakout_up or breakout_down:
            breakout_checks += 1
            
            # TRADE QUALITY FILTER: Check ORB breakout strength
            if breakout_strength < ORB_BREAKOUT_STRENGTH_THRESHOLD:
                continue  # Skip weak breakouts
            
            # TRADE QUALITY FILTER: Check symbol score and regime
            # Only trade if symbol_score > SYMBOL_SCORE_THRESHOLD AND regime != CHOP
            if symbol_score < SYMBOL_SCORE_THRESHOLD:
                continue  # Skip if symbol score is too low
            if regime == 'CHOP':
                continue  # Skip if regime is CHOP (already handled above, but double-check)
            
            # Apply compression filter for orb_compression and multi_signal modes
            if FILTER_MODE in ['orb_compression', 'multi_signal']:
                last_5_ranges = df['candle_range'].iloc[i-5:i]
                
                if len(last_5_ranges) >= 5:
                    avg_last_5_range = last_5_ranges.mean()
                    compression_met = avg_last_5_range < (avg_range * COMPRESSION_THRESHOLD)
                    
                    if compression_met:
                        compression_checks += 1
                        side = 'LONG' if breakout_up else 'SHORT'
                        
                        # Store ORB breakout direction for re-entry logic
                        orb_breakout_direction[current_date] = side
                        
                        signals.append({
                            'time': row.name,
                            'price': row['close'],
                            'side': side,
                            'or_high': today_or_high,
                            'or_low': today_or_low,
                            'volume': row['volume'],
                            'atr': row['atr'],
                            'candle_body': row['candle_body'],
                            'avg_body': row['avg_body'],
                            'avg_range': avg_range,
                            'avg_last_5_range': avg_last_5_range,
                            'signal_type': 'orb_compression',
                            'regime': regime
                        })
                        
                        trades_per_day[current_date] = trades_today + 1
                        all_passed += 1
                        continue
        
        # SIGNAL TYPE 2: VWAP/EMA BOUNCE RE-ENTRY AFTER ORB BREAKOUT
        # Only allow ONE re-entry per day after valid ORB breakout (EXPANSION days only)
        if allow_re_entry and current_date in orb_breakout_direction and not re_entry_used.get(current_date, False):
            if trades_today < max_trades_today and i >= 20:  # Need enough history
                orb_direction = orb_breakout_direction[current_date]
                
                # Check if trend direction still intact
                trend_intact = False
                if orb_direction == 'LONG':
                    trend_intact = row['close'] > row['vwap']
                else:
                    trend_intact = row['close'] < row['vwap']
                
                if trend_intact:
                    # Check if price pulled back to VWAP or 9 EMA
                    prev_close = df['close'].iloc[i-1]
                    prev_vwap = df['vwap'].iloc[i-1]
                    prev_ema9 = df['ema9'].iloc[i-1]
                    
                    pulled_to_vwap = False
                    pulled_to_ema = False
                    
                    if orb_direction == 'LONG':
                        # For longs: pulled back to VWAP or EMA (price was below, now bouncing)
                        pulled_to_vwap = prev_close < prev_vwap and row['close'] >= row['vwap']
                        pulled_to_ema = prev_close < prev_ema9 and row['close'] >= row['ema9']
                    else:
                        # For shorts: pulled back to VWAP or EMA (price was above, now bouncing)
                        pulled_to_vwap = prev_close > prev_vwap and row['close'] <= row['vwap']
                        pulled_to_ema = prev_close > prev_ema9 and row['close'] <= row['ema9']
                    
                    if pulled_to_vwap or pulled_to_ema:
                        # Check bounce candle confirms direction
                        if i >= 2:
                            prev2_close = df['close'].iloc[i-2]
                            prev2_low = df['low'].iloc[i-2]
                            prev2_high = df['high'].iloc[i-2]
                            
                            bounce_confirmed = False
                            if orb_direction == 'LONG':
                                # Higher low confirmation
                                bounce_confirmed = row['low'] > prev2_low
                            else:
                                # Lower high confirmation
                                bounce_confirmed = row['high'] < prev2_high
                            
                            if bounce_confirmed:
                                reentry_checks += 1
                                
                                signals.append({
                                    'time': row.name,
                                    'price': row['close'],
                                    'side': orb_direction,
                                    'or_high': today_or_high,
                                    'or_low': today_or_low,
                                    'volume': row['volume'],
                                    'atr': row['atr'],
                                    'candle_body': row['candle_body'],
                                    'avg_body': row['avg_body'],
                                    'avg_range': avg_range,
                                    'avg_last_5_range': avg_range,
                                    'signal_type': 'vwap_ema_bounce',
                                    'regime': regime
                                })
                                
                                trades_per_day[current_date] = trades_today + 1
                                re_entry_used[current_date] = True  # Mark re-entry as used
                                all_passed += 1
                                continue
    
    print(f"Debug: total={total_checks}, window={window_checks}, or={or_checks}, breakout={breakout_checks}, compression={compression_checks}, reentry={reentry_checks}, regime_exp={regime_expansion_count}, regime_trans={regime_transition_count}, regime_chop={regime_chop_count}, all_passed={all_passed}")
    
    return signals, df

# =========================================================
# BACKTEST ENGINE
# =========================================================

def backtest_boof18(df_underlying, symbol="SPY", symbol_score=50):
    """Backtest Boof 18.0 with 0DTE options simulation"""
    
    signals, df = generate_signals_boof18(df_underlying, symbol_score)
    
    if not signals:
        return {
            'symbol': symbol,
            'total_trades': 0,
            'win_rate': 0,
            'avg_pnl': 0,
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
        
        if entry_time not in df.index:
            continue
        
        idx = df.index.get_loc(entry_time)
        future = df.iloc[idx + 1: idx + 60]  # Look ahead 60 minutes (1 hour max)
        
        if len(future) == 0:
            continue
        
        # Simulate options PnL
        delta = 0.50
        
        for bar_idx, (_, row) in enumerate(future.iterrows()):
            current_price = row['close']
            
            if side == 'LONG':
                underlying_pnl = (current_price - entry_price) / entry_price
            else:
                underlying_pnl = (entry_price - current_price) / entry_price
            
            options_pnl = underlying_pnl * delta
            
            # Time stop (10 minutes)
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
            
            # Take profit (+40%)
            if options_pnl >= TP_TARGET:
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
            
            # Stop loss (-20%)
            if options_pnl <= STOP_LOSS:
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
        'daily_breakdown': daily_breakdown
    }

# =========================================================
# MAIN EXECUTION
# =========================================================

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    ALPACA_API_KEY = "AK5QL43AEYXZSYCRSNSIDYO36D"
    ALPACA_SECRET_KEY = "qwEfPQ2CWZYzDzJLn4QQNYcs9tdNprxP44C4dWT5md3"
    
    # Backtest April 2026
    end_date = datetime(2026, 4, 30)
    start_date = datetime(2026, 4, 1)
    
    print(f"\n{'='*60}")
    print(f"BOOF 18.0 - ORB + FILTER TESTING")
    print(f"Filter Mode: {FILTER_MODE}")
    print(f"{start_date.date()} to {end_date.date()}")
    print(f"{'='*60}\n")
    
    # SCAN_BOOF90 - Top 50 volatility scan list
    boof_list = [
        'ARM', 'AI', 'MSTR', 'TSLA', 'NVDA', 'AMD', 'PLTR', 'SOFI', 'MARA', 'RIOT',
        'OPEN', 'LCID', 'AAL', 'DKNG', 'AFRM', 'HOOD', 'AAPL', 'MSFT', 'META', 'AMZN',
        'GOOGL', 'NFLX', 'INTC', 'MU', 'SNOW', 'CRM', 'UBER', 'RIVN', 'NIO', 'XPEV',
        'LI', 'F', 'GM', 'GME', 'AMC', 'BB', 'SOUN', 'COIN', 'BITO', 'CLSK', 'PFE',
        'MRNA', 'BAC', 'JPM', 'C', 'WFC', 'DAL', 'UAL', 'BA', 'SMCI'
    ]
    
    all_results = {}
    symbol_scores = {}
    
    for ticker in boof_list:
        print(f"\n{'='*60}")
        print(f"BACKTEST: {ticker}")
        print(f"{'='*60}\n")
        
        # Download data
        print(f"  Downloading {ticker} data from Alpaca API...")
        df = fetch_alpaca_bars(ticker, start_date, end_date, '1Min', 
                              ALPACA_API_KEY, ALPACA_SECRET_KEY)
        
        if df is None or len(df) == 0:
            print(f"No data found for {ticker}")
            continue
        
        print(f"Downloaded {len(df)} candles\n")
        
        # Calculate indicators needed for scoring
        df['atr'] = atr(df, period=14)
        df['avg_atr'] = df['atr'].rolling(window=20).mean()
        
        # Calculate symbol score (market structure based - for initial filter)
        print("Calculating symbol score (market structure)...")
        score = calculate_symbol_score(df, ticker)
        symbol_scores[ticker] = score
        
        # Only run backtest if symbol passes initial filter
        if score < SYMBOL_SCORE_THRESHOLD:
            print(f"Symbol Score: {score:.1f}/100 → IGNORE (no trades)")
            continue
        
        print(f"Symbol Score: {score:.1f}/100 → Running backtest...")
        
        # Run backtest
        print("Running Boof 18.0 backtest...")
        result = backtest_boof18(df, ticker, score)
        
        # Recalculate score based on ACTUAL trade outcomes (not market structure)
        outcome_score = calculate_symbol_score_from_backtest(result)
        result['symbol_score'] = outcome_score
        
        # Determine allocation based on OUTCOME score
        if outcome_score >= 70:
            allocation = "ACTIVE"
        elif outcome_score >= 50:
            allocation = "LIMITED"
        else:
            allocation = "IGNORE"
        
        result['allocation'] = allocation
        print(f"Outcome-based Score: {outcome_score:.1f}/100 → {allocation}")
        
        # Print results
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}\n")
        
        print(f"Total Trades: {result['total_trades']}")
        print(f"Win Rate: {result['win_rate']*100:.1f}% (Target: >50%) {'✓' if result['win_rate'] > 0.5 else '✗'}")
        print(f"Avg PnL: {result['avg_pnl']*100:.2f}%")
        print(f"Expectancy: {result['expectancy']*100:.2f}%")
        print(f"Profit Factor: {result['profit_factor']:.2f} (Target: >1.5) {'✓' if result['profit_factor'] > 1.5 else '✗'}")
        print(f"Max Drawdown: {result['max_drawdown']*100:.2f}% (Target: <15%) {'✓' if result['max_drawdown'] < 0.15 else '✗'}")
        print(f"Avg Winner > Avg Loser: {result['avg_winner_gt_loser']} (Target: True) {'✓' if result['avg_winner_gt_loser'] else '✗'}")
        
        # Add $250/trade PnL calculation
        trade_capital = result['total_trades'] * 250
        total_pnl_dollars = trade_capital * (result['total_pnl'] / 100)
        print(f"Trade capital: ${trade_capital:,.0f} ($250/trade)")
        print(f"PnL at $250/trade: ${total_pnl_dollars:,.2f}")
        
        # Check if all targets met
        targets_met = (
            result['win_rate'] > 0.5 and
            result['profit_factor'] > 1.5 and
            result['max_drawdown'] < 0.15 and
            result['avg_winner_gt_loser']
        )
        print(f"\nAll Targets Met: {'YES ✓' if targets_met else 'NO ✗'}")
        
        # Skip daily breakdown for large symbol lists
        # print(f"\n{'='*60}")
        # print(f"DAILY BREAKDOWN")
        # print(f"{'='*60}\n")
        # 
        # if result['daily_breakdown']:
        #     for date, data in sorted(result['daily_breakdown'].items()):
        #         print(f"{date}:")
        #         print(f"  Trades: {len(data['trades'])}")
        #         print(f"  Wins: {data['wins']}")
        #         print(f"  Losses: {data['losses']}")
        #         print(f"  Daily PnL: {data['pnl']*100:.2f}%")
        #         print()
        # else:
        #     print("No trades recorded\n")
        
        all_results[ticker] = result
    
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
        avg_winner_gt_loser = np.mean([r['avg_winner_gt_loser'] for r in all_results.values()])
        
        # Count symbols meeting all targets
        symbols_meeting_targets = sum(1 for r in all_results.values() if 
            r['win_rate'] > 0.5 and 
            r['profit_factor'] > 1.5 and 
            r['max_drawdown'] < 0.15 and 
            r['avg_winner_gt_loser'])
    else:
        avg_win_rate = 0
        avg_expectancy = 0
        avg_profit_factor = 0
        avg_max_drawdown = 0
        avg_winner_gt_loser = 0
        symbols_meeting_targets = 0
    
    print(f"Total Trades: {total_trades}")
    print(f"Average Win Rate: {avg_win_rate*100:.1f}% (Target: >50%)")
    print(f"Average Expectancy: {avg_expectancy*100:.2f}%")
    print(f"Average Profit Factor: {avg_profit_factor:.2f} (Target: >1.5)")
    print(f"Average Max Drawdown: {avg_max_drawdown*100:.2f}% (Target: <15%)")
    print(f"Average Winner > Loser: {avg_winner_gt_loser:.0%} (Target: True)")
    print(f"\nSymbols Meeting All Targets: {symbols_meeting_targets}/{len(all_results)}")
    
    # Calculate trades per day
    trading_days = 20  # April 23 - May 23, 2026 (approx 20 trading days)
    trades_per_day = total_trades / (len(all_results) * trading_days) if all_results else 0
    print(f"\nTrades per Day (avg): {trades_per_day:.1f} (Target: 1-5)")
    
    # Select top 10 performers by outcome score
    sorted_results = sorted(all_results.items(), key=lambda x: x[1]['symbol_score'], reverse=True)
    top_10 = dict(sorted_results[:10])
    
    print(f"\n{'='*60}")
    print(f"TOP 10 PERFORMERS (by outcome score)")
    print(f"{'='*60}\n")
    
    for symbol, result in top_10.items():
        print(f"{symbol}: {result['symbol_score']:.1f}/100 - {result['total_trades']} trades, {result['win_rate']*100:.1f}% WR, {result['profit_factor']:.2f} PF")
    
    # Recalculate summary for top 10 only
    total_trades_top10 = sum(r['total_trades'] for r in top_10.values())
    avg_win_rate_top10 = sum(r['win_rate'] for r in top_10.values()) / len(top_10) if top_10 else 0
    avg_expectancy_top10 = sum(r['expectancy'] for r in top_10.values()) / len(top_10) if top_10 else 0
    avg_profit_factor_top10 = sum(r['profit_factor'] for r in top_10.values()) / len(top_10) if top_10 else 0
    avg_max_drawdown_top10 = sum(r['max_drawdown'] for r in top_10.values()) / len(top_10) if top_10 else 0
    avg_winner_gt_loser_top10 = sum(r['avg_winner_gt_loser'] for r in top_10.values()) / len(top_10) if top_10 else 0
    symbols_meeting_targets_top10 = sum(1 for r in top_10.values() if 
        r['win_rate'] > 0.5 and 
        r['profit_factor'] > 1.5 and 
        r['max_drawdown'] < 0.15 and 
        r['avg_winner_gt_loser'])
    
    trades_per_day_top10 = total_trades_top10 / (len(top_10) * trading_days) if top_10 else 0
    
    print(f"\n{'='*60}")
    print(f"TOP 10 SUMMARY")
    print(f"{'='*60}\n")
    print(f"Total Trades: {total_trades_top10}")
    print(f"Average Win Rate: {avg_win_rate_top10*100:.1f}% (Target: >50%)")
    print(f"Average Expectancy: {avg_expectancy_top10*100:.2f}%")
    print(f"Average Profit Factor: {avg_profit_factor_top10:.2f} (Target: >1.5)")
    print(f"Average Max Drawdown: {avg_max_drawdown_top10*100:.2f}% (Target: <15%)")
    print(f"Average Winner > Loser: {avg_winner_gt_loser_top10:.0%} (Target: True)")
    print(f"\nSymbols Meeting All Targets: {symbols_meeting_targets_top10}/10")
    print(f"\nTrades per Day (avg): {trades_per_day_top10:.1f} (Target: 1-5)")
    
    # Print symbol scores summary (outcome-based)
    print(f"\n{'='*60}")
    print(f"OUTCOME-BASED SYMBOL SCORES SUMMARY (ALL 50)")
    print(f"{'='*60}\n")

    active_symbols = [s for s, r in all_results.items() if r['allocation'] == 'ACTIVE']
    limited_symbols = [s for s, r in all_results.items() if r['allocation'] == 'LIMITED']
    ignored_symbols = [s for s, r in all_results.items() if r['allocation'] == 'IGNORE']

    print(f"ACTIVE (≥70): {len(active_symbols)} symbols")
    for s in sorted(active_symbols, key=lambda x: all_results[x]['symbol_score'], reverse=True):
        print(f"  {s}: {all_results[s]['symbol_score']:.1f}")

    print(f"\nLIMITED (50-69): {len(limited_symbols)} symbols")
    for s in sorted(limited_symbols, key=lambda x: all_results[x]['symbol_score'], reverse=True):
        print(f"  {s}: {all_results[s]['symbol_score']:.1f}")

    print(f"\nIGNORED (<50): {len(ignored_symbols)} symbols")
    for s in sorted(ignored_symbols, key=lambda x: all_results[x]['symbol_score'], reverse=True):
        print(f"  {s}: {all_results[s]['symbol_score']:.1f}")
    
    print(f"\n{'='*60}")
    print(f"BACKTEST COMPLETE")
    print(f"{'='*60}")
