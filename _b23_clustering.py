"""
Boof 23 — Trade Clustering Risk Test
Real sequential P&L analysis (not aggregated EV):
- Max consecutive loss streaks
- Loss streak distribution
- Drawdown by actual trade sequence
- Daily clustering risk (multiple losses in same day)
- Recovery time from drawdown troughs
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

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl', 'rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))

def run_b23_sequential(cache, mos):
    """Run B23 and return trades in chronological order with date tagging."""
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
            if hasattr(df.index, 'date'):
                df['date'] = df.index.date.astype(str)
            elif 'datetime' in df.columns:
                df['date'] = pd.to_datetime(df['datetime']).dt.date.astype(str)
            else:
                df['date'] = mo

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
                size = CORE_SIZE if slack >= 1.4 else EXP_SIZE

                all_trades.append({
                    'pnl':   pnl_pct * size,
                    'et':    et,
                    'size':  size,
                    'tier':  'core' if slack >= 1.4 else 'expanded',
                    'date':  str(dates[i]),
                    'sym':   sym,
                    'mo':    mo,
                    'bar_i': i,
                })
    return all_trades

print('Running sequential backtest...')
trades = (run_b23_sequential(cache25, MOS_25) +
          run_b23_sequential(cache26, MOS_26))
# Sort by bar index within month (approximate chronological order within each month)
trades.sort(key=lambda t: (t['mo'], t['bar_i']))
print(f'  {len(trades):,} trades in sequence\n')

pnl_seq = np.array([t['pnl'] for t in trades])
win_seq  = [p > 0 for p in pnl_seq]

# ── 1. Consecutive loss streaks ────────────────────────────────────
streaks = []
cur_streak = 0
all_streaks = []
for w in win_seq:
    if not w:
        cur_streak += 1
    else:
        if cur_streak > 0:
            all_streaks.append(cur_streak)
        cur_streak = 0
if cur_streak > 0:
    all_streaks.append(cur_streak)

streak_arr = np.array(all_streaks) if all_streaks else np.array([0])
max_streak   = int(streak_arr.max())
avg_streak   = round(float(streak_arr.mean()), 2)
p90_streak   = int(np.percentile(streak_arr, 90))
p99_streak   = int(np.percentile(streak_arr, 99))

# Cost of worst streak
worst_streak_trades = []
cur = []; best_seq = []
for t in trades:
    if t['pnl'] <= 0:
        cur.append(t)
    else:
        if len(cur) > len(best_seq):
            best_seq = cur[:]
        cur = []
if len(cur) > len(best_seq):
    best_seq = cur[:]
worst_cost = round(sum(t['pnl'] for t in best_seq))

# ── 2. Sequential drawdown ────────────────────────────────────────
cum_pnl  = np.cumsum(pnl_seq)
running_max = np.maximum.accumulate(cum_pnl)
drawdown    = running_max - cum_pnl
max_dd      = round(float(drawdown.max()))
max_dd_idx  = int(np.argmax(drawdown))
peak_idx    = int(np.argmax(cum_pnl[:max_dd_idx+1]))

# Recovery: trades from trough back to new high
recovery_trades = 0
if max_dd_idx < len(cum_pnl) - 1:
    trough_val = cum_pnl[max_dd_idx]
    for k in range(max_dd_idx+1, len(cum_pnl)):
        if cum_pnl[k] >= running_max[max_dd_idx]:
            recovery_trades = k - max_dd_idx
            break
    if recovery_trades == 0:
        recovery_trades = len(cum_pnl) - max_dd_idx

# ── 3. Daily clustering ───────────────────────────────────────────
from collections import defaultdict
daily = defaultdict(list)
for t in trades:
    daily[t['date']].append(t['pnl'])

daily_pnls    = [sum(v) for v in daily.values()]
daily_arr     = np.array(daily_pnls)
red_days      = sum(1 for d in daily_pnls if d < 0)
worst_day     = round(float(daily_arr.min()))
best_day      = round(float(daily_arr.max()))
avg_day       = round(float(daily_arr.mean()), 2)
multi_loss_days = sum(1 for v in daily.values() if sum(1 for p in v if p<0) >= 3)

# ── 4. Loss streak P&L distribution ──────────────────────────────
streak_costs = []
cur_cost = 0; in_streak = False
for p in pnl_seq:
    if p <= 0:
        cur_cost += p; in_streak = True
    else:
        if in_streak:
            streak_costs.append(cur_cost)
        cur_cost = 0; in_streak = False
if in_streak: streak_costs.append(cur_cost)
sc_arr = np.array(streak_costs) if streak_costs else np.array([0.0])

# ── Print results ──────────────────────────────────────────────────
print(f'{"="*70}')
print(f'  BOOF 23 — Trade Clustering Risk | prox=30, engulf=off')
print(f'  {len(trades):,} trades | 17 months')
print(f'{"="*70}')

print(f'\n  CONSECUTIVE LOSS STREAKS')
print(f'  {"-"*50}')
print(f'    Max streak:          {max_streak} consecutive losses')
print(f'    Avg streak:          {avg_streak} losses')
print(f'    p90 streak:          {p90_streak} losses')
print(f'    p99 streak:          {p99_streak} losses')
print(f'    Worst streak cost:   ${worst_cost:,}')
print(f'    Total streak events: {len(all_streaks)}')

print(f'\n  Streak length distribution:')
for length in range(1, min(max_streak+1, 12)):
    cnt = sum(1 for s in all_streaks if s == length)
    pct = round(cnt/len(all_streaks)*100, 1) if all_streaks else 0
    bar = '#' * cnt if cnt <= 40 else '#'*40 + f'..({cnt})'
    print(f'    {length:>3} losses:  {cnt:>5} ({pct:>5}%)  {bar}')

print(f'\n  SEQUENTIAL DRAWDOWN')
print(f'  {"-"*50}')
print(f'    Max drawdown:        ${max_dd:,}  (trade #{max_dd_idx:,})')
print(f'    Peak before DD:      trade #{peak_idx:,}')
print(f'    Recovery time:       {recovery_trades} trades to new equity high')
print(f'    Final equity:        ${round(float(cum_pnl[-1])):,}')

print(f'\n  DAILY CLUSTERING')
print(f'  {"-"*50}')
print(f'    Total trading days:  {len(daily)}')
print(f'    Red days:            {red_days} ({round(red_days/len(daily)*100,1)}%)')
print(f'    Worst day:           ${worst_day:,}')
print(f'    Best day:            ${best_day:,}')
print(f'    Avg day P&L:         ${avg_day}')
print(f'    Days w/ 3+ losses:   {multi_loss_days}')

print(f'\n  LOSS STREAK COST DISTRIBUTION')
print(f'  {"-"*50}')
print(f'    Total streak events: {len(sc_arr)}')
print(f'    Avg streak cost:     ${round(float(sc_arr.mean()),2)}')
print(f'    p50 streak cost:     ${round(float(np.percentile(sc_arr,50)),2)}')
print(f'    p90 streak cost:     ${round(float(np.percentile(sc_arr,90)),2)}')
print(f'    p99 streak cost:     ${round(float(np.percentile(sc_arr,99)),2)}')
print(f'    Worst streak cost:   ${round(float(sc_arr.min()),2)}')

print(f'\n{"="*70}')
print(f'  SUMMARY')
print(f'{"="*70}')
print(f'    Total P&L:    ${round(float(cum_pnl[-1])):,}')
print(f'    Win Rate:     {round(sum(win_seq)/len(win_seq)*100,1)}%')
print(f'    Max DD:       ${max_dd:,}  ({round(max_dd/max(float(running_max.max()),1)*100,1)}% of peak equity)')
print(f'    Worst streak: {max_streak} trades / ${worst_cost:,}')
print(f'    Red days:     {red_days}/{len(daily)} ({round(red_days/len(daily)*100,1)}%)')
print(f'{"="*70}')
