"""
volume_cluster_sr.py
====================
Exact Python port of the QuantAlgo Volume Cluster S/R Pine Script.
Pine stays on the chart for visuals — this runs the strategy logic.

Main function:
    levels = build_levels(df, lookback=100, vol_threshold=1.3, cluster_pct=0.5)

Returns list of dicts:
    {
        'price':              float,   # VWAP-weighted cluster price
        'strength':           float,   # total volume of the cluster (HV bars)
        'total_vol':          float,   # total volume of all bars touching this level
        'touches':            int,     # number of bars that touched this level
        'is_support':         bool,    # True if cluster price < current close
        'level_strength':     float,   # Pine: (totalVol / avgVol) + (touches * 2)
        'is_broken_support':  bool,    # support that price has closed below
        'is_broken_res':      bool,    # resistance that price has closed above
        'flip_to_support':    bool,    # broken resistance now acting as support
        'flip_to_resistance': bool,    # broken support now acting as resistance
    }
Sorted by level_strength descending (strongest levels first).
"""

import numpy as np
import pandas as pd


def build_levels(df: pd.DataFrame,
                 lookback:       int   = 100,
                 vol_threshold:  float = 1.3,
                 cluster_pct:    float = 0.5,
                 confirmed:      bool  = False) -> list[dict]:
    """
    Direct port of the Pine Script core calculation block.

    Args:
        df            — OHLCV DataFrame (columns: open, high, low, close, volume)
        lookback      — number of bars to look back (Pine: safeLookback)
        vol_threshold — volume spike multiplier (Pine: volumeThreshold)
        cluster_pct   — price cluster % (Pine: priceClusterPct)
        confirmed     — if True, skip current bar (Pine: useConfirmedData)

    Returns sorted list of level dicts, strongest first.
    """
    offset    = 1 if confirmed else 0
    n         = len(df)
    safe_lb   = min(lookback, n - offset)

    if safe_lb <= 0:
        return []

    window = df.iloc[n - safe_lb - offset: n - offset] if offset else df.iloc[n - safe_lb:]

    avg_vol       = window['volume'].mean()
    current_close = window['close'].iloc[-1]

    if avg_vol <= 0 or current_close <= 0:
        return []

    # ── Step 1: collect high-volume bar typical prices (Pine: hvPrices) ──
    hv_prices, hv_volumes = [], []
    for i in range(len(window)):
        vol = window['volume'].iloc[i]
        if vol > 0 and vol > avg_vol * vol_threshold:
            tp = (window['high'].iloc[i] + window['low'].iloc[i] + window['close'].iloc[i]) / 3.0
            hv_prices.append(tp)
            hv_volumes.append(float(vol))

    if not hv_prices:
        return []

    # ── Step 2: cluster nearby prices (Pine: clusterPrices) ──
    cluster_range = current_close * (cluster_pct / 100.0)
    used          = [False] * len(hv_prices)
    cluster_prices, cluster_strengths = [], []

    # Pine iterates i=0..n in order (first-seen anchors the cluster)
    for i in range(len(hv_prices)):
        if used[i]:
            continue
        base_price   = hv_prices[i]
        total_vol    = hv_volumes[i]
        weighted_sum = base_price * hv_volumes[i]
        used[i]      = True

        for j in range(len(hv_prices)):
            if j != i and not used[j]:
                if abs(hv_prices[j] - base_price) <= cluster_range:
                    total_vol    += hv_volumes[j]
                    weighted_sum += hv_prices[j] * hv_volumes[j]
                    used[j]       = True

        if total_vol > 0:
            cluster_prices.append(weighted_sum / total_vol)
            cluster_strengths.append(total_vol)

    if not cluster_prices:
        return []

    # ── Step 3: count touches + total volume per cluster ──
    highs   = window['high'].values
    lows    = window['low'].values
    volumes = window['volume'].values

    total_vols, touch_counts = [], []
    for cp in cluster_prices:
        tv, tc = 0.0, 0
        for i in range(len(window)):
            if lows[i] <= cp <= highs[i]:
                tv += volumes[i]
                tc += 1
        total_vols.append(tv)
        touch_counts.append(tc)

    # ── Step 4: compute levelStrength + sort descending (Pine: sortedPrices) ──
    # Pine: levelStrength = (touches * 2) + ((totalVol / avgVol) * 3)
    level_strengths = [
        (touch_counts[idx] * 2) + ((total_vols[idx] / avg_vol) * 3)
        for idx in range(len(cluster_prices))
    ]

    closes = window['close'].values

    order = np.argsort(level_strengths)[::-1]
    levels = []
    for idx in order:
        price_lvl  = cluster_prices[idx]
        is_support = price_lvl < current_close

        # ── Level state flags (Pine Step 3) ──
        # Replay the window close-by-close to detect break → flip transitions
        broken_as_support = False    # support broken: close < price
        broken_as_res     = False    # resistance broken: close > price
        flip_to_support   = False    # broken resistance retested from below (close < price after break)
        flip_to_resistance= False    # broken support retested from above (close > price after break)

        for c in closes:
            if is_support:
                if not broken_as_support and c < price_lvl:
                    broken_as_support = True
                if broken_as_support and c > price_lvl:
                    flip_to_resistance = True
            else:
                if not broken_as_res and c > price_lvl:
                    broken_as_res = True
                if broken_as_res and c < price_lvl:
                    flip_to_support = True

        is_broken_support = broken_as_support
        is_broken_res     = broken_as_res

        levels.append({
            'price':              price_lvl,
            'strength':           cluster_strengths[idx],
            'total_vol':          total_vols[idx],
            'touches':            touch_counts[idx],
            'is_support':         is_support,
            'level_strength':     level_strengths[idx],
            'is_broken_support':  is_broken_support,
            'is_broken_res':      is_broken_res,
            'flip_to_support':    flip_to_support,
            'flip_to_resistance': flip_to_resistance,
        })

    return levels


# =============================================================
# STEP 4 — TRADE SIGNALS (Pine port)
# =============================================================

def breakout_signals(close_prev: float, close_now: float,
                     volume: float, avg_vol: float,
                     vol_threshold: float, min_strength: float,
                     levels: list,
                     open_now: float = None,
                     close_prev2: float = None) -> dict:
    """
    2-bar confirmed breakout (Pine port):

        Bar 1 (breakoutLong):
            close > resistance and close[1] <= resistance and close > open

        Bar 2 (confirmLong):
            breakoutLong and close[1] > resistance
            i.e. the previous bar already broke out and held above

    When close_prev2 is provided: require BOTH bars (full confirmation).
    When close_prev2 is None: single-bar crossover only (legacy fallback).
    """
    vol_ok = volume > avg_vol * vol_threshold
    longs, shorts = [], []
    for lvl in levels:
        if not vol_ok or lvl['level_strength'] <= min_strength:
            continue
        price = lvl['price']

        if close_prev2 is not None:
            # Full 2-bar confirmation
            # Long: bar[-2] <= level, bar[-1] crossed above (bullish candle),
            #       bar[0] (now) also holds above  →  confirmLong
            bar1_long  = (close_prev2 <= price < close_prev) and \
                         (open_now is None or close_prev > open_now)
            confirm_long = bar1_long and close_now > price

            bar1_short = (close_prev2 >= price > close_prev) and \
                         (open_now is None or close_prev < open_now)
            confirm_short = bar1_short and close_now < price

            if not lvl['is_support'] and confirm_long:
                longs.append(lvl)
            if lvl['is_support'] and confirm_short:
                shorts.append(lvl)
        else:
            # Legacy single-bar crossover
            if not lvl['is_support'] and close_prev <= price < close_now:
                longs.append(lvl)
            if lvl['is_support'] and close_now < price <= close_prev:
                shorts.append(lvl)

    return {'long': longs, 'short': shorts}


def retest_signals(close_now: float, levels: list,
                   retest_pct: float = 0.002) -> dict:
    """
    Pine:
        retestLong  = isSupport  and abs(close-price)/price < 0.002 and close > price
        retestShort = not isSupport and abs(close-price)/price < 0.002 and close < price
    """
    longs, shorts = [], []
    for lvl in levels:
        proximity = abs(close_now - lvl['price']) / lvl['price']
        if proximity >= retest_pct:
            continue
        if lvl['is_support'] and close_now > lvl['price']:
            longs.append(lvl)
        if not lvl['is_support'] and close_now < lvl['price']:
            shorts.append(lvl)
    return {'long': longs, 'short': shorts}


def rejection_signals(low: float, high: float, close_now: float,
                      levels: list) -> dict:
    """
    Pine:
        rejectionLong  = isSupport     and low < price and close > price
        rejectionShort = not isSupport and high > price and close < price
    """
    longs, shorts = [], []
    for lvl in levels:
        if lvl['is_support'] and low < lvl['price'] and close_now > lvl['price']:
            longs.append(lvl)
        if not lvl['is_support'] and high > lvl['price'] and close_now < lvl['price']:
            shorts.append(lvl)
    return {'long': longs, 'short': shorts}


# Legacy helpers kept for compatibility
def crossed_resistance(close_prev: float, close_now: float, levels: list) -> list:
    return [lvl for lvl in levels
            if not lvl['is_support']
            and close_prev <= lvl['price'] < close_now]

def crossed_support(close_prev: float, close_now: float, levels: list) -> list:
    return [lvl for lvl in levels
            if lvl['is_support']
            and close_now < lvl['price'] <= close_prev]
