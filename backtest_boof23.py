import pandas as pd
import numpy as np

# =============================================================================
# BOOF 23.0 — SR Cluster Entry + ZigZag Regime Filter + Engulf Confirmation
# =============================================================================
# LIVE BOT ALIGNED — Updated June 2026
#   atr_mult: 0.4 (tighter than original 0.6 for more selective entries)
#   use_engulf: False (disabled per live bot optimization)
#   Proximity filter: 30 bars (ZigZag swing proximity)
# =============================================================================
# Architecture:
#   Layer 1 — ZigZag state machine (ported from "Peaks and Troughs" Pine):
#       Tracks trend (up/down), swing cycle position, HH/HL vs LH/LL structure,
#       and leg exhaustion (current leg length vs prior leg).
#       Used ONLY as regime/bias filter — does NOT fire entries.
#
#   Layer 2 — SR cluster entry (Boof 22 core):
#       Fractal peak/trough + ATR rejection/bounce near a high-volume cluster.
#       Entry only fires when ZigZag regime AGREES with the signal direction:
#           short fractal → requires ZigZag trend == 'up' (fading exhausted up-leg)
#           long  fractal → requires ZigZag trend == 'down' (fading exhausted down-leg)
#       Additionally: only enter near the CURRENT ZigZag swing extreme (trough for
#       longs, peak for shorts) — avoids mid-leg noise entries.
#
#   Layer 3 — Engulf confirmation (optional, default on):
#       At the fractal bar, require the candle body to be a reversal engulf:
#           short fractal: close < open (bearish body at the peak)
#           long  fractal: close > open (bullish body at the trough)
#
#   Exit: ATR-based TP/SL (4x ATR TP / 2x ATR SL), 30-bar time stop
#   Tiered sizing: slack >= 1.4 ATR → Core ($600), else Expanded ($200)
# =============================================================================

ATR_LEN        = 14
VOL_LEN        = 50
MAX_HOLD       = 30
TP_PCT         = 0.0008  # +0.08% take profit on underlying
SL_PCT         = 0.0005  # -0.05% stop loss on underlying
ATR_MULT       = 0.6    # min slack for fractal confirmation
TIME_EXIT_PCT  = 0.08
FRACTAL_BARS   = 3      # bars each side for fractal peak/trough
CLUSTER_MERGE  = 0.5
SR_STRENGTH_MIN= 2
SR_DIST_MAX    = 1.0

# ── ESM-derived filters ─────────────────────────────────────────
LOW_VOL_FILTER    = False   # skip entries where ATR/price < LOW_VOL_THRESH
LOW_VOL_THRESH    = 0.00057 # 0.057% ATR/price — below = low-vol regime

# ── Cluster completion logic ─────────────────────────────────────
# Burst positions: first / middle / late
#   first:  cluster not yet activated → standard risk, standard sizing
#   middle: cluster activating        → tight SL (ATR_SL_MIDDLE), standard sizing
#   late:   cluster activated (middle seen) → standard SL, boosted sizing
CLUSTER_COMPLETION = False           # enable cluster completion logic
BURST_WIN_BARS     = 30              # bars window for burst membership
ATR_SL_MIDDLE      = 1.2             # tighter SL for middle entries (vs ATR_SL=2.0)
LATE_SIZE_MULT     = 1.5             # size multiplier for activated late entries

# ── Scan list ─────────────────────────────────────────────────────
BOOFINGTON23 = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']

SYMBOL_PARAMS = {
    'NVDA': {'atr_mult': 0.4, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': False},
    'META': {'atr_mult': 0.4, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': False},
    'AAPL': {'atr_mult': 0.4, 'vol_mult': 1.2, 'sr_dist': 1.0, 'use_engulf': False},
    'GOOGL':{'atr_mult': 0.4, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': False},
    'AMD':  {'atr_mult': 0.4, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': False},
}
DEFAULT_PARAMS = {'atr_mult': 0.4, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': False}


def compute_atr(df, period=ATR_LEN):
    high = df['high']; low = df['low']; close = df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def build_cluster_array(df, atr_series, vol_mult=1.3):
    """Build volume-weighted price cluster array (same as Boof 22)."""
    vol_sma   = df['volume'].rolling(VOL_LEN).mean()
    hi_vol    = df['volume'] > vol_sma * vol_mult
    hi_vol_df = df[hi_vol].copy()
    if len(hi_vol_df) == 0:
        return np.array([]), np.array([])

    prices    = hi_vol_df['close'].values
    vols      = hi_vol_df['volume'].values
    atr_val   = atr_series.iloc[-1] if not np.isnan(atr_series.iloc[-1]) else 1.0
    merge_gap = atr_val * CLUSTER_MERGE

    clusters  = []
    for p, v in zip(prices, vols):
        merged = False
        for c in clusters:
            if abs(p - c['price']) <= merge_gap:
                c['price']   = (c['price'] * c['vol'] + p * v) / (c['vol'] + v)
                c['vol']    += v
                c['touches'] += 1
                merged = True
                break
        if not merged:
            clusters.append({'price': p, 'vol': v, 'touches': 1})

    valid = [c for c in clusters if c['touches'] >= SR_STRENGTH_MIN]
    if not valid:
        return np.array([]), np.array([])

    cluster_prices  = np.array([c['price']   for c in valid])
    cluster_touches = np.array([c['touches'] for c in valid])
    return cluster_prices, cluster_touches


def nearest_sr_distance(price, cluster_prices, atr):
    if len(cluster_prices) == 0 or atr == 0:
        return float('inf')
    return float(np.min(np.abs(cluster_prices - price)) / atr)


def _build_zigzag(highs, lows, opens, closes, start=1):
    """
    Compute ZigZag state at every bar.
    Returns arrays: trend[], zz_high[], zz_high_bar[], zz_low[], zz_low_bar[]
    trend: 'up' | 'down' | ''
    zz_high/zz_low: most recent confirmed swing high/low price
    """
    n = len(highs)
    trend       = [''] * n
    zz_high     = np.full(n, np.nan)
    zz_high_bar = np.full(n, -1, dtype=int)
    zz_low      = np.full(n, np.nan)
    zz_low_bar  = np.full(n, -1, dtype=int)

    t           = ''
    last_high   = highs[0]
    last_low    = lows[0]
    higher_pt   = highs[0]; higher_bar = 0
    lower_pt    = lows[0];  lower_bar  = 0
    cur_zz_high = highs[0]; cur_zz_high_bar = 0
    cur_zz_low  = lows[0];  cur_zz_low_bar  = 0

    for i in range(start, n):
        if highs[i] > higher_pt:
            higher_pt  = highs[i]; higher_bar = i
        if lows[i] < lower_pt:
            lower_pt   = lows[i];  lower_bar  = i

        if closes[i] > last_high or opens[i] > last_high:
            if t == 'down':
                cur_zz_low      = lower_pt
                cur_zz_low_bar  = lower_bar
                higher_pt  = highs[i]; higher_bar = i
            t          = 'up'
            last_high  = highs[i]; last_low = lows[i]

        elif closes[i] < last_low or opens[i] < last_low:
            if t == 'up':
                cur_zz_high     = higher_pt
                cur_zz_high_bar = higher_bar
                lower_pt   = lows[i]; lower_bar = i
            t          = 'down'
            last_high  = highs[i]; last_low = lows[i]

        trend[i]           = t
        zz_high[i]         = cur_zz_high
        zz_high_bar[i]     = cur_zz_high_bar
        zz_low[i]          = cur_zz_low
        zz_low_bar[i]      = cur_zz_low_bar

    return trend, zz_high, zz_high_bar, zz_low, zz_low_bar


def run_boof23(df, symbol='NVDA'):
    """
    Run Boof 23.0 backtest on a 1-min OHLCV dataframe.
    Returns list of trade dicts.
    """
    params      = SYMBOL_PARAMS.get(symbol, DEFAULT_PARAMS)
    vol_mult    = params['vol_mult']
    atr_mult    = params['atr_mult']
    sr_dist_max = params['sr_dist']
    use_engulf  = params['use_engulf']
    F           = FRACTAL_BARS

    df = df.copy().reset_index(drop=True)
    if len(df) < max(ATR_LEN, VOL_LEN) + F * 2 + 10:
        return []

    atr_series    = compute_atr(df)
    df['atr']     = atr_series
    df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
    df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult

    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

    opens  = df['open'].values
    highs  = df['high'].values
    lows   = df['low'].values
    closes = df['close'].values
    atrs   = df['atr'].values
    hi_vol = df['hi_vol'].values

    # ── Layer 1: build ZigZag state for every bar ─────────────────
    trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag(
        highs, lows, opens, closes
    )

    # ── Layer 2 + 3: fractal entry gated by ZigZag + engulf ──────
    trades    = []
    in_trade  = False
    trade_end = 0
    last_signal_bar    = -9999  # bar of most recent signal
    cluster_activated  = False  # True once a middle entry has fired in this burst

    warmup = VOL_LEN + ATR_LEN + F

    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end:
            continue

        row   = df.iloc[i]
        atr   = atrs[i]
        trend = trend_arr[i]

        if np.isnan(atr) or atr == 0: continue
        if row['rvol'] < 80:          continue
        if not hi_vol[i]:             continue
        if trend == '':               continue

        # Low-vol regime filter
        if LOW_VOL_FILTER:
            ep_proxy = closes[i]
            if ep_proxy > 0 and (atr / ep_proxy) < LOW_VOL_THRESH:
                continue

        # SR cluster proximity gate
        if nearest_sr_distance(row['close'], cluster_prices, atr) > sr_dist_max:
            continue

        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]

        fractal_peak   = (highs[i] > lh.max()) and (highs[i] > rh.max())
        fractal_trough = (lows[i]  < ll.min()) and (lows[i]  < rl.min())

        peak_slack   = (highs[i] - closes[i]) / atr
        trough_slack = (closes[i] - lows[i])  / atr

        direction = None
        slack     = 0.0

        # Short: fractal peak + ZigZag in 'up' trend (exhaustion fade)
        # + price near the current ZigZag swing high
        if (fractal_peak and peak_slack >= atr_mult and trend == 'up'):
            # Swing proximity: peak bar should be within 10 bars of ZigZag high
            zz_h_bar = int(zz_high_bar[i])
            if zz_h_bar >= 0 and abs(i - zz_h_bar) <= 10:
                # Engulf: bearish candle body at peak (optional)
                engulf_ok = (not use_engulf) or (closes[i] < opens[i])
                if engulf_ok:
                    direction = 'short'
                    slack     = peak_slack

        # Long: fractal trough + ZigZag in 'down' trend (exhaustion fade)
        # + price near the current ZigZag swing low
        elif (fractal_trough and trough_slack >= atr_mult and trend == 'down'):
            zz_l_bar = int(zz_low_bar[i])
            if zz_l_bar >= 0 and abs(i - zz_l_bar) <= 10:
                engulf_ok = (not use_engulf) or (closes[i] > opens[i])
                if engulf_ok:
                    direction = 'long'
                    slack     = trough_slack

        if direction is None:
            continue

        # ── Cluster completion state machine ──────────────────────
        bars_since_last = i - last_signal_bar
        in_burst        = (0 < bars_since_last <= BURST_WIN_BARS)

        if CLUSTER_COMPLETION:
            if not in_burst:
                # Fresh burst — first entry
                cluster_pos       = 'first'
                cluster_activated = False
            elif not cluster_activated:
                # Still within burst window, no middle yet → this IS the middle
                cluster_pos       = 'middle'
                cluster_activated = True   # mark cluster as activated
            else:
                # Middle already fired → late entry, cluster confirmed
                cluster_pos = 'late'
        else:
            cluster_pos = 'first'  # unused when feature is off

        last_signal_bar = i

        # ── Entry simulation ──────────────────────────────────────
        entry_bar = i + 1
        if entry_bar >= len(df) - MAX_HOLD - 2:
            continue

        ep = float(opens[entry_bar])

        tp_p  = ep * (1 + TP_PCT) if direction == 'long'  else ep * (1 - TP_PCT)
        sl_p  = ep * (1 - SL_PCT) if direction == 'long'  else ep * (1 + SL_PCT)

        et       = 'time'
        exit_bar = min(entry_bar + MAX_HOLD, len(df) - 1)
        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD + 1, len(df))):
            h = highs[j]; l = lows[j]
            if direction == 'long':
                if h >= tp_p: et = 'tp'; exit_bar = j; break
                if l <= sl_p: et = 'sl'; exit_bar = j; break
            else:
                if l <= tp_p: et = 'tp'; exit_bar = j; break
                if h >= sl_p: et = 'sl'; exit_bar = j; break

        in_trade  = True
        trade_end = exit_bar

        pnl_pct = (
             TP_PCT if et == 'tp'
            else -SL_PCT if et == 'sl'
            else TIME_EXIT_PCT
        )

        # Sizing: late entries in an activated cluster get a boost
        base_tier = 'core' if slack >= 1.4 else 'expanded'
        if CLUSTER_COMPLETION and cluster_pos == 'late':
            size_mult = LATE_SIZE_MULT
        else:
            size_mult = 1.0

        trades.append({
            'symbol':      symbol,
            'direction':   direction,
            'entry':       ep,
            'exit_type':   et,
            'pnl_pct':     pnl_pct,
            'slack':       slack,
            'tier':        base_tier,
            'size_mult':   size_mult,
            'cluster_pos': cluster_pos if CLUSTER_COMPLETION else 'first',
            'entry_bar':   entry_bar,
            'zz_trend':    trend,
        })

    return trades
