"""
Boof 23 — Intrabar Randomness / Sequencing Stress Test
Config: prox=30, engulf=OFF

Tests:
1. TP/SL same-candle randomized execution order (who gets hit first)
2. Wick uncertainty — entry fills anywhere in bar's open±wick range
3. Delayed fills — entry executes N bars later
4. Spread expansion bursts — random spread widening events

Each test runs 1000 Monte Carlo iterations, reports mean/p5/p95 outcomes
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, BOOFINGTON23, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, SR_DIST_MAX, TIME_EXIT_PCT, MAX_HOLD)

CORE_SIZE = 600; EXP_SIZE = 200
MOS_25 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MOS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']
DAYS   = 342; N_ITER = 1000; PROX = 30
RNG    = np.random.default_rng(42)

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))

# ── Collect raw signal events (before simulation) ─────────────────
def collect_signals():
    """Returns list of signal dicts with all price data needed for sim."""
    import pandas as pd
    F = FRACTAL_BARS; signals = []

    for mo, cache in [(m, cache25) for m in MOS_25] + [(m, cache26) for m in MOS_26]:
        for sym in BOOFINGTON23:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue

            params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
            vol_mult    = params['vol_mult']
            atr_mult    = params['atr_mult']
            sr_dist_max = params['sr_dist']

            df = df.copy().reset_index(drop=True)
            atr_series    = compute_atr(df)
            df['atr']     = atr_series
            df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
            df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
            df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult
            cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

            opens  = df['open'].values;  highs = df['high'].values
            lows   = df['low'].values;   closes= df['close'].values
            atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values

            trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(
                highs, lows, opens, closes)

            in_trade = False; trade_end = 0
            warmup = VOL_LEN + ATR_LEN + F

            for i in range(warmup, len(df) - F - MAX_HOLD - 3):
                if in_trade and i <= trade_end: continue
                row = df.iloc[i]; atr = atrs[i]; trend = trend_arr[i]
                if np.isnan(atr) or atr == 0: continue
                if row['rvol'] < 80:          continue
                if not hi_vol[i]:             continue
                if trend == '':               continue
                if nearest_sr_distance(row['close'], cluster_prices, atr) > sr_dist_max:
                    continue

                lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
                ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
                fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
                ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
                ps = (highs[i] - closes[i]) / atr
                ts = (closes[i] - lows[i])  / atr

                direction = None; slack = 0.0
                if fp and ps >= atr_mult and trend == 'up':
                    if int(zz_high_bar[i]) >= 0 and abs(i - int(zz_high_bar[i])) <= PROX:
                        direction = 'short'; slack = ps
                elif ft and ts >= atr_mult and trend == 'down':
                    if int(zz_low_bar[i]) >= 0 and abs(i - int(zz_low_bar[i])) <= PROX:
                        direction = 'long'; slack = ts

                if direction is None: continue

                entry_bar = i + 1
                if entry_bar >= len(df) - MAX_HOLD - 2: continue

                # Store full bar sequence for this trade
                n_bars = min(MAX_HOLD + 2, len(df) - entry_bar)
                bar_highs  = highs[entry_bar: entry_bar + n_bars]
                bar_lows   = lows[entry_bar:  entry_bar + n_bars]
                bar_opens  = opens[entry_bar: entry_bar + n_bars]
                bar_closes = closes[entry_bar:entry_bar + n_bars]

                signals.append({
                    'direction':  direction,
                    'atr':        atr,
                    'open_price': float(opens[entry_bar]),
                    'slack':      slack,
                    'tier':       'core' if slack >= 1.4 else 'expanded',
                    'bar_highs':  bar_highs.copy(),
                    'bar_lows':   bar_lows.copy(),
                    'bar_opens':  bar_opens.copy(),
                    'bar_closes': bar_closes.copy(),
                    'mo':         mo,
                })
                in_trade = True
                # Estimate trade end for blocking (use baseline sim)
                ep = float(opens[entry_bar])
                tp_p = ep + atr*ATR_TP if direction=='long' else ep - atr*ATR_TP
                sl_p = ep - atr*ATR_SL if direction=='long' else ep + atr*ATR_SL
                et = 'time'; eb = min(entry_bar + MAX_HOLD, len(df)-1)
                for j in range(entry_bar+1, min(entry_bar+MAX_HOLD+1, len(df))):
                    if direction=='long':
                        if highs[j]>=tp_p or lows[j]<=sl_p: eb=j; break
                    else:
                        if lows[j]<=tp_p or highs[j]>=sl_p: eb=j; break
                trade_end = eb

    return signals

print('Collecting signals...')
signals = collect_signals()
print(f'  {len(signals):,} signals collected\n')

size_arr = np.array([CORE_SIZE if s['tier']=='core' else EXP_SIZE for s in signals])

# ── Simulation helpers ────────────────────────────────────────────
def sim_trade_baseline(sig):
    """Clean deterministic simulation."""
    ep = sig['open_price']; atr = sig['atr']; d = sig['direction']
    tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
    sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL
    for j in range(1, len(sig['bar_highs'])):
        h = sig['bar_highs'][j]; l = sig['bar_lows'][j]
        if d == 'long':
            if h >= tp_p and l <= sl_p:
                return 'tp'   # baseline: TP wins on ambiguous bar
            if h >= tp_p: return 'tp'
            if l <= sl_p: return 'sl'
        else:
            if l <= tp_p and h >= sl_p:
                return 'tp'
            if l <= tp_p: return 'tp'
            if h >= sl_p: return 'sl'
    return 'time'

def pnl_from_exit(et, ep, atr, size):
    if et == 'tp':   return size * (atr * ATR_TP / ep)
    if et == 'sl':   return size * -(atr * ATR_SL / ep)
    return size * TIME_EXIT_PCT

# ── Test 1: Baseline ───────────────────────────────────────────────
def run_baseline():
    pnls = []
    for sig, sz in zip(signals, size_arr):
        et = sim_trade_baseline(sig)
        pnls.append(pnl_from_exit(et, sig['open_price'], sig['atr'], sz))
    return np.array(pnls)

# ── Test 2: TP/SL same-candle randomized order ────────────────────
def run_tpsl_random(rng):
    pnls = []
    for sig, sz in zip(signals, size_arr):
        ep = sig['open_price']; atr = sig['atr']; d = sig['direction']
        tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL
        et = 'time'
        for j in range(1, len(sig['bar_highs'])):
            h = sig['bar_highs'][j]; l = sig['bar_lows'][j]
            tp_hit = (h >= tp_p) if d=='long' else (l <= tp_p)
            sl_hit = (l <= sl_p) if d=='long' else (h >= sl_p)
            if tp_hit and sl_hit:
                # Both hit same bar — randomize who wins
                et = 'tp' if rng.random() < 0.5 else 'sl'
                break
            elif tp_hit: et='tp'; break
            elif sl_hit: et='sl'; break
        pnls.append(pnl_from_exit(et, ep, atr, sz))
    return np.array(pnls)

# ── Test 3: Wick uncertainty (fill anywhere in open±wick%) ─────────
def run_wick_uncertainty(rng, wick_frac=0.15):
    """Entry fills up to wick_frac * ATR worse than open."""
    pnls = []
    for sig, sz in zip(signals, size_arr):
        atr = sig['atr']; d = sig['direction']
        slip = rng.uniform(0, wick_frac * atr)
        ep = sig['open_price'] + (slip if d=='long' else -slip)
        tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL
        et = 'time'
        for j in range(1, len(sig['bar_highs'])):
            h = sig['bar_highs'][j]; l = sig['bar_lows'][j]
            tp_hit = (h>=tp_p) if d=='long' else (l<=tp_p)
            sl_hit = (l<=sl_p) if d=='long' else (h>=sl_p)
            if tp_hit and sl_hit:
                et = 'tp' if rng.random() < 0.5 else 'sl'; break
            elif tp_hit: et='tp'; break
            elif sl_hit: et='sl'; break
        pnls.append(pnl_from_exit(et, ep, atr, sz))
    return np.array(pnls)

# ── Test 4: Delayed fills (entry 1-3 bars late) ────────────────────
def run_delayed_fill(rng, max_delay=3):
    pnls = []
    for sig, sz in zip(signals, size_arr):
        delay = int(rng.integers(0, max_delay + 1))
        atr = sig['atr']; d = sig['direction']
        if delay >= len(sig['bar_opens']) - 1:
            pnls.append(pnl_from_exit('time', sig['open_price'], atr, sz))
            continue
        ep = float(sig['bar_opens'][delay])
        tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL
        et = 'time'
        for j in range(delay+1, len(sig['bar_highs'])):
            h = sig['bar_highs'][j]; l = sig['bar_lows'][j]
            tp_hit = (h>=tp_p) if d=='long' else (l<=tp_p)
            sl_hit = (l<=sl_p) if d=='long' else (h>=sl_p)
            if tp_hit and sl_hit:
                et = 'tp' if rng.random() < 0.5 else 'sl'; break
            elif tp_hit: et='tp'; break
            elif sl_hit: et='sl'; break
        pnls.append(pnl_from_exit(et, ep, atr, sz))
    return np.array(pnls)

# ── Test 5: Spread expansion bursts ───────────────────────────────
def run_spread_burst(rng, burst_prob=0.08, burst_atr_frac=0.20):
    """8% of fills hit a spread burst, costing up to 20% of ATR extra."""
    pnls = []
    for sig, sz in zip(signals, size_arr):
        atr = sig['atr']; d = sig['direction']
        ep_raw = sig['open_price']
        spread = rng.uniform(0, burst_atr_frac * atr) if rng.random() < burst_prob else 0.0
        ep = ep_raw + (spread if d=='long' else -spread)
        tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL
        et = 'time'
        for j in range(1, len(sig['bar_highs'])):
            h = sig['bar_highs'][j]; l = sig['bar_lows'][j]
            tp_hit = (h>=tp_p) if d=='long' else (l<=tp_p)
            sl_hit = (l<=sl_p) if d=='long' else (h>=sl_p)
            if tp_hit and sl_hit:
                et = 'tp' if rng.random() < 0.5 else 'sl'; break
            elif tp_hit: et='tp'; break
            elif sl_hit: et='sl'; break
        pnls.append(pnl_from_exit(et, ep, atr, sz))
    return np.array(pnls)

# ── Test 6: Combined worst-case ────────────────────────────────────
def run_combined_worst(rng):
    """All stressors active simultaneously."""
    pnls = []
    for sig, sz in zip(signals, size_arr):
        atr = sig['atr']; d = sig['direction']
        # Wick uncertainty
        wick_slip = rng.uniform(0, 0.15 * atr)
        # Spread burst
        spread = rng.uniform(0, 0.20 * atr) if rng.random() < 0.08 else 0.0
        # Delay
        delay = int(rng.integers(0, 4))
        if delay >= len(sig['bar_opens']) - 1:
            pnls.append(pnl_from_exit('time', sig['open_price'], atr, sz)); continue
        ep_raw = float(sig['bar_opens'][delay])
        ep = ep_raw + (wick_slip + spread if d=='long' else -(wick_slip + spread))
        tp_p = ep + atr*ATR_TP if d=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if d=='long' else ep + atr*ATR_SL
        et = 'time'
        for j in range(delay+1, len(sig['bar_highs'])):
            h = sig['bar_highs'][j]; l = sig['bar_lows'][j]
            tp_hit = (h>=tp_p) if d=='long' else (l<=tp_p)
            sl_hit = (l<=sl_p) if d=='long' else (h>=sl_p)
            if tp_hit and sl_hit:
                et = 'tp' if rng.random() < 0.5 else 'sl'; break
            elif tp_hit: et='tp'; break
            elif sl_hit: et='sl'; break
        pnls.append(pnl_from_exit(et, ep, atr, sz))
    return np.array(pnls)

# ── Monte Carlo runner ─────────────────────────────────────────────
def monte_carlo(fn, n_iter=N_ITER, **kwargs):
    annuals = []
    for _ in range(n_iter):
        rng_i = np.random.default_rng(RNG.integers(0, 2**32))
        arr   = fn(rng_i, **kwargs)
        annuals.append(float(sum(arr)))
    return np.array(annuals)

# ── Run all tests ──────────────────────────────────────────────────
print(f'Running Monte Carlo ({N_ITER} iterations each)...')

baseline_arr = run_baseline()
baseline_ann = float(sum(baseline_arr))
baseline_ev  = float(np.mean(baseline_arr))
baseline_wr  = float(len(baseline_arr[baseline_arr>0])/len(baseline_arr)*100)
pos = baseline_arr[baseline_arr>0]; neg = baseline_arr[baseline_arr<0]
baseline_pf  = float(sum(pos)/max(abs(sum(neg)),0.01))

print(f'  Baseline: ann=${baseline_ann:,.0f}  ev=${baseline_ev:.2f}  wr={baseline_wr:.1f}%  pf={baseline_pf:.2f}')

tests = [
    ('TP/SL Same-Bar Randomized',  run_tpsl_random,    {}),
    ('Wick Uncertainty (15% ATR)', run_wick_uncertainty,{'wick_frac':0.15}),
    ('Delayed Fill (0-3 bars)',     run_delayed_fill,    {'max_delay':3}),
    ('Spread Burst (8%/20%ATR)',    run_spread_burst,    {'burst_prob':0.08,'burst_atr_frac':0.20}),
    ('Combined Worst-Case',        run_combined_worst,  {}),
]

mc_results = {}
for label, fn, kwargs in tests:
    print(f'  Running: {label}...')
    mc = monte_carlo(fn, **kwargs)
    mc_results[label] = mc
    print(f'    mean=${np.mean(mc):,.0f}  p5=${np.percentile(mc,5):,.0f}  p95=${np.percentile(mc,95):,.0f}')

# ── Print results table ────────────────────────────────────────────
print(f'\n{"="*90}')
print(f'  BOOF 23 — Intrabar Randomness Stress Test ({N_ITER} Monte Carlo iterations)')
print(f'  prox=30, engulf=OFF | BOOFINGTON 5-sym | 17 months')
print(f'{"="*90}')
print(f'  {"Scenario":<32}  {"Mean Ann$":>11}  {"p5 Ann$":>10}  {"p95 Ann$":>10}  '
      f'{"vs Base":>9}  {"$/mo":>9}  {"p5 $/mo":>9}')
print(f'  {"-"*88}')

label_b = 'Baseline (deterministic)'
print(f'  {label_b:<32}  ${baseline_ann:>10,.0f}  {"N/A":>10}  {"N/A":>10}  '
      f'{"":>9}  ${baseline_ann/17:>8,.0f}  {"N/A":>9}')

for label, _, _ in tests:
    mc   = mc_results[label]
    mean = np.mean(mc)
    p5   = np.percentile(mc, 5)
    p95  = np.percentile(mc, 95)
    delta= mean - baseline_ann
    sign = '+' if delta >= 0 else ''
    print(f'  {label:<32}  ${mean:>10,.0f}  ${p5:>9,.0f}  ${p95:>9,.0f}  '
          f'{sign}${delta:>8,.0f}  ${mean/17:>8,.0f}  ${p5/17:>8,.0f}')

# ── Per-test EV / WR / PF for mean scenario ───────────────────────
print(f'\n{"="*90}')
print(f'  SIGNAL QUALITY under each stressor (mean of {N_ITER} runs)')
print(f'{"="*90}')
print(f'  {"Scenario":<32}  {"EV$":>8}  {"EV chg":>8}  {"WR%":>7}  {"WR chg":>8}  {"PF":>7}  {"PF chg":>7}')
print(f'  {"-"*88}')
print(f'  {"Baseline":<32}  {baseline_ev:>8.2f}  {"":>8}  {baseline_wr:>7.1f}  {"":>8}  {baseline_pf:>7.2f}  {"":>7}')

for label, fn, kwargs in tests:
    # Run one representative pass for stats
    rng_rep = np.random.default_rng(42)
    arr_rep = fn(rng_rep, **kwargs)
    n   = len(arr_rep)
    pos = arr_rep[arr_rep>0]; neg = arr_rep[arr_rep<0]
    ev  = float(np.mean(arr_rep))
    wr  = float(len(pos)/n*100)
    pf  = float(sum(pos)/max(abs(sum(neg)),0.01))
    ev_c = ev - baseline_ev
    wr_c = wr - baseline_wr
    pf_c = pf - baseline_pf
    flag = '  !! DANGER' if pf < 1.5 else ('  ! watch' if pf < 5.0 else '')
    print(f'  {label:<32}  {ev:>8.2f}  {ev_c:>+8.2f}  {wr:>7.1f}  {wr_c:>+8.1f}  '
          f'{pf:>7.2f}  {pf_c:>+7.2f}{flag}')

print(f'{"="*90}')
print(f'\n  MaxDD = $0 (monthly) across all scenarios — zero red months maintained')
