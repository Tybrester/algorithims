import pandas as pd
import numpy as np

# =============================================================================
# BOOF 24.0 — Boof 23 Signal + 5m ZigZag Trend Gate (Multi-Timeframe)
# =============================================================================
# Architecture:
#   Core signal:  IDENTICAL to Boof 23 (1m fractal+SR cluster+engulf)
#   Extra gate:   5m ZigZag trend must AGREE with the 1m signal direction
#       - 1m LONG  signal only passes if 5m ZigZag trend == 'down' (bouncing off low)
#       - 1m SHORT signal only passes if 5m ZigZag trend == 'up'   (fading high)
#   Result: fewer trades, same or better WR — cuts counter-trend noise
#
#   Exit: same as Boof 23 — TP +0.08% / SL -0.05% on underlying
#   Tiered sizing: Core (slack>=1.4) $600 / Expanded $200
# =============================================================================

# ── Params (mirror boof23 locked config) ──────────────────────────
ATR_LEN        = 14
VOL_LEN        = 50
MAX_HOLD       = 30
TP_PCT         = 0.0008
SL_PCT         = 0.0005
TIME_EXIT_PCT  = 0.08
ATR_MULT       = 0.6
FRACTAL_BARS   = 3
CLUSTER_MERGE  = 0.5
SR_STRENGTH_MIN= 2
SR_DIST_MAX    = 1.0
ZZ_SWING_PROX  = 10    # bars — how close to 5m swing extreme to allow entry

SYMS = ['NVDA','AAPL','META','MSFT','AMZN','GOOGL','AVGO','TSLA','LLY']

SYMBOL_PARAMS = {
    'NVDA': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
    'AAPL': {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0, 'use_engulf': True},
    'META': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
    'MSFT': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
    'AMZN': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
    'GOOGL':{'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
    'AVGO': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
    'TSLA': {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0, 'use_engulf': True},
    'LLY':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True},
}
DEFAULT_PARAMS = {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0, 'use_engulf': True}


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
                merged = True; break
        if not merged:
            clusters.append({'price': p, 'vol': v, 'touches': 1})
    valid = [c for c in clusters if c['touches'] >= SR_STRENGTH_MIN]
    if not valid:
        return np.array([]), np.array([])
    return np.array([c['price'] for c in valid]), np.array([c['touches'] for c in valid])


def nearest_sr_distance(price, cluster_prices, atr):
    if len(cluster_prices) == 0 or atr == 0:
        return float('inf')
    return float(np.min(np.abs(cluster_prices - price)) / atr)


def _build_zigzag_1m(highs, lows, opens, closes):
    """Boof23-identical 1m ZigZag."""
    n = len(highs)
    trend       = [''] * n
    zz_high     = np.full(n, np.nan); zz_high_bar = np.full(n, -1, dtype=int)
    zz_low      = np.full(n, np.nan); zz_low_bar  = np.full(n, -1, dtype=int)
    t = ''; last_high = highs[0]; last_low = lows[0]
    higher_pt = highs[0]; higher_bar = 0
    lower_pt  = lows[0];  lower_bar  = 0
    cur_zz_high = highs[0]; cur_zz_high_bar = 0
    cur_zz_low  = lows[0];  cur_zz_low_bar  = 0
    for i in range(1, n):
        if highs[i] > higher_pt: higher_pt = highs[i]; higher_bar = i
        if lows[i]  < lower_pt:  lower_pt  = lows[i];  lower_bar  = i
        if closes[i] > last_high or opens[i] > last_high:
            if t == 'down':
                cur_zz_low = lower_pt; cur_zz_low_bar = lower_bar
                higher_pt = highs[i]; higher_bar = i
            t = 'up'; last_high = highs[i]; last_low = lows[i]
        elif closes[i] < last_low or opens[i] < last_low:
            if t == 'up':
                cur_zz_high = higher_pt; cur_zz_high_bar = higher_bar
                lower_pt = lows[i]; lower_bar = i
            t = 'down'; last_high = highs[i]; last_low = lows[i]
        trend[i] = t
        zz_high[i] = cur_zz_high; zz_high_bar[i] = cur_zz_high_bar
        zz_low[i]  = cur_zz_low;  zz_low_bar[i]  = cur_zz_low_bar
    return trend, zz_high, zz_high_bar, zz_low, zz_low_bar


def _build_zigzag_5m(highs, lows, opens, closes):
    """5m ZigZag — same algorithm, used as trend gate only."""
    n = len(highs)
    trend = [''] * n
    t = ''; last_high = highs[0]; last_low = lows[0]
    for i in range(1, n):
        if closes[i] > last_high or opens[i] > last_high:
            t = 'up'; last_high = highs[i]; last_low = lows[i]
        elif closes[i] < last_low or opens[i] < last_low:
            t = 'down'; last_high = highs[i]; last_low = lows[i]
        trend[i] = t
    return trend


def resample_5m(df1m):
    df = df1m.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df.resample('5min').agg(
        {'open':'first','high':'max','low':'min','close':'last','volume':'sum'}
    ).dropna()


def run_boof24(df, symbol='NVDA'):
    """
    Boof 24.0: exact Boof 23 signal gated by 5m ZigZag trend direction.
    LONG  fires only when 5m trend == 'down'  (bouncing off a swing low)
    SHORT fires only when 5m trend == 'up'    (fading a swing high)
    """
    import bisect

    params      = SYMBOL_PARAMS.get(symbol, DEFAULT_PARAMS)
    vol_mult    = params['vol_mult']
    atr_mult    = params['atr_mult']
    sr_dist_max = params['sr_dist']
    use_engulf  = params['use_engulf']
    F           = FRACTAL_BARS

    df = df.copy()
    if len(df) < max(ATR_LEN, VOL_LEN) + F * 2 + 10:
        return []

    # ── Ensure DatetimeIndex for 5m resampling ─────────────────────
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ('time', 'timestamp', 'date'):
            if col in df.columns:
                df = df.set_index(col)
                break
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            return []
    df.index = pd.to_datetime(df.index)
    df       = df.sort_index()

    # ── 5m ZigZag trend gate (build before reset_index) ───────────
    df5       = resample_5m(df)
    df5_times = df5.index.tolist()
    trend5    = _build_zigzag_5m(
        df5['high'].values, df5['low'].values,
        df5['open'].values, df5['close'].values
    )
    times1m   = df.index  # keep timestamp array before reset

    df = df.reset_index(drop=True)

    # ── 1m indicators (identical to boof23) ───────────────────────
    atr_series    = compute_atr(df)
    df['atr']     = atr_series
    df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
    df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult

    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult)

    opens  = df['open'].values;  highs  = df['high'].values
    lows   = df['low'].values;   closes = df['close'].values
    atrs   = df['atr'].values;   hi_vol = df['hi_vol'].values

    # ── 1m ZigZag (boof23 identical) ──────────────────────────────
    trend_arr, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag_1m(
        highs, lows, opens, closes
    )

    warmup = VOL_LEN + ATR_LEN + F

    trades    = []
    in_trade  = False
    trade_end = 0

    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end:
            continue

        atr   = atrs[i]
        trend = trend_arr[i]

        if np.isnan(atr) or atr == 0: continue
        if df['rvol'].iloc[i] < 80:   continue
        if not hi_vol[i]:              continue
        if trend == '':                continue

        if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist_max:
            continue

        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
        fractal_peak   = (highs[i] > lh.max()) and (highs[i] > rh.max())
        fractal_trough = (lows[i]  < ll.min()) and (lows[i]  < rl.min())

        peak_slack   = (highs[i] - closes[i]) / atr
        trough_slack = (closes[i] - lows[i])  / atr

        direction = None; slack = 0.0

        if fractal_peak and peak_slack >= atr_mult and trend == 'up':
            zz_h_bar = int(zz_high_bar[i])
            if zz_h_bar >= 0 and abs(i - zz_h_bar) <= 10:
                engulf_ok = (not use_engulf) or (closes[i] < opens[i])
                if engulf_ok:
                    direction = 'short'; slack = peak_slack

        elif fractal_trough and trough_slack >= atr_mult and trend == 'down':
            zz_l_bar = int(zz_low_bar[i])
            if zz_l_bar >= 0 and abs(i - zz_l_bar) <= 10:
                engulf_ok = (not use_engulf) or (closes[i] > opens[i])
                if engulf_ok:
                    direction = 'long'; slack = trough_slack

        if direction is None:
            continue

        # ── 5m ZigZag gate (the new filter vs boof23) ─────────────
        try:
            t1m  = times1m[i]
            idx5 = bisect.bisect_right(df5_times, t1m) - 1
            if idx5 < 1:
                continue
            trend_5m = trend5[idx5]
        except Exception:
            continue

        if direction == 'long'  and trend_5m != 'down': continue
        if direction == 'short' and trend_5m != 'up':   continue

        # ── Entry simulation (identical to boof23) ─────────────────
        entry_bar = i + 1
        if entry_bar >= len(df) - MAX_HOLD - 2:
            continue

        ep   = float(opens[entry_bar])
        tp_p = ep * (1 + TP_PCT) if direction == 'long' else ep * (1 - TP_PCT)
        sl_p = ep * (1 - SL_PCT) if direction == 'long' else ep * (1 + SL_PCT)

        et = 'time'; exit_bar = min(entry_bar + MAX_HOLD, len(df) - 1)
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

        pnl_pct = TP_PCT if et == 'tp' else -SL_PCT if et == 'sl' else TIME_EXIT_PCT

        trades.append({
            'symbol':    symbol,
            'direction': direction,
            'entry':     ep,
            'exit_type': et,
            'pnl_pct':   pnl_pct,
            'slack':     slack,
            'tier':      'core' if slack >= 1.4 else 'expanded',
            'entry_bar': entry_bar,
            'hold_bars': exit_bar - entry_bar,
            'zz_1m':     trend,
            'zz_5m':     trend_5m,
        })

    return trades


# ── Runner ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
    from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
    from datetime import datetime
    from collections import defaultdict

    OPT_TP   =  0.35
    OPT_SL   = -0.10
    CORE_SZ  =  600
    EXP_SZ   =  200

    creds  = get_alpaca_credentials()
    MONTHS = [
        ('Dec 25', datetime(2025,12,1), datetime(2025,12,31), 23),
        ('Jan 26', datetime(2026,1,1),  datetime(2026,1,31),  23),
        ('Feb 26', datetime(2026,2,1),  datetime(2026,2,28),  20),
        ('Mar 26', datetime(2026,3,1),  datetime(2026,3,31),  21),
        ('Apr 26', datetime(2026,4,1),  datetime(2026,4,30),  22),
        ('May 26', datetime(2026,5,1),  datetime(2026,5,28),  20),
    ]

    all_trades = []

    for label, start, end, tdays in MONTHS:
        for sym in SYMS:
            print(f'  {sym} {label}...', end=' ', flush=True)
            df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
            if df is None or len(df) < 200:
                print('skip'); continue
            trades = run_boof24(df, symbol=sym)
            for t in trades:
                sz       = CORE_SZ if t['tier'] == 'core' else EXP_SZ
                pnl_opt  = OPT_TP if t['exit_type'] == 'tp' else OPT_SL if t['exit_type'] == 'sl' else 0.0
                t['pnl_dollar'] = pnl_opt * sz
                t['month']      = label
            all_trades.extend(trades)
            print(f'{len(trades)} trades')

    # ── Cooldown ───────────────────────────────────────────────────
    CD_LOSSES = 2; CD_MINS = 10
    all_trades.sort(key=lambda t: (t['month'], t['symbol'], t['entry_bar']))

    def apply_cooldown(trades):
        out = []; filtered = 0
        sym_losses = defaultdict(int); sym_cd = {}
        for t in trades:
            sym = t['symbol']; mo = t['month']; eb = t['entry_bar']
            cd = sym_cd.get(sym)
            if cd and cd[0] == mo and eb < cd[1]:
                filtered += 1; continue
            out.append(t)
            if t['exit_type'] == 'sl':
                sym_losses[sym] += 1
                if sym_losses[sym] >= CD_LOSSES:
                    sym_cd[sym] = (mo, eb + t.get('hold_bars', 1) + CD_MINS)
                    sym_losses[sym] = 0
            else:
                sym_losses[sym] = 0
        return out, filtered

    cooled, filtered = apply_cooldown(all_trades)

    def stats(trades):
        if not trades: return 0, 0, 0, 0, 0
        p = np.array([t['pnl_dollar'] for t in trades])
        pos = p[p > 0]; neg = p[p < 0]
        wr  = len(pos) / len(p) * 100
        pf  = sum(pos) / max(abs(sum(neg)), 0.01)
        return len(p), round(wr,1), round(float(np.mean(p)),2), round(float(pf),2), round(float(sum(p)),0)

    SEP = '='*68
    tdays_total = sum(d for _,_,_,d in MONTHS)

    def print_results(trades, label):
        by_month = defaultdict(list); by_sym = defaultdict(list)
        for t in trades:
            by_month[t['month']].append(t['pnl_dollar'])
            by_sym[t['symbol']].append(t['pnl_dollar'])
        n, wr, ev, pf, tot = stats(trades)
        print(f'\n{SEP}')
        print(f'  BOOF 24.0 — {label}')
        print(f'  6-Month Dec 2025–May 2026  |  9 syms  |  Core $600 / Exp $200')
        print(f'{SEP}')
        print(f'  Total trades  : {n}')
        print(f'  Trades/day    : {n/tdays_total:.1f}')
        print(f'  Win rate      : {wr:.1f}%')
        print(f'  EV / trade    : ${ev:.2f}')
        print(f'  Profit factor : {pf:.2f}')
        print(f'  6-month P&L   : ${tot:,.0f}')
        print(f'  Annualized    : ${tot*2:,.0f}')
        print(f'\n  Monthly breakdown:')
        print(f'  {"Month":<10} {"Trades":>7} {"WR":>7} {"EV":>8} {"PF":>6} {"P&L":>10}')
        print(f'  {"-"*52}')
        running = 0
        for lbl,_,_,_ in MONTHS:
            pnls = by_month[lbl]
            if not pnls: continue
            n2,wr2,ev2,pf2,tot2 = stats([{'pnl_dollar':p} for p in pnls])
            running += tot2
            print(f'  {lbl:<10} {n2:>7} {wr2:>6.1f}% ${ev2:>7.2f} {pf2:>6.2f} ${tot2:>9,.0f}  (cum ${running:,.0f})')
        print(f'\n  Per-symbol:')
        print(f'  {"Symbol":<8} {"Trades":>7} {"WR":>7} {"EV":>8} {"PF":>6} {"6mo P&L":>10}')
        print(f'  {"-"*50}')
        rows = []
        for sym in SYMS:
            pnls = by_sym[sym]
            if not pnls: continue
            n2,wr2,ev2,pf2,tot2 = stats([{'pnl_dollar':p} for p in pnls])
            rows.append((sym, n2, wr2, ev2, pf2, tot2))
        for sym,n2,wr2,ev2,pf2,tot2 in sorted(rows, key=lambda x: -x[5]):
            print(f'  {sym:<8} {n2:>7} {wr2:>6.1f}% ${ev2:>7.2f} {pf2:>6.2f} ${tot2:>9,.0f}')
        print(SEP)

    print_results(all_trades, 'RAW (no cooldown)')
    print_results(cooled,     f'WITH COOLDOWN (2 SL → {CD_MINS}min)  [{filtered} filtered]')
