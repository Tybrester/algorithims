"""
Boof 23 — Regime Stress Test
Classifies each trading day as: trend_up, trend_down, chop, high_vix, fomc/cpi
Then compares B23 performance across regimes
prox=30, engulf=off
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, BOOFINGTON23, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, SR_DIST_MAX, TIME_EXIT_PCT, MAX_HOLD)

CORE_SIZE = 600; EXP_SIZE = 200; PROX = 30
MOS_25 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MOS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']

# ── Known FOMC/CPI dates (2025-2026) — approximate ───────────────
FOMC_CPI_DATES = {
    # 2025 FOMC: Jan 29, Mar 19, May 7, Jun 18, Jul 30, Sep 17, Oct 29, Dec 10
    # 2025 CPI:  Jan 15, Feb 12, Mar 12, Apr 10, May 13, Jun 11, Jul 15, Aug 13, Sep 10, Oct 15, Nov 12, Dec 10
    '2025-01-15','2025-01-29','2025-02-12','2025-03-12','2025-03-19',
    '2025-04-10','2025-05-07','2025-05-13','2025-06-11','2025-06-18',
    '2025-07-15','2025-07-30','2025-08-13','2025-09-10','2025-09-17',
    '2025-10-15','2025-10-29','2025-11-12','2025-12-10',
    # 2026
    '2026-01-28','2026-02-11','2026-03-18','2026-04-08','2026-05-06',
}

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))

def classify_day(day_df):
    """Classify a single day's 1-min bars into regime."""
    if len(day_df) < 60: return 'unknown'
    o = day_df['open'].iloc[0]
    c = day_df['close'].iloc[-1]
    h = day_df['high'].max()
    l = day_df['low'].min()
    move_pct = abs(c - o) / o * 100
    range_pct = (h - l) / o * 100
    # Trend: directional move > 0.7% AND range/move ratio < 2.5
    trend_ratio = range_pct / max(move_pct, 0.01)
    if move_pct > 0.7 and trend_ratio < 2.5:
        return 'trend_up' if c > o else 'trend_down'
    # Chop: range < 0.8% or high trend_ratio
    if range_pct < 0.8 or trend_ratio > 4.0:
        return 'chop'
    return 'normal'

def run_b23_tagged(cache, mos):
    """Run B23 and tag each trade with day regime."""
    F = FRACTAL_BARS; all_trades = []

    for mo in mos:
        for sym in BOOFINGTON23:
            df = cache.get((sym, mo))
            if df is None or len(df) < 100: continue

            params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
            vol_mult    = params['vol_mult']
            atr_mult    = params['atr_mult']
            sr_dist_max = params['sr_dist']

            df = df.copy().reset_index(drop=True)

            # Tag each bar with date and regime
            if hasattr(df.index, 'date'):
                df['date'] = df.index.date.astype(str)
            elif 'datetime' in df.columns:
                df['date'] = pd.to_datetime(df['datetime']).dt.date.astype(str)
            else:
                df['date'] = 'unknown'

            # Classify each unique day
            day_regimes = {}
            for day, grp in df.groupby('date'):
                regime = classify_day(grp)
                if str(day) in FOMC_CPI_DATES:
                    regime = 'fomc_cpi'
                day_regimes[str(day)] = regime

            atr_series    = compute_atr(df)
            df['atr']     = atr_series
            df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
            df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
            df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult
            cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

            opens  = df['open'].values;  highs = df['high'].values
            lows   = df['low'].values;   closes= df['close'].values
            atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values
            dates  = df['date'].values

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
                size    = CORE_SIZE if slack >= 1.4 else EXP_SIZE
                regime  = day_regimes.get(str(dates[i]), 'unknown')

                all_trades.append({
                    'pnl': pnl_pct * size, 'et': et, 'regime': regime,
                    'slack': slack, 'tier': 'core' if slack >= 1.4 else 'expanded',
                })
    return all_trades

print('Running regime-tagged backtest...')
trades25 = run_b23_tagged(cache25, MOS_25)
trades26 = run_b23_tagged(cache26, MOS_26)
all_trades = trades25 + trades26
print(f'  {len(all_trades):,} total trades')

# ── Stats per regime ───────────────────────────────────────────────
REGIMES = ['trend_up','trend_down','chop','fomc_cpi','normal','unknown']

def regime_stats(trades):
    if not trades: return None
    arr = np.array([t['pnl'] for t in trades])
    n   = len(arr)
    pos = arr[arr>0]; neg = arr[arr<0]
    wr  = round(len(pos)/n*100,1)
    pf  = round(float(sum(pos)/max(abs(sum(neg)),0.01)),2)
    ev  = round(float(np.mean(arr)),2)
    tot = round(float(sum(arr)))
    return n, wr, pf, ev, tot

print(f'\n{"="*80}')
print(f'  BOOF 23 — Regime Stress Test | prox=30, engulf=off')
print(f'  Day classified by open→close direction + range/move ratio')
print(f'{"="*80}')
print(f'  {"Regime":<14}  {"N":>6}  {"WR%":>7}  {"PF":>7}  {"EV$":>8}  {"Total$":>11}  {"$/trade":>9}')
print(f'  {"-"*78}')

total_n = len(all_trades)
for regime in REGIMES:
    rt = [t for t in all_trades if t['regime'] == regime]
    if not rt: continue
    n, wr, pf, ev, tot = regime_stats(rt)
    pct = round(n/total_n*100,1)
    flag = ''
    if pf < 5:   flag = '  !! LOW PF'
    elif pf < 10: flag = '  ! watch'
    print(f'  {regime:<14}  {n:>6} ({pct:>4}%)  {wr:>6}  {pf:>7}  {ev:>8}  ${tot:>10,}  '
          f'  {flag}')

# Overall
n, wr, pf, ev, tot = regime_stats(all_trades)
print(f'  {"-"*78}')
print(f'  {"ALL":<14}  {n:>6}         {wr:>6}  {pf:>7}  {ev:>8}  ${tot:>10,}')
print(f'{"="*80}')

# ── Regime distribution ────────────────────────────────────────────
print(f'\n  Regime distribution (% of trades):')
for regime in REGIMES:
    rt = [t for t in all_trades if t['regime'] == regime]
    if not rt: continue
    pct = round(len(rt)/total_n*100,1)
    bar = '#' * int(pct/2)
    print(f'    {regime:<14} {pct:>5}%  {bar}')
print()
