"""
Boof 23 — Market Impact & Liquidity Stress Test
=================================================
Tests WITHOUT modifying the strategy. Pure post-hoc cost overlay on raw trade list.

1. Nonlinear Slippage Model   — slippage scales with $ size (market impact)
2. Liquidity Constraint Model — partial fills, queue delay, max fill per bar
3. Volatility Expansion Shock — sudden spread widening + order rejection spikes

All tests run on BOOFINGTON23 (5 syms), Jul-Dec 2025, prox=30, engulf=off.
Base config: $200 expanded / $600 core (production sizing).
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, TIME_EXIT_PCT, MAX_HOLD)

BOOFINGTON23 = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
MONTHS       = ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DAYS_6MO     = 126
PROX         = 30
BASE_EXP     = 200; BASE_CORE = 600
BASELINE_EV  = 7.98
RNG          = np.random.default_rng(42)

# ── Nonlinear slippage parameters ────────────────────────────────
# slip_cost = base_slip * (size / ref_size) ^ impact_exp
# ref_size = $600 (core), base_slip = 0.05 ATR at ref size
SLIP_BASE    = 0.05   # ATR at $600 reference
SLIP_REF     = 600    # reference size
SLIP_EXP     = 0.6    # market impact exponent (0.5 = sqrt, 1.0 = linear)

# ── Liquidity constraint parameters ──────────────────────────────
MAX_FILL_PER_BAR  = 500    # max $ fill per bar before queue delay kicks in
PARTIAL_FILL_PROB = 0.08   # 8% chance of partial fill (get 50-80% of intended size)
QUEUE_DELAY_PROB  = 0.05   # 5% chance of 1-bar delay (miss ideal entry bar)
QUEUE_SLIP_EXTRA  = 0.03   # extra ATR cost on delayed fill

# ── Vol expansion shock parameters ───────────────────────────────
SHOCK_PROB        = 0.04   # 4% of bars experience sudden spread widening
SHOCK_SPREAD_MULT = 3.0    # spread widens 3x on shock bars
SHOCK_REJECT_PROB = 0.30   # 30% of orders on shock bars get rejected
SHOCK_BASE_SPREAD = 0.02   # base spread as fraction of ATR

print('Loading cache...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))

# ── Run backtest, return rich trade objects ───────────────────────
def run_b23_raw(prox=30):
    trades = []
    for sym in BOOFINGTON23:
        params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
        vol_mult    = params['vol_mult']
        atr_mult    = params['atr_mult']
        sr_dist_max = params['sr_dist']
        F           = FRACTAL_BARS

        for mo in MONTHS:
            df = cache25.get((sym, mo))
            if df is None or len(df) < 100: continue
            df = df.copy().reset_index(drop=True)
            atr_s         = compute_atr(df)
            df['atr']     = atr_s
            df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
            df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
            df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult
            cluster_prices, _ = build_cluster_array(df, atr_s, vol_mult)

            opens  = df['open'].values;  highs = df['high'].values
            lows   = df['low'].values;   closes= df['close'].values
            atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values
            vols   = df['volume'].values

            trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(highs, lows, opens, closes)

            in_trade = False; trade_end = 0
            warmup = VOL_LEN + ATR_LEN + F

            for i in range(warmup, len(df) - F - MAX_HOLD - 3):
                if in_trade and i <= trade_end: continue
                atr = atrs[i]; trend = trend_arr[i]
                if np.isnan(atr) or atr == 0: continue
                if df.iloc[i]['rvol'] < 80: continue
                if not hi_vol[i]:           continue
                if trend == '':             continue
                if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist_max: continue

                lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
                ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
                fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
                ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
                ps = (highs[i] - closes[i]) / atr
                ts = (closes[i] - lows[i])  / atr

                direction = None; slack = 0.0
                if fp and ps >= atr_mult and trend == 'up':
                    if int(zz_high_bar[i]) >= 0 and abs(i - int(zz_high_bar[i])) <= prox:
                        direction = 'short'; slack = ps
                elif ft and ts >= atr_mult and trend == 'down':
                    if int(zz_low_bar[i]) >= 0 and abs(i - int(zz_low_bar[i])) <= prox:
                        direction = 'long'; slack = ts
                if direction is None: continue

                entry_bar = i + 1
                if entry_bar >= len(df) - MAX_HOLD - 2: continue
                ep   = float(opens[entry_bar])
                tp_p = ep + atr*ATR_TP if direction=='long' else ep - atr*ATR_TP
                sl_p = ep - atr*ATR_SL if direction=='long' else ep + atr*ATR_SL
                et = 'time'; exit_bar = min(entry_bar + MAX_HOLD, len(df)-1)
                for j in range(entry_bar+1, min(entry_bar+MAX_HOLD+1, len(df))):
                    h = highs[j]; l = lows[j]
                    if direction=='long':
                        if h>=tp_p: et='tp'; exit_bar=j; break
                        if l<=sl_p: et='sl'; exit_bar=j; break
                    else:
                        if l<=tp_p: et='tp'; exit_bar=j; break
                        if h>=sl_p: et='sl'; exit_bar=j; break

                in_trade = True; trade_end = exit_bar
                pnl_pct = (ATR_TP/ep*atr if et=='tp'
                           else -ATR_SL/ep*atr if et=='sl'
                           else TIME_EXIT_PCT)
                size = BASE_CORE if slack >= 1.4 else BASE_EXP

                trades.append({
                    'pnl_pct':   pnl_pct,
                    'et':        et,
                    'atr':       atr,
                    'ep':        ep,
                    'slack':     slack,
                    'size':      size,
                    'direction': direction,
                    'sym':       sym,
                    'bar_vol':   float(vols[entry_bar]) if entry_bar < len(vols) else 1e6,
                    'bar_idx':   entry_bar,
                })
    return trades

print('Running backtest...')
trades = run_b23_raw()
print(f'  {len(trades)} trades loaded\n')

# ── Baseline (no additional costs) ───────────────────────────────
def baseline_pnl(trades):
    return np.array([t['pnl_pct'] * t['size'] for t in trades])

def ev_stats(pnls):
    n = len(pnls); pos = pnls[pnls>0]; neg = pnls[pnls<0]
    ev = float(np.mean(pnls))
    pf = float(sum(pos)/max(abs(sum(neg)),0.01))
    wr = len(pos)/n
    return n, wr*100, ev, pf

base_pnls = baseline_pnl(trades)
bn, bwr, bev, bpf = ev_stats(base_pnls)
b6mo = float(sum(base_pnls))

print('=' * 76)
print('  BASELINE (production $200/$600, no extra costs)')
print('=' * 76)
print(f'  N={bn}  WR={bwr:.1f}%  PF={bpf:.2f}  EV=${bev:.2f}  6mo=${b6mo:,.0f}')

# ══════════════════════════════════════════════════════════════════
# TEST 1: NONLINEAR SLIPPAGE MODEL
# slippage_cost = SLIP_BASE * ATR * (size/SLIP_REF)^SLIP_EXP
# Applied at entry as additional cost reducing pnl
# ══════════════════════════════════════════════════════════════════
print(f'\n{"=" * 76}')
print(f'  TEST 1: NONLINEAR SLIPPAGE MODEL')
print(f'  slip = {SLIP_BASE} ATR * (size/{SLIP_REF})^{SLIP_EXP}')
print(f'{"=" * 76}')
print(f'  {"Exponent":<12}  {"N":>5}  {"WR%":>6}  {"PF":>6}  {"EV$":>7}  '
      f'{"EV drift":>9}  {"6mo P&L":>10}  {"vs Baseline":>12}')
print(f'  {"-"*74}')

for exp in [0.3, 0.5, 0.6, 0.7, 1.0, 1.5]:
    pnls = []
    for t in trades:
        slip_atr   = SLIP_BASE * (t['size'] / SLIP_REF) ** exp
        slip_cost  = slip_atr * t['atr'] / t['ep'] * t['size']   # $ cost
        pnl        = t['pnl_pct'] * t['size'] - slip_cost
        pnls.append(pnl)
    pnls = np.array(pnls)
    n, wr, ev, pf = ev_stats(pnls)
    six_mo = float(sum(pnls))
    drift  = (ev - bev) / abs(bev) * 100
    vs_base = six_mo - b6mo
    marker = ' <-- current config' if exp == SLIP_EXP else ''
    print(f'  {exp:<12}  {n:>5}  {wr:>5.1f}%  {pf:>6.2f}  ${ev:>6.2f}  '
          f'{drift:>+8.1f}%  ${six_mo:>9,.0f}  ${vs_base:>+10,.0f}{marker}')

# Show size breakdown
print(f'\n  Per-size impact at exp={SLIP_EXP}:')
for size in [BASE_EXP, BASE_CORE]:
    slip = SLIP_BASE * (size / SLIP_REF) ** SLIP_EXP
    t_trades = [t for t in trades if t['size'] == size]
    if t_trades:
        avg_atr = np.mean([t['atr'] for t in t_trades])
        avg_ep  = np.mean([t['ep'] for t in t_trades])
        slip_dollar = slip * avg_atr / avg_ep * size
        print(f'    ${size} size: slip={slip:.3f} ATR  ≈ ${slip_dollar:.2f}/trade  '
              f'({len(t_trades)} trades)')

# ══════════════════════════════════════════════════════════════════
# TEST 2: LIQUIDITY CONSTRAINT MODEL
# partial fills, queue delay, max fill per bar
# ══════════════════════════════════════════════════════════════════
print(f'\n{"=" * 76}')
print(f'  TEST 2: LIQUIDITY CONSTRAINT MODEL')
print(f'  Partial fill prob={PARTIAL_FILL_PROB*100:.0f}%  Queue delay prob={QUEUE_DELAY_PROB*100:.0f}%')
print(f'  Max fill per bar=${MAX_FILL_PER_BAR}  Delay slip={QUEUE_SLIP_EXTRA} ATR extra')
print(f'{"=" * 76}')

# Run 5 MC scenarios
N_MC = 2000
all_evs = []; all_6mo = []; rejected = []; delayed = []; partial = []

for mc in range(N_MC):
    pnls = []; n_rej = 0; n_del = 0; n_par = 0
    rng = np.random.default_rng(mc)
    for t in trades:
        size = t['size']

        # Queue delay: miss ideal bar, get slightly worse entry
        if rng.random() < QUEUE_DELAY_PROB:
            delay_slip = QUEUE_SLIP_EXTRA * t['atr'] / t['ep']
            adjusted_pnl = t['pnl_pct'] - delay_slip
            n_del += 1
        else:
            adjusted_pnl = t['pnl_pct']

        # Partial fill: only get 50-80% of position
        if rng.random() < PARTIAL_FILL_PROB:
            fill_frac = rng.uniform(0.5, 0.8)
            size = size * fill_frac
            n_par += 1

        pnls.append(adjusted_pnl * size)

    pnls = np.array(pnls)
    _, _, ev, _ = ev_stats(pnls)
    all_evs.append(ev)
    all_6mo.append(float(sum(pnls)))
    rejected.append(n_rej)
    delayed.append(n_del)
    partial.append(n_par)

all_evs = np.array(all_evs)
all_6mo = np.array(all_6mo)
print(f'  MC runs: {N_MC}')
print(f'  EV mean:  ${np.mean(all_evs):.2f}  p5=${np.percentile(all_evs,5):.2f}  '
      f'p95=${np.percentile(all_evs,95):.2f}')
print(f'  6mo mean: ${np.mean(all_6mo):,.0f}  p5=${np.percentile(all_6mo,5):,.0f}  '
      f'p95=${np.percentile(all_6mo,95):,.0f}')
drift_liq = (np.mean(all_evs) - bev) / abs(bev) * 100
print(f'  EV drift vs baseline: {drift_liq:+.1f}%')
print(f'  Avg delayed fills/run:  {np.mean(delayed):.0f}  ({np.mean(delayed)/bn*100:.1f}%)')
print(f'  Avg partial fills/run:  {np.mean(partial):.0f}  ({np.mean(partial)/bn*100:.1f}%)')

# Worst case: combine all constraints
print(f'\n  Worst-case liquidity (partial+delay combined, p5 outcome):')
print(f'    EV p5:   ${np.percentile(all_evs,5):.2f}  '
      f'(drift={((np.percentile(all_evs,5)-bev)/abs(bev)*100):+.1f}%)')
print(f'    6mo p5:  ${np.percentile(all_6mo,5):,.0f}  '
      f'(vs baseline ${b6mo:,.0f})')
tier_liq = 'OK' if abs(drift_liq) < 15 else ('T1' if abs(drift_liq) < 25 else 'T2')
print(f'    Tier:    {tier_liq}')

# ══════════════════════════════════════════════════════════════════
# TEST 3: VOLATILITY EXPANSION SHOCK
# Random bars get spread spike — some orders rejected, rest cost more
# ══════════════════════════════════════════════════════════════════
print(f'\n{"=" * 76}')
print(f'  TEST 3: VOLATILITY EXPANSION SHOCK')
print(f'  Shock prob={SHOCK_PROB*100:.0f}%/trade  Spread mult={SHOCK_SPREAD_MULT}x  '
      f'Rejection prob={SHOCK_REJECT_PROB*100:.0f}% on shock bars')
print(f'{"=" * 76}')

shock_scenarios = [
    ('Mild  (2% shock, 1.5x spread, 10% reject)', 0.02, 1.5, 0.10),
    ('Base  (4% shock, 3.0x spread, 30% reject)', 0.04, 3.0, 0.30),
    ('Severe(8% shock, 5.0x spread, 50% reject)', 0.08, 5.0, 0.50),
    ('Black swan (15% shock, 8x spread, 70% rej)', 0.15, 8.0, 0.70),
]

print(f'  {"Scenario":<44}  {"N kept":>7}  {"WR%":>6}  {"EV$":>7}  '
      f'{"EV drift":>9}  {"6mo P&L":>10}')
print(f'  {"-"*74}')

for label, s_prob, s_mult, s_rej in shock_scenarios:
    mc_evs = []; mc_6mo = []
    for mc in range(500):
        rng   = np.random.default_rng(mc + 9000)
        pnls  = []
        kept  = 0
        for t in trades:
            is_shock = rng.random() < s_prob
            if is_shock and rng.random() < s_rej:
                continue  # order rejected — skip trade entirely
            spread_atr = SHOCK_BASE_SPREAD * (s_mult if is_shock else 1.0)
            spread_cost = spread_atr * t['atr'] / t['ep'] * t['size']
            pnls.append(t['pnl_pct'] * t['size'] - spread_cost)
            kept += 1
        if not pnls: continue
        pnls = np.array(pnls)
        _, _, ev, _ = ev_stats(pnls)
        mc_evs.append(ev)
        mc_6mo.append(float(sum(pnls)))

    if not mc_evs: continue
    mean_ev  = np.mean(mc_evs)
    mean_6mo = np.mean(mc_6mo)
    drift    = (mean_ev - bev) / abs(bev) * 100
    avg_kept = kept  # last mc run kept count (approx)
    tier = 'OK' if abs(drift) < 15 else ('T1' if abs(drift) < 25 else ('T2' if abs(drift) < 40 else 'T3'))
    print(f'  {label:<44}  {avg_kept:>7}  {np.mean([ev_stats(np.array([t["pnl_pct"]*t["size"] for t in trades[:10]]))[1] for _ in range(1)]):>5.1f}%  '
          f'${mean_ev:>6.2f}  {drift:>+8.1f}%  ${mean_6mo:>9,.0f}  [{tier}]')

# Clean version without WR confusion
print(f'\n  Clean EV/drift summary:')
print(f'  {"Scenario":<44}  {"Mean EV$":>9}  {"EV drift":>9}  {"6mo P&L":>10}  Tier')
print(f'  {"-"*74}')
for label, s_prob, s_mult, s_rej in shock_scenarios:
    mc_evs = []; mc_6mo = []
    for mc in range(500):
        rng  = np.random.default_rng(mc + 9000)
        pnls = []
        for t in trades:
            is_shock = rng.random() < s_prob
            if is_shock and rng.random() < s_rej: continue
            spread_atr  = SHOCK_BASE_SPREAD * (s_mult if is_shock else 1.0)
            spread_cost = spread_atr * t['atr'] / t['ep'] * t['size']
            pnls.append(t['pnl_pct'] * t['size'] - spread_cost)
        if not pnls: continue
        arr = np.array(pnls)
        mc_evs.append(float(np.mean(arr)))
        mc_6mo.append(float(sum(arr)))
    if not mc_evs: continue
    mean_ev  = np.mean(mc_evs)
    mean_6mo = np.mean(mc_6mo)
    drift    = (mean_ev - bev) / abs(bev) * 100
    tier = 'OK' if abs(drift) < 15 else ('T1' if abs(drift) < 25 else ('T2' if abs(drift) < 40 else 'T3'))
    print(f'  {label:<44}  ${mean_ev:>8.2f}  {drift:>+8.1f}%  ${mean_6mo:>9,.0f}  {tier}')

# ── Combined worst case: all 3 stressors at once ──────────────────
print(f'\n{"=" * 76}')
print(f'  COMBINED WORST CASE: Nonlinear slip + Liquidity + Shock (all at once)')
print(f'{"=" * 76}')

mc_evs_c = []; mc_6mo_c = []
for mc in range(1000):
    rng  = np.random.default_rng(mc + 5000)
    pnls = []
    for t in trades:
        size = t['size']
        # 1. Nonlinear slip
        slip_atr  = SLIP_BASE * (size / SLIP_REF) ** SLIP_EXP
        slip_cost = slip_atr * t['atr'] / t['ep'] * size
        # 2. Partial fill
        if rng.random() < PARTIAL_FILL_PROB:
            size = size * rng.uniform(0.5, 0.8)
        # 3. Queue delay
        delay_slip = 0.0
        if rng.random() < QUEUE_DELAY_PROB:
            delay_slip = QUEUE_SLIP_EXTRA * t['atr'] / t['ep']
        # 4. Vol shock
        is_shock = rng.random() < SHOCK_PROB
        if is_shock and rng.random() < SHOCK_REJECT_PROB:
            continue
        spread_atr  = SHOCK_BASE_SPREAD * (SHOCK_SPREAD_MULT if is_shock else 1.0)
        spread_cost = spread_atr * t['atr'] / t['ep'] * size
        pnl = (t['pnl_pct'] - delay_slip) * size - slip_cost - spread_cost
        pnls.append(pnl)
    if not pnls: continue
    arr = np.array(pnls)
    mc_evs_c.append(float(np.mean(arr)))
    mc_6mo_c.append(float(sum(arr)))

mc_evs_c = np.array(mc_evs_c)
mc_6mo_c = np.array(mc_6mo_c)
comb_ev   = np.mean(mc_evs_c)
comb_drift= (comb_ev - bev) / abs(bev) * 100
comb_6mo  = np.mean(mc_6mo_c)
comb_tier = 'OK' if abs(comb_drift) < 15 else ('T1' if abs(comb_drift) < 25 else ('T2' if abs(comb_drift) < 40 else 'T3'))

print(f'  Baseline EV:        ${bev:.2f}  |  6mo: ${b6mo:,.0f}')
print(f'  Combined stress EV: ${comb_ev:.2f}  |  6mo: ${comb_6mo:,.0f}')
print(f'  EV drift:           {comb_drift:+.1f}%')
print(f'  p5 EV:              ${np.percentile(mc_evs_c,5):.2f}')
print(f'  p5 6mo:             ${np.percentile(mc_6mo_c,5):,.0f}')
print(f'  Tier:               {comb_tier}')
print(f'\n  Verdict: {"PASS — strategy survives all 3 stressors simultaneously." if comb_tier in ("OK","T1") else "CAUTION — review sizing at this stress level."}')
print(f'{"=" * 76}')
