"""
Ablation test for Boof 20.0 — removes one feature at a time and compares results.
"""
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from scipy.signal import argrelextrema
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# =========================
# FIXED CONFIG
# =========================
SYMBOLS    = ["SPY", "QQQ"]
TIMEFRAME  = "1Min"
START_DATE = datetime(2026, 4, 1)
END_DATE   = datetime(2026, 4, 30)

LOOKBACK_BARS  = 120
PIVOT_ORDER    = 5
ATR_TOLERANCE  = 0.25
MIN_TOUCHES    = 2
ATR_BREAK_MULT = 0.1
ATR_BODY_MULT  = 0.3
VOL_MULT       = 1.5
ATR_STOP_MULT  = 1.0
ATR_TP_MULT    = 2.0
TIME_STOP_BARS = 30
USE_LEVEL_STOP = True
SWEEP_LOOKBACK  = 20
OB_IMPULSE_MULT = 2.0
MP_BINS         = 50
OPTION_COST_PCT = 0.004
DELTA           = 0.50
THETA_PER_MIN   = OPTION_COST_PCT * (0.50 / 390)
TIME_FILTER     = True
TIME_WINDOWS    = [(5, 120), (300, 450)]
ML_MIN_SAMPLES  = 200
ML_PROB_THRESH  = 0.55

# =========================
# ABLATION FLAGS
# =========================
class Config:
    use_zone_clustering  = True
    use_body_filter      = True
    use_volume_filter    = True
    use_sweep            = True
    use_order_blocks     = True
    use_market_profile   = True
    use_regime           = True
    use_ml               = True

# =========================
# CORE FUNCTIONS (same as boof20)
# =========================
@dataclass
class SRLevel:
    low: float; high: float; touches: int; volume: float
    strength: float; timeframe: str; created_index: int
    last_touch: int; level_type: str; classification: str

def compute_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low']  - df['close'].shift())
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

def detect_pivots(df, order=PIVOT_ORDER):
    highs = df.iloc[argrelextrema(df['high'].values, np.greater_equal, order=order)[0]]
    lows  = df.iloc[argrelextrema(df['low'].values,  np.less_equal,    order=order)[0]]
    return highs, lows

def build_raw_levels(df, highs, lows):
    levels = []
    for idx, row in highs.iterrows():
        levels.append({"price": row['high'], "type": "resistance", "index": idx})
    for idx, row in lows.iterrows():
        levels.append({"price": row['low'],  "type": "support",    "index": idx})
    return levels

def cluster_levels(levels, atr_value, cfg):
    clustered = []
    for lvl in sorted(levels, key=lambda x: x['price']):
        merged = False
        if cfg.use_zone_clustering:
            for zone in clustered:
                zone_mid = (zone['low'] + zone['high']) / 2
                if abs(lvl['price'] - zone_mid) < atr_value * ATR_TOLERANCE:
                    zone['prices'].append(lvl['price'])
                    zone['low']     = min(zone['low'],  lvl['price'])
                    zone['high']    = max(zone['high'], lvl['price'])
                    zone['touches'] += 1
                    merged = True
                    break
        if not merged:
            clustered.append({"low": lvl['price'], "high": lvl['price'],
                               "prices": [lvl['price']], "touches": 1, "type": lvl['type']})
    return clustered

def score_levels(df, zones):
    scored  = []
    avg_vol = df['volume'].mean()
    for zone in zones:
        if zone['touches'] < MIN_TOUCHES:
            continue
        mid          = (zone['low'] + zone['high']) / 2
        touch_score  = np.log1p(zone['touches']) * 20
        nearby       = df[(df['low'] <= mid) & (df['high'] >= mid)]
        vol_score    = (nearby['volume'].mean() / avg_vol) * 30 if len(nearby) else 0
        age_score    = min(zone['touches'] * 5, 20)
        strength     = touch_score + vol_score + age_score
        scored.append(SRLevel(
            low=zone['low'], high=zone['high'], touches=zone['touches'],
            volume=nearby['volume'].sum() if len(nearby) else 0,
            strength=strength, timeframe=TIMEFRAME, created_index=0,
            last_touch=len(df)-1, level_type=zone['type'],
            classification="major" if strength >= 50 else "minor"
        ))
    return scored

def detect_breakouts(df, sr_levels, cfg):
    signals    = []
    atr        = compute_atr(df).iloc[-1]
    current    = df.iloc[-1]
    avg_volume = df['volume'].rolling(20).mean().iloc[-1]
    for lvl in sr_levels:
        vol_ok  = current['volume'] > avg_volume * VOL_MULT if cfg.use_volume_filter else True
        body_ok = (current['close'] - current['open']) > atr * ATR_BODY_MULT if cfg.use_body_filter else True
        rbody_ok = (current['open'] - current['close']) > atr * ATR_BODY_MULT if cfg.use_body_filter else True
        if (lvl.level_type == "resistance" and
                current['close'] > lvl.high + atr * ATR_BREAK_MULT and
                vol_ok and body_ok):
            signals.append({"type": "LONG_BREAKOUT",  "level": lvl, "price": current['close']})
        elif (lvl.level_type == "support" and
                current['close'] < lvl.low - atr * ATR_BREAK_MULT and
                vol_ok and rbody_ok):
            signals.append({"type": "SHORT_BREAKDOWN", "level": lvl, "price": current['close']})
    return signals

def run_sr_detector(df, cfg):
    highs, lows = detect_pivots(df)
    raw         = build_raw_levels(df, highs, lows)
    atr         = compute_atr(df).iloc[-1]
    zones       = cluster_levels(raw, atr, cfg)
    scored      = score_levels(df, zones)
    signals     = detect_breakouts(df, scored, cfg)
    return scored, signals

def detect_liquidity_sweeps(df):
    sweeps = []
    for i in range(SWEEP_LOOKBACK, len(df)):
        c = df.iloc[i]
        ph = df['high'].iloc[i-SWEEP_LOOKBACK:i].max()
        pl = df['low'].iloc[i-SWEEP_LOOKBACK:i].min()
        if c['high'] > ph and c['close'] < ph:
            sweeps.append({"index": i, "type": "bearish_sweep"})
        if c['low'] < pl and c['close'] > pl:
            sweeps.append({"index": i, "type": "bullish_sweep"})
    return sweeps

def detect_order_blocks(df):
    obs = []
    atr = compute_atr(df)
    for i in range(3, len(df)-1):
        c = df.iloc[i]; n = df.iloc[i+1]
        imp = abs(n['close'] - n['open'])
        if c['close'] < c['open'] and imp > atr.iloc[i] * OB_IMPULSE_MULT and n['close'] > n['open']:
            obs.append({"type": "bullish_ob", "index": i})
        if c['close'] > c['open'] and imp > atr.iloc[i] * OB_IMPULSE_MULT and n['close'] < n['open']:
            obs.append({"type": "bearish_ob", "index": i})
    return obs

def market_profile(df):
    prices = (df['high'] + df['low'] + df['close']) / 3
    hist, edges = np.histogram(prices, bins=MP_BINS, weights=df['volume'])
    poc_idx  = np.argmax(hist)
    poc      = (edges[poc_idx] + edges[poc_idx+1]) / 2
    total    = hist.sum()
    cumvol   = np.cumsum(hist)
    va_low   = edges[np.searchsorted(cumvol, total * 0.15)]
    va_high  = edges[min(np.searchsorted(cumvol, total * 0.85)+1, len(edges)-1)]
    nz       = hist[hist > 0]
    lvn_idx  = np.where(hist == nz.min())[0][0] if len(nz) else 0
    lvn      = (edges[lvn_idx] + edges[lvn_idx+1]) / 2
    return {"poc": poc, "va_low": va_low, "va_high": va_high, "lvn": lvn}

def detect_regime(df, up_to_idx):
    window = df.iloc[max(0, up_to_idx-100): up_to_idx]
    if len(window) < 20:
        return 1
    rets = np.log(window['close'] / window['close'].shift(1)).dropna()
    vol  = rets.rolling(10).std().dropna()
    n    = min(len(rets), len(vol))
    X    = np.column_stack([rets.values[-n:], vol.values[-n:]])
    if len(X) < 3:
        return 1
    sc  = StandardScaler()
    km  = KMeans(n_clusters=3, n_init=5, random_state=42)
    return int(km.fit_predict(sc.fit_transform(X))[-1])

def is_time_allowed(ts):
    m = ts.hour * 60 + ts.minute - 570
    return any(s <= m <= e for s, e in TIME_WINDOWS)

def option_pnl(entry, exit_price, direction, hold_minutes):
    u = (exit_price - entry) / entry if direction == 'LONG' else (entry - exit_price) / entry
    return ((u * DELTA) - (THETA_PER_MIN * hold_minutes)) / OPTION_COST_PCT

def build_features(df, i, lvl, direction, mp, sweeps, obs, regime, cfg):
    row = df.iloc[i]
    atr = row['atr']
    vwap_v = row['vwap']
    sweep_feat = int(cfg.use_sweep and any(
        s['index'] >= i-10 and ((direction=='LONG' and s['type']=='bullish_sweep') or
                                (direction=='SHORT' and s['type']=='bearish_sweep'))
        for s in sweeps))
    ob_feat = int(cfg.use_order_blocks and any(
        o['index'] >= i-20 and ((direction=='LONG' and o['type']=='bullish_ob') or
                                (direction=='SHORT' and o['type']=='bearish_ob'))
        for o in obs))
    if cfg.use_market_profile:
        dist_poc  = (row['close'] - mp['poc'])    / atr if atr > 0 else 0
        dist_va_h = (row['close'] - mp['va_high']) / atr if atr > 0 else 0
        dist_va_l = (row['close'] - mp['va_low'])  / atr if atr > 0 else 0
        dist_lvn  = (row['close'] - mp['lvn'])     / atr if atr > 0 else 0
    else:
        dist_poc = dist_va_h = dist_va_l = dist_lvn = 0
    regime_feat = regime if cfg.use_regime else 1
    return [
        lvl.strength, lvl.touches,
        1 if lvl.classification == 'major' else 0,
        (row['close'] - vwap_v) / vwap_v,
        row['volume'] / row['vol_avg'] if row['vol_avg'] > 0 else 1,
        dist_poc, dist_va_h, dist_va_l, dist_lvn,
        sweep_feat, ob_feat,
        regime_feat,
        abs(row['close'] - row['open']) / atr if atr > 0 else 0
    ]

# =========================
# BACKTEST WITH CONFIG
# =========================
def backtest(df, cfg):
    df = df.copy()
    df['atr']     = compute_atr(df)
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['vwap']    = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

    all_sweeps  = detect_liquidity_sweeps(df) if cfg.use_sweep else []
    all_obs     = detect_order_blocks(df)     if cfg.use_order_blocks else []

    trades        = []
    in_trade      = False
    ml_model      = None
    ml_features   = []
    ml_labels     = []
    regime_cache  = {}

    for i in range(LOOKBACK_BARS + PIVOT_ORDER, len(df) - TIME_STOP_BARS - 1):
        if in_trade:
            continue
        if TIME_FILTER and not is_time_allowed(df.index[i]):
            continue
        row = df.iloc[i]
        atr = row['atr']
        if np.isnan(atr) or atr == 0:
            continue

        window          = df.iloc[i - LOOKBACK_BARS: i + 1]
        scored, signals = run_sr_detector(window, cfg)
        if not signals:
            continue

        signals.sort(key=lambda s: s['level'].strength, reverse=True)
        best      = signals[0]
        direction = 'LONG' if best['type'] == 'LONG_BREAKOUT' else 'SHORT'
        lvl       = best['level']

        mp          = market_profile(window) if cfg.use_market_profile else {"poc": 0, "va_low": 0, "va_high": 0, "lvn": 0}
        cache_key   = i // 10
        if cfg.use_regime:
            if cache_key not in regime_cache:
                regime_cache[cache_key] = detect_regime(df, i)
            regime = regime_cache[cache_key]
        else:
            regime = 1

        feats = build_features(df, i, lvl, direction, mp, all_sweeps, all_obs, regime, cfg)

        if cfg.use_ml and ml_model is not None:
            prob = ml_model.predict_proba([feats])[0][1]
            if prob < ML_PROB_THRESH:
                continue

        entry_price = df['close'].iloc[i + 1]
        stop_price  = lvl.low  if direction == 'LONG' else lvl.high
        tp_price    = entry_price + atr * ATR_TP_MULT if direction == 'LONG' else entry_price - atr * ATR_TP_MULT

        in_trade = True

        for j in range(i + 2, min(i + TIME_STOP_BARS + 2, len(df))):
            current      = df['close'].iloc[j]
            hold_minutes = j - (i + 1)
            hit_stop = (direction == 'LONG' and current <= stop_price) or (direction == 'SHORT' and current >= stop_price)
            hit_tp   = (direction == 'LONG' and current >= tp_price)   or (direction == 'SHORT' and current <= tp_price)
            hit_time = (j == min(i + TIME_STOP_BARS + 1, len(df) - 1))

            if hit_stop or hit_tp or hit_time:
                pnl = option_pnl(entry_price, current, direction, hold_minutes)
                trades.append(pnl)
                in_trade = False
                ml_features.append(feats)
                ml_labels.append(1 if pnl > 0 else 0)
                if cfg.use_ml and len(ml_labels) >= ML_MIN_SAMPLES and len(ml_labels) % 50 == 0:
                    try:
                        X = np.array(ml_features); y = np.array(ml_labels)
                        if len(set(y)) > 1:
                            ml_model = XGBClassifier(n_estimators=100, max_depth=4,
                                                     learning_rate=0.05, subsample=0.8,
                                                     colsample_bytree=0.8, eval_metric='logloss', verbosity=0)
                            ml_model.fit(X, y)
                    except Exception:
                        pass
                break
    return trades

def run_test(name, cfg, dfs):
    print(f"  Running: {name}...", flush=True)
    all_pnls = []
    for symbol, df in dfs.items():
        trades = backtest(df, cfg)
        all_pnls.extend(trades)
    if not all_pnls:
        return {"name": name, "trades": 0, "wr": 0, "pf": 0, "pnl": 0}
    wins   = [p for p in all_pnls if p > 0]
    losses = [p for p in all_pnls if p <= 0]
    pf     = sum(wins) / abs(sum(losses)) if losses else float('inf')
    return {
        "name":   name,
        "trades": len(all_pnls),
        "wr":     len(wins) / len(all_pnls) * 100,
        "pf":     pf,
        "pnl":    sum(all_pnls) * 100
    }

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("Downloading data...")
    credentials = get_alpaca_credentials()
    dfs = {}
    for sym in SYMBOLS:
        df = fetch_alpaca_bars(sym, START_DATE, END_DATE, TIMEFRAME,
                               api_key=credentials['api_key'],
                               secret_key=credentials['secret_key'])
        if df is not None and not df.empty:
            dfs[sym] = df
            print(f"  {sym}: {len(df)} candles")

    tests = []

    # 1. Baseline
    cfg = Config()
    tests.append(run_test("BASELINE (all features)", cfg, dfs))

    # 2. Remove zone clustering
    cfg = Config(); cfg.use_zone_clustering = False
    tests.append(run_test("NO zone clustering", cfg, dfs))

    # 3. Remove candle body filter
    cfg = Config(); cfg.use_body_filter = False
    tests.append(run_test("NO body filter", cfg, dfs))

    # 4. Remove volume filter
    cfg = Config(); cfg.use_volume_filter = False
    tests.append(run_test("NO volume filter", cfg, dfs))

    # 5. Remove liquidity sweep
    cfg = Config(); cfg.use_sweep = False
    tests.append(run_test("NO sweep detection", cfg, dfs))

    # 6. Remove order blocks
    cfg = Config(); cfg.use_order_blocks = False
    tests.append(run_test("NO order blocks", cfg, dfs))

    # 7. Remove market profile
    cfg = Config(); cfg.use_market_profile = False
    tests.append(run_test("NO market profile", cfg, dfs))

    # 8. Remove regime detection
    cfg = Config(); cfg.use_regime = False
    tests.append(run_test("NO regime detection", cfg, dfs))

    # 9. Remove ML filter
    cfg = Config(); cfg.use_ml = False
    tests.append(run_test("NO ML filter", cfg, dfs))

    # =========================
    # RESULTS TABLE
    # =========================
    print(f"\n{'='*65}")
    print(f"{'TEST':<30} {'TRADES':>7} {'WR%':>7} {'PF':>6} {'TOTAL PNL%':>11}")
    print(f"{'='*65}")
    baseline_pnl = tests[0]['pnl']
    for t in tests:
        delta = t['pnl'] - baseline_pnl
        delta_str = f"({delta:+.1f})" if t['name'] != "BASELINE (all features)" else ""
        print(f"{t['name']:<30} {t['trades']:>7} {t['wr']:>6.1f}% {t['pf']:>6.2f} {t['pnl']:>9.2f}% {delta_str}")
    print(f"{'='*65}")
    print("\nDelta = change vs baseline. Positive = feature HURTS. Negative = feature HELPS.")
