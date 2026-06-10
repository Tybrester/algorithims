"""
Boof 23 — Boofinator No-ETF Per-Symbol Backtest
Symbols: AAPL, AMD, AMZN, COIN, GOOGL, META, NVDA, PLTR, TSLA  (MSFT not in cache)
Window:  Jul–Dec 2025 (6 months)
Config:  prox=30, engulf=off

Per-symbol report:
  EV/trade
  EV drift vs B23 baseline ($7.98)
  Tier 1/2/3 trigger frequency (per rolling 30-trade window)
  Max loss streak
  Slippage p90 (intrabar randomness proxy — wick uncertainty sim)
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, TIME_EXIT_PCT, MAX_HOLD)

CORE_SIZE  = 600; EXP_SIZE = 200; PROX = 30
BASELINE_EV = 7.98   # B23 17-month benchmark

# Boofinator no-ETF (cached symbols only — MSFT not in cache)
BOOFINATOR      = ['AAPL', 'AMD', 'AMZN', 'COIN', 'GOOGL', 'META', 'NVDA', 'PLTR', 'TSLA']
BOOFINATOR_ETF  = ['QQQ', 'SPY']
MONTHS          = ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTHS_21       = ['Jul 25', 'Aug 25', 'Sep 25', 'Oct 25', 'Nov 25', 'Dec 25']

# ── Tier thresholds (from live tracker) ──────────────────────────
T1_EV, T2_EV, T3_EV             = 0.15, 0.25, 0.40
T1_SLIP_P90, T2_SLIP, T3_SLIP   = 0.12, 0.15, 0.20
T1_STREAK, T3_STREAK             = 7, 9

RNG = np.random.default_rng(42)

print('Loading caches...')
cache25   = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache21   = pickle.load(open('_boof21_cache.pkl', 'rb'))

def run_symbol(sym, prox=30, cache=None, months=None):
    """Run B23 on one symbol, return list of trade dicts."""
    if cache  is None: cache  = cache25
    if months is None: months = MONTHS
    F = FRACTAL_BARS; trades = []
    params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
    vol_mult    = params['vol_mult']
    atr_mult    = params['atr_mult']
    sr_dist_max = params['sr_dist']

    for mo in months:
        df = cache.get((sym, mo))
        if df is None or len(df) < 100: continue
        import pandas as pd
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

        trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(highs, lows, opens, closes)

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
            pnl_pct = ((atr*ATR_TP/ep) if et=='tp'
                       else -(atr*ATR_SL/ep) if et=='sl'
                       else TIME_EXIT_PCT)
            size = CORE_SIZE if slack >= 1.4 else EXP_SIZE

            # Wick uncertainty proxy for slippage p90 (single pass, no MC)
            wick_slip = float(RNG.uniform(0, 0.15 * atr))
            slip_atr  = wick_slip / atr

            trades.append({
                'pnl':      pnl_pct * size,
                'et':       et,
                'atr':      atr,
                'ep':       ep,
                'slip_atr': slip_atr,
                'mo':       mo,
            })
    return trades

def tier_flags(ev_drift_pct, mean_slip, p90_slip, max_streak, n_heavy):
    """Return (t_ev, t_slip, t_streak, overall)."""
    d = abs(ev_drift_pct)
    t_ev     = 3 if d > T3_EV*100 else 2 if d > T2_EV*100 else 1 if d > T1_EV*100 else 0
    t_slip   = 3 if mean_slip > T3_SLIP else 2 if mean_slip > T2_SLIP else 1 if p90_slip > T1_SLIP_P90 else 0
    t_streak = 3 if max_streak > T3_STREAK else 2 if n_heavy > 1 else 1 if max_streak >= T1_STREAK else 0
    return t_ev, t_slip, t_streak, max(t_ev, t_slip, t_streak)

def streak_stats(trades):
    win_seq = [t['pnl'] > 0 for t in trades]
    streaks = []; cur = 0
    for w in win_seq:
        if not w: cur += 1
        else:
            if cur > 0: streaks.append(cur)
            cur = 0
    if cur > 0: streaks.append(cur)
    max_streak = max(streaks) if streaks else 0
    n_heavy    = sum(1 for s in streaks if s >= T1_STREAK)
    return max_streak, n_heavy, streaks

# ── Rolling tier trigger frequency (30-trade window) ──────────────
def rolling_tier_freq(trades, window=30):
    """Count how often each tier is triggered in rolling windows."""
    counts = {0:0, 1:0, 2:0, 3:0}
    if len(trades) < window:
        return counts, 0
    n_windows = 0
    for start in range(0, len(trades) - window + 1, window):
        chunk = trades[start:start+window]
        arr   = np.array([t['pnl'] for t in chunk])
        n = len(arr); pos = arr[arr>0]; neg = arr[arr<0]
        ev_c   = float(np.mean(arr))
        drift  = (ev_c - BASELINE_EV) / BASELINE_EV * 100
        slips  = np.array([t['slip_atr'] for t in chunk])
        ms, nh, _ = streak_stats(chunk)
        _, _, _, overall = tier_flags(drift, float(np.mean(slips)), float(np.percentile(slips,90)), ms, nh)
        counts[overall] += 1
        n_windows += 1
    return counts, n_windows

TIER_SYM = {0: ' . ', 1: ' 1 ', 2: ' 2 ', 3: ' 3 '}

# ── Run all symbols ────────────────────────────────────────────────
ALL_SYMS = BOOFINATOR + BOOFINATOR_ETF

print(f'Running Boofinator no-ETF (9 syms, Jul–Dec 2025)...\n')
results = {}
for sym in BOOFINATOR:
    t = run_symbol(sym, cache=cache25, months=MONTHS)
    results[sym] = t
    print(f'  {sym}: {len(t)} trades')

print(f'\nRunning ETFs (QQQ, SPY from boof21 cache, Jul–Dec 2025)...\n')
for sym in BOOFINATOR_ETF:
    t = run_symbol(sym, cache=cache21, months=MONTHS_21)
    results[sym] = t
    print(f'  {sym}: {len(t)} trades')

# ── Print per-symbol table ────────────────────────────────────────
DAYS_6MO = 126

print(f'\n{"="*105}')
print(f'  BOOF 23 — Boofinator Full (No-ETF + QQQ/SPY) | Per-Symbol | Jul–Dec 2025 (6 months)')
print(f'  Baseline EV: ${BASELINE_EV}  |  prox=30, engulf=off')
print(f'{"="*105}')
print(f'  {"Sym":<6}  {"N":>5}  {"T/day":>6}  {"WR%":>6}  {"PF":>6}  {"EV$":>7}  '
      f'{"EV drift":>9}  {"MaxStr":>7}  {"SlipP90":>8}  {"Tier%":>16}  {"Overall":>9}')
print(f'  {"-"*103}')

sym_rows = []
for sym in ALL_SYMS:
    trades = results[sym]
    if not trades:
        print(f'  {sym:<6}  NO DATA')
        continue
    arr    = np.array([t['pnl'] for t in trades])
    n      = len(arr)
    pos    = arr[arr>0]; neg = arr[arr<0]
    wr     = round(len(pos)/n*100, 1)
    pf     = round(float(sum(pos)/max(abs(sum(neg)),0.01)), 2)
    ev     = round(float(np.mean(arr)), 2)
    tpd    = round(n/DAYS_6MO, 1)
    drift  = round((ev - BASELINE_EV)/BASELINE_EV*100, 1)

    slips   = np.array([t['slip_atr'] for t in trades])
    mean_sl = round(float(np.mean(slips)), 3)
    p90_sl  = round(float(np.percentile(slips, 90)), 3)

    ms, nh, _ = streak_stats(trades)
    t_ev, t_slip, t_streak, overall = tier_flags(drift, mean_sl, p90_sl, ms, nh)

    tier_counts, n_win = rolling_tier_freq(trades)
    t0_pct = round(tier_counts[0]/max(n_win,1)*100)
    t1_pct = round(tier_counts[1]/max(n_win,1)*100)
    t2_pct = round(tier_counts[2]/max(n_win,1)*100)
    t3_pct = round(tier_counts[3]/max(n_win,1)*100)
    tier_str = f'T0:{t0_pct}% T1:{t1_pct}% T2:{t2_pct}% T3:{t3_pct}%'

    overall_str = {0:'  OK', 1:'[T1]', 2:'[T2]', 3:'[T3]'}[overall]
    drift_str   = f'{drift:+.1f}%'
    drift_flag  = ' !' if abs(drift) > 25 else ('  ' if abs(drift) <= 15 else ' ~')

    sym_rows.append((sym, n, tpd, wr, pf, ev, drift, ms, p90_sl, tier_str, overall_str,
                     t_ev, t_slip, t_streak, tier_counts, n_win))
    print(f'  {sym:<6}  {n:>5}  {tpd:>6}  {wr:>6}  {pf:>6}  {ev:>7}  '
          f'{drift_str:>8}{drift_flag}  {ms:>7}  {p90_sl:>8}  {tier_str:>16}  {overall_str}')

print(f'  {"-"*103}')

# -- Aggregate across all symbols ──────────────────────────────────
all_trades = [t for sym in ALL_SYMS for t in results[sym]]
if all_trades:
    arr    = np.array([t['pnl'] for t in all_trades])
    n      = len(arr)
    pos    = arr[arr>0]; neg = arr[arr<0]
    wr     = round(len(pos)/n*100, 1)
    pf     = round(float(sum(pos)/max(abs(sum(neg)),0.01)), 2)
    ev     = round(float(np.mean(arr)), 2)
    tpd    = round(n/DAYS_6MO, 1)
    drift  = round((ev - BASELINE_EV)/BASELINE_EV*100, 1)
    ms_all, nh_all, _ = streak_stats(all_trades)
    slips_all = np.array([t['slip_atr'] for t in all_trades])
    p90_all   = round(float(np.percentile(slips_all, 90)), 3)
    total_pnl = round(float(sum(arr)))
    print(f'  {"ALL":<6}  {n:>5}  {tpd:>6}  {wr:>6}  {pf:>6}  {ev:>7}  '
          f'{drift:>+8.1f}%   {ms_all:>7}  {p90_all:>8}  {"":>16}  ${total_pnl:,}')

# ── Per-symbol narrative ───────────────────────────────────────────
print(f'\n{"="*105}')
print(f'  PER-SYMBOL TIER SUMMARY')
print(f'{"="*105}')
print(f'  {"Sym":<6}  {"EV$":>7}  {"EV drift":>9}  {"EV":>5}  {"Slip":>6}  {"Streak":>8}  {"Overall":>9}  Notes')
print(f'  {"-"*103}')

TIER_ICON = {0:'  OK', 1:'  T1', 2:'  T2', 3:'  T3'}
for row in sym_rows:  # ALL_SYMS order
    sym, n, tpd, wr, pf, ev, drift, ms, p90_sl, tier_str, overall_str, t_ev, t_slip, t_streak, tc, nw = row
    notes = []
    if t_ev   == 3: notes.append('EV FAIL')
    elif t_ev == 2: notes.append('EV degraded')
    elif t_ev == 1: notes.append('EV watch')
    if t_slip == 3: notes.append('SLIP FAIL')
    elif t_slip==2: notes.append('slip high')
    elif t_slip==1: notes.append('slip watch')
    if t_streak==3: notes.append('STREAK FAIL')
    elif t_streak==2: notes.append('streak clusters')
    elif t_streak==1: notes.append(f'streak {ms}')
    if not notes: notes.append('clean')
    print(f'  {sym:<6}  {ev:>7}  {drift:>+8.1f}%  {TIER_ICON[t_ev]:>5}  {TIER_ICON[t_slip]:>6}  '
          f'{TIER_ICON[t_streak]:>8}  {overall_str:>9}  {", ".join(notes)}')

# ── Ranking: best to worst ─────────────────────────────────────────
print(f'\n{"="*105}')
print(f'  SYMBOL RANKING (by EV, Jul–Dec 2025) — include or drop guidance')
print(f'{"="*105}')
ranked = sorted(sym_rows, key=lambda r: r[5], reverse=True)
for rank, row in enumerate(ranked, 1):
    sym, n, tpd, wr, pf, ev, drift, ms, p90_sl, tier_str, overall_str, *_ = row
    ann_proj = round(ev * n / 6 * 12)  # rough annualized
    rec = 'KEEP' if overall_str in ('  OK','[T1]') else ('WATCH' if '[T2]' in overall_str else 'DROP')
    print(f'  {rank}. {sym:<6}  EV=${ev:>7}  drift={drift:>+6.1f}%  WR={wr}%  '
          f'streak={ms}  ann~${ann_proj:,}  {overall_str}  → {rec}')

print(f'{"="*105}')
print(f'\n  Note: MSFT not in cache — excluded. QQQ/SPY pulled from boof21 cache (1-min bars, same B23 engine).')
print(f'  Slippage p90 simulated via wick-uncertainty proxy (uniform 0–0.15 ATR).')
print(f'  For real live slippage, use _b23_live_tracker.py with actual fill prices.')
