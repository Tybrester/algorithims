"""
Exact live deployed Boof 22 & 23 backtest
Config from aws-bot-runner/src/signals/boof22.ts & boof23.ts
- BOOFINGTON: AAPL, NVDA, META, GOOGL, AMD
- SLACK_MAX: 0.8 filter
- Offset-based fractal scan (no look-ahead)
- Fixed % TP/SL (0.05% / 0.03%) for both — tests both ATR and fixed
"""

import pickle, os
import pandas as pd
import numpy as np
from collections import defaultdict

# ── CONFIG (exact from live TS files) ────────────────────────────────────────
BOOF22_CFG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'VOL_MULT': 1.3, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6, 'CLUSTER_MERGE': 0.5, 'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0, 'RVOL_MIN': 0.8, 'SLACK_MAX': 0.8, 'MAX_LOOKBACK': 10,
}
BOOF23_CFG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'FRACTAL_BARS': 3, 'ATR_MULT': 0.4,
    'CLUSTER_MERGE': 0.5, 'SR_STRENGTH_MIN': 2, 'SR_DIST_MAX': 1.0,
    'RVOL_MIN': 0.8, 'ZZ_PROX_BARS': 30, 'USE_ENGULF': False,
    'ATR_TP_MULT': 4.0, 'ATR_SL_MULT': 2.0, 'MAX_LOOKBACK': 10,
}
SYMBOL_PARAMS = {
    'NVDA':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'META':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AAPL':  {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0},
    'GOOGL': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AMD':   {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
}
SYMBOLS   = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
START     = pd.Timestamp("2025-06-01", tz="America/New_York")
END       = pd.Timestamp("2026-06-09", tz="America/New_York")
CACHE_DIR = "boof_cache"
ET        = "America/New_York"
TP_PCT    = 0.0005   # +0.05%
SL_PCT    = 0.0003   # -0.03%


# ── helpers ───────────────────────────────────────────────────────────────────
def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([(high-low), (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def compute_session_rvol(df, vol_len=50):
    return df['volume'] / compute_vol_sma(df, vol_len)

def build_cluster_array(df, atr_series, vol_mult, cfg):
    vol_sma = compute_vol_sma(df, cfg['VOL_LEN'])
    avg_atr = float(atr_series[atr_series > 0].median())
    if avg_atr == 0 or np.isnan(avg_atr): return [], []
    merge_tol = avg_atr * cfg['CLUSTER_MERGE']
    buckets = []
    for i in range(len(df)):
        if df['volume'].iloc[i] <= vol_sma.iloc[i] * vol_mult: continue
        price = (df['high'].iloc[i] + df['low'].iloc[i]) / 2
        merged = False
        for b in buckets:
            if abs(b[0] - price) <= merge_tol:
                b[0] = (b[0]*b[1] + price) / (b[1]+1); b[1] += 1; merged = True; break
        if not merged: buckets.append([price, 1])
    buckets = [b for b in buckets if b[1] >= cfg['SR_STRENGTH_MIN']]
    buckets.sort(key=lambda x: -x[1])
    return [b[0] for b in buckets], [b[1] for b in buckets]

def build_zigzag(df):
    n = len(df)
    highs, lows = df['high'].values, df['low'].values
    opens, closes = df['open'].values, df['close'].values
    trend = [''] * n
    zz_high = [None]*n; zz_high_bar = [-1]*n
    zz_low  = [None]*n; zz_low_bar  = [-1]*n
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


# ── Boof 22 ───────────────────────────────────────────────────────────────────
def backtest_boof22(df, symbol, use_atr_exits=False):
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0})
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']
    cfg = BOOF22_CFG
    df = df.copy().reset_index(drop=True)
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult, cfg)
    F = cfg['FRACTAL_BARS']
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    trades = []; in_trade = False
    entry_price = direction = None; entry_slack = 0.0
    tp_price = sl_price = 0.0

    for i in range(cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5, len(df) - 2):
        row = df.iloc[i]
        if in_trade:
            nxt = df.iloc[i+1]
            exit_price = exit_type = None
            if direction == 'long':
                if nxt['high'] >= tp_price: exit_price, exit_type = tp_price, 'tp'
                elif nxt['low'] <= sl_price: exit_price, exit_type = sl_price, 'sl'
            else:
                if nxt['low'] <= tp_price: exit_price, exit_type = tp_price, 'tp'
                elif nxt['high'] >= sl_price: exit_price, exit_type = sl_price, 'sl'
            if exit_price is not None:
                pnl = (exit_price - entry_price) / entry_price
                if direction == 'short': pnl = -pnl
                trades.append({'symbol': symbol, 'direction': direction, 'entry': entry_price,
                                'exit': exit_price, 'exit_type': exit_type, 'pnl_pct': pnl,
                                'tier': 'core' if entry_slack >= 1.4 else 'expanded', 'strategy': 'boof22'})
                in_trade = False
            continue

        if row['rvol'] < cfg['RVOL_MIN']: continue
        atr = row['atr']
        if pd.isna(atr) or atr == 0: continue
        if not cluster_prices: continue

        # Scan confirmed fractals (offset loop — matches live TS code)
        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            atr_p = df.iloc[p]['atr']
            if pd.isna(atr_p) or atr_p == 0: continue
            vol_p = df.iloc[p]['volume']; vol_sma_p = df.iloc[p]['vol_sma']
            if vol_p < vol_sma_p * vol_mult: continue

            if p - F < 0 or p + F + 1 > len(highs): continue
            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
            atr_rej   = closes[p] < highs[p] - atr_p * atr_mult
            atr_bnc   = closes[p] > lows[p]  + atr_p * atr_mult

            price = closes[i]
            dists = [abs(price - cp) / atr for cp in cluster_prices]
            if min(dists) > cfg['SR_DIST_MAX']: continue

            if fp and atr_rej:
                slack = (highs[p] - closes[p]) / atr_p
                if slack >= cfg['SLACK_MAX']: continue
                ep = df.iloc[i+1]['open']
                tp_price = ep * (1 - TP_PCT); sl_price = ep * (1 + SL_PCT)
                entry_price = ep; direction = 'short'; entry_slack = slack; in_trade = True
                break
            elif ft and atr_bnc:
                slack = (closes[p] - lows[p]) / atr_p
                if slack >= cfg['SLACK_MAX']: continue
                ep = df.iloc[i+1]['open']
                tp_price = ep * (1 + TP_PCT); sl_price = ep * (1 - SL_PCT)
                entry_price = ep; direction = 'long'; entry_slack = slack; in_trade = True
                break

    return trades


# ── Boof 23 ───────────────────────────────────────────────────────────────────
def backtest_boof23(df, symbol, use_atr_exits=True):
    cfg = BOOF23_CFG
    df = df.copy().reset_index(drop=True)
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    trend, zz_high, zz_high_bar, zz_low, zz_low_bar = build_zigzag(df)
    F = cfg['FRACTAL_BARS']
    highs = df['high'].values; lows = df['low'].values
    opens = df['open'].values; closes = df['close'].values
    trades = []; in_trade = False
    entry_price = direction = None; entry_slack = 0.0
    tp_price = sl_price = 0.0

    for i in range(cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5, len(df) - 2):
        row = df.iloc[i]
        if in_trade:
            nxt = df.iloc[i+1]
            exit_price = exit_type = None
            if direction == 'long':
                if nxt['high'] >= tp_price: exit_price, exit_type = tp_price, 'tp'
                elif nxt['low'] <= sl_price: exit_price, exit_type = sl_price, 'sl'
            else:
                if nxt['low'] <= tp_price: exit_price, exit_type = tp_price, 'tp'
                elif nxt['high'] >= sl_price: exit_price, exit_type = sl_price, 'sl'
            if exit_price is not None:
                pnl = (exit_price - entry_price) / entry_price
                if direction == 'short': pnl = -pnl
                trades.append({'symbol': symbol, 'direction': direction, 'entry': entry_price,
                                'exit': exit_price, 'exit_type': exit_type, 'pnl_pct': pnl,
                                'tier': 'core' if entry_slack >= 1.4 else 'expanded', 'strategy': 'boof23'})
                in_trade = False
            continue

        if row['rvol'] < cfg['RVOL_MIN']: continue
        atr = row['atr']
        if pd.isna(atr) or atr == 0: continue

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            atr_p = df.iloc[p]['atr']
            if pd.isna(atr_p) or atr_p == 0: continue

            if p - F < 0 or p + F + 1 > len(highs): continue
            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
            atr_rej = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
            t = trend[p]

            if fp and atr_rej and t == 'up':
                slack = (highs[p] - closes[p]) / atr_p
                zz_h = int(zz_high_bar[p])
                if zz_h < 0 or abs(p - zz_h) > cfg['ZZ_PROX_BARS']: continue
                engulf_ok = not cfg['USE_ENGULF'] or closes[p] < opens[p]
                if not engulf_ok: continue
                ep = df.iloc[i+1]['open']
                if use_atr_exits:
                    tp_price = ep - atr_p * cfg['ATR_TP_MULT']
                    sl_price = ep + atr_p * cfg['ATR_SL_MULT']
                else:
                    tp_price = ep * (1 - TP_PCT); sl_price = ep * (1 + SL_PCT)
                entry_price = ep; direction = 'short'; entry_slack = slack; in_trade = True
                break
            elif ft and atr_bnc and t == 'down':
                slack = (closes[p] - lows[p]) / atr_p
                zz_l = int(zz_low_bar[p])
                if zz_l < 0 or abs(p - zz_l) > cfg['ZZ_PROX_BARS']: continue
                engulf_ok = not cfg['USE_ENGULF'] or closes[p] > opens[p]
                if not engulf_ok: continue
                ep = df.iloc[i+1]['open']
                if use_atr_exits:
                    tp_price = ep + atr_p * cfg['ATR_TP_MULT']
                    sl_price = ep - atr_p * cfg['ATR_SL_MULT']
                else:
                    tp_price = ep * (1 + TP_PCT); sl_price = ep * (1 - SL_PCT)
                entry_price = ep; direction = 'long'; entry_slack = slack; in_trade = True
                break

    return trades


# ── data loader ───────────────────────────────────────────────────────────────
def load_symbol(sym):
    for key in ["2025-01-01_2026-12-31", "2024-01-01_2026-12-31"]:
        path = os.path.join(CACHE_DIR, f"{sym}_{key}.pkl")
        if os.path.exists(path):
            df = pickle.load(open(path, "rb"))
            if not isinstance(df, pd.DataFrame): continue
            df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
            df.columns = [c.lower() for c in df.columns]
            df = df[~df.index.duplicated(keep='first')].sort_index()
            df = df[(df.index >= START) & (df.index <= END)]
            if len(df) < 300: continue
            df = df.reset_index(drop=False).rename(columns={'index': 'time'})
            return df
    return None


# ── report ────────────────────────────────────────────────────────────────────
def report(trades, title):
    if not trades: print(f"{title}: No trades"); return
    df = pd.DataFrame(trades)
    pnls = df['pnl_pct']
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf')
    cum = pnls.cumsum(); mdd = (cum - cum.cummax()).min()
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    print(f"  Trades:        {len(df)}")
    print(f"  Win Rate:      {(pnls>0).mean()*100:.1f}%")
    print(f"  Avg Trade:     {pnls.mean()*100:+.4f}%")
    print(f"  Avg Winner:    {wins.mean()*100:+.4f}%" if not wins.empty else "  Avg Winner:    --")
    print(f"  Avg Loser:     {losses.mean()*100:+.4f}%" if not losses.empty else "  Avg Loser:     --")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Total Return:  {pnls.sum()*100:+.2f}%")
    print(f"  Max Drawdown:  {mdd*100:+.2f}%")
    by_dir  = df.groupby('direction')['pnl_pct'].agg(n='count', wr=lambda x:(x>0).mean()*100, avg=lambda x:x.mean()*100)
    by_exit = df.groupby('exit_type')['pnl_pct'].agg(n='count', wr=lambda x:(x>0).mean()*100, avg=lambda x:x.mean()*100)
    by_tier = df.groupby('tier')['pnl_pct'].agg(n='count', wr=lambda x:(x>0).mean()*100, avg=lambda x:x.mean()*100)
    print(f"\n  BY DIRECTION:\n{by_dir.round(2)}")
    print(f"\n  BY EXIT:\n{by_exit.round(3)}")
    print(f"\n  BY TIER:\n{by_tier.round(2)}")


# ── main ──────────────────────────────────────────────────────────────────────
def simulate_exit(df, entry_idx, direction, tp_price, sl_price, max_bars=None):
    """Scan forward until TP or SL is hit. If max_bars=None, run until end of data."""
    limit = len(df) - 1 if max_bars is None else min(entry_idx + max_bars, len(df) - 1)
    for j in range(entry_idx, limit):
        bar = df.iloc[j]
        if direction == 'long':
            if bar['high'] >= tp_price: return tp_price, 'tp', j
            if bar['low']  <= sl_price: return sl_price, 'sl', j
        else:
            if bar['low']  <= tp_price: return tp_price, 'tp', j
            if bar['high'] >= sl_price: return sl_price, 'sl', j
    # Never hit — close at last bar
    exit_p = df.iloc[limit]['close']
    return exit_p, 'time', limit


def backtest_nolimit(df, symbol, algo='22'):
    """Run with no time exit — hold until TP or SL is actually hit."""
    cfg = BOOF22_CFG if algo == '22' else BOOF23_CFG
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0})
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']
    df = df.copy().reset_index(drop=True)
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult, cfg)
    F = cfg['FRACTAL_BARS']
    highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
    trend, zz_high, zz_high_bar, zz_low, zz_low_bar = build_zigzag(df) if algo == '23' else (['']*len(df), None, [-1]*len(df), None, [-1]*len(df))
    opens = df['open'].values

    trades = []
    i = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F * 2 + cfg['MAX_LOOKBACK'] + 5

    while i < len(df) - 2:
        row = df.iloc[i]
        if row['rvol'] < cfg['RVOL_MIN']: i += 1; continue
        atr = row['atr']
        if pd.isna(atr) or atr == 0: i += 1; continue

        direction = None; entry_slack = 0.0

        for offset in range(F + 2, F + 2 + cfg['MAX_LOOKBACK'] + 1):
            p = i - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i: continue
            if p - F < 0 or p + F + 1 > len(highs): continue
            atr_p = df.iloc[p]['atr']
            if pd.isna(atr_p) or atr_p == 0: continue

            fp = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
            ft = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())

            if algo == '22':
                vol_p = df.iloc[p]['volume']; vol_sma_p = df.iloc[p]['vol_sma']
                if vol_p < vol_sma_p * vol_mult: continue
                if not cluster_prices: break
                dists = [abs(closes[i] - cp) / atr for cp in cluster_prices]
                if min(dists) > cfg['SR_DIST_MAX']: continue
                atr_rej = closes[p] < highs[p] - atr_p * atr_mult
                atr_bnc = closes[p] > lows[p]  + atr_p * atr_mult
                if fp and atr_rej:
                    slack = (highs[p] - closes[p]) / atr_p
                    if slack >= cfg['SLACK_MAX']: continue
                    direction = 'short'; entry_slack = slack; break
                elif ft and atr_bnc:
                    slack = (closes[p] - lows[p]) / atr_p
                    if slack >= cfg['SLACK_MAX']: continue
                    direction = 'long'; entry_slack = slack; break
            else:
                atr_rej = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
                atr_bnc = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
                t = trend[p]
                if fp and atr_rej and t == 'up':
                    zz_h = int(zz_high_bar[p])
                    if zz_h < 0 or abs(p - zz_h) > cfg['ZZ_PROX_BARS']: continue
                    direction = 'short'; entry_slack = (highs[p] - closes[p]) / atr_p; break
                elif ft and atr_bnc and t == 'down':
                    zz_l = int(zz_low_bar[p])
                    if zz_l < 0 or abs(p - zz_l) > cfg['ZZ_PROX_BARS']: continue
                    direction = 'long'; entry_slack = (closes[p] - lows[p]) / atr_p; break

        if direction is None: i += 1; continue

        ep = df.iloc[i+1]['open']
        tp_price = ep * (1 + TP_PCT) if direction == 'long' else ep * (1 - TP_PCT)
        sl_price = ep * (1 - SL_PCT) if direction == 'long' else ep * (1 + SL_PCT)

        exit_p, exit_type, exit_i = simulate_exit(df, i + 1, direction, tp_price, sl_price)
        pnl = (exit_p - ep) / ep if direction == 'long' else (ep - exit_p) / ep
        trades.append({'symbol': symbol, 'direction': direction, 'entry': ep,
                        'exit': exit_p, 'exit_type': exit_type, 'pnl_pct': pnl,
                        'tier': 'core' if entry_slack >= 1.4 else 'expanded',
                        'strategy': f'boof{algo}_nolimit'})
        i = exit_i + 1  # skip to after trade

    return trades


if __name__ == "__main__":
    print(f"BOOFINGTON: {SYMBOLS}")
    print(f"Period: {START.date()} to {END.date()}\n")

    data = {}
    for sym in SYMBOLS:
        df = load_symbol(sym)
        if df is None: print(f"  {sym}: NO DATA"); continue
        data[sym] = df
        print(f"  {sym}: {len(df)} bars loaded")

    print()

    # B22 — fixed % exits, SLACK_MAX filter, offset fractal
    all22 = []
    for sym, df in data.items():
        t = backtest_boof22(df, sym)
        print(f"  {sym} B22: {len(t)} trades")
        all22 += t

    # B23 — fixed % exits
    all23_fixed = []
    for sym, df in data.items():
        t = backtest_boof23(df, sym, use_atr_exits=False)
        print(f"  {sym} B23 (fixed): {len(t)} trades")
        all23_fixed += t

    # B23 — ATR exits (live config)
    all23_atr = []
    for sym, df in data.items():
        t = backtest_boof23(df, sym, use_atr_exits=True)
        print(f"  {sym} B23 (ATR):   {len(t)} trades")
        all23_atr += t

    # No-limit exits — hold until TP/SL actually hit
    all22_nl, all23_nl = [], []
    for sym, df in data.items():
        t22 = backtest_nolimit(df, sym, algo='22')
        t23 = backtest_nolimit(df, sym, algo='23')
        print(f"  {sym} B22 no-limit: {len(t22)}  B23 no-limit: {len(t23)}")
        all22_nl += t22; all23_nl += t23

    report(all22,       f"BOOF 22 — fixed exits + SLACK<0.8 (overlapping)  [{START.date()} to {END.date()}]")
    report(all23_fixed, f"BOOF 23 — fixed exits (overlapping)              [{START.date()} to {END.date()}]")
    report(all23_atr,   f"BOOF 23 — ATR exits 4x/2x (overlapping)         [{START.date()} to {END.date()}]")
    report(all22_nl,    f"BOOF 22 — no-limit hold until TP/SL              [{START.date()} to {END.date()}]")
    report(all23_nl,    f"BOOF 23 — no-limit hold until TP/SL              [{START.date()} to {END.date()}]")
