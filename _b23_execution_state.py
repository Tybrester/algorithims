"""
Boof 23 — Execution State Machine + Conditional MC + Worst Realistic Day
=========================================================================
EVALUATION ONLY.

STEP 1 — Execution State Machine
  Each trade tagged with:
    volatility_state: low / normal / high / spike
    liquidity_state:  deep / normal / thin  (proxy: time-of-day + rvol)
    cluster_position: first / middle / late  (position within burst cluster)
    tod_bucket:       open (9:30-10:30) / mid (10:30-14:00) / close (14:00-16:00)
  Slippage is conditional on all four states combined.

STEP 2 — Conditional MC (1000 runs)
  Partial burst correlation: trades in same burst share 40% of outcome noise
  Dynamic slippage scaling inside clusters: each successive trade in cluster
    adds 15% more slippage (queue depth / market impact compounds)
  Regime-dependent spreads baked into slippage model

STEP 3 — Worst Realistic Day Stress Test
  Simulate: 1 high-vol spike day, 5-10 cluster bursts firing back-to-back
  Compounding spread widening: spread doubles after each burst
  Slippage compounds within burst (market impact accumulates)
  Report: worst-day P&L, true tail risk, drawdown signature
"""
import pickle, sys, numpy as np, pandas as pd
from collections import defaultdict
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, TIME_EXIT_PCT, MAX_HOLD)

# ── Config ────────────────────────────────────────────────────────
B23_SYMS   = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','LLY']
B23_EXP    = 200; B23_CORE = 500
MONTHS     = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MONTH_DAYS = [23,20,21,22,21,21,23,21,22,23,20,23]
TOTAL_DAYS = sum(MONTH_DAYS)
BURST_WIN  = 30       # bars for burst detection
MC_RUNS    = 1000
CLUSTER_SLIP_SCALE = 0.15   # +15% slip per successive trade in burst
BURST_CORR = 0.40           # 40% shared outcome noise within burst
rng = np.random.default_rng(42)

# ── Slippage model: conditional on execution state ─────────────────
# (mean_rt, sigma_rt) as fraction of price, round-trip
SLIP_TABLE = {
    # (vol_state, liq_state, cluster_pos, tod_bucket) → (mean, sigma)
    ('low',    'deep',   'first',  'open' ): (0.00014, 0.00005),
    ('low',    'deep',   'first',  'mid'  ): (0.00010, 0.00004),
    ('low',    'deep',   'first',  'close'): (0.00012, 0.00005),
    ('low',    'deep',   'middle', 'open' ): (0.00018, 0.00007),
    ('low',    'deep',   'middle', 'mid'  ): (0.00014, 0.00005),
    ('low',    'deep',   'late',   'open' ): (0.00022, 0.00009),
    ('low',    'deep',   'late',   'mid'  ): (0.00017, 0.00007),
    ('low',    'normal', 'first',  'open' ): (0.00018, 0.00007),
    ('low',    'normal', 'middle', 'mid'  ): (0.00020, 0.00008),
    ('low',    'thin',   'first',  'open' ): (0.00030, 0.00012),
    ('low',    'thin',   'middle', 'open' ): (0.00040, 0.00015),
    ('normal', 'deep',   'first',  'open' ): (0.00020, 0.00008),
    ('normal', 'deep',   'first',  'mid'  ): (0.00015, 0.00006),
    ('normal', 'deep',   'middle', 'open' ): (0.00026, 0.00010),
    ('normal', 'deep',   'middle', 'mid'  ): (0.00020, 0.00008),
    ('normal', 'deep',   'late',   'mid'  ): (0.00025, 0.00009),
    ('normal', 'normal', 'first',  'open' ): (0.00028, 0.00010),
    ('normal', 'normal', 'middle', 'open' ): (0.00036, 0.00013),
    ('normal', 'normal', 'late',   'open' ): (0.00045, 0.00016),
    ('normal', 'thin',   'first',  'open' ): (0.00050, 0.00018),
    ('normal', 'thin',   'middle', 'open' ): (0.00065, 0.00022),
    ('high',   'deep',   'first',  'open' ): (0.00040, 0.00015),
    ('high',   'deep',   'first',  'mid'  ): (0.00030, 0.00012),
    ('high',   'deep',   'middle', 'open' ): (0.00055, 0.00020),
    ('high',   'deep',   'middle', 'mid'  ): (0.00040, 0.00015),
    ('high',   'deep',   'late',   'open' ): (0.00070, 0.00025),
    ('high',   'normal', 'first',  'open' ): (0.00055, 0.00020),
    ('high',   'normal', 'middle', 'open' ): (0.00075, 0.00028),
    ('high',   'normal', 'late',   'open' ): (0.00095, 0.00035),
    ('high',   'thin',   'first',  'open' ): (0.00090, 0.00035),
    ('high',   'thin',   'middle', 'open' ): (0.00120, 0.00045),
    ('high',   'thin',   'late',   'open' ): (0.00150, 0.00060),
    ('spike',  'deep',   'first',  'open' ): (0.00080, 0.00040),
    ('spike',  'deep',   'middle', 'open' ): (0.00130, 0.00060),
    ('spike',  'deep',   'late',   'open' ): (0.00180, 0.00080),
    ('spike',  'normal', 'first',  'open' ): (0.00120, 0.00055),
    ('spike',  'normal', 'middle', 'open' ): (0.00180, 0.00075),
    ('spike',  'normal', 'late',   'open' ): (0.00240, 0.00100),
    ('spike',  'thin',   'first',  'open' ): (0.00200, 0.00090),
    ('spike',  'thin',   'middle', 'open' ): (0.00300, 0.00130),
    ('spike',  'thin',   'late',   'open' ): (0.00400, 0.00180),
}
DEFAULT_SLIP = (0.00030, 0.00012)

def lookup_slip(vol, liq, cpos, tod):
    # Try exact key first, then fall back to closest match
    key = (vol, liq, cpos, tod)
    if key in SLIP_TABLE: return SLIP_TABLE[key]
    # Fallback: match (vol, liq, cpos) ignoring tod
    for k, v in SLIP_TABLE.items():
        if k[0]==vol and k[1]==liq and k[2]==cpos: return v
    # Fallback: match (vol, liq)
    for k, v in SLIP_TABLE.items():
        if k[0]==vol and k[1]==liq: return v
    return DEFAULT_SLIP

# ── Engine ────────────────────────────────────────────────────────
print('Loading cache...')
cache = pickle.load(open('_boof22_cache.pkl', 'rb'))
print('  Done.\n')

def run_b23_esm(sym, df, mo):
    """Run B23 and tag each trade with execution state machine labels."""
    trades = []
    params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
    vol_mult    = params['vol_mult']; atr_mult = params['atr_mult']
    sr_dist_max = params['sr_dist']; F = FRACTAL_BARS
    df = df.copy().reset_index(drop=True)
    atr_s = compute_atr(df)
    df['atr']    = atr_s
    df['vol_sma']= df['volume'].rolling(VOL_LEN).mean()
    df['rvol']   = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol'] = df['volume'] > df['vol_sma'] * vol_mult
    cluster_prices, _ = build_cluster_array(df, atr_s, vol_mult)
    opens  = df['open'].values;  highs = df['high'].values
    lows   = df['low'].values;   closes= df['close'].values
    atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values
    rvols  = df['rvol'].values
    trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(highs, lows, opens, closes)

    # Pre-compute daily ATR median for spike detection
    med_atr_rel = np.nanmedian([a/c for a,c in zip(atrs, closes) if c > 0 and a > 0])

    # time-of-day from bar index (market opens at bar ~0 = 9:30 ET, 1-min bars)
    def tod_bucket(bar_i):
        mins = bar_i % 390   # bars per trading day
        if mins < 60:  return 'open'
        if mins < 270: return 'mid'
        return 'close'

    in_trade = False; trade_end = 0
    warmup = VOL_LEN + ATR_LEN + F
    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end: continue
        atr = atrs[i]; trend = trend_arr[i]
        if np.isnan(atr) or atr == 0: continue
        if df.iloc[i]['rvol'] < 80: continue
        if not hi_vol[i]: continue
        if trend == '': continue
        if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist_max: continue
        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
        fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
        ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
        ps = (highs[i] - closes[i]) / atr
        ts = (closes[i] - lows[i])  / atr
        direction = None; slack = 0.0
        if fp and ps >= atr_mult and trend == 'up':
            if int(zz_high_bar[i]) >= 0 and abs(i - int(zz_high_bar[i])) <= 30:
                direction = 'short'; slack = ps
        elif ft and ts >= atr_mult and trend == 'down':
            if int(zz_low_bar[i]) >= 0 and abs(i - int(zz_low_bar[i])) <= 30:
                direction = 'long'; slack = ts
        if direction is None: continue
        entry_bar = i + 1
        if entry_bar >= len(df) - MAX_HOLD - 2: continue
        ep = float(opens[entry_bar])
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
        raw_pnl_pct = (ATR_TP/ep*atr if et=='tp' else -ATR_SL/ep*atr if et=='sl' else TIME_EXIT_PCT)
        size = B23_CORE if slack >= 1.4 else B23_EXP

        # ── Execution State Machine tagging ──────────────────────
        atr_rel = atr / ep if ep > 0 else med_atr_rel
        if   atr_rel > med_atr_rel * 2.0: vol_state = 'spike'
        elif atr_rel > med_atr_rel * 1.4: vol_state = 'high'
        elif atr_rel > med_atr_rel * 0.6: vol_state = 'normal'
        else:                              vol_state = 'low'

        rv = rvols[i]
        if   rv > 200: liq_state = 'deep'
        elif rv > 100: liq_state = 'normal'
        else:          liq_state = 'thin'

        tod = tod_bucket(i)

        trades.append({
            'sym': sym, 'mo': mo, 'bar': i, 'ep': ep,
            'raw_pnl_pct': raw_pnl_pct, 'size': size,
            'tier': 'core' if slack >= 1.4 else 'expanded',
            'et': et, 'atr': atr, 'atr_rel': atr_rel,
            'vol_state': vol_state, 'liq_state': liq_state,
            'tod': tod, 'rvol': rv,
            'cluster_pos': 'first',  # filled in burst pass below
        })
    return trades

print('Running B23 with execution state machine...')
all_trades = []
for mo in MONTHS:
    for sym in B23_SYMS:
        df = cache.get((sym, mo))
        if df is None or len(df) < 100: continue
        all_trades.extend(run_b23_esm(sym, df, mo))
print(f'  {len(all_trades)} trades\n')

# ── Tag cluster position (first/middle/late within burst) ──────────
by_sym_mo = defaultdict(list)
for i, t in enumerate(all_trades):
    by_sym_mo[(t['sym'], t['mo'])].append((t['bar'], i))
for key, entries in by_sym_mo.items():
    entries.sort()
    burst = [entries[0]]
    for j in range(1, len(entries)):
        if entries[j][0] - burst[-1][0] <= BURST_WIN:
            burst.append(entries[j])
        else:
            # label previous burst
            for k, (_, idx) in enumerate(burst):
                if len(burst) == 1: pos = 'first'
                elif k == 0:        pos = 'first'
                elif k < len(burst)-1: pos = 'middle'
                else:               pos = 'late'
                all_trades[idx]['cluster_pos'] = pos
            burst = [entries[j]]
    for k, (_, idx) in enumerate(burst):
        if len(burst) == 1: pos = 'first'
        elif k == 0:        pos = 'first'
        elif k < len(burst)-1: pos = 'middle'
        else:               pos = 'late'
        all_trades[idx]['cluster_pos'] = pos

# Also tag cluster_id for burst grouping
cluster_id = 0
for key, entries in by_sym_mo.items():
    entries.sort()
    current_cluster = [entries[0]]
    for j in range(1, len(entries)):
        if entries[j][0] - current_cluster[-1][0] <= BURST_WIN:
            current_cluster.append(entries[j])
        else:
            for _, idx in current_cluster:
                all_trades[idx]['cluster_id'] = cluster_id
            cluster_id += 1
            current_cluster = [entries[j]]
    for _, idx in current_cluster:
        all_trades[idx]['cluster_id'] = cluster_id
    cluster_id += 1

SEP = '=' * 74

# ══════════════════════════════════════════════════════════════════
# STEP 1 — Execution State Machine summary
# ══════════════════════════════════════════════════════════════════
print(SEP)
print('  STEP 1 — EXECUTION STATE MACHINE BREAKDOWN')
print(SEP)

def stats(trades):
    if not trades: return 0, 0.0, 0.0
    p = np.array([t['raw_pnl_pct']*t['size'] for t in trades])
    pos = p[p>0]; neg = p[p<0]
    return len(p), round(float(np.mean(p)),2), round(len(pos)/len(p)*100,1)

print(f'\n  Cluster Position:')
print(f'  {"Position":<12} {"Trades":>8} {"EV/trade":>10} {"WR":>7}')
print(f'  {"-"*40}')
for cp in ['first','middle','late']:
    tr = [t for t in all_trades if t['cluster_pos']==cp]
    n, ev, wr = stats(tr)
    print(f'  {cp:<12} {n:>8} ${ev:>9.2f} {wr:>6.1f}%')

print(f'\n  Volatility State:')
print(f'  {"State":<12} {"Trades":>8} {"EV/trade":>10} {"WR":>7} {"Avg slip key":>14}')
print(f'  {"-"*50}')
for vs in ['low','normal','high','spike']:
    tr = [t for t in all_trades if t['vol_state']==vs]
    n, ev, wr = stats(tr)
    sample_slip = lookup_slip(vs, 'normal', 'first', 'open')
    print(f'  {vs:<12} {n:>8} ${ev:>9.2f} {wr:>6.1f}%  '
          f'{sample_slip[0]*100:.4f}% base slip')

print(f'\n  Liquidity State:')
print(f'  {"State":<12} {"Trades":>8} {"EV/trade":>10} {"WR":>7}')
print(f'  {"-"*40}')
for ls in ['deep','normal','thin']:
    tr = [t for t in all_trades if t['liq_state']==ls]
    n, ev, wr = stats(tr)
    print(f'  {ls:<12} {n:>8} ${ev:>9.2f} {wr:>6.1f}%')

print(f'\n  Time-of-Day Bucket:')
print(f'  {"TOD":<12} {"Trades":>8} {"EV/trade":>10} {"WR":>7}')
print(f'  {"-"*40}')
for tod in ['open','mid','close']:
    tr = [t for t in all_trades if t['tod']==tod]
    n, ev, wr = stats(tr)
    print(f'  {tod:<12} {n:>8} ${ev:>9.2f} {wr:>6.1f}%')

# ══════════════════════════════════════════════════════════════════
# STEP 2 — Conditional MC with partial burst correlation + dynamic slip
# ══════════════════════════════════════════════════════════════════
print(f'\n{SEP}')
print(f'  STEP 2 — CONDITIONAL MC ({MC_RUNS} runs)')
print(f'     Partial burst correlation: {BURST_CORR*100:.0f}% shared outcome noise')
print(f'     Dynamic slippage: +{CLUSTER_SLIP_SCALE*100:.0f}% per successive trade in cluster')
print(f'     Regime-dependent spreads via ESM lookup table')
print(SEP)

raw_pnl_pcts = np.array([t['raw_pnl_pct'] for t in all_trades])
sizes        = np.array([t['size']         for t in all_trades])

# Precompute ESM slip params per trade
slip_means  = np.array([lookup_slip(t['vol_state'], t['liq_state'],
                                    t['cluster_pos'], t['tod'])[0] for t in all_trades])
slip_sigmas = np.array([lookup_slip(t['vol_state'], t['liq_state'],
                                    t['cluster_pos'], t['tod'])[1] for t in all_trades])

# Cluster scaling: each trade in burst gets compounding slip multiplier
cluster_scale = np.ones(len(all_trades))
for key, entries in by_sym_mo.items():
    entries.sort()
    burst = [entries[0]]; pos_in_burst = [0]
    for j in range(1, len(entries)):
        if entries[j][0] - burst[-1][0] <= BURST_WIN:
            burst.append(entries[j])
            pos_in_burst.append(len(burst)-1)
        else:
            for pos, (_, idx) in zip(pos_in_burst, burst):
                cluster_scale[idx] = 1.0 + pos * CLUSTER_SLIP_SCALE
            burst = [entries[j]]; pos_in_burst = [0]
    for pos, (_, idx) in zip(pos_in_burst, burst):
        cluster_scale[idx] = 1.0 + pos * CLUSTER_SLIP_SCALE

# Cluster membership for correlation
cluster_ids   = np.array([t.get('cluster_id', 0) for t in all_trades])
n_clusters    = cluster_ids.max() + 1

mc_annual = []; mc_ev = []
for run in range(MC_RUNS):
    # Draw shared cluster noise (correlated component)
    cluster_noise = rng.normal(0, 1, n_clusters)   # one draw per cluster
    # Draw individual noise (idiosyncratic component)
    indiv_noise   = rng.normal(0, 1, len(all_trades))
    # Combine: 40% from cluster, 60% from individual
    combined_z    = (BURST_CORR**0.5 * cluster_noise[cluster_ids]
                    + (1-BURST_CORR)**0.5 * indiv_noise)
    # Draw slippage from ESM table + cluster scaling
    scaled_means  = slip_means  * cluster_scale
    scaled_sigmas = slip_sigmas * cluster_scale
    slip_rt = scaled_means + scaled_sigmas * np.abs(combined_z)  # always positive drag
    # 5% bad fill overlay
    bad_mask = rng.random(len(all_trades)) < 0.05
    bad_slip = rng.normal(0.0006, 0.0003, len(all_trades))
    slip_rt  = np.where(bad_mask, bad_slip, slip_rt)
    slip_rt  = np.clip(slip_rt, 0, None)
    net_pnl = (raw_pnl_pcts - slip_rt) * sizes
    mc_annual.append(float(sum(net_pnl)) * 2)
    mc_ev.append(float(np.mean(net_pnl)))

mc_annual = np.array(mc_annual); mc_ev = np.array(mc_ev)
p5, p25, p50, p75, p95 = np.percentile(mc_annual, [5,25,50,75,95])
ev5, ev50, ev95 = np.percentile(mc_ev, [5,50,95])

raw_annual = float(sum(raw_pnl_pcts * sizes)) * 2

print(f'\n  Annual P&L distribution:')
print(f'  {"Percentile":<16}  {"Annual P&L":>14}  {"EV/trade":>12}  {"vs raw":>8}')
print(f'  {"-"*55}')
for pct, val, ev in [(5,p5,ev5),(25,p25,None),(50,p50,ev50),(75,p75,None),(95,p95,ev95)]:
    vs = f'{val/raw_annual*100:.1f}%' if raw_annual else '-'
    ev_str = f'${ev:.2f}' if ev is not None else ''
    print(f'  {"P"+str(pct):<16}  ${val:>13,.0f}  {ev_str:>12}  {vs:>8}')

pct_above_5  = (mc_ev > 5.0).mean()*100
pct_below_3  = (mc_ev < 3.0).mean()*100
pct_positive = (mc_annual > 0).mean()*100
print(f'\n  Scenarios: EV>$5={pct_above_5:.0f}%  EV<$3={pct_below_3:.0f}%  Positive={pct_positive:.0f}%')
print(f'  Raw annual: ${raw_annual:,.0f}  |  P50: ${p50:,.0f}  |  P5: ${p5:,.0f}')
print(f'  ESM slip cost vs flat model: ${raw_annual-p50:,.0f}/yr median | ${raw_annual-p5:,.0f}/yr worst-P5')

# ══════════════════════════════════════════════════════════════════
# STEP 3 — WORST REALISTIC DAY STRESS TEST
# ══════════════════════════════════════════════════════════════════
print(f'\n{SEP}')
print('  STEP 3 — WORST REALISTIC DAY STRESS TEST')
print('     Scenario: 1 high-vol spike day, 6 cluster bursts back-to-back')
print('     Spread doubles after each burst, slippage compounds within burst')
print('     All trades lose (worst directional outcome)')
print(SEP)

# Parameters of the worst day
N_BURSTS          = 6
TRADES_PER_BURST  = [4, 5, 3, 6, 4, 5]  # realistic burst sizes
BASE_SPREAD_PCT   = 0.0004   # 0.04% — high vol spike spread
SPREAD_MULTIPLY   = 2.0      # spread doubles each burst
BASE_SLIP_PCT     = 0.0012   # 0.12% per side — spike conditions
SLIP_COMPOUND     = 0.20     # +20% slip each successive trade in burst
CORE_RATIO        = 0.40     # fraction of trades that are core ($500)
EXP_RATIO         = 0.60     # fraction expanded ($200)

def worst_day_sim(n_runs=10000):
    results = []
    for _ in range(n_runs):
        day_pnl = 0.0
        spread = BASE_SPREAD_PCT
        for b in range(N_BURSTS):
            n_trades = TRADES_PER_BURST[b]
            burst_pnl = 0.0
            for pos in range(n_trades):
                slip_entry = BASE_SLIP_PCT * (1 + pos * SLIP_COMPOUND) + spread/2
                slip_exit  = BASE_SLIP_PCT * (1 + pos * SLIP_COMPOUND) + spread/2
                total_drag = slip_entry + slip_exit
                # Worst outcome: all trades hit SL
                # B23 ATR SL is ~2x ATR, ATR/price for spike = ~0.25%
                # So SL pnl_pct ≈ -0.50% for spike day
                raw_sl_pct = -0.0050   # -0.50% (spike ATR * SL mult)
                net_pct = raw_sl_pct - total_drag
                size = rng.choice([B23_CORE, B23_EXP],
                                   p=[CORE_RATIO, EXP_RATIO])
                burst_pnl += net_pct * size
            day_pnl  += burst_pnl
            spread   *= SPREAD_MULTIPLY   # spread widens each burst
        results.append(day_pnl)
    return np.array(results)

wd = worst_day_sim(10000)
wd_p5, wd_p10, wd_p25, wd_p50 = np.percentile(wd, [5,10,25,50])
total_trades_day = sum(TRADES_PER_BURST)

print(f'\n  Day configuration:')
print(f'    Bursts: {N_BURSTS}  |  Trades: {total_trades_day}  |  '
      f'Base spread: {BASE_SPREAD_PCT*100:.3f}%  |  '
      f'Spread multiplier per burst: {SPREAD_MULTIPLY}x')
print(f'    Base slip/side: {BASE_SLIP_PCT*100:.3f}%  |  '
      f'Slip compounding: +{SLIP_COMPOUND*100:.0f}% per trade in burst')
print(f'    All trades hit SL (worst directional outcome)')
print(f'    Core/Exp mix: {CORE_RATIO*100:.0f}% / {EXP_RATIO*100:.0f}%')

print(f'\n  Worst-day P&L distribution (10,000 simulations):')
print(f'  {"Percentile":<16}  {"Day P&L":>12}  {"As % of monthly avg":>22}')
print(f'  {"-"*55}')
monthly_avg = 5360.0
for pct, val in [(5,wd_p5),(10,wd_p10),(25,wd_p25),(50,wd_p50)]:
    pct_mo = val/monthly_avg*100
    print(f'  {"P"+str(pct)+" (worst)":<16}  ${val:>11,.0f}  {pct_mo:>21.1f}%')

print(f'\n  Burst-by-burst P&L breakdown (median scenario):')
print(f'  {"Burst":>8}  {"Trades":>8}  {"Spread":>10}  {"Slip/trade":>12}  '
      f'{"Burst P&L":>12}  {"Cumulative":>12}')
print(f'  {"-"*68}')
spread = BASE_SPREAD_PCT; cum = 0.0
for b in range(N_BURSTS):
    n = TRADES_PER_BURST[b]
    burst_pnl = 0.0
    for pos in range(n):
        drag = 2*(BASE_SLIP_PCT*(1+pos*SLIP_COMPOUND) + spread/2)
        net  = (-0.0050 - drag) * (B23_CORE*CORE_RATIO + B23_EXP*EXP_RATIO)
        burst_pnl += net
    avg_slip = np.mean([2*(BASE_SLIP_PCT*(1+p*SLIP_COMPOUND)+spread/2) for p in range(n)])
    cum += burst_pnl
    print(f'  {"Burst "+str(b+1):>8}  {n:>8}  {spread*100:>9.4f}%  '
          f'{avg_slip*100:>11.4f}%  ${burst_pnl:>11,.0f}  ${cum:>11,.0f}')
    spread *= SPREAD_MULTIPLY

print(f'\n  Annual context:')
print(f'  Worst P5 day: ${wd_p5:,.0f}  vs  monthly avg: ${monthly_avg:,.0f}  '
      f'({abs(wd_p5)/monthly_avg*100:.1f}% of one month)')
print(f'  Daily avg P&L (backtest): ${raw_annual/TOTAL_DAYS:,.0f}  '
      f'| Worst day = {abs(wd_p5)/(raw_annual/TOTAL_DAYS):.1f}x average day')
print(f'  Annual P&L needed to absorb worst day: {abs(wd_p5)/raw_annual*100:.2f}% of annual')

print(f'\n{SEP}')
print('  FULL VERDICT')
print(SEP)
print(f'  ESM reveals:')
print(f'    Cluster "late" trades pay ~{(lookup_slip("normal","normal","late","open")[0]/lookup_slip("normal","normal","first","open")[0]-1)*100:.0f}% more slip than "first"')
print(f'    Spike vol trades pay ~{(lookup_slip("spike","normal","first","open")[0]/lookup_slip("normal","normal","first","open")[0]-1)*100:.0f}% more slip than normal')
print(f'    Thin liquidity vs deep: ~{(lookup_slip("high","thin","first","open")[0]/lookup_slip("high","deep","first","open")[0]-1)*100:.0f}% more slip (high vol)')
print(f'  Conditional MC P50: ${p50:,.0f}  P5: ${p5:,.0f}  (vs flat model P5: $126,929)')
print(f'  Burst correlation cost: ~${raw_annual-p50:,.0f}/yr vs uncorrelated')
print(f'  Worst realistic day: ${wd_p50:,.0f} median / ${wd_p5:,.0f} P5')
print(f'  System absorbs worst day in {abs(wd_p5)/(raw_annual/252):.1f} avg-day equivalents')
print(SEP)
