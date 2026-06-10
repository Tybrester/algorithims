"""
BOOF 24.0 — CLEAN BACKTEST (no lookahead bias)
================================================
Fixes vs original backtest_boof24.py:
  1. FRACTAL: confirmed at bar i-F using only bars i-2F..i-F..i-1 (no future bars)
     Signal fires when bar i == i_fractal + F (all right-side bars now known)
  2. CLUSTERS: rebuilt rolling at each signal bar using only bars 0..i
  3. TIME EXIT: uses actual close[exit_bar] — not a hardcoded 0.08% constant

Data: Databento CME Globex 1-minute OHLCV
Symbols: ES (E-mini S&P 500) and MNQ (Micro Nasdaq)
"""

import databento as db
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ── Databento key ────────────────────────────────────────────────────
DATABENTO_KEY = 'db-HjUMrsa7gNvavTcwU8fUdywvQSfH7'

# ── Strategy params (mirror locked boof23/24 config) ─────────────────
ATR_LEN        = 14
VOL_LEN        = 50
MAX_HOLD       = 30
TP_PCT         = 0.0008    # 0.08% on underlying
SL_PCT         = 0.0005    # 0.05% on underlying
ATR_MULT       = 0.6
FRACTAL_BARS   = 3         # F: bars each side for fractal confirmation
CLUSTER_MERGE  = 0.5       # merge gap in ATR units
SR_STRENGTH_MIN= 2         # min touches to count as SR
SR_DIST_MAX    = 1.0       # max ATR distance from cluster
ZZ_PROX_BARS   = 10        # max bars from last ZZ swing

# ── Futures symbol config ─────────────────────────────────────────────
# Databento continuous front-month symbols for CME Globex
FUTURES_SYMBOLS = {
    'ES':  {'dataset': 'GLBX.MDP3', 'stype': 'continuous', 'symbol': 'ES.c.0',
            'tick': 0.25, 'multiplier': 50,  'core_sz': 1, 'exp_sz': 1},
    'MNQ': {'dataset': 'GLBX.MDP3', 'stype': 'continuous', 'symbol': 'MNQ.c.0',
            'tick': 0.25, 'multiplier': 2,   'core_sz': 2, 'exp_sz': 1},
}

# 6-month window
START_DATE = '2025-12-01'
END_DATE   = '2026-06-01'

MONTHS = [
    ('Dec 25', '2025-12-01', '2026-01-01'),
    ('Jan 26', '2026-01-01', '2026-02-01'),
    ('Feb 26', '2026-02-01', '2026-03-01'),
    ('Mar 26', '2026-03-01', '2026-04-01'),
    ('Apr 26', '2026-04-01', '2026-05-01'),
    ('May 26', '2026-05-01', '2026-06-01'),
]


# ─────────────────────────────────────────────────────────────────────
# DATA FETCH
# ─────────────────────────────────────────────────────────────────────

def fetch_futures_1m(symbol_key: str) -> pd.DataFrame:
    """Fetch 1-minute OHLCV from Databento for a futures symbol."""
    cfg = FUTURES_SYMBOLS[symbol_key]
    print(f'  Fetching {symbol_key} ({cfg["symbol"]}) from Databento...', end=' ', flush=True)
    try:
        client = db.Historical(DATABENTO_KEY)
        data = client.timeseries.get_range(
            dataset=cfg['dataset'],
            symbols=[cfg['symbol']],
            stype_in=cfg['stype'],
            schema='ohlcv-1m',
            start=START_DATE,
            end=END_DATE,
        )
        df = data.to_df()
        if df is None or len(df) == 0:
            print('NO DATA'); return pd.DataFrame()

        df = df.rename(columns={
            'open': 'open', 'high': 'high', 'low': 'low',
            'close': 'close', 'volume': 'volume'
        })
        # Databento returns prices in 1e-9 fixed-point for some schemas
        # Check if prices look like they need scaling
        if df['close'].median() > 1e6:
            for col in ('open', 'high', 'low', 'close'):
                df[col] = df[col] / 1e9

        df.index = pd.to_datetime(df.index, utc=True)
        df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
        df = df.sort_index()

        # Keep only RTH+ETH session bars (exclude dead overnight with 0 volume)
        df = df[df['volume'] > 0]

        print(f'{len(df):,} bars  ({df.index[0].date()} → {df.index[-1].date()})')
        return df

    except Exception as e:
        print(f'ERROR: {e}')
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────

def compute_atr_series(df: pd.DataFrame, period: int = ATR_LEN) -> np.ndarray:
    high = df['high'].values; low = df['low'].values; close = df['close'].values
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        tr = max(high[i] - low[i],
                 abs(high[i] - close[i-1]),
                 abs(low[i]  - close[i-1]))
        if i < period:
            atr[i] = tr
        else:
            atr[i] = atr[i-1] * (period - 1) / period + tr / period
    return atr


def compute_vol_sma(volumes: np.ndarray, period: int = VOL_LEN) -> np.ndarray:
    sma = np.zeros(len(volumes))
    for i in range(period, len(volumes)):
        sma[i] = volumes[i-period:i].mean()
    return sma


# ─────────────────────────────────────────────────────────────────────
# ROLLING CLUSTER BUILD (only bars 0..i — no lookahead)
# ─────────────────────────────────────────────────────────────────────

def build_clusters_up_to(i: int,
                         highs: np.ndarray, lows: np.ndarray,
                         volumes: np.ndarray, vol_sma: np.ndarray,
                         atr_val: float, vol_mult: float = 1.3):
    """Build SR clusters using only bars [VOL_LEN .. i]. No future data."""
    if atr_val == 0:
        return np.array([]), np.array([])

    merge_gap = atr_val * CLUSTER_MERGE
    clusters  = []

    for k in range(VOL_LEN, i + 1):
        if vol_sma[k] == 0:
            continue
        if volumes[k] <= vol_sma[k] * vol_mult:
            continue
        price = (highs[k] + lows[k]) / 2.0
        merged = False
        for c in clusters:
            if abs(price - c['price']) <= merge_gap:
                c['price'] = (c['price'] * c['vol'] + price * volumes[k]) / (c['vol'] + volumes[k])
                c['vol']   += volumes[k]
                c['n']     += 1
                merged = True; break
        if not merged:
            clusters.append({'price': price, 'vol': float(volumes[k]), 'n': 1})

    valid = [c for c in clusters if c['n'] >= SR_STRENGTH_MIN]
    if not valid:
        return np.array([]), np.array([])
    return (np.array([c['price'] for c in valid]),
            np.array([c['n']     for c in valid]))


def nearest_sr_dist(price: float, cluster_prices: np.ndarray, atr: float) -> float:
    if len(cluster_prices) == 0 or atr == 0:
        return float('inf')
    return float(np.min(np.abs(cluster_prices - price)) / atr)


# ─────────────────────────────────────────────────────────────────────
# ZIGZAG STATE MACHINES
# ─────────────────────────────────────────────────────────────────────

def build_zigzag_1m(highs, lows, opens, closes):
    n = len(highs)
    trend      = [''] * n
    zz_hi      = np.full(n, np.nan);  zz_hi_bar = np.full(n, -1, int)
    zz_lo      = np.full(n, np.nan);  zz_lo_bar = np.full(n, -1, int)
    t = ''; last_hi = highs[0]; last_lo = lows[0]
    hi_pt = highs[0]; hi_bar = 0
    lo_pt = lows[0];  lo_bar = 0
    cur_zz_hi = highs[0]; cur_zz_hi_bar = 0
    cur_zz_lo = lows[0];  cur_zz_lo_bar = 0
    for i in range(1, n):
        if highs[i] > hi_pt: hi_pt = highs[i]; hi_bar = i
        if lows[i]  < lo_pt: lo_pt = lows[i];  lo_bar = i
        if closes[i] > last_hi or opens[i] > last_hi:
            if t == 'down':
                cur_zz_lo = lo_pt; cur_zz_lo_bar = lo_bar
                hi_pt = highs[i]; hi_bar = i
            t = 'up'; last_hi = highs[i]; last_lo = lows[i]
        elif closes[i] < last_lo or opens[i] < last_lo:
            if t == 'up':
                cur_zz_hi = hi_pt; cur_zz_hi_bar = hi_bar
                lo_pt = lows[i]; lo_bar = i
            t = 'down'; last_hi = highs[i]; last_lo = lows[i]
        trend[i]      = t
        zz_hi[i]      = cur_zz_hi;     zz_hi_bar[i] = cur_zz_hi_bar
        zz_lo[i]      = cur_zz_lo;     zz_lo_bar[i] = cur_zz_lo_bar
    return trend, zz_hi, zz_hi_bar, zz_lo, zz_lo_bar


def build_zigzag_5m(highs, lows, opens, closes):
    n = len(highs)
    trend = [''] * n
    t = ''; last_hi = highs[0]; last_lo = lows[0]
    for i in range(1, n):
        if closes[i] > last_hi or opens[i] > last_hi:
            t = 'up'; last_hi = highs[i]; last_lo = lows[i]
        elif closes[i] < last_lo or opens[i] < last_lo:
            t = 'down'; last_hi = highs[i]; last_lo = lows[i]
        trend[i] = t
    return trend


def resample_5m(df1m: pd.DataFrame) -> pd.DataFrame:
    return df1m.resample('5min').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    ).dropna()


# ─────────────────────────────────────────────────────────────────────
# MAIN BACKTEST LOOP — CLEAN
# ─────────────────────────────────────────────────────────────────────

def run_boof24_clean(df1m: pd.DataFrame, symbol: str = 'ES') -> list:
    """
    Clean Boof 24 backtest — zero lookahead:
      - Fractal at bar c uses only bars [c-F .. c-1] left and [c+1 .. c+F] right,
        but we only KNOW bar c is a fractal at time c+F (all right bars observed).
        So signal fires at bar i = c+F, entry at bar i+1 = c+F+1.
      - Clusters built from bars [0 .. i] at each signal bar.
      - Time exit P&L uses actual close[exit_bar].
    """
    import bisect

    F    = FRACTAL_BARS
    df   = df1m.copy()
    df   = df.sort_index()

    if len(df) < VOL_LEN + ATR_LEN + F * 2 + 20:
        return []

    # ── 5m ZigZag (built once — only uses past bars at each 5m bar) ──
    df5        = resample_5m(df)
    df5_times  = df5.index.tolist()
    trend5     = build_zigzag_5m(
        df5['high'].values, df5['low'].values,
        df5['open'].values, df5['close'].values
    )
    times1m = df.index.tolist()

    df = df.reset_index(drop=True)

    # Pre-compute ATR and vol SMA arrays
    opens   = df['open'].values
    highs   = df['high'].values
    lows    = df['low'].values
    closes  = df['close'].values
    volumes = df['volume'].values.astype(float)

    atr_arr = compute_atr_series(df)
    vol_sma = compute_vol_sma(volumes)

    # 1m ZigZag (causal — only reads past bars, no bias)
    trend1m, zz_hi, zz_hi_bar, zz_lo, zz_lo_bar = build_zigzag_1m(
        highs, lows, opens, closes
    )

    warmup = VOL_LEN + ATR_LEN + F * 2 + 5

    trades    = []
    in_trade  = False
    trade_end = 0

    # Cluster cache: rebuild every N bars to avoid O(n²) per-bar cost
    # but still maintain rolling correctness (no future data)
    CLUSTER_REBUILD_FREQ = 20
    cached_clusters = (np.array([]), np.array([]))
    cluster_built_at = -1

    for i in range(warmup, len(df) - 1):
        if in_trade and i <= trade_end:
            continue

        # ── The fractal candidate bar is c = i - F ────────────────
        # At bar i, we've now seen F bars to the RIGHT of c, so fractal is confirmed.
        c = i - F
        if c < F + VOL_LEN:
            continue

        atr = atr_arr[c]
        if np.isnan(atr) or atr == 0:
            continue

        trend = trend1m[c]
        if trend == '':
            continue

        # Volume filter at fractal bar c
        if vol_sma[c] == 0:
            continue
        rvol = volumes[c] / vol_sma[c]
        if rvol < 0.8:
            continue

        # ── FRACTAL: only uses bars [c-F..c-1] left, [c+1..c+F] right ──
        # At time i, bars [c+1..c+F] = [c+1..i] are all known. No lookahead.
        lh = highs[c-F:c];       rh = highs[c+1:c+F+1]
        ll = lows[c-F:c];        rl = lows[c+1:c+F+1]
        if len(lh) < F or len(rh) < F or len(ll) < F or len(rl) < F:
            continue

        fractal_peak   = (highs[c] > lh.max()) and (highs[c] > rh.max())
        fractal_trough = (lows[c]  < ll.min()) and (lows[c]  < rl.min())

        if not fractal_peak and not fractal_trough:
            continue

        peak_slack   = (highs[c] - closes[c]) / atr
        trough_slack = (closes[c] - lows[c])  / atr

        direction = None; slack = 0.0

        if fractal_peak and peak_slack >= ATR_MULT and trend == 'up':
            zz_h_bar = int(zz_hi_bar[c])
            if zz_h_bar >= 0 and abs(c - zz_h_bar) <= ZZ_PROX_BARS:
                direction = 'short'; slack = peak_slack

        elif fractal_trough and trough_slack >= ATR_MULT and trend == 'down':
            zz_l_bar = int(zz_lo_bar[c])
            if zz_l_bar >= 0 and abs(c - zz_l_bar) <= ZZ_PROX_BARS:
                direction = 'long'; slack = trough_slack

        if direction is None:
            continue

        # ── Rolling cluster check (up to bar i, not full df) ──────
        if i - cluster_built_at >= CLUSTER_REBUILD_FREQ:
            cached_clusters = build_clusters_up_to(
                i, highs, lows, volumes, vol_sma, atr
            )
            cluster_built_at = i
        cluster_prices, _ = cached_clusters

        if nearest_sr_dist(closes[c], cluster_prices, atr) > SR_DIST_MAX:
            continue

        # ── 5m ZigZag gate ────────────────────────────────────────
        t1m  = times1m[c]
        idx5 = bisect.bisect_right(df5_times, t1m) - 1
        if idx5 < 1:
            continue
        trend_5m = trend5[idx5]
        if trend_5m == '':
            continue
        if direction == 'long'  and trend_5m != 'down': continue
        if direction == 'short' and trend_5m != 'up':   continue

        # ── Entry: next bar after i (= c + F + 1) ────────────────
        entry_bar = i + 1
        if entry_bar >= len(df) - 2:
            continue

        ep   = float(opens[entry_bar])
        tp_p = ep * (1 + TP_PCT) if direction == 'long' else ep * (1 - TP_PCT)
        sl_p = ep * (1 - SL_PCT) if direction == 'long' else ep * (1 + SL_PCT)

        et = 'time'
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

        # ── P&L: use actual exit price ────────────────────────────
        if et == 'tp':
            exit_price = tp_p          # touched TP level
        elif et == 'sl':
            exit_price = sl_p          # touched SL level
        else:
            exit_price = float(closes[exit_bar])   # actual close — no hardcoded pct

        if direction == 'long':
            pnl_pct = (exit_price - ep) / ep
        else:
            pnl_pct = (ep - exit_price) / ep

        trades.append({
            'symbol':     symbol,
            'direction':  direction,
            'entry':      ep,
            'exit_price': exit_price,
            'exit_type':  et,
            'pnl_pct':    pnl_pct,
            'slack':      slack,
            'tier':       'core' if slack >= 1.4 else 'expanded',
            'entry_bar':  entry_bar,
            'exit_bar':   exit_bar,
            'hold_bars':  exit_bar - entry_bar,
            'zz_1m':      trend,
            'zz_5m':      trend_5m,
            'fractal_bar': c,
            'signal_bar':  i,
        })

    return trades


# ─────────────────────────────────────────────────────────────────────
# STATS + REPORTING
# ─────────────────────────────────────────────────────────────────────

def dollar_pnl(trade: dict, sym_key: str) -> float:
    cfg = FUTURES_SYMBOLS[sym_key]
    contracts = cfg['core_sz'] if trade['tier'] == 'core' else cfg['exp_sz']
    return trade['pnl_pct'] * trade['entry'] * cfg['multiplier'] * contracts


def stats(pnls: list) -> tuple:
    if not pnls: return 0, 0.0, 0.0, 0.0, 0.0
    p   = np.array(pnls, dtype=float)
    pos = p[p > 0]; neg = p[p < 0]
    wr  = len(pos) / len(p) * 100
    pf  = float(pos.sum()) / max(float(abs(neg.sum())), 0.01)
    return len(p), round(wr, 1), round(float(p.mean()), 2), round(pf, 2), round(float(p.sum()), 0)


def print_results(all_trades: list, label: str, sym_key: str):
    SEP = '=' * 70

    # Attach dollar P&L
    for t in all_trades:
        t['pnl_dollar'] = dollar_pnl(t, sym_key)

    by_month = defaultdict(list)
    for t in all_trades:
        by_month[t['month']].append(t['pnl_dollar'])

    all_pnl = [t['pnl_dollar'] for t in all_trades]
    n, wr, ev, pf, tot = stats(all_pnl)

    trading_days = sum(
        len(pd.bdate_range(s, e)) for _, s, e in MONTHS
    )

    print(f'\n{SEP}')
    print(f'  BOOF 24.0 CLEAN — {sym_key}  |  {label}')
    print(f'  {START_DATE} → {END_DATE}  |  no lookahead, rolling clusters, actual exit price')
    print(f'{SEP}')
    print(f'  Total trades  : {n}')
    print(f'  Trades/day    : {n/max(trading_days,1):.1f}')
    print(f'  Win rate      : {wr:.1f}%')
    print(f'  EV / trade    : ${ev:,.2f}')
    print(f'  Profit factor : {pf:.2f}')
    print(f'  6-month P&L   : ${tot:,.0f}')
    print(f'  Annualized    : ${tot*2:,.0f}')
    print(f'\n  Monthly breakdown:')
    print(f'  {"Month":<10} {"Trades":>7} {"WR%":>7} {"EV":>9} {"PF":>6} {"P&L":>11}')
    print(f'  {"-"*55}')
    cum = 0.0
    for lbl, s, e in MONTHS:
        pnls = by_month[lbl]
        if not pnls: continue
        n2, wr2, ev2, pf2, tot2 = stats(pnls)
        cum += tot2
        print(f'  {lbl:<10} {n2:>7} {wr2:>6.1f}% ${ev2:>8.2f} {pf2:>6.2f} ${tot2:>10,.0f}  (cum ${cum:,.0f})')
    print(SEP)


# ─────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('BOOF 24.0 CLEAN BACKTEST — Databento CME Globex 1m')
    print('Symbols: ES (E-mini S&P 500), MNQ (Micro Nasdaq)')
    print('Period : Dec 2025 – May 2026\n')

    for sym_key in ('ES', 'MNQ'):
        print(f'\n{"─"*60}')
        print(f'  {sym_key}')
        print(f'{"─"*60}')

        df1m = fetch_futures_1m(sym_key)
        if df1m.empty:
            print(f'  Skipping {sym_key} — no data\n')
            continue

        all_trades = []
        for lbl, start_str, end_str in MONTHS:
            mask  = (df1m.index >= pd.Timestamp(start_str, tz='UTC')) & \
                    (df1m.index <  pd.Timestamp(end_str,   tz='UTC'))
            df_mo = df1m[mask]
            if len(df_mo) < 200:
                continue
            trades = run_boof24_clean(df_mo, sym_key)
            for t in trades:
                t['month'] = lbl
            print(f'    {lbl}: {len(trades)} trades')
            all_trades.extend(trades)

        if not all_trades:
            print(f'  No trades generated for {sym_key}')
            continue

        print_results(all_trades, 'RAW', sym_key)
