"""
Run the ORIGINAL Boof 22 & 23 from backtest_6mo_boof_22_23.py
against cached pkl data (resampled to 1-min equivalent = 5-min bars as-is)
"""

import pickle, os, sys
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple

# ── inject original functions directly ───────────────────────────────────────
sys.path.insert(0, r'c:\Users\tybre\Desktop\aivibe')

# Copy all config/functions verbatim from backtest_6mo_boof_22_23.py
# Exact live deployed config from aws-bot-runner/src/signals/boof22.ts & boof23.ts
TP_PCT = 0.0005   # used only for B22 (options TP %)
SL_PCT = 0.0003   # used only for B22 (options SL %)

BOOF22_CFG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'VOL_MULT': 1.3, 'FRACTAL_BARS': 3,
    'ATR_MULT': 0.6, 'CLUSTER_MERGE': 0.5, 'SR_STRENGTH_MIN': 2,
    'SR_DIST_MAX': 1.0, 'RVOL_MIN': 0.8, 'SLACK_MAX': 0.8,
    'MAX_LOOKBACK': 10,
}
BOOF23_CFG = {
    'ATR_LEN': 14, 'VOL_LEN': 50, 'FRACTAL_BARS': 3, 'ATR_MULT': 0.4,
    'CLUSTER_MERGE': 0.5, 'SR_STRENGTH_MIN': 2, 'SR_DIST_MAX': 1.0,
    'RVOL_MIN': 0.8, 'ZZ_PROX_BARS': 30, 'USE_ENGULF': False,
    'ATR_TP_MULT': 4.0, 'ATR_SL_MULT': 2.0,
    'MAX_LOOKBACK': 10,
}
SYMBOL_PARAMS = {
    'NVDA':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'META':  {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AAPL':  {'atr_mult': 0.6, 'vol_mult': 1.2, 'sr_dist': 1.0},
    'GOOGL': {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
    'AMD':   {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0},
}

# Exact BOOFINGTON list from live code
SYMBOLS    = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
START      = pd.Timestamp("2025-06-01", tz="America/New_York")
END        = pd.Timestamp("2026-06-09", tz="America/New_York")
CACHE_DIR  = "boof_cache"
ET         = "America/New_York"


# ── helpers (verbatim from original) ─────────────────────────────────────────
def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_vol_sma(df, period=50):
    return df['volume'].rolling(period).mean()

def compute_session_rvol(df, vol_len=50):
    return df['volume'] / compute_vol_sma(df, vol_len)

def build_cluster_array(df, atr_series, vol_mult, cfg):
    vol_sma = compute_vol_sma(df, cfg['VOL_LEN'])
    hi_vol = df['volume'] > vol_sma * vol_mult
    avg_atr = atr_series.median()
    if avg_atr == 0 or pd.isna(avg_atr):
        return [], []
    merge_tol = avg_atr * cfg['CLUSTER_MERGE']
    buckets = []
    for i in range(len(df)):
        if not hi_vol.iloc[i]: continue
        price = (df['high'].iloc[i] + df['low'].iloc[i]) / 2
        merged = False
        for b in buckets:
            if abs(b[0] - price) <= merge_tol:
                b[0] = (b[0]*b[1] + price) / (b[1]+1); b[1] += 1; merged = True; break
        if not merged:
            buckets.append([price, 1])
    buckets = [b for b in buckets if b[1] >= cfg['SR_STRENGTH_MIN']]
    buckets.sort(key=lambda x: -x[1])
    return [b[0] for b in buckets], [b[1] for b in buckets]

def build_zigzag(df):
    n = len(df)
    highs, lows, opens, closes = df['high'].values, df['low'].values, df['open'].values, df['close'].values
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


# ── Boof 22 (verbatim) ────────────────────────────────────────────────────────
def backtest_boof22(df, symbol):
    params = SYMBOL_PARAMS.get(symbol, {'atr_mult': 0.6, 'vol_mult': 1.3, 'sr_dist': 1.0})
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']
    cfg = BOOF22_CFG
    df = df.copy().reset_index(drop=True)
    if len(df) < max(cfg['VOL_LEN'], cfg['ATR_LEN']) + cfg['FRACTAL_BARS']*2 + 10:
        return []
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    cluster_prices, _ = build_cluster_array(df, atr_series, vol_mult, cfg)
    F = cfg['FRACTAL_BARS']
    trades = []; in_trade = False
    entry_price = direction = None; entry_bar = 0; entry_slack = 0.0
    tp_price = sl_price = 0.0
    for i in range(cfg['VOL_LEN'] + cfg['ATR_LEN'] + F, len(df) - F - 1):
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
        if row['volume'] < row['vol_sma'] * vol_mult: continue
        highs = df['high'].values; lows = df['low'].values; closes = df['close'].values
        # No look-ahead: confirm fractal at pivot = i-F (all F right bars are now known)
        p = i - F  # pivot bar fully confirmed at bar i
        if p < F: continue
        fractal_peak   = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
        fractal_trough = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
        atr_p = df.iloc[p]['atr']
        if pd.isna(atr_p) or atr_p == 0: continue
        atr_rejected_peak   = closes[p] < highs[p] - atr_p * atr_mult
        atr_bounced_trough  = closes[p] > lows[p]  + atr_p * atr_mult
        if not cluster_prices: continue
        price = closes[i]  # current price for SR distance check
        dists = [abs(price - cp) / atr for cp in cluster_prices]
        nearest_dist = min(dists)
        if nearest_dist > cfg['SR_DIST_MAX']: continue
        if fractal_peak and atr_rejected_peak:
            peak_slack = (highs[p] - closes[p]) / atr_p
            entry_price = df.iloc[i+1]['open']
            direction = 'short'; tp_price = entry_price*(1-TP_PCT); sl_price = entry_price*(1+SL_PCT)
            entry_bar = i+1; entry_slack = peak_slack; in_trade = True
        elif fractal_trough and atr_bounced_trough:
            trough_slack = (closes[p] - lows[p]) / atr_p
            entry_price = df.iloc[i+1]['open']
            direction = 'long'; tp_price = entry_price*(1+TP_PCT); sl_price = entry_price*(1-SL_PCT)
            entry_bar = i+1; entry_slack = trough_slack; in_trade = True
    return trades


# ── Boof 23 (verbatim) ────────────────────────────────────────────────────────
def backtest_boof23(df, symbol):
    cfg = BOOF23_CFG
    df = df.copy().reset_index(drop=True)
    if len(df) < max(cfg['VOL_LEN'], cfg['ATR_LEN']) + cfg['FRACTAL_BARS']*2 + 10:
        return []
    atr_series = compute_atr(df, cfg['ATR_LEN'])
    df['atr'] = atr_series
    df['vol_sma'] = compute_vol_sma(df, cfg['VOL_LEN'])
    df['rvol'] = compute_session_rvol(df, cfg['VOL_LEN'])
    trend, zz_high, zz_high_bar, zz_low, zz_low_bar = build_zigzag(df)
    F = cfg['FRACTAL_BARS']
    highs = df['high'].values; lows = df['low'].values
    opens = df['open'].values; closes = df['close'].values
    trades = []; in_trade = False
    entry_price = direction = None; entry_bar = 0; entry_slack = 0.0
    tp_price = sl_price = 0.0
    for i in range(cfg['VOL_LEN'] + cfg['ATR_LEN'] + F, len(df) - F - 1):
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
        # No look-ahead: pivot confirmed F bars ago
        p = i - F
        if p < F: continue
        atr_p = df.iloc[p]['atr']
        if pd.isna(atr_p) or atr_p == 0: continue
        fractal_peak   = (highs[p] > highs[p-F:p].max()) and (highs[p] > highs[p+1:p+F+1].max())
        fractal_trough = (lows[p]  < lows[p-F:p].min())  and (lows[p]  < lows[p+1:p+F+1].min())
        atr_rejected_peak  = closes[p] < highs[p] - atr_p * cfg['ATR_MULT']
        atr_bounced_trough = closes[p] > lows[p]  + atr_p * cfg['ATR_MULT']
        t = trend[p]
        if fractal_peak and atr_rejected_peak and t == 'up':
            peak_slack = (highs[p] - closes[p]) / atr_p
            zz_h_bar = int(zz_high_bar[p])
            if zz_h_bar >= 0 and abs(p - zz_h_bar) <= cfg['ZZ_PROX_BARS']:
                engulf_ok = not cfg['USE_ENGULF'] or closes[p] < opens[p]
                if engulf_ok:
                    entry_price = df.iloc[i+1]['open']
                    direction = 'short'; tp_price = entry_price*(1-TP_PCT); sl_price = entry_price*(1+SL_PCT)
                    entry_bar = i+1; entry_slack = peak_slack; in_trade = True
        elif fractal_trough and atr_bounced_trough and t == 'down':
            trough_slack = (closes[p] - lows[p]) / atr_p
            zz_l_bar = int(zz_low_bar[p])
            if zz_l_bar >= 0 and abs(p - zz_l_bar) <= cfg['ZZ_PROX_BARS']:
                engulf_ok = not cfg['USE_ENGULF'] or closes[p] > opens[p]
                if engulf_ok:
                    entry_price = df.iloc[i+1]['open']
                    direction = 'long'; tp_price = entry_price*(1+TP_PCT); sl_price = entry_price*(1-SL_PCT)
                    entry_bar = i+1; entry_slack = trough_slack; in_trade = True
    return trades


# ── data loader ───────────────────────────────────────────────────────────────
def load_symbol(sym):
    names = [sym, 'GOOGL'] if sym in ('GOOG', 'GOOGL') else [sym]
    for name in names:
        for key in ["2025-01-01_2026-12-31", "2024-01-01_2026-12-31"]:
            path = os.path.join(CACHE_DIR, f"{name}_{key}.pkl")
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
    if not trades:
        print(f"{title}: No trades"); return
    df = pd.DataFrame(trades)
    pnls = df['pnl_pct']
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 else float('inf')
    cum = pnls.cumsum(); mdd = (cum - cum.cummax()).min()
    print(f"\n{'='*70}")
    print(f"  {title}  |  TP: +{TP_PCT*100:.3f}%  SL: -{SL_PCT*100:.3f}%")
    print(f"{'='*70}")
    print(f"  Trades:        {len(df)}")
    print(f"  Win Rate:      {(pnls>0).mean()*100:.1f}%")
    print(f"  Avg Trade:     {pnls.mean()*100:+.4f}%")
    print(f"  Avg Winner:    {wins.mean()*100:+.4f}%" if not wins.empty else "  Avg Winner:    --")
    print(f"  Avg Loser:     {losses.mean()*100:+.4f}%" if not losses.empty else "  Avg Loser:     --")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Total Return:  {pnls.sum()*100:+.2f}%")
    print(f"  Max Drawdown:  {mdd*100:+.2f}%")
    by_dir = df.groupby('direction')['pnl_pct'].agg(n='count', wr=lambda x:(x>0).mean()*100, avg=lambda x:x.mean()*100)
    print(f"\n  BY DIRECTION:\n{by_dir.round(2)}")
    by_exit = df.groupby('exit_type')['pnl_pct'].agg(n='count', wr=lambda x:(x>0).mean()*100, avg=lambda x:x.mean()*100)
    print(f"\n  BY EXIT:\n{by_exit.round(3)}")
    by_tier = df.groupby('tier')['pnl_pct'].agg(n='count', wr=lambda x:(x>0).mean()*100, avg=lambda x:x.mean()*100)
    print(f"\n  BY TIER:\n{by_tier.round(2)}")


# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Period: {START.date()} → {END.date()}")
    print(f"Symbols: {SYMBOLS}\n")

    all22, all23 = [], []

    for sym in SYMBOLS:
        df = load_symbol(sym)
        if df is None:
            print(f"  {sym}: NO DATA — skip"); continue
        print(f"  {sym}: {len(df)} bars", end="  ")
        t22 = backtest_boof22(df, sym)
        t23 = backtest_boof23(df, sym)
        print(f"B22:{len(t22)}  B23:{len(t23)}")
        all22 += t22; all23 += t23

    report(all22, f"BOOF 22 — Fractal + SR Cluster  [{START.date()} → {END.date()}]")
    report(all23, f"BOOF 23 — Fractal + ZigZag      [{START.date()} → {END.date()}]")
