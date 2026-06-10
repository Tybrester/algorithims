"""
Boof 23 Deep Analysis
- Per-year: 2024, 2025, 2026
- Walk-forward (train 2024, test 2025, test 2026)
- Monte Carlo (1000 runs, resample trades with replacement)
"""

import pickle, os
import pandas as pd
import numpy as np

# ── CONFIG (exact live deployed) ─────────────────────────────────────────────
BOOF23_CFG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'FRACTAL_BARS': 3, 'ATR_MULT': 0.4,
    'CLUSTER_MERGE': 0.5, 'SR_STRENGTH_MIN': 2, 'SR_DIST_MAX': 1.0,
    'RVOL_MIN': 0.8, 'ZZ_PROX_BARS': 30, 'USE_ENGULF': False,
    'MAX_LOOKBACK': 10,
}
SYMBOLS   = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
TOP20     = ['INTC','AAPL','TSLA','AMZN','AMD','GOOGL','BAC','UBER',
             'WFC','CSCO','MU','XOM','FCX','SLB','CCL','MSFT','NKE',
             'MRVL','TSM','SOFI']
CACHE_DIR = "boof_cache"
ET        = "America/New_York"
TP_PCT    = 0.0005
SL_PCT    = 0.0003


# ── helpers ───────────────────────────────────────────────────────────────────
def compute_atr(df, period=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def compute_rvol(df, vol_len=50):
    return df['volume'] / compute_vol_sma(df, vol_len)

def build_zigzag(df):
    n = len(df)
    highs, lows = df['high'].values, df['low'].values
    opens, closes = df['open'].values, df['close'].values
    trend = [''] * n
    zz_high_bar = [-1] * n; zz_low_bar = [-1] * n
    t = ''; last_high = highs[0]; last_low = lows[0]
    higher_pt = highs[0]; higher_bar = 0
    lower_pt  = lows[0];  lower_bar  = 0
    cur_zz_high_bar = 0; cur_zz_low_bar = 0
    for i in range(1, n):
        if highs[i] > higher_pt: higher_pt = highs[i]; higher_bar = i
        if lows[i]  < lower_pt:  lower_pt  = lows[i];  lower_bar  = i
        if closes[i] > last_high or opens[i] > last_high:
            if t == 'down':
                cur_zz_low_bar = lower_bar
                higher_pt = highs[i]; higher_bar = i
            t = 'up'; last_high = highs[i]; last_low = lows[i]
        elif closes[i] < last_low or opens[i] < last_low:
            if t == 'up':
                cur_zz_high_bar = higher_bar
                lower_pt = lows[i]; lower_bar = i
            t = 'down'; last_high = highs[i]; last_low = lows[i]
        trend[i] = t
        zz_high_bar[i] = cur_zz_high_bar
        zz_low_bar[i]  = cur_zz_low_bar
    return trend, zz_high_bar, zz_low_bar


# ── resample 1-min to 5-min ─────────────────────────────────────────────────
def resample_to_5min(df_1min):
    df = df_1min.copy()
    if 'time' in df.columns:
        df = df.set_index('time')
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
    df5 = df.resample('5min').agg({
        'open':  'first', 'high': 'max', 'low': 'min',
        'close': 'last',  'volume': 'sum'
    }).dropna(subset=['open'])
    df5 = df5.reset_index()
    df5.columns = [c.lower() for c in df5.columns]
    dt_cols = [c for c in df5.columns if c not in ('open','high','low','close','volume')]
    if dt_cols and dt_cols[0] != 'time':
        df5 = df5.rename(columns={dt_cols[0]: 'time'})
    return df5


# ── SR cluster builder (mirrors TS buildClusterArray) ──────────────────
def build_clusters(df, atr_vals, vol_mult=1.3):
    vol_sma = compute_vol_sma(df, BOOF23_CFG['VOL_LEN'])
    valid_atr = atr_vals[atr_vals > 0]
    avg_atr = valid_atr.mean() if len(valid_atr) else 0
    if avg_atr == 0: return []
    merge_tol = avg_atr * BOOF23_CFG['CLUSTER_MERGE']
    buckets = []  # list of [price, strength]
    for i in range(BOOF23_CFG['VOL_LEN'], len(df)):
        vol = df.iloc[i]['volume']
        if vol < vol_sma.iloc[i] * vol_mult: continue
        price = (df.iloc[i]['high'] + df.iloc[i]['low']) / 2
        merged = False
        for b in buckets:
            if abs(b[0] - price) <= merge_tol:
                b[0] = (b[0] * b[1] + price) / (b[1] + 1)
                b[1] += 1
                merged = True; break
        if not merged:
            buckets.append([price, 1])
    return [b for b in buckets if b[1] >= BOOF23_CFG['SR_STRENGTH_MIN']]


def nearest_cluster_dist(price, clusters, atr):
    if not clusters or atr == 0: return float('inf')
    return min(abs(price - b[0]) / atr for b in clusters)


# ── Boof 23 backtest ─────────────────────────────────────────────────
def run_boof23(df, symbol):
    """
    Mirrors live TS getBoof23Signal exactly.
    Always operates on 5-min bars (resampled internally if needed).
    Signal + exit both on 5-min bars.
    """
    cfg = BOOF23_CFG
    # Resample to 5-min if input looks like 1-min data
    if len(df) > 5000:
        df = resample_to_5min(df)
    df = df.copy().reset_index(drop=True)
    df['atr']     = compute_atr(df, cfg['ATR_LEN'])
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol']    = compute_rvol(df, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df)
    atr_vals = df['atr'].values
    clusters  = build_clusters(df, atr_vals)  # built once over full history
    F = cfg['FRACTAL_BARS']
    highs  = df['high'].values;  lows   = df['low'].values
    closes = df['close'].values

    trades = []
    i = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5

    while i < len(df) - 2:
        # mirror: one signal check per bar, return first match
        direction = None; entry_slack = 0.0

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            if p - F < 0 or p + F + 1 > len(highs): continue

            atr_p = atr_vals[p]
            if pd.isna(atr_p) or atr_p == 0: continue

            rvol_p = df['rvol'].iloc[p]
            if rvol_p < cfg['RVOL_MIN']: continue

            # SR cluster distance filter (was missing — critical filter from TS)
            dist = nearest_cluster_dist(closes[p], clusters, atr_p)
            if dist > cfg['SR_DIST_MAX']: continue

            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
            atr_rej = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]

            if fp and atr_rej and t == 'up':
                zh = int(zz_high_bar[p])
                # TS: distFromSwing = abs(i - zz.zzHighBar) where i=pivot bar
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
                direction = 'short'; entry_slack = (highs[p] - closes[p]) / atr_p; break
            elif ft and atr_bnc and t == 'down':
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
                direction = 'long'; entry_slack = (closes[p] - lows[p]) / atr_p; break

        if direction is None: i += 1; continue

        ep = df.iloc[i+1]['open']
        tp = ep * (1 + TP_PCT) if direction == 'long' else ep * (1 - TP_PCT)
        sl = ep * (1 - SL_PCT) if direction == 'long' else ep * (1 + SL_PCT)

        exit_p = None; exit_type = None; exit_i = len(df) - 1
        same_bar_conflict = False
        for j in range(i+1, len(df)-1):
            bar = df.iloc[j]
            if direction == 'long':
                both = bar['high'] >= tp and bar['low'] <= sl
                if both: same_bar_conflict = True
                if bar['high'] >= tp: exit_p, exit_type, exit_i = tp, 'tp', j; break
                if bar['low']  <= sl: exit_p, exit_type, exit_i = sl, 'sl', j; break
            else:
                both = bar['low'] <= tp and bar['high'] >= sl
                if both: same_bar_conflict = True
                if bar['low']  <= tp: exit_p, exit_type, exit_i = tp, 'tp', j; break
                if bar['high'] >= sl: exit_p, exit_type, exit_i = sl, 'sl', j; break
        if exit_p is None:
            exit_p = df.iloc[exit_i]['close']; exit_type = 'time'

        pnl = (exit_p - ep) / ep if direction == 'long' else (ep - exit_p) / ep
        hold = exit_i - (i + 1)

        trades.append({
            'symbol': symbol,
            'entry_time': df.iloc[i+1].get('time', i+1),
            'exit_time':  df.iloc[exit_i].get('time', exit_i),
            'direction': direction,
            'entry': ep, 'exit': exit_p,
            'exit_type': exit_type,
            'pnl_pct': pnl,
            'hold_bars': hold,
            'tier': 'core' if entry_slack >= 1.4 else 'expanded',
            'same_bar_conflict': same_bar_conflict,
        })
        i = exit_i + 1  # lockout until exit

    return trades


# ── data loader ───────────────────────────────────────────────────────────────
def load_symbol(sym, start, end):
    for key in ["2024-01-01_2026-12-31", "2025-01-01_2026-12-31", "2024-01-01_2026-12-31"]:
        path = os.path.join(CACHE_DIR, f"{sym}_{key}.pkl")
        if not os.path.exists(path): continue
        df = pickle.load(open(path, "rb"))
        if not isinstance(df, pd.DataFrame): continue
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
        df.columns = [c.lower() for c in df.columns]
        df = df[~df.index.duplicated(keep='first')].sort_index()
        df = df[(df.index >= start) & (df.index <= end)]
        if len(df) < 500: continue
        df = df.reset_index(drop=False)
        # rename whatever the datetime index col is to 'time'
        dt_cols = [c for c in df.columns if c not in ('open','high','low','close','volume')]
        if dt_cols and dt_cols[0] != 'time':
            df = df.rename(columns={dt_cols[0]: 'time'})
        return df
    return None


# ── report ────────────────────────────────────────────────────────────────────
def report(trades, title):
    if not trades: print(f"\n{title}: No trades"); return
    df  = pd.DataFrame(trades)
    pnl = df['pnl_pct']
    wins = pnl[pnl > 0]; losses = pnl[pnl <= 0]
    pf  = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf')
    cum = pnl.cumsum(); mdd = (cum - cum.cummax()).min()
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")
    print(f"  Trades:        {len(df)}")
    print(f"  Win Rate:      {(pnl>0).mean()*100:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Avg Trade:     {pnl.mean()*100:+.4f}%")
    print(f"  Total Return:  {pnl.sum()*100:+.2f}%")
    print(f"  Max Drawdown:  {mdd*100:+.2f}%")
    if 'hold_bars' in df.columns:
        h = df['hold_bars']
        print(f"  Hold Bars:     med={h.median():.0f}  p90={h.quantile(.9):.0f}  max={h.max()}")
    by_dir = df.groupby('direction')['pnl_pct'].agg(
        n='count', wr=lambda x: (x>0).mean()*100, avg=lambda x: x.mean()*100).round(2)
    by_exit = df.groupby('exit_type')['pnl_pct'].agg(
        n='count', wr=lambda x: (x>0).mean()*100).round(2)
    print(f"\n  BY DIRECTION:\n{by_dir}")
    print(f"\n  BY EXIT:\n{by_exit}")

    # Sanity check: trades per day distribution
    if 'entry_time' in df.columns:
        dates = pd.to_datetime(df['entry_time']).dt.date
        per_day = dates.value_counts()
        desc = per_day.describe()
        print(f"\n  TRADES/DAY (sanity):")
        print(f"    Days traded: {len(per_day)}  Total: {len(df)}")
        print(f"    mean={desc['mean']:.1f}  median={per_day.median():.0f}  "
              f"p90={per_day.quantile(.9):.0f}  max={per_day.max()}")
        if per_day.max() > 50:
            top = per_day[per_day > 50]
            print(f"    WARNING: {len(top)} days with >50 trades: {top.head(3).to_dict()}")

    if 'same_bar_conflict' in df.columns:
        conflict = df[df['same_bar_conflict']]
        n_conflict = len(conflict)
        pct = n_conflict / len(df) * 100
        print(f"\n  SAME-BAR CONFLICTS (TP and SL both touched):")
        print(f"    Count:    {n_conflict} / {len(df)}  ({pct:.1f}% of all trades)")
        if n_conflict > 0:
            # Current result (checked TP first)
            cur_wr = (conflict['pnl_pct'] > 0).mean() * 100
            cur_ret = conflict['pnl_pct'].sum() * 100
            # Worst case: assume SL hit first on all conflicts
            wc_pnl = np.where(conflict['pnl_pct'] > 0, -SL_PCT, conflict['pnl_pct'].values)
            wc_wr  = (wc_pnl > 0).mean() * 100
            wc_ret = wc_pnl.sum() * 100
            # Best case: assume TP hit first on all conflicts
            bc_pnl = np.where(conflict['pnl_pct'] <= 0, TP_PCT, conflict['pnl_pct'].values)
            bc_wr  = (bc_pnl > 0).mean() * 100
            bc_ret = bc_pnl.sum() * 100
            print(f"    Current  (TP checked first): WR={cur_wr:.1f}%  Ret={cur_ret:+.2f}%")
            print(f"    Worst    (SL always first):  WR={wc_wr:.1f}%  Ret={wc_ret:+.2f}%")
            print(f"    Best     (TP always first):  WR={bc_wr:.1f}%  Ret={bc_ret:+.2f}%")
            # Impact on overall strategy
            all_pnl = df['pnl_pct'].values.copy()
            idx = df[df['same_bar_conflict']].index
            all_wc = all_pnl.copy()
            all_wc[idx] = np.where(all_pnl[idx] > 0, -SL_PCT, all_pnl[idx])
            overall_wc_wr  = (all_wc > 0).mean() * 100
            overall_wc_ret = all_wc.sum() * 100
            print(f"    Overall WR worst case:       {overall_wc_wr:.1f}%  Ret={overall_wc_ret:+.2f}%")


# ── Monte Carlo ───────────────────────────────────────────────────────────────
def monte_carlo(trades, n_sims=1000, title="Monte Carlo"):
    if not trades: print(f"\n{title}: No trades"); return
    pnls = np.array([t['pnl_pct'] for t in trades])
    n    = len(pnls)

    sim_wr    = []
    sim_pf    = []
    sim_ret   = []
    sim_mdd   = []

    rng = np.random.default_rng(42)
    for _ in range(n_sims):
        sample = rng.choice(pnls, size=n, replace=True)
        wins   = sample[sample > 0]
        losses = sample[sample <= 0]
        wr     = (sample > 0).mean()
        pf_s   = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')
        ret    = sample.sum()
        cum    = np.cumsum(sample)
        mdd    = (cum - np.maximum.accumulate(cum)).min()
        sim_wr.append(wr); sim_pf.append(pf_s)
        sim_ret.append(ret); sim_mdd.append(mdd)

    sim_wr  = np.array(sim_wr)
    sim_pf  = np.array(sim_pf)
    sim_ret = np.array(sim_ret)
    sim_mdd = np.array(sim_mdd)

    print(f"\n{'='*65}")
    print(f"  {title}  (n={n_sims} simulations, {n} trades resampled)")
    print(f"{'='*65}")
    print(f"  Win Rate    — median: {np.median(sim_wr)*100:.1f}%  "
          f"p5: {np.percentile(sim_wr,5)*100:.1f}%  "
          f"p95: {np.percentile(sim_wr,95)*100:.1f}%")
    print(f"  Prof Factor — median: {np.median(sim_pf):.2f}  "
          f"p5: {np.percentile(sim_pf,5):.2f}  "
          f"p95: {np.percentile(sim_pf,95):.2f}")
    print(f"  Total Ret   — median: {np.median(sim_ret)*100:+.2f}%  "
          f"p5: {np.percentile(sim_ret,5)*100:+.2f}%  "
          f"p95: {np.percentile(sim_ret,95)*100:+.2f}%")
    print(f"  Max DD      — median: {np.median(sim_mdd)*100:+.2f}%  "
          f"worst p5: {np.percentile(sim_mdd,5)*100:+.2f}%")
    print(f"  P(profitable): {(sim_ret > 0).mean()*100:.1f}%")
    print(f"  P(WR > 60%):   {(sim_wr > 0.60).mean()*100:.1f}%")
    print(f"  P(WR > 65%):   {(sim_wr > 0.65).mean()*100:.1f}%")


# ── walk-forward ──────────────────────────────────────────────────────────────
def walk_forward(data_by_year):
    """Train on each year, report OOS on next. 2024->2025, 2025->2026."""
    pairs = [("2024", "2025"), ("2025", "2026"), ("2024+2025", "2026")]
    print(f"\n{'='*65}")
    print(f"  WALK-FORWARD VALIDATION")
    print(f"{'='*65}")
    for train_key, test_key in pairs:
        if '+' in train_key:
            train_t = data_by_year.get("2024", []) + data_by_year.get("2025", [])
        else:
            train_t = data_by_year.get(train_key, [])
        test_t = data_by_year.get(test_key, [])
        if not train_t or not test_t:
            print(f"  {train_key} -> {test_key}: missing data"); continue

        def stats(t):
            p = [x['pnl_pct'] for x in t]
            pnl = np.array(p)
            wins = pnl[pnl > 0]; losses = pnl[pnl <= 0]
            wr = (pnl > 0).mean()
            pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')
            return len(pnl), wr, pf, pnl.sum()

        tn, twr, tpf, tret = stats(train_t)
        en, ewr, epf, eret = stats(test_t)
        deg_wr  = (ewr - twr) * 100
        deg_ret = (eret - tret) * 100
        print(f"\n  Train {train_key}: {tn} trades  WR={twr*100:.1f}%  PF={tpf:.2f}  Ret={tret*100:+.1f}%")
        print(f"  Test  {test_key}:  {en} trades  WR={ewr*100:.1f}%  PF={epf:.2f}  Ret={eret*100:+.1f}%")
        print(f"  Degradation:     WR {deg_wr:+.1f}pp  Ret {deg_ret:+.1f}pp")


# ── main ──────────────────────────────────────────────────────────────────────
PERIODS = {
    "2024": (pd.Timestamp("2024-01-01", tz=ET), pd.Timestamp("2024-12-31", tz=ET)),
    "2025": (pd.Timestamp("2025-01-01", tz=ET), pd.Timestamp("2025-12-31", tz=ET)),
    "2026": (pd.Timestamp("2026-01-01", tz=ET), pd.Timestamp("2026-06-09", tz=ET)),
}

# ── TEST 1: 5-min signal, 1-min execution ────────────────────────────────────
def run_boof23_5sig_1exec(df_1min, symbol, tp_pct=TP_PCT, sl_pct=SL_PCT):
    """Generate signals on 5-min structure, execute/exit on 1-min bars."""
    df5 = resample_to_5min(df_1min)
    cfg = BOOF23_CFG
    df5['atr']     = compute_atr(df5, cfg['ATR_LEN'])
    df5['vol_sma'] = compute_vol_sma(df5, cfg['VOL_LEN'])
    df5['rvol']    = compute_rvol(df5, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df5)
    F = cfg['FRACTAL_BARS']
    highs5  = df5['high'].values;  lows5   = df5['low'].values
    closes5 = df5['close'].values; atrs5   = df5['atr'].values

    # Build 1-min lookup — df_1min already has 'time' col from load_symbol
    df1 = df_1min.copy().reset_index(drop=True)
    df1['time'] = pd.to_datetime(df1['time']).dt.tz_convert(ET)

    trades = []
    min_i5 = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5

    for i5 in range(min_i5, len(df5) - 2):
        row5 = df5.iloc[i5]
        if row5['rvol'] < cfg['RVOL_MIN']: continue
        atr = atrs5[i5]
        if pd.isna(atr) or atr == 0: continue

        direction = None; entry_slack = 0.0

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i5 - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i5: continue
            if p - F < 0 or p + F + 1 > len(highs5): continue
            atr_p = atrs5[p]
            if pd.isna(atr_p) or atr_p == 0: continue

            fp = (highs5[p] > highs5[p-F:p].max()) and (highs5[p] > highs5[p+1:p+F+1].max())
            ft = (lows5[p]  < lows5[p-F:p].min())  and (lows5[p]  < lows5[p+1:p+F+1].min())
            atr_rej = closes5[p] < highs5[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes5[p] > lows5[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]

            if fp and atr_rej and t == 'up':
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
                direction = 'short'; entry_slack = (highs5[p] - closes5[p]) / atr_p; break
            elif ft and atr_bnc and t == 'down':
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
                direction = 'long'; entry_slack = (closes5[p] - lows5[p]) / atr_p; break

        if direction is None: continue

        # Entry on next 1-min bar after this 5-min bar closes
        signal_time = pd.Timestamp(df5.iloc[i5]['time'])
        if signal_time.tzinfo is None:
            signal_time = signal_time.tz_localize(ET)
        # Find first 1-min bar strictly after signal_time
        mask = df1['time'] > signal_time
        if not mask.any(): continue
        entry_idx_1 = df1[mask].index[0]
        ep = df1.loc[entry_idx_1, 'open']

        tp = ep * (1 + tp_pct) if direction == 'long' else ep * (1 - tp_pct)
        sl = ep * (1 - sl_pct) if direction == 'long' else ep * (1 + sl_pct)

        # Exit on 1-min bars
        exit_p = None; exit_type = 'time'; exit_idx = len(df1) - 1
        same_bar_conflict = False
        for j in range(entry_idx_1, len(df1) - 1):
            bar = df1.iloc[j]
            if direction == 'long':
                both = bar['high'] >= tp and bar['low'] <= sl
                if both: same_bar_conflict = True
                if bar['high'] >= tp: exit_p, exit_type, exit_idx = tp, 'tp', j; break
                if bar['low']  <= sl: exit_p, exit_type, exit_idx = sl, 'sl', j; break
            else:
                both = bar['low'] <= tp and bar['high'] >= sl
                if both: same_bar_conflict = True
                if bar['low']  <= tp: exit_p, exit_type, exit_idx = tp, 'tp', j; break
                if bar['high'] >= sl: exit_p, exit_type, exit_idx = sl, 'sl', j; break
        if exit_p is None:
            exit_p = df1.iloc[exit_idx]['close']

        pnl = (exit_p - ep) / ep if direction == 'long' else (ep - exit_p) / ep
        hold = exit_idx - entry_idx_1

        trades.append({
            'symbol': symbol, 'direction': direction,
            'entry': ep, 'exit': exit_p, 'exit_type': exit_type,
            'pnl_pct': pnl, 'hold_bars': hold,
            'tier': 'core' if entry_slack >= 1.4 else 'expanded',
            'same_bar_conflict': same_bar_conflict,
        })

    return trades


# ── Strict 4-rule: 5-min signal + 1-min execution ────────────────────────────
def run_boof23_strict_5sig_1exec(df_1min, symbol, tp_pct=TP_PCT, sl_pct=SL_PCT, cooldown_bars=10):
    """
    4-rule strict signal on 5-min bars, entry+exit on 1-min bars.
    Rule 1: one trade per pivot (used_pivots)
    Rule 2: lockout — skip 5-min bars until 1-min exit found
    Rule 3: 10-bar (5-min) cooldown after exit
    Rule 4: close must CROSS pivot level (not just be past it)
    """
    df5 = resample_to_5min(df_1min)
    cfg = BOOF23_CFG
    df5['atr']     = compute_atr(df5, cfg['ATR_LEN'])
    df5['vol_sma'] = compute_vol_sma(df5, cfg['VOL_LEN'])
    df5['rvol']    = compute_rvol(df5, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df5)
    atr5    = df5['atr'].values
    clusters = build_clusters(df5, atr5)
    F       = cfg['FRACTAL_BARS']
    highs5  = df5['high'].values;  lows5   = df5['low'].values
    closes5 = df5['close'].values

    df1 = df_1min.copy().reset_index(drop=True)
    df1['time'] = pd.to_datetime(df1['time']).dt.tz_convert(ET)
    times1 = df1['time'].values  # numpy array for fast search

    trades      = []
    used_pivots = set()
    min_i5      = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5
    i5          = min_i5
    next_entry_after_1min = 0  # 1-min index: don't enter before this

    while i5 < len(df5) - 2:
        row5 = df5.iloc[i5]
        if row5['rvol'] < cfg['RVOL_MIN']: i5 += 1; continue
        atr_i = atr5[i5]
        if pd.isna(atr_i) or atr_i == 0: i5 += 1; continue

        direction = None; entry_slack = 0.0; chosen_p = -1

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i5 - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i5: continue
            if p - F < 0 or p + F + 1 > len(highs5): continue
            if p in used_pivots: continue  # Rule 1

            atr_p = atr5[p]
            if pd.isna(atr_p) or atr_p == 0: continue
            if df5.iloc[p]['rvol'] < cfg['RVOL_MIN']: continue

            dist = nearest_cluster_dist(closes5[p], clusters, atr_p)
            if dist > cfg['SR_DIST_MAX']: continue

            fp = (highs5[p] > highs5[p-F:p].max()) and (highs5[p] > highs5[p+1:p+F+1].max())
            ft = (lows5[p]  < lows5[p-F:p].min())  and (lows5[p]  < lows5[p+1:p+F+1].min())
            atr_rej = closes5[p] < highs5[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes5[p] > lows5[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]

            # Rule 4: cross check on 5-min bars
            if i5 < 1: continue
            prev_c = closes5[i5 - 1]; cur_c = closes5[i5]

            if fp and atr_rej and t == 'up':
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
                if not (prev_c >= highs5[p] and cur_c < highs5[p]): continue
                direction = 'short'; entry_slack = (highs5[p] - closes5[p]) / atr_p
                chosen_p = p; break
            elif ft and atr_bnc and t == 'down':
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
                if not (prev_c <= lows5[p] and cur_c > lows5[p]): continue
                direction = 'long'; entry_slack = (closes5[p] - lows5[p]) / atr_p
                chosen_p = p; break

        if direction is None: i5 += 1; continue

        # Rule 1: consume pivot
        used_pivots.add(chosen_p)

        # Find first 1-min bar after this 5-min bar closes
        signal_time = pd.Timestamp(df5.iloc[i5]['time'])
        if signal_time.tzinfo is None:
            signal_time = signal_time.tz_localize(ET)
        mask = df1['time'] > signal_time
        if not mask.any(): i5 += 1; continue
        entry_idx_1 = df1[mask].index[0]

        # Rule 2: respect lockout
        if entry_idx_1 < next_entry_after_1min:
            i5 += 1; continue

        ep = df1.loc[entry_idx_1, 'open']
        tp = ep * (1 + tp_pct) if direction == 'long' else ep * (1 - tp_pct)
        sl = ep * (1 - sl_pct) if direction == 'long' else ep * (1 + sl_pct)

        exit_p = None; exit_type = 'time'; exit_idx = len(df1) - 1
        same_bar_conflict = False
        for j in range(entry_idx_1, len(df1) - 1):
            bar = df1.iloc[j]
            if direction == 'long':
                both = bar['high'] >= tp and bar['low'] <= sl
                if both: same_bar_conflict = True
                if bar['high'] >= tp: exit_p, exit_type, exit_idx = tp, 'tp', j; break
                if bar['low']  <= sl: exit_p, exit_type, exit_idx = sl, 'sl', j; break
            else:
                both = bar['low'] <= tp and bar['high'] >= sl
                if both: same_bar_conflict = True
                if bar['low']  <= tp: exit_p, exit_type, exit_idx = tp, 'tp', j; break
                if bar['high'] >= sl: exit_p, exit_type, exit_idx = sl, 'sl', j; break
        if exit_p is None:
            exit_p = df1.iloc[exit_idx]['close']

        pnl  = (exit_p - ep) / ep if direction == 'long' else (ep - exit_p) / ep
        hold = exit_idx - entry_idx_1

        trades.append({
            'symbol': symbol, 'direction': direction,
            'entry': ep, 'exit': exit_p, 'exit_type': exit_type,
            'pnl_pct': pnl, 'hold_bars': hold,
            'tier': 'core' if entry_slack >= 1.4 else 'expanded',
            'same_bar_conflict': same_bar_conflict,
        })

        # Rules 2+3: lockout past 1-min exit + cooldown (cooldown in 5-min bars)
        next_entry_after_1min = exit_idx + 1
        i5 += cooldown_bars + 1

    return trades


# ── TEST 2: 5-min bars, wide targets ─────────────────────────────────────────
def run_boof23_wide(df, symbol, tp_pct=0.005, sl_pct=0.003):
    """Exact same logic as run_boof23 but with wider TP/SL."""
    return run_boof23_custom(df, symbol, tp_pct, sl_pct)

def run_boof23_custom(df, symbol, tp_pct, sl_pct):
    cfg = BOOF23_CFG
    df = df.copy().reset_index(drop=True)
    df['atr']     = compute_atr(df, cfg['ATR_LEN'])
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol']    = compute_rvol(df, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df)
    F = cfg['FRACTAL_BARS']
    highs  = df['high'].values;  lows   = df['low'].values
    closes = df['close'].values; atrs   = df['atr'].values

    trades = []
    i = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5

    while i < len(df) - 2:
        rvol = df['rvol'].iloc[i]; atr = atrs[i]
        if rvol < cfg['RVOL_MIN'] or pd.isna(atr) or atr == 0:
            i += 1; continue

        direction = None; entry_slack = 0.0

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            if p - F < 0 or p + F + 1 > len(highs): continue
            atr_p = atrs[p]
            if pd.isna(atr_p) or atr_p == 0: continue

            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
            atr_rej = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]

            if fp and atr_rej and t == 'up':
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
                direction = 'short'; entry_slack = (highs[p] - closes[p]) / atr_p; break
            elif ft and atr_bnc and t == 'down':
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
                direction = 'long'; entry_slack = (closes[p] - lows[p]) / atr_p; break

        if direction is None: i += 1; continue

        ep = df.iloc[i+1]['open']
        tp = ep * (1 + tp_pct) if direction == 'long' else ep * (1 - tp_pct)
        sl = ep * (1 - sl_pct) if direction == 'long' else ep * (1 + sl_pct)

        exit_p = None; exit_type = 'time'; exit_i = len(df) - 1
        same_bar_conflict = False
        for j in range(i+1, len(df)-1):
            bar = df.iloc[j]
            if direction == 'long':
                both = bar['high'] >= tp and bar['low'] <= sl
                if both: same_bar_conflict = True
                if bar['high'] >= tp: exit_p, exit_type, exit_i = tp, 'tp', j; break
                if bar['low']  <= sl: exit_p, exit_type, exit_i = sl, 'sl', j; break
            else:
                both = bar['low'] <= tp and bar['high'] >= sl
                if both: same_bar_conflict = True
                if bar['low']  <= tp: exit_p, exit_type, exit_i = tp, 'tp', j; break
                if bar['high'] >= sl: exit_p, exit_type, exit_i = sl, 'sl', j; break
        if exit_p is None:
            exit_p = df.iloc[exit_i]['close']

        pnl = (exit_p - ep) / ep if direction == 'long' else (ep - exit_p) / ep
        hold = exit_i - (i + 1)

        trades.append({
            'symbol': symbol, 'direction': direction,
            'entry': ep, 'exit': exit_p, 'exit_type': exit_type,
            'pnl_pct': pnl, 'hold_bars': hold,
            'tier': 'core' if entry_slack >= 1.4 else 'expanded',
            'same_bar_conflict': same_bar_conflict,
        })
        i = exit_i + 1

    return trades


def load_symbol_1min(sym, start, end):
    """Load 1-min bars (same cache files, already 1-min)."""
    return load_symbol(sym, start, end)


# ── run_boof23_strict — all 4 dedup rules applied ────────────────────
def run_boof23_strict(df, symbol, cooldown_bars=10):
    """
    Rule 1: One trade per pivot — used_pivots set.
    Rule 2: One open trade per symbol — enforced by i=exit_i+1 + cooldown.
    Rule 3: 10-bar cooldown after every trade exit.
    Rule 4: Fractal close must CROSS the pivot level (prev_close on same
            side, current close crosses through) — not just be above/below.
    """
    cfg = BOOF23_CFG
    if len(df) > 5000:
        df = resample_to_5min(df)
    df = df.copy().reset_index(drop=True)
    df['atr']     = compute_atr(df, cfg['ATR_LEN'])
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol']    = compute_rvol(df, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df)
    atr_vals = df['atr'].values
    clusters  = build_clusters(df, atr_vals)
    F = cfg['FRACTAL_BARS']
    highs  = df['high'].values;  lows  = df['low'].values
    closes = df['close'].values

    trades      = []
    used_pivots = set()   # Rule 1
    i = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5

    while i < len(df) - 2:
        direction = None; entry_slack = 0.0; chosen_p = -1

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            if p - F < 0 or p + F + 1 > len(highs): continue

            # Rule 1: skip used pivots
            if p in used_pivots: continue

            atr_p = atr_vals[p]
            if pd.isna(atr_p) or atr_p == 0: continue

            rvol_p = df['rvol'].iloc[p]
            if rvol_p < cfg['RVOL_MIN']: continue

            dist = nearest_cluster_dist(closes[p], clusters, atr_p)
            if dist > cfg['SR_DIST_MAX']: continue

            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
            atr_rej = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]

            # Rule 4: close must CROSS the pivot level on bar i
            # short: pivot high was resistance — current bar closes below it
            #        but previous bar closed above (or at) it  => cross down
            # long:  pivot low was support — current bar closes above it
            #        but previous bar closed below (or at) it  => cross up
            if i < 1: continue
            prev_close = closes[i - 1]
            cur_close  = closes[i]

            if fp and atr_rej and t == 'up':
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
                pivot_level = highs[p]
                # Rule 4: must cross BELOW pivot high (fade the peak)
                if not (prev_close >= pivot_level and cur_close < pivot_level): continue
                direction = 'short'; entry_slack = (highs[p] - closes[p]) / atr_p
                chosen_p = p; break
            elif ft and atr_bnc and t == 'down':
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
                pivot_level = lows[p]
                # Rule 4: must cross ABOVE pivot low (fade the trough)
                if not (prev_close <= pivot_level and cur_close > pivot_level): continue
                direction = 'long'; entry_slack = (closes[p] - lows[p]) / atr_p
                chosen_p = p; break

        if direction is None: i += 1; continue

        # Rule 1: consume pivot
        used_pivots.add(chosen_p)

        ep = df.iloc[i+1]['open']
        tp = ep * (1 + TP_PCT) if direction == 'long' else ep * (1 - TP_PCT)
        sl = ep * (1 - SL_PCT) if direction == 'long' else ep * (1 + SL_PCT)

        exit_p = None; exit_type = None; exit_i = len(df) - 1
        same_bar_conflict = False
        for j in range(i+1, len(df)-1):
            bar = df.iloc[j]
            if direction == 'long':
                both = bar['high'] >= tp and bar['low'] <= sl
                if both: same_bar_conflict = True
                if bar['high'] >= tp: exit_p, exit_type, exit_i = tp, 'tp', j; break
                if bar['low']  <= sl: exit_p, exit_type, exit_i = sl, 'sl', j; break
            else:
                both = bar['low'] <= tp and bar['high'] >= sl
                if both: same_bar_conflict = True
                if bar['low']  <= tp: exit_p, exit_type, exit_i = tp, 'tp', j; break
                if bar['high'] >= sl: exit_p, exit_type, exit_i = sl, 'sl', j; break
        if exit_p is None:
            exit_p = df.iloc[exit_i]['close']; exit_type = 'time'

        pnl  = (exit_p - ep) / ep if direction == 'long' else (ep - exit_p) / ep
        hold = exit_i - (i + 1)

        trades.append({
            'symbol':           symbol,
            'entry_time':       df.iloc[i+1].get('time', i+1),
            'exit_time':        df.iloc[exit_i].get('time', exit_i),
            'direction':        direction,
            'entry':            ep,
            'exit':             exit_p,
            'exit_type':        exit_type,
            'pnl_pct':          pnl,
            'hold_bars':        hold,
            'tier':             'core' if entry_slack >= 1.4 else 'expanded',
            'same_bar_conflict': same_bar_conflict,
        })
        # Rule 2 + 3: lockout to exit, then cooldown
        i = exit_i + 1 + cooldown_bars

    return trades


# ── MFE/MAE free-run: no TP, no SL, no time limit ────────────────────────────
def run_boof23_freerun(df, symbol):
    """
    Same signal logic as run_boof23.
    After each signal: scan to EOD (or next session) and record:
      MFE = max favorable excursion (how far it went in your direction)
      MAE = max adverse excursion  (how far it went against you)
      final_pct = where price ended up at EOD
    No exits. One signal per bar. Next signal only after EOD of this one.
    """
    cfg = BOOF23_CFG
    if len(df) > 5000:
        df = resample_to_5min(df)
    df = df.copy().reset_index(drop=True)
    df['atr']     = compute_atr(df, cfg['ATR_LEN'])
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol']    = compute_rvol(df, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df)
    atr_vals = df['atr'].values
    clusters  = build_clusters(df, atr_vals)
    F = cfg['FRACTAL_BARS']
    highs  = df['high'].values;  lows = df['low'].values
    closes = df['close'].values

    # Pre-build session-end index for each bar (last bar of same trading date)
    if 'time' in df.columns:
        times = pd.to_datetime(df['time'])
        dates = times.dt.date
    else:
        dates = pd.Series(['unknown'] * len(df))
    # For each bar, find the last bar index with the same date
    date_last = {}
    for idx, d in enumerate(dates):
        date_last[d] = idx  # keeps overwriting, ends up as last bar of each date

    trades = []
    i = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5

    while i < len(df) - 2:
        direction = None; entry_slack = 0.0

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            if p - F < 0 or p + F + 1 > len(highs): continue
            atr_p = atr_vals[p]
            if pd.isna(atr_p) or atr_p == 0: continue
            rvol_p = df['rvol'].iloc[p]
            if rvol_p < cfg['RVOL_MIN']: continue
            dist = nearest_cluster_dist(closes[p], clusters, atr_p)
            if dist > cfg['SR_DIST_MAX']: continue
            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
            atr_rej = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]
            if fp and atr_rej and t == 'up':
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
                direction = 'short'; entry_slack = (highs[p] - closes[p]) / atr_p; break
            elif ft and atr_bnc and t == 'down':
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
                direction = 'long'; entry_slack = (closes[p] - lows[p]) / atr_p; break

        if direction is None: i += 1; continue

        entry_bar = i + 1
        if entry_bar >= len(df): break
        ep = df.iloc[entry_bar]['open']

        # EOD = last bar of the same date as entry
        entry_date = dates.iloc[entry_bar] if entry_bar < len(dates) else None
        eod_i = date_last.get(entry_date, len(df) - 1)
        eod_i = min(eod_i, len(df) - 1)

        # Scan from entry to EOD — no exits, just track MFE and MAE
        mfe = 0.0   # max favorable excursion (always positive = good)
        mae = 0.0   # max adverse excursion  (always positive = bad)
        for j in range(entry_bar, eod_i + 1):
            bar_h = highs[j]; bar_l = lows[j]
            if direction == 'long':
                favorable = (bar_h - ep) / ep
                adverse   = (ep - bar_l) / ep
            else:
                favorable = (ep - bar_l) / ep
                adverse   = (bar_h - ep) / ep
            if favorable > mfe: mfe = favorable
            if adverse   > mae: mae = adverse

        final_close = closes[eod_i]
        final_pct = (final_close - ep) / ep if direction == 'long' else (ep - final_close) / ep

        trades.append({
            'symbol':      symbol,
            'direction':   direction,
            'entry':       ep,
            'entry_time':  df.iloc[entry_bar].get('time', entry_bar),
            'mfe_pct':     mfe * 100,    # % max move in your favor
            'mae_pct':     mae * 100,    # % max move against you
            'final_pct':   final_pct * 100,  # % at EOD close
            'hold_bars':   eod_i - entry_bar,
            'tier':        'core' if entry_slack >= 1.4 else 'expanded',
        })
        # advance past EOD so next signal is a fresh day
        i = eod_i + 1

    return trades


def report_freerun(trades, title):
    if not trades: print(f"\n{title}: No trades"); return
    df = pd.DataFrame(trades)
    mfe = df['mfe_pct']; mae = df['mae_pct']; fin = df['final_pct']

    # What % of trades ever reached various MFE thresholds
    thresholds = [0.03, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0]

    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")
    print(f"  Signals:      {len(df)}")
    print(f"\n  MAX FAVORABLE EXCURSION (MFE) — how far it went your way:")
    print(f"    mean={mfe.mean():.3f}%  median={mfe.median():.3f}%  "
          f"p90={mfe.quantile(.9):.3f}%  max={mfe.max():.3f}%")
    print(f"\n  MAX ADVERSE EXCURSION (MAE) — how far it went against you:")
    print(f"    mean={mae.mean():.3f}%  median={mae.median():.3f}%  "
          f"p90={mae.quantile(.9):.3f}%  max={mae.max():.3f}%")
    print(f"\n  FINAL (EOD close):")
    print(f"    mean={fin.mean():.3f}%  median={fin.median():.3f}%  "
          f"positive={( fin>0).mean()*100:.1f}%")
    print(f"\n  % OF TRADES THAT EVER REACHED EACH MFE THRESHOLD:")
    for thr in thresholds:
        pct_hit = (mfe >= thr).mean() * 100
        print(f"    MFE >= {thr:.2f}%  =>  {pct_hit:.1f}% of trades")
    print(f"\n  MFE vs MAE ratio (median): {(mfe/mae.replace(0, np.nan)).median():.2f}x")
    print(f"\n  TRADES/DAY (sanity):")
    dates2 = pd.to_datetime(df['entry_time']).dt.date
    per_day = dates2.value_counts()
    print(f"    Days: {len(per_day)}  mean={per_day.mean():.1f}  "
          f"median={per_day.median():.0f}  max={per_day.max()}")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    PERIODS = {
        "2024": (pd.Timestamp("2024-01-01", tz=ET), pd.Timestamp("2024-12-31", tz=ET)),
        "2025": (pd.Timestamp("2025-01-01", tz=ET), pd.Timestamp("2025-12-31", tz=ET)),
        "2026": (pd.Timestamp("2026-01-01", tz=ET), pd.Timestamp("2026-06-09", tz=ET)),
    }

    if mode in ('all', 'original'):
        print("\n" + "="*65)
        print("BOOF 23 — Per-Year + Walk-Forward + Monte Carlo")
        print("="*65)
        trades_by_year = {}
        for year, (start, end) in PERIODS.items():
            print(f"\n--- {year} ---")
            all_trades = []
            for sym in SYMBOLS:
                df = load_symbol(sym, start, end)
                if df is None: print(f"  {sym}: no data"); continue
                print(f"  {sym}: {len(df)} bars", end="  ")
                t = run_boof23(df, sym)
                print(f"{len(t)} trades")
                all_trades += t
            trades_by_year[year] = all_trades
            report(all_trades, f"BOOF 23 — {year}  [{start.date()} to {end.date()}]")
        walk_forward(trades_by_year)
        for year, trades in trades_by_year.items():
            monte_carlo(trades, n_sims=1000, title=f"BOOF 23 Monte Carlo — {year}")
        combined = sum(trades_by_year.values(), [])
        monte_carlo(combined, n_sims=2000, title="BOOF 23 Monte Carlo — ALL YEARS COMBINED")

    if mode in ('all', 'test1'):
        print("\n" + "="*65)
        print("TEST 1: 5-min SIGNAL + 1-min EXECUTION")
        print("="*65)
        for year, (start, end) in PERIODS.items():
            print(f"\n--- {year} ---")
            all_trades = []
            for sym in SYMBOLS:
                df1 = load_symbol_1min(sym, start, end)
                if df1 is None: print(f"  {sym}: no data"); continue
                print(f"  {sym}: {len(df1)} 1-min bars", end="  ")
                t = run_boof23_5sig_1exec(df1, sym)
                print(f"{len(t)} trades")
                all_trades += t
            report(all_trades, f"TEST 1 (5-min sig / 1-min exec) — {year}")

    if mode in ('all', 'test2'):
        print("\n" + "="*65)
        print("TEST 2: 5-min BARS, WIDE TARGETS  TP=0.50%  SL=0.30%")
        print("="*65)
        for year, (start, end) in PERIODS.items():
            print(f"\n--- {year} ---")
            all_trades = []
            for sym in SYMBOLS:
                df5 = load_symbol(sym, start, end)
                if df5 is None: print(f"  {sym}: no data"); continue
                df5_rs = resample_to_5min(df5)
                print(f"  {sym}: {len(df5_rs)} 5-min bars", end="  ")
                t = run_boof23_wide(df5_rs, sym, tp_pct=0.005, sl_pct=0.003)
                print(f"{len(t)} trades")
                all_trades += t
            report(all_trades, f"TEST 2 (wide TP=0.50%/SL=0.30%) — {year}")

    if mode in ('all', 'freerun'):
        print("\n" + "="*65)
        print("FREE RUN — 20 symbols, No TP/SL, Just MFE/MAE to EOD")
        print("="*65)
        all_years = []
        for year, (start, end) in PERIODS.items():
            print(f"\n--- {year} ---")
            all_trades = []
            sym_summary = []
            for sym in TOP20:
                df = load_symbol(sym, start, end)
                if df is None: print(f"  {sym}: no data"); continue
                t = run_boof23_freerun(df, sym)
                if not t: print(f"  {sym}: 0 signals"); continue
                td = pd.DataFrame(t)
                mfe = td['mfe_pct']; mae = td['mae_pct']
                ratio = (mfe / mae.replace(0, np.nan)).median()
                pct05 = (mfe >= 0.05).mean() * 100
                pct50 = (mfe >= 0.50).mean() * 100
                eod_pos = (td['final_pct'] > 0).mean() * 100
                sym_summary.append({
                    'sym': sym, 'n': len(t),
                    'mfe_med': mfe.median(), 'mae_med': mae.median(),
                    'ratio': ratio, 'pct05': pct05, 'pct50': pct50,
                    'eod_pos': eod_pos
                })
                all_trades += t
            # Per-symbol table
            ss = pd.DataFrame(sym_summary).set_index('sym')
            print(f"\n  {'SYM':6s} {'N':>5} {'MFE_med':>8} {'MAE_med':>8} "
                  f"{'MFE/MAE':>8} {'>0.05%':>7} {'>0.50%':>7} {'EOD+':>6}")
            print("  " + "-"*62)
            for row in sym_summary:
                print(f"  {row['sym']:6s} {row['n']:>5} {row['mfe_med']:>7.3f}% "
                      f"{row['mae_med']:>7.3f}% {row['ratio']:>8.2f}x "
                      f"{row['pct05']:>6.1f}% {row['pct50']:>6.1f}% {row['eod_pos']:>5.1f}%")
            all_years += all_trades
            report_freerun(all_trades, f"FREE RUN ALL 20 — {year}  [{start.date()} to {end.date()}]")
        report_freerun(all_years, "FREE RUN — ALL YEARS COMBINED")
