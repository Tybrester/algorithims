import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import os

# =========================================================
# SUPABASE & ALPACA SETUP
# =========================================================

SUPABASE_URL = 'https://isanhutzyctcjygjhzbn.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0'

_alpaca_creds_cache = None

def get_alpaca_credentials():
    """Fetch Alpaca credentials live from Supabase broker_credentials table."""
    global _alpaca_creds_cache
    if _alpaca_creds_cache:
        return _alpaca_creds_cache
    try:
        resp = requests.get(
            f'{SUPABASE_URL}/rest/v1/broker_credentials',
            params={'select': 'credentials', 'broker': 'eq.alpaca', 'limit': '1'},
            headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'},
            timeout=10
        )
        rows = resp.json()
        if rows and isinstance(rows, list) and rows[0].get('credentials'):
            c = rows[0]['credentials']
            _alpaca_creds_cache = {'api_key': c['api_key'], 'secret_key': c['secret_key']}
            return _alpaca_creds_cache
    except Exception as e:
        print(f'[get_alpaca_credentials] Supabase fetch failed: {e}')
    return {'api_key': '', 'secret_key': ''}

def fetch_alpaca_bars(symbol, start_date, end_date, timeframe='1Min', api_key=None, secret_key=None):
    """Fetch historical bars from Alpaca API"""
    if not api_key or not secret_key:
        print(f"No Alpaca credentials provided for {symbol}")
        return None
    
    try:
        # Alpaca API for historical bars
        start = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        end = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
        params = {
            'timeframe': timeframe,
            'start': start,
            'end': end,
            'adjustment': 'raw',
            'feed': 'sip',
            'limit': 10000
        }
        
        response = requests.get(url, params=params, headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        })
        
        if response.status_code == 200:
            data = response.json()
            bars = data.get('bars', [])
            
            if bars:
                df = pd.DataFrame(bars)
                df['time'] = pd.to_datetime(df['t'])
                df = df.rename(columns={
                    'o': 'open',
                    'h': 'high',
                    'l': 'low',
                    'c': 'close',
                    'v': 'volume'
                })
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
                df = df.set_index('time')
                return df
            else:
                print(f"No bars returned from Alpaca for {symbol}")
        else:
            print(f"Alpaca API error for {symbol}: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error fetching Alpaca data for {symbol}: {e}")
    
    return None

# =========================================================
# INDICATORS
# =========================================================

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * df['volume']).cumsum() / df['volume'].cumsum()


def relative_volume(df, period=20):
    return df['volume'] / df['volume'].rolling(period).mean()


# =========================================================
# REGIME (context only)
# =========================================================

def classify_regime(df):
    a = atr(df)
    ratio = a / a.rolling(20).mean()

    last = ratio.iloc[-1]

    if last > 1.1:
        return "EXPANSION"
    elif last < 0.9:
        return "COMPRESSION"
    return "NORMAL"


# =========================================================
# MICRO BREAKOUT ENTRY ENGINE (SCORING SYSTEM)
# =========================================================

def generate_entries(df, symbol="SPY", ev_table=None, use_ev=False, symbol_model=None, use_symbol_ev_matrix=False, use_continuous_ev=False, use_kelly=False):

    df = df.copy()

    # indicators
    df['ema9'] = ema(df['close'], 9)
    df['ema20'] = ema(df['close'], 20)
    df['vwap'] = vwap(df)
    df['rvol'] = relative_volume(df)
    df['atr'] = atr(df)

    entries = []
    diagnostics = {
        "score_distribution": [],
        "rejected_reasons": [],
        "total_signals": 0,
        "accepted_signals": 0,
        "ev_decisions": [],
        "position_sizes": [],
        "bucket_distribution": []
    }

    lookback = 10  # micro range (5–15 min structure)

    # Adaptive threshold based on volatility regime
    atr_series_full = df['atr'].dropna()
    atr_percentile = (atr_series_full < atr_series_full.iloc[-1]).sum() / len(atr_series_full) if len(atr_series_full) > 0 else 0.5

    # Base threshold by symbol
    if symbol in ["AMD", "TSLA"]:
        base_threshold = 3.0  # Momentum regime
    elif symbol == "SPY":
        base_threshold = 3.0  # Adaptive will adjust
    elif symbol == "QQQ":
        base_threshold = 3.0  # Diagnostic mode - track everything
    else:
        base_threshold = 3.0

    # Volatility regime adjustment
    if atr_percentile > 0.7:
        volatility_adjustment = 0.5  # High volatility - require higher score
    elif atr_percentile < 0.3:
        volatility_adjustment = -0.3  # Low volatility - lower threshold
    else:
        volatility_adjustment = 0

    entry_threshold = base_threshold + volatility_adjustment

    # Get regime for symbol model
    regime = classify_regime(df)

    for i in range(lookback + 2, len(df)):

        row = df.iloc[i]
        window = df.iloc[i - lookback:i]

        # micro structure breakout levels
        range_high = window['high'].max()
        range_low = window['low'].min()
        range_width = range_high - range_low

        # SCORING SYSTEM (not gates)
        score = 0

        # SCORE 1: ATR rising (pre-expansion)
        atr_series = df['atr'].iloc[i-20:i]
        atr_avg = atr_series.mean()
        atr_current = df['atr'].iloc[i]
        atr_rising = atr_current > atr_avg * 1.02
        if atr_rising:
            score += 1

        # SCORE 1: ATR compression (relative percentile)
        atr_series = df['atr'].iloc[i-20:i]
        atr_series_clean = atr_series.dropna()
        if len(atr_series_clean) > 0:
            atr_current = df['atr'].iloc[i]
            if not pd.isna(atr_current):
                atr_rank = (atr_series_clean < atr_current).sum() / len(atr_series_clean)
                atr_compression = atr_rank < 0.4  # Below 40th percentile
                if atr_compression:
                    score += 1

        # SCORE 1: Clean consolidation (tight range)
        recent_ranges = []
        for j in range(i - lookback - 5, i - lookback):
            if j >= lookback:
                past_window = df.iloc[j - lookback:j]
                recent_ranges.append(past_window['high'].max() - past_window['low'].min())
        avg_recent_range = np.mean(recent_ranges) if recent_ranges else range_width
        tight_range = range_width < avg_recent_range * 1.3
        if tight_range:
            score += 1

        # SCORE 1: Time-of-day filter
        time_score = 0
        if hasattr(row.name, 'hour'):
            hour = row.name.hour
            minute = row.name.minute
            time_minutes = hour * 60 + minute
            is_open = 570 <= time_minutes <= 660
            is_lunch = 750 <= time_minutes <= 810
            is_close = 900 <= time_minutes <= 960
            if is_open or is_lunch or is_close:
                time_score = 1
        score += time_score

        # =========================
        # LONG ENTRY CONDITIONS
        # =========================
        long_breakout = row['close'] > range_high

        if long_breakout:
            # Base entry conditions
            long_entry = (
                row['close'] > row['vwap'] and
                row['ema9'] > row['ema20'] and
                row['rvol'] > 1.3
            )

            if long_entry:
                diagnostics["total_signals"] += 1

                # SCORE 2: First impulse confirmation (AFTER trigger, not before)
                # Check if momentum continues for 2-3 bars after breakout
                impulse_score = 0
                if i + 2 < len(df):
                    next_bar = df.iloc[i + 1]
                    next_next_bar = df.iloc[i + 2]
                    # Price continues in direction
                    if next_bar['close'] > row['close']:
                        impulse_score += 1
                    if next_next_bar['close'] > next_bar['close']:
                        impulse_score += 1
                score += impulse_score

                diagnostics["score_distribution"].append(score)

                # EV-based decision using continuous estimator, SYMBOL_EV matrix, or lookup table
                if use_continuous_ev:
                    # Use continuous EV estimator (new approach)
                    session = get_session(row.name)
                    ev = compute_continuous_ev(symbol, score, regime, atr_percentile, session)
                    diagnostics["ev_decisions"].append((score, ev, session))

                    if ev > 0:  # Only trade if positive EV
                        # Calculate position size
                        atr_val = df.loc[row.name, 'atr'] if row.name in df.index else 0.5
                        position_size = calculate_position_size(ev, atr_val, use_kelly=use_kelly)
                        diagnostics["position_sizes"].append(position_size)

                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "LONG",
                            "price": row['close'],
                            "score": score,
                            "ev": ev,
                            "position_size": position_size,
                            "symbol": symbol
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"LONG: score {score}, EV {ev:.3f} <= 0")

                elif use_symbol_ev_matrix:
                    # Use SYMBOL_EV matrix (legacy approach)
                    bucket = score_bucket(score)
                    diagnostics["bucket_distribution"].append(bucket)
                    base_ev = compute_ev(symbol, score)
                    adjusted_ev = base_ev  # No symbol model adjustment for matrix approach

                    diagnostics["ev_decisions"].append((score, bucket, base_ev))

                    if adjusted_ev > 0:  # Only trade if positive EV
                        # Calculate position size
                        atr_val = df.loc[row.name, 'atr'] if row.name in df.index else 0.5
                        position_size = calculate_position_size(adjusted_ev, atr_val)
                        diagnostics["position_sizes"].append(position_size)

                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "LONG",
                            "price": row['close'],
                            "score": score,
                            "bucket": bucket,
                            "ev": adjusted_ev,
                            "position_size": position_size
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"LONG: score {score}, bucket {bucket}, EV {adjusted_ev:.3f} <= 0")

                elif use_ev and ev_table:
                    # Use historical EV lookup table (old approach)
                    base_ev = get_ev_for_score(ev_table, score)

                    # Apply symbol model adjustment
                    if symbol_model:
                        adjusted_ev = symbol_model.predict(base_ev, score, regime)
                    else:
                        adjusted_ev = base_ev

                    diagnostics["ev_decisions"].append((score, base_ev, adjusted_ev))

                    if adjusted_ev > 0:  # Only trade if positive adjusted EV
                        # Calculate position size
                        atr_val = df.loc[row.name, 'atr'] if row.name in df.index else 0.5
                        position_size = calculate_position_size(adjusted_ev, atr_val)
                        diagnostics["position_sizes"].append(position_size)

                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "LONG",
                            "price": row['close'],
                            "score": score,
                            "ev": adjusted_ev,
                            "position_size": position_size
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"LONG: score {score}, base_EV {base_ev:.3f}, adj_EV {adjusted_ev:.3f} <= 0")
                else:
                    # Threshold-based (original approach)
                    if score >= entry_threshold:
                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "LONG",
                            "price": row['close'],
                            "score": score
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"LONG: score {score} < threshold {entry_threshold:.1f}")

        # =========================
        # SHORT ENTRY CONDITIONS
        # =========================
        short_breakout = row['close'] < range_low

        if short_breakout:
            # Base entry conditions
            short_entry = (
                row['close'] < row['vwap'] and
                row['ema9'] < row['ema20'] and
                row['rvol'] > 1.3
            )

            if short_entry:
                diagnostics["total_signals"] += 1

                # SCORE 2: First impulse confirmation (AFTER trigger, not before)
                impulse_score = 0
                if i + 2 < len(df):
                    next_bar = df.iloc[i + 1]
                    next_next_bar = df.iloc[i + 2]
                    # Price continues in direction
                    if next_bar['close'] < row['close']:
                        impulse_score += 1
                    if next_next_bar['close'] < next_bar['close']:
                        impulse_score += 1
                score += impulse_score

                diagnostics["score_distribution"].append(score)

                # EV-based decision using continuous estimator, SYMBOL_EV matrix, or lookup table
                if use_continuous_ev:
                    # Use continuous EV estimator (new approach)
                    session = get_session(row.name)
                    ev = compute_continuous_ev(symbol, score, regime, atr_percentile, session)
                    diagnostics["ev_decisions"].append((score, ev, session))

                    if ev > 0:  # Only trade if positive EV
                        # Calculate position size
                        atr_val = df.loc[row.name, 'atr'] if row.name in df.index else 0.5
                        position_size = calculate_position_size(ev, atr_val, use_kelly=use_kelly)
                        diagnostics["position_sizes"].append(position_size)

                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "SHORT",
                            "price": row['close'],
                            "score": score,
                            "ev": ev,
                            "position_size": position_size
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"SHORT: score {score}, EV {ev:.3f} <= 0")

                elif use_symbol_ev_matrix:
                    # Use SYMBOL_EV matrix (legacy approach)
                    bucket = score_bucket(score)
                    diagnostics["bucket_distribution"].append(bucket)
                    base_ev = compute_ev(symbol, score)
                    adjusted_ev = base_ev  # No symbol model adjustment for matrix approach

                    diagnostics["ev_decisions"].append((score, bucket, base_ev))

                    if adjusted_ev > 0:  # Only trade if positive EV
                        # Calculate position size
                        atr_val = df.loc[row.name, 'atr'] if row.name in df.index else 0.5
                        position_size = calculate_position_size(adjusted_ev, atr_val)
                        diagnostics["position_sizes"].append(position_size)

                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "SHORT",
                            "price": row['close'],
                            "score": score,
                            "bucket": bucket,
                            "ev": adjusted_ev,
                            "position_size": position_size
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"SHORT: score {score}, bucket {bucket}, EV {adjusted_ev:.3f} <= 0")

                elif use_ev and ev_table:
                    # Use historical EV lookup table (old approach)
                    base_ev = get_ev_for_score(ev_table, score)

                    # Apply symbol model adjustment
                    if symbol_model:
                        adjusted_ev = symbol_model.predict(base_ev, score, regime)
                    else:
                        adjusted_ev = base_ev

                    diagnostics["ev_decisions"].append((score, base_ev, adjusted_ev))

                    if adjusted_ev > 0:  # Only trade if positive adjusted EV
                        # Calculate position size
                        atr_val = df.loc[row.name, 'atr'] if row.name in df.index else 0.5
                        position_size = calculate_position_size(adjusted_ev, atr_val)
                        diagnostics["position_sizes"].append(position_size)

                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "SHORT",
                            "price": row['close'],
                            "score": score,
                            "ev": adjusted_ev,
                            "position_size": position_size
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"SHORT: score {score}, base_EV {base_ev:.3f}, adj_EV {adjusted_ev:.3f} <= 0")
                else:
                    # Threshold-based (original approach)
                    if score >= entry_threshold:
                        diagnostics["accepted_signals"] += 1
                        entries.append({
                            "time": row.name,
                            "side": "SHORT",
                            "price": row['close'],
                            "score": score
                        })
                    else:
                        diagnostics["rejected_reasons"].append(f"SHORT: score {score} < threshold {entry_threshold:.1f}")

    return entries, diagnostics


# =========================================================
# TRADE ENGINE (EXITS + PnL ONLY)
# =========================================================

def backtest(df, entries, tp_pct=0.005, sl_pct=-0.003, use_dynamic_risk=False, transaction_cost=0.001):

    df = df.copy()

    df['vwap'] = vwap(df)
    df['ema9'] = ema(df['close'], 9)
    df['ema20'] = ema(df['close'], 20)
    df['atr'] = atr(df)

    trades = []
    trade_scores = []  # Track scores with outcomes

    for entry in entries:

        time = entry['time']
        direction = entry['side']
        entry_price = entry['price']
        entry_score = entry.get('score', 0)
        entry_ev = entry.get('ev', 0)
        symbol = entry.get('symbol', 'SPY')

        if time not in df.index:
            continue

        idx = df.index.get_loc(time)
        future = df.iloc[idx + 1: idx + 80]

        if len(future) == 0:
            continue

        atr_val = df.loc[time, 'atr']

        if pd.isna(atr_val):
            continue

        # Dynamic risk management (ATR-based SL, EV-based TP)
        if use_dynamic_risk:
            sl_distance, tp_distance = calculate_risk_parameters(symbol, entry_ev, atr_val)
            sl_price = entry_price - sl_distance if direction == "LONG" else entry_price + sl_distance
            tp_price = entry_price + tp_distance if direction == "LONG" else entry_price - tp_distance
        else:
            # Fixed percentage TP/SL (legacy)
            tp_price = entry_price * (1 + tp_pct) if direction == "LONG" else entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct) if direction == "LONG" else entry_price * (1 - sl_pct)

        stop_mult = 1.2

        if direction == "LONG":

            stop = entry_price - stop_mult * atr_val
            max_price = entry_price
            trail_active = False
            structure_break_count = 0
            min_hold_bars = 10
            safe_pullback_zone = 0.6 * atr_val
            max_safe_pullback = 0.9 * atr_val

            for bar_idx, (_, row) in enumerate(future.iterrows()):

                price = row['close']

                max_price = max(max_price, price)

                if price > entry_price + 1.2 * atr_val:
                    trail_active = True

                if price >= tp_price:
                    pnl = (price - entry_price) - transaction_cost
                    trades.append(pnl)
                    trade_scores.append((entry_score, pnl))
                    break
                if price <= sl_price:
                    pnl = (price - entry_price) - transaction_cost
                    trades.append(pnl)
                    trade_scores.append((entry_score, pnl))
                    break

                if price <= stop:
                    pnl = (price - entry_price) - transaction_cost
                    trades.append(pnl)
                    trade_scores.append((entry_score, pnl))
                    break

                if bar_idx >= min_hold_bars and trail_active:
                    pullback = max_price - price
                    if safe_pullback_zone <= pullback <= max_safe_pullback:
                        continue

                    if price < row['vwap'] and row['ema9'] < row['ema20']:
                        structure_break_count += 1
                        if structure_break_count >= 2:
                            pnl = (price - entry_price) - transaction_cost
                            trades.append(pnl)
                            trade_scores.append((entry_score, pnl))
                            break
                    else:
                        structure_break_count = 0

                    trail_stop = max_price - 1.0 * atr_val
                    if price <= trail_stop:
                        pnl = (price - entry_price) - transaction_cost
                        trades.append(pnl)
                        trade_scores.append((entry_score, pnl))
                        break

            else:
                pnl = (future.iloc[-1]['close'] - entry_price) - transaction_cost
                trades.append(pnl)
                trade_scores.append((entry_score, pnl))

        else:  # SHORT

            stop = entry_price + stop_mult * atr_val
            min_price = entry_price
            trail_active = False
            structure_break_count = 0
            min_hold_bars = 10
            safe_pullback_zone = 0.6 * atr_val
            max_safe_pullback = 0.9 * atr_val

            for bar_idx, (_, row) in enumerate(future.iterrows()):

                price = row['close']

                min_price = min(min_price, price)

                if price < entry_price - 1.2 * atr_val:
                    trail_active = True

                if price <= tp_price:
                    pnl = (entry_price - price) - transaction_cost
                    trades.append(pnl)
                    trade_scores.append((entry_score, pnl))
                    break
                if price >= sl_price:
                    pnl = (entry_price - price) - transaction_cost
                    trades.append(pnl)
                    trade_scores.append((entry_score, pnl))
                    break

                if price >= stop:
                    pnl = (entry_price - price) - transaction_cost
                    trades.append(pnl)
                    trade_scores.append((entry_score, pnl))
                    break

                if bar_idx >= min_hold_bars and trail_active:
                    pullback = price - min_price
                    if safe_pullback_zone <= pullback <= max_safe_pullback:
                        continue

                    if price > row['vwap'] and row['ema9'] > row['ema20']:
                        structure_break_count += 1
                        if structure_break_count >= 2:
                            pnl = (entry_price - price) - transaction_cost
                            trades.append(pnl)
                            trade_scores.append((entry_score, pnl))
                            break
                    else:
                        structure_break_count = 0

                    if trail_active:
                        trail_stop = min_price + 1.0 * atr_val
                        if price >= trail_stop:
                            pnl = (entry_price - price) - transaction_cost
                            trades.append(pnl)
                            trade_scores.append((entry_score, pnl))
                            break

            else:
                pnl = (entry_price - future.iloc[-1]['close']) - transaction_cost
                trades.append(pnl)
                trade_scores.append((entry_score, pnl))

    trades = np.array(trades)

    return {
        "trades": len(trades),
        "win_rate": np.mean(trades > 0),
        "avg_pnl": np.mean(trades),
        "expectancy": np.mean(trades),
        "profit_factor": np.sum(trades[trades > 0]) / (abs(np.sum(trades[trades < 0])) + 1e-9),
        "trade_scores": trade_scores
    }


def score_bucket(score):
    """Discretize score into buckets (legacy, not used in continuous estimator)"""
    if score < 2.0:
        return "low"
    elif score < 3.0:
        return "mid"
    elif score < 4.0:
        return "high"
    else:
        return "extreme"


# SYMBOL_EV MATRIX - legacy, replaced by continuous estimator
# SYMBOL_EV = {
#     "AMD": {"low": -0.05, "mid": 0.11, "high": 1.15, "extreme": 1.15},
#     "TSLA": {"low": -0.08, "mid": 0.27, "high": 0.02, "extreme": 0.02},
#     "SPY": {"low": -0.03, "mid": -0.07, "high": 0.13, "extreme": 0.29},
#     "QQQ": {"low": -0.06, "mid": -0.34, "high": 0.33, "extreme": 0.33}
# }


# CONTINUOUS EV ESTIMATOR
SYMBOL_MULTIPLIER = {
    "AMD": 1.25,
    "TSLA": 1.10,
    "SPY": 1.00,
    "QQQ": 0.85,
    "NVDA": 1.15,
    "PLTR": 1.15,
    "AAPL": 0.95,
    "MSFT": 0.90,
    "AMZN": 1.05,
    "AVGO": 0.95
}

REGIME_MULTIPLIER = {
    "EXPANSION": 1.1,
    "NORMAL": 0.8,  # CHOP
    "COMPRESSION": 0.9
}

# Session multipliers (time-of-day adjustments)
SESSION_MULTIPLIER = {
    "SPY": {
        "OPEN": 1.2,
        "MID": 0.9,
        "CLOSE": 1.0
    },
    "QQQ": {
        "OPEN": 1.3,
        "MID": 0.7,
        "CLOSE": 0.9
    },
    "TSLA": {
        "OPEN": 1.1,
        "MID": 1.0,
        "CLOSE": 1.1
    },
    "AMD": {
        "OPEN": 1.25,
        "MID": 1.05,
        "CLOSE": 1.15
    },
    "NVDA": {
        "OPEN": 1.2,
        "MID": 1.0,
        "CLOSE": 1.1
    }
}

# Risk Management: Symbol-aware TP adjustments
SYMBOL_TP_MULTIPLIER = {
    # Stocks
    "AMD": 1.2,
    "TSLA": 1.0,
    "SPY": 0.9,
    "QQQ": 0.8,
    "NVDA": 1.0,
    "PLTR": 1.1,
    "AAPL": 0.85,
    "MSFT": 0.85,
    "AMZN": 0.95,
    "AVGO": 0.9,
    # Crypto (higher volatility = tighter TP)
    "BTC": 0.7,
    "ETH": 0.75,
    "SOL": 0.8,
    "XRP": 0.85,
    "DOGE": 0.9,
    "default": 1.0
}


def get_session(timestamp):
    """Determine trading session from timestamp"""
    t = timestamp.time()

    if t >= pd.Timestamp("09:30").time() and t < pd.Timestamp("10:30").time():
        return "OPEN"
    elif t >= pd.Timestamp("10:30").time() and t < pd.Timestamp("14:00").time():
        return "MID"
    else:
        return "CLOSE"


def calculate_tp_multiplier(ev):
    """
    Map EV to TP multiplier (reward: risk ratio)
    EV < 0.05: 1.2R (weak edge, quick exit)
    EV < 0.15: 1.5R (moderate edge)
    EV >= 0.15: 2.0R (strong edge, let it run)
    """
    if ev < 0.05:
        return 1.2
    elif ev < 0.15:
        return 1.5
    else:
        return 2.0


def calculate_risk_parameters(symbol, ev, atr_value):
    """
    Calculate ATR-based stop loss and EV-based take profit

    Args:
        symbol: Trading symbol
        ev: Expected value from continuous estimator
        atr_value: Current ATR value

    Returns:
        sl_distance: Stop loss distance in price units (0.8 * ATR)
        tp_distance: Take profit distance in price units (EV-based * symbol adjustment)
    """
    # Step 1: ATR-based stop loss
    sl_distance = 0.8 * atr_value

    # Step 2: EV → TP multiplier
    tp_multiplier = calculate_tp_multiplier(ev)

    # Step 3: Symbol-aware adjustment
    symbol_tp_mult = SYMBOL_TP_MULTIPLIER.get(symbol, SYMBOL_TP_MULTIPLIER["default"])

    # Final TP distance
    tp_distance = sl_distance * tp_multiplier * symbol_tp_mult

    return sl_distance, tp_distance


def compute_continuous_ev(symbol, score, regime, atr_percentile=0.5, session="MID"):
    """
    Compute continuous EV from score, symbol, regime, volatility, and session

    EV = base_ev(score) * symbol_multiplier(symbol) * session_multiplier(symbol, session) * regime_multiplier(regime) * volatility_adjustment(atr_state)
    """
    # Base EV from score
    base_ev = (score - 3.0) * 0.08

    # Symbol multiplier
    sym_mult = SYMBOL_MULTIPLIER.get(symbol, 1.0)

    # Session multiplier
    session_mults = SESSION_MULTIPLIER.get(symbol, {"OPEN": 1.0, "MID": 1.0, "CLOSE": 1.0})
    sess_mult = session_mults.get(session, 1.0)

    # Regime multiplier
    reg_mult = REGIME_MULTIPLIER.get(regime, 1.0)

    # Volatility adjustment
    if atr_percentile > 0.7:
        vol_adj = 0.9  # High volatility - slight reduction
    elif atr_percentile < 0.3:
        vol_adj = 1.1  # Low volatility - slight boost
    else:
        vol_adj = 1.0

    # Final EV
    ev = base_ev * sym_mult * sess_mult * reg_mult * vol_adj

    return ev


def build_ev_lookup_table(trade_scores, bucket_size=0.5):
    """Build EV lookup table from historical score buckets"""
    ev_table = {}

    if not trade_scores:
        return ev_table

    # Group by score buckets
    buckets = {}
    for score, pnl in trade_scores:
        bucket = round(score / bucket_size) * bucket_size
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(pnl)

    # Calculate EV for each bucket
    for bucket, pnls in buckets.items():
        ev_table[bucket] = np.mean(pnls)

    return ev_table


def get_ev_for_score(ev_table, score, bucket_size=0.5):
    """Get EV for a given score using bucket lookup"""
    bucket = round(score / bucket_size) * bucket_size
    return ev_table.get(bucket, 0)


class SymbolEdgeModel:
    """Symbol-specific edge model with regime interaction"""

    def __init__(self, symbol):
        self.symbol = symbol
        self.model_type = self._get_model_type()

    def _get_model_type(self):
        """Determine model type based on symbol characteristics"""
        if self.symbol == "SPY":
            return "momentum_decay"
        elif self.symbol == "QQQ":
            return "mean_reversion"
        elif self.symbol == "TSLA":
            return "momentum_continuation"
        elif self.symbol == "AMD":
            return "volatility_breakout"
        else:
            return "neutral"

    def predict(self, base_ev, score, regime):
        """
        Adjust base EV based on symbol model and regime

        Args:
            base_ev: Base EV from lookup table
            score: Feature score
            regime: Market regime (EXPANSION, COMPRESSION, NORMAL)

        Returns:
            Adjusted EV
        """
        if self.model_type == "momentum_decay":
            # SPY: EV curve + mild momentum decay
            # Higher scores get slight decay adjustment
            decay_factor = 1.0 - (score * 0.05)  # 5% decay per score point
            adjusted_ev = base_ev * decay_factor

            # Regime adjustment
            if regime == "EXPANSION":
                adjusted_ev *= 1.1  # Boost in expansion
            elif regime == "COMPRESSION":
                adjusted_ev *= 0.8  # Reduce in compression

        elif self.model_type == "mean_reversion":
            # QQQ: Mean reversion bias
            # Invert score impact - lower scores can be better
            inversion_factor = 1.0 - (score * 0.1)
            adjusted_ev = base_ev * inversion_factor

            # Regime adjustment - opposite of momentum
            if regime == "EXPANSION":
                adjusted_ev *= 0.7  # Reduce in expansion (bad for mean reversion)
            elif regime == "COMPRESSION":
                adjusted_ev *= 1.3  # Boost in compression (good for mean reversion)

        elif self.model_type == "momentum_continuation":
            # TSLA: Strong momentum continuation
            # Higher scores get amplified
            momentum_factor = 1.0 + (score * 0.15)  # 15% boost per score point
            adjusted_ev = base_ev * momentum_factor

            # Regime adjustment
            if regime == "EXPANSION":
                adjusted_ev *= 1.2  # Strong boost in expansion
            elif regime == "COMPRESSION":
                adjusted_ev *= 0.9  # Slight reduction in compression

        elif self.model_type == "volatility_breakout":
            # AMD: High volatility breakout continuation
            # Non-linear amplification for high scores
            if score >= 4:
                breakout_factor = 1.5  # 50% boost for high scores
            elif score >= 3:
                breakout_factor = 1.2  # 20% boost for medium scores
            else:
                breakout_factor = 1.0

            adjusted_ev = base_ev * breakout_factor

            # Regime adjustment
            if regime == "EXPANSION":
                adjusted_ev *= 1.3  # Strong boost in expansion
            elif regime == "COMPRESSION":
                adjusted_ev *= 0.6  # Significant reduction in compression

        else:  # neutral
            adjusted_ev = base_ev

        return adjusted_ev


def calculate_position_size(ev, volatility, base_size=1.0, win_rate=0.70, use_kelly=False):
    """
    Calculate position size based on EV and volatility (Boof 15.0) or Kelly criterion (Boof 16.0)

    Args:
        ev: Expected value
        volatility: ATR or volatility measure
        base_size: Base position size
        win_rate: Historical win rate for Kelly criterion
        use_kelly: Use Kelly criterion instead of EV-based sizing

    Returns:
        Adjusted position size
    """
    if use_kelly:
        # Kelly criterion: f* = (bp - q) / b
        # where b = odds, p = win probability, q = loss probability
        # Simplified: Kelly % = (Win% * AvgWin - Loss% * AvgLoss) / AvgWin
        # We use EV as proxy for (Win% * AvgWin - Loss% * AvgLoss)
        
        # Conservative Kelly (half-Kelly to reduce drawdown risk)
        kelly_fraction = (ev * 0.5)  # Half-Kelly
        
        # Cap Kelly at 25% of capital per trade
        kelly_fraction = min(kelly_fraction, 0.25)
        
        # Adjust for volatility
        vol_factor = 1.0 / (1.0 + volatility * 0.5)
        
        adjusted_size = base_size * kelly_fraction * vol_factor * 4  # Scale up for practical sizing
        
        return max(adjusted_size, 0.1)  # Minimum 10% of base
    else:
        # Boof 15.0: EV-based sizing
        ev_factor = min(ev * 5, 2.0)  # Cap at 2x
        vol_factor = 1.0 / (1.0 + volatility * 0.5)
        adjusted_size = base_size * ev_factor * vol_factor
        return max(adjusted_size, 0.1)  # Minimum 10% of base

def run_system(df, symbol="SPY", tp_pct=0.005, sl_pct=-0.003, ev_table=None, use_ev=False, symbol_model=None, use_symbol_ev_matrix=False, use_continuous_ev=False, use_dynamic_risk=False, use_kelly=False, transaction_cost=0.001):

    regime = classify_regime(df)
    entries, diagnostics = generate_entries(df, symbol, ev_table, use_ev, symbol_model, use_symbol_ev_matrix, use_continuous_ev, use_kelly)

    results = backtest(df, entries, tp_pct, sl_pct, use_dynamic_risk, transaction_cost)

    return {
        "regime": regime,
        "diagnostics": diagnostics,
        **results
    }


# =========================================================
# DATA DOWNLOAD
# =========================================================

def download_data_in_chunks(ticker, start_date, end_date, interval='1m', api_key=None, secret_key=None):
    """Download data using Alpaca API for historical data (no 30-day limit)"""
    if api_key and secret_key:
        # Use Alpaca API
        print(f"  Downloading {ticker} from Alpaca API...")
        df = fetch_alpaca_bars(ticker, start_date, end_date, timeframe='1Min', api_key=api_key, secret_key=secret_key)
        if df is not None and len(df) > 0:
            df.columns = [c.lower() for c in df.columns]
            return df
        else:
            print(f"  Alpaca failed, falling back to Yahoo...")
    
    # Fallback to Yahoo Finance (limited to 30 days)
    dfs = []
    current = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    
    while current < end:
        chunk_end = min(current + timedelta(days=7), end)
        print(f"  Downloading {current.date()} to {chunk_end.date()} from Yahoo...")
        
        chunk = yf.download(ticker, start=current.strftime("%Y-%m-%d"),
                          end=chunk_end.strftime("%Y-%m-%d"), interval=interval, progress=False)
        
        if len(chunk) > 0:
            # Flatten multi-index columns if present
            if isinstance(chunk.columns, pd.MultiIndex):
                chunk.columns = chunk.columns.get_level_values(0)
            dfs.append(chunk)
        
        current = chunk_end + timedelta(days=1)
    
    if dfs:
        df = pd.concat(dfs).sort_index()
        # Ensure lowercase column names
        df.columns = [c.lower() for c in df.columns]
        return df
    return pd.DataFrame()


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    # Backtest March 26 - May 23, 2026 (today)
    start_date = datetime(2026, 3, 26)
    end_date = datetime(2026, 5, 23)

    # Fetch Alpaca credentials
    print("Using provided Alpaca credentials...")
    alpaca_creds = get_alpaca_credentials()
    alpaca_api_key = alpaca_creds.get('api_key') if alpaca_creds else None
    alpaca_secret_key = alpaca_creds.get('secret_key') if alpaca_creds else None
    
    if alpaca_api_key and alpaca_secret_key:
        print("Alpaca credentials loaded successfully")
    else:
        print("No Alpaca credentials found, will use Yahoo Finance (limited to 30 days)")

    results = {}
    ev_tables = {}  # Store EV tables per symbol

    # PHASE 1: Build EV tables using threshold-based entries
    print("="*60)
    print("PHASE 1: Building EV Lookup Tables")
    print("="*60)

    for ticker in ["QQQ", "SPY", "TSLA", "NVDA", "AMD", "AAPL", "MSFT", "AMZN"]:
        print(f"\nDownloading {ticker} data...")
        df = download_data_in_chunks(ticker, start_date, end_date, '1m', alpaca_api_key, alpaca_secret_key)

        if len(df) == 0:
            print(f"No data found for {ticker}")
            continue

        print(f"Downloaded {len(df)} candles")

        # Run with threshold-based to build EV table
        result = run_system(df, ticker)

        # Build EV table from trade scores
        trade_scores = result.get('trade_scores', [])
        if trade_scores:
            ev_table = build_ev_lookup_table(trade_scores)
            ev_tables[ticker] = ev_table
            print(f"{ticker} EV Table: {ev_table}")
        else:
            print(f"{ticker}: No trades to build EV table")

    # PHASE 4: Run with Continuous EV Estimator (new approach)
    print("\n" + "="*60)
    print("PHASE 4: Continuous EV Estimator System")
    print("="*60)

    for ticker in ["QQQ", "SPY", "TSLA", "NVDA", "AMD", "AAPL", "MSFT", "AMZN"]:
        print(f"\n{'='*60}")
        print(f"BACKTEST: {ticker} | {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} | 1m")
        print(f"{'='*60}\n")

        df = download_data_in_chunks(ticker, start_date, end_date, '1m', alpaca_api_key, alpaca_secret_key)

        if len(df) == 0:
            print(f"No data found for {ticker}")
            continue

        print(f"Downloaded {len(df)} candles\n")

        print(f"Symbol Multiplier: {SYMBOL_MULTIPLIER[ticker]}")
        print(f"Regime Multipliers: {REGIME_MULTIPLIER}")
        print(f"TP Multipliers: {SYMBOL_TP_MULTIPLIER}")

        print("Running Boof 16.0 system with Kelly criterion + transaction costs + continuous EV estimator + dynamic risk management...")
        result = run_system(df, ticker, use_continuous_ev=True, use_dynamic_risk=True, use_kelly=True, transaction_cost=0.001)

        # Print results
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}\n")

        print(f"Regime: {result['regime']}")
        print(f"Total Trades: {result['trades']}")
        print(f"Win Rate: {result['win_rate']*100:.1f}%")
        print(f"Avg PnL: ${result['avg_pnl']:.4f}")
        print(f"Expectancy: ${result['expectancy']:.4f}")
        print(f"Profit Factor: {result['profit_factor']:.2f}")

        # Print diagnostics
        diag = result.get('diagnostics', {})
        if diag:
            print(f"\n{'='*60}")
            print(f"DIAGNOSTICS")
            print(f"{'='*60}\n")
            print(f"Total Signals: {diag.get('total_signals', 0)}")
            print(f"Accepted Signals: {diag.get('accepted_signals', 0)}")
            print(f"Acceptance Rate: {diag.get('accepted_signals', 0) / max(diag.get('total_signals', 1), 1) * 100:.1f}%")

            if diag.get('score_distribution'):
                scores = diag['score_distribution']
                print(f"Score Distribution: min={min(scores):.1f}, max={max(scores):.1f}, avg={np.mean(scores):.2f}")

            if diag.get('bucket_distribution'):
                from collections import Counter
                buckets = Counter(diag['bucket_distribution'])
                print(f"Bucket Distribution: {dict(buckets)}")

            if diag.get('ev_decisions'):
                ev_decisions = diag['ev_decisions']
                if len(ev_decisions) > 0:
                    if isinstance(ev_decisions[0], tuple) and len(ev_decisions[0]) == 3:
                        # Continuous estimator format with session: (score, ev, session)
                        ev_values = [ev for _, ev, _ in ev_decisions]
                        sessions = [sess for _, _, sess in ev_decisions]
                        print(f"EV Distribution: min={min(ev_values):.3f}, max={max(ev_values):.3f}, avg={np.mean(ev_values):.3f}")
                        from collections import Counter
                        session_counts = Counter(sessions)
                        print(f"Session Distribution: {dict(session_counts)}")
                    elif isinstance(ev_decisions[0], tuple) and len(ev_decisions[0]) == 2:
                        # Old continuous estimator format: (score, ev)
                        ev_values = [ev for _, ev in ev_decisions]
                        print(f"EV Distribution: min={min(ev_values):.3f}, max={max(ev_values):.3f}, avg={np.mean(ev_values):.3f}")
                    elif isinstance(ev_decisions[0], tuple) and len(ev_decisions[0]) == 3:
                        # SYMBOL_EV matrix format: (score, bucket, ev)
                        ev_values = [ev for _, _, ev in ev_decisions]
                        print(f"EV Distribution: min={min(ev_values):.3f}, max={max(ev_values):.3f}, avg={np.mean(ev_values):.3f}")
                    else:
                        # Old format: (score, base_ev, adj_ev)
                        base_evs = [base for _, base, _ in ev_decisions]
                        adj_evs = [adj for _, _, adj in ev_decisions]
                        print(f"Base EV Distribution: min={min(base_evs):.3f}, max={max(base_evs):.3f}, avg={np.mean(base_evs):.3f}")
                        print(f"Adjusted EV Distribution: min={min(adj_evs):.3f}, max={max(adj_evs):.3f}, avg={np.mean(adj_evs):.3f}")

            if diag.get('position_sizes'):
                pos_sizes = diag['position_sizes']
                print(f"Position Size Distribution: min={min(pos_sizes):.2f}, max={max(pos_sizes):.2f}, avg={np.mean(pos_sizes):.2f}")

            if diag.get('rejected_reasons'):
                print(f"\nTop Rejection Reasons:")
                from collections import Counter
                reasons = Counter(diag['rejected_reasons'])
                for reason, count in reasons.most_common(5):
                    print(f"  {reason}: {count}")

        results[ticker] = result

    print(f"\n{'='*60}")
    print("BACKTEST COMPLETE")
    print(f"{'='*60}")
