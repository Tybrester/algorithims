import pandas as pd
import numpy as np

# =============================================================================
# BOOF 22.0 — Volume Cluster Array + ZigZag ATR Swing + Nearest SR Filter
# =============================================================================
# Upgrades over v1:
#   1. Real cluster array: clusterPrices[], clusterStrengths[] built from
#      high-volume bar price buckets, merged within ATR tolerance
#   2. ZigZag ATR swing engine replaces ta.highest(high, 5):
#      fractal confirmation — bar[i] is a peak if high[i] > high[i-2..i-1]
#      AND high[i] > high[i+1..i+2], confirmed by ATR rejection close
#   3. Nearest SR distance filter: entry only if current price is within
#      1x ATR of a cluster level with strength >= threshold
# =============================================================================

ATR_LEN         = 14
VOL_LEN         = 50
MAX_HOLD_MIN    = 30
CLUSTER_MERGE   = 0.5      # merge cluster levels within ATR * this factor
SR_DIST_MAX     = 1.0      # max distance to nearest cluster (ATR multiples)
SR_STRENGTH_MIN = 2        # min touches to count as valid SR cluster
FRACTAL_BARS    = 3        # bars each side for fractal confirmation

# ─────────────────────────────────────────────────────────────────
# BOOFINGTON — official Boof 22 scan list
# Ranked by annual P&L (2025–2026 backtest, atr_mult=0.6, tiered sizing)
# Core signals (slack>=1.4): $600/trade | Expanded (slack<1.4): $200/trade
# ~65 trades/day | WR ~60% | PF ~25 | EV ~$8.40/trade | ~$200k/yr
# ─────────────────────────────────────────────────────────────────
BOOFINGTON = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']

# Active symbols: NVDA, META, AAPL, GOOGL, AMD (top performers, ~65 trades/day)
SYMBOL_PARAMS = {
    'NVDA': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'META': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AAPL': {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0},
    'GOOGL':{'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AMD':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
}

DEFAULT_PARAMS = {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0}


def compute_atr(df, period=ATR_LEN):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def build_cluster_array(df, atr_series, vol_mult=1.3):
    """
    Build clusterPrices[] and clusterStrengths[] from high-volume bars.
    Each high-volume bar contributes its price (hl2) to a bucket.
    Buckets within ATR*CLUSTER_MERGE are merged into one cluster level.
    Returns list of (price, strength) sorted by strength desc.
    """
    vol_sma  = df['volume'].rolling(VOL_LEN).mean()
    hi_vol   = df['volume'] > vol_sma * vol_mult
    hl2      = (df['high'] + df['low']) / 2
    avg_atr  = atr_series.median()

    if avg_atr == 0 or pd.isna(avg_atr):
        return [], []

    merge_tol = avg_atr * CLUSTER_MERGE
    buckets   = []  # list of [price, strength]

    for i in range(len(df)):
        if not hi_vol.iloc[i]:
            continue
        price = hl2.iloc[i]
        merged = False
        for b in buckets:
            if abs(b[0] - price) <= merge_tol:
                b[0] = (b[0] * b[1] + price) / (b[1] + 1)  # weighted avg
                b[1] += 1
                merged = True
                break
        if not merged:
            buckets.append([price, 1])

    buckets = [b for b in buckets if b[1] >= SR_STRENGTH_MIN]
    buckets.sort(key=lambda x: -x[1])

    cluster_prices    = [b[0] for b in buckets]
    cluster_strengths = [b[1] for b in buckets]
    return cluster_prices, cluster_strengths


def nearest_sr_distance(price, cluster_prices, atr):
    """
    Returns distance to nearest SR level in ATR units.
    Returns inf if no clusters exist.
    """
    if not cluster_prices or atr == 0:
        return float('inf')
    dists = [abs(price - cp) / atr for cp in cluster_prices]
    return min(dists)


def run_boof22(df, symbol='SPY', tp_pct=0.40, sl_pct=-0.15, rvol_min=80):
    """
    Run Boof 22.0 backtest on 1-min OHLCV dataframe.
    Returns list of trade dicts.
    """
    params   = SYMBOL_PARAMS.get(symbol, DEFAULT_PARAMS)
    atr_mult = params['atr_mult']
    vol_mult = params['vol_mult']
    sr_dist  = params['sr_dist']

    df = df.copy().reset_index(drop=True)
    if len(df) < max(ATR_LEN, VOL_LEN, FRACTAL_BARS * 2) + 10:
        return []

    atr_series   = compute_atr(df)
    df['atr']    = atr_series
    df['vol_sma']= df['volume'].rolling(VOL_LEN).mean()
    df['rvol']   = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol'] = df['volume'] > df['vol_sma'] * vol_mult

    # Build cluster array from entire session
    cluster_prices, cluster_strengths = build_cluster_array(df, atr_series, vol_mult)

    F = FRACTAL_BARS
    trades   = []
    in_trade = False
    entry_price = direction = None
    entry_bar   = 0
    entry_slack = 0.0
    tp_price = sl_price = 0.0

    for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - 1):
        row = df.iloc[i]

        # --- Exit logic ---
        if in_trade:
            nxt        = df.iloc[i + 1]
            exit_price = None
            exit_type  = None
            bars_held  = i - entry_bar

            if direction == 'long':
                if nxt['high'] >= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['low'] <= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
                elif bars_held >= MAX_HOLD_MIN:
                    exit_price, exit_type = nxt['close'], 'time'
            else:
                if nxt['low'] <= tp_price:
                    exit_price, exit_type = tp_price, 'tp'
                elif nxt['high'] >= sl_price:
                    exit_price, exit_type = sl_price, 'sl'
                elif bars_held >= MAX_HOLD_MIN:
                    exit_price, exit_type = nxt['close'], 'time'

            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price
                if direction == 'short':
                    pnl_pct = -pnl_pct
                trades.append({
                    'symbol':    symbol,
                    'direction': direction,
                    'entry':     entry_price,
                    'exit':      exit_price,
                    'exit_type': exit_type,
                    'pnl_pct':   pnl_pct,
                    'bar':       i,
                    'slack':     entry_slack,
                    'tier':      'core' if entry_slack >= 1.4 else 'expanded',
                })
                in_trade = False
            continue

        # --- RVOL gate ---
        if row['rvol'] < rvol_min:
            continue

        atr    = row['atr']
        hi_vol = row['hi_vol']

        if pd.isna(atr) or atr == 0 or not hi_vol:
            continue

        # --- ZigZag fractal peak: high[i] > high[i-F..i-1] AND high[i] > high[i+1..i+F] ---
        highs  = df['high'].values
        lows   = df['low'].values
        closes = df['close'].values

        left_highs  = highs[i - F: i]
        right_highs = highs[i + 1: i + F + 1]
        left_lows   = lows[i - F: i]
        right_lows  = lows[i + 1: i + F + 1]

        fractal_peak   = (highs[i] > left_highs.max()) and (highs[i] > right_highs.max())
        fractal_trough = (lows[i]  < left_lows.min())  and (lows[i]  < right_lows.min())

        # ATR rejection confirmation
        atr_rejected_peak   = closes[i] < highs[i] - atr * atr_mult
        atr_bounced_trough  = closes[i] > lows[i]  + atr * atr_mult

        # Slack ratio — used for tiered trade sizing (Core>=1.4: $600, Expanded<1.4: $200)
        peak_slack   = (highs[i] - closes[i]) / atr if atr > 0 else 0
        trough_slack = (closes[i] - lows[i])  / atr if atr > 0 else 0

        # Nearest SR cluster distance filter
        dist_to_sr = nearest_sr_distance(row['close'], cluster_prices, atr)

        if dist_to_sr > sr_dist:
            continue

        is_peak   = fractal_peak   and atr_rejected_peak
        is_trough = fractal_trough and atr_bounced_trough

        if is_peak:
            entry_price = df.iloc[i + 1]['open']
            direction   = 'short'
            tp_price    = entry_price * (1 - abs(tp_pct))
            sl_price    = entry_price * (1 + abs(sl_pct))
            entry_bar   = i + 1
            entry_slack = peak_slack
            in_trade    = True

        elif is_trough:
            entry_price = df.iloc[i + 1]['open']
            direction   = 'long'
            tp_price    = entry_price * (1 + tp_pct)
            sl_price    = entry_price * (1 + sl_pct)
            entry_bar   = i + 1
            entry_slack = trough_slack
            in_trade    = True

    return trades
