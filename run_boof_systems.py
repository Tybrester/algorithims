"""
Boof 22 / 22.5 / 23 / 23.5 — EXACT original boof_backtest_final.py logic
Dec 2025 – May 2026, 9 symbols (Boof No-ETF list)
Data from pkl cache, tail(10000) bars to match original Alpaca API limit
"""

import pickle, os
import numpy as np
import pandas as pd
from collections import defaultdict

# ── CONFIG (identical to original) ───────────────────────────────────────────
SYMBOLS   = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY']
START     = pd.Timestamp("2025-01-01", tz="America/New_York")
END       = pd.Timestamp("2026-06-09", tz="America/New_York")
CACHE_DIR = "boof_cache"
ET        = "America/New_York"
CFG       = {'ATR_LEN': 14, 'VOL_LEN': 50, 'MAX_HOLD': 20, 'TP_R': 2.0, 'SL_R': 1.0}

def load_symbol(sym):
    # Try GOOGL for GOOG
    names = [sym, 'GOOGL'] if sym == 'GOOG' else [sym]
    for name in names:
        for key in ["2025-01-01_2026-12-31", "2024-01-01_2026-12-31"]:
            path = os.path.join(CACHE_DIR, f"{name}_{key}.pkl")
            if os.path.exists(path):
                df = pickle.load(open(path, "rb"))
                if not isinstance(df, pd.DataFrame): continue
                df.index = pd.to_datetime(df.index, utc=True)
                df.index = df.index.tz_convert(ET)
                df.columns = [c.lower() for c in df.columns]
                df = df[~df.index.duplicated(keep='first')]
                df = df.sort_index()
                df = df[(df.index >= START) & (df.index <= END)]
                df = df.reset_index(drop=True)
                return df
    return None







# ── CORE HELPERS (original logic) ────────────────────────────────────────────
def compute_atr(df):
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        h = df['high'].iloc[i]; l = df['low'].iloc[i]; c = df['close'].iloc[i-1]
        tr = max(h-l, abs(h-c), abs(l-c))
        atr[i] = tr if i < 14 else atr[i-1]*13/14 + tr/14
    return atr

def simulate_trade(df, entry_idx, direction, entry, sl, tp, max_bars=20):
    for j in range(entry_idx+1, min(entry_idx+max_bars, len(df))):
        if direction == 'LONG':
            if df['low'].iloc[j] <= sl:  return (sl-entry)/entry*100, 'SL', j
            if df['high'].iloc[j] >= tp: return (tp-entry)/entry*100, 'TP', j
        else:
            if df['high'].iloc[j] >= sl: return (entry-sl)/entry*100, 'SL', j
            if df['low'].iloc[j] <= tp:  return (entry-tp)/entry*100, 'TP', j
    j = min(entry_idx+max_bars-1, len(df)-1)
    ep = df['close'].iloc[j]
    pnl = (ep-entry)/entry*100 if direction=='LONG' else (entry-ep)/entry*100
    return pnl, 'TIME', j


# ── BOOF 22: Volume Clusters (O(log n) per bar) ───────────────────────────────
import bisect

def _merge_cluster(clusters_prices, clusters_data, price, atr_half):
    """Insert/merge a new high-vol bar price into sorted cluster list. O(log n)."""
    pos = bisect.bisect_left(clusters_prices, price)
    # Check neighbours for merge
    for idx in (pos-1, pos):
        if 0 <= idx < len(clusters_prices):
            if abs(clusters_prices[idx] - price) <= atr_half:
                d = clusters_data[idx]
                new_price = (d['price'] * d['strength'] + price) / (d['strength'] + 1)
                d['strength'] += 1
                d['price'] = new_price
                # Re-sort after price update
                clusters_prices[idx] = new_price
                return
    # No merge — insert new cluster
    bisect.insort(clusters_prices, price)
    insert_pos = bisect.bisect_left(clusters_prices, price)
    clusters_data.insert(insert_pos, {'price': price, 'strength': 1})

def run_boof22(df, sym):
    trades = []
    atr      = compute_atr(df)
    vol_arr  = df['volume'].values
    close_arr= df['close'].values
    high_arr = df['high'].values
    low_arr  = df['low'].values
    vol_sma  = df['volume'].rolling(window=CFG['VOL_LEN']).mean().values

    # Rolling window: keep clusters for last WINDOW bars only
    WINDOW = 500   # ~500 5-min bars ≈ 2 trading weeks of lookback
    clusters_prices = []   # sorted list of cluster prices
    clusters_data   = []   # parallel list of {'price', 'strength'}
    bar_added       = []   # bar index when each cluster was added (for expiry)

    start = CFG['VOL_LEN'] + 50

    # Pre-populate clusters up to start bar
    avg_atr0 = float(np.mean(atr[1:start+1][atr[1:start+1] > 0])) if np.any(atr[1:start+1] > 0) else 1.0
    for j in range(CFG['VOL_LEN'], start):
        if not np.isnan(vol_sma[j]) and vol_arr[j] >= vol_sma[j] * 1.3:
            price = (high_arr[j] + low_arr[j]) / 2
            _merge_cluster(clusters_prices, clusters_data, price, avg_atr0 * 0.5)
            bar_added.append(j)

    i = start
    n = len(df) - 20
    while i < n:
        if atr[i] == 0:
            i += 1; continue

        current_atr = atr[i]
        atr_half    = current_atr * 0.5

        # Expire clusters older than WINDOW bars
        while bar_added and bar_added[0] < i - WINDOW:
            bar_added.pop(0)
            if clusters_data:
                clusters_prices.pop(0)
                clusters_data.pop(0)

        # Add current bar if high-volume
        if not np.isnan(vol_sma[i]) and vol_arr[i] >= vol_sma[i] * 1.3:
            price = (high_arr[i] + low_arr[i]) / 2
            _merge_cluster(clusters_prices, clusters_data, price, atr_half)
            bar_added.append(i)

        # Filter to strong clusters only
        strong = [d for d in clusters_data if d['strength'] >= 2]
        if not strong:
            i += 1; continue

        close = close_arr[i]
        dist  = min(abs(close - c['price']) / current_atr for c in strong)
        if dist > 1.0:
            i += 1; continue

        nearest   = min(strong, key=lambda c: abs(close - c['price']))
        direction = 'LONG' if close < nearest['price'] else 'SHORT'
        entry     = close
        sl, tp    = (entry - current_atr, entry + current_atr * 2) if direction == 'LONG' \
                    else (entry + current_atr, entry - current_atr * 2)
        pnl, exit_type, exit_i = simulate_trade(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'exit': exit_type, 'dir': direction, 'entry': entry})
        i = exit_i + 1  # skip forward past this trade
    return trades


# ── BOOF 23: ZigZag ───────────────────────────────────────────────────────────
def run_boof23(df, sym):
    trades = []
    atr = compute_atr(df)
    close_col = df['close'].values
    high_col  = df['high'].values
    low_col   = df['low'].values
    zz_high, zz_low, trend = high_col[0], low_col[0], ''
    i = 50
    n = len(df) - 20
    while i < n:
        if atr[i] == 0: i += 1; continue
        close, high, low, current_atr = close_col[i], high_col[i], low_col[i], atr[i]
        if high > zz_high: zz_high = high
        if low  < zz_low:  zz_low  = low
        threshold = current_atr * 0.75
        if   trend=='up'   and close < zz_low  - threshold: trend='down'; zz_low=low
        elif trend=='down' and close > zz_high + threshold: trend='up';   zz_high=high
        elif trend=='':    trend = 'up' if close > close_col[i-20] else 'down'
        if trend == '': i += 1; continue
        ret5 = (close - close_col[max(0,i-5)]) / close_col[max(0,i-5)] * 100
        if abs(ret5) < 0.05: i += 1; continue
        if not ((ret5>0 and trend=='up') or (ret5<0 and trend=='down')): i += 1; continue
        direction = 'LONG' if ret5 > 0 else 'SHORT'
        entry = close
        sl, tp = (entry-current_atr, entry+current_atr*2) if direction=='LONG' else (entry+current_atr, entry-current_atr*2)
        pnl, exit_type, exit_i = simulate_trade(df, i, direction, entry, sl, tp)
        trades.append({'sym': sym, 'pnl': pnl, 'exit': exit_type, 'dir': direction, 'entry': entry})
        i = exit_i + 1  # skip past this trade
    return trades


# ── BOOF 22.5: Boof 22 + ADX>20 ──────────────────────────────────────────────
def run_boof22_5(df, sym):
    atr = compute_atr(df)
    adx = np.zeros(len(df))
    for i in range(14, len(df)):
        plus_dm  = max(df['high'].iloc[i] - df['high'].iloc[i-1], 0)
        minus_dm = max(df['low'].iloc[i-1] - df['low'].iloc[i], 0)
        if minus_dm > plus_dm:  plus_dm  = 0
        if plus_dm  > minus_dm: minus_dm = 0
        adx[i] = abs(plus_dm - minus_dm) / (atr[i] + 0.0001) * 100
    raw = run_boof22(df, sym)
    filtered = []
    for t in raw:
        matches = (df['close'] == t['entry'])
        idx = matches[matches].index
        adx_val = adx[idx[0]] if len(idx) > 0 and idx[0] < len(adx) else 0
        if adx_val > 20:
            filtered.append(t)
    return filtered


# ── BOOF 23.5: Boof 23 + RSI(2) ──────────────────────────────────────────────
def run_boof23_5(df, sym):
    delta = df['close'].diff()
    gain  = delta.where(delta > 0, 0).rolling(2).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(2).mean()
    rsi2  = 100 - (100 / (1 + gain / loss.replace(0, 0.001)))
    raw = run_boof23(df, sym)
    filtered = []
    for t in raw:
        matches = (df['close'] == t['entry'])
        idx = matches[matches].index
        r = rsi2.iloc[idx[0]] if len(idx) > 0 and idx[0] < len(rsi2) else 50
        if t['dir'] == 'LONG'  and r > 80: continue
        if t['dir'] == 'SHORT' and r < 20: continue
        filtered.append(t)
    return filtered


# ── METRICS ───────────────────────────────────────────────────────────────────
def metrics(trades, name):
    if not trades:
        print(f"\n{name}: NO TRADES")
        return

    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]
    loss = pnls[pnls <= 0]

    total     = pnls.sum()
    n         = len(pnls)
    wr        = (pnls > 0).mean() * 100
    ev        = pnls.mean()
    gw        = wins.sum() if len(wins) else 0
    gl        = abs(loss.sum()) if len(loss) else 1e-9
    pf        = gw / gl if gl > 0 else float("inf")
    sharpe    = (pnls.mean() / pnls.std() * np.sqrt(252)) if pnls.std() > 0 else 0

    # Drawdown on cumulative
    cum  = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd   = (cum - peak)
    mdd  = dd.min()

    # Find peak P&L point
    peak_idx  = np.argmax(cum)
    peak_pnl  = cum[peak_idx]

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Trades        : {n}")
    print(f"  Win Rate      : {wr:.1f}%")
    print(f"  EV / Trade    : {ev:+.3f}%")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  Sharpe Ratio  : {sharpe:.2f}  (annualised)")
    print(f"  Total P&L     : {total:+.2f}%")
    print(f"  Peak P&L      : {peak_pnl:+.2f}%  (trade #{peak_idx+1} of {n})")
    print(f"  Max Drawdown  : {mdd:+.2f}%")
    print(f"  Avg Winner    : {wins.mean():+.3f}%  ({len(wins)} trades)")
    print(f"  Avg Loser     : {loss.mean():+.3f}%  ({len(loss)} trades)")


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print('='*70)
    print('BOOF 22, 22.5, 23, 23.5 - NO ETF LIST - Dec2025-May2026')
    print(f'Symbols: {SYMBOLS}')
    print(f'Dates: {START.date()} to {END.date()}')
    print('='*70)

    # Load all data
    data = {}
    for sym in SYMBOLS:
        df = load_symbol(sym)
        if df is not None and len(df) >= 200:
            data[sym] = df
            print(f'  [{sym}] {len(df)} bars loaded')
        else:
            print(f'  [{sym}] NO DATA — skip')

    print(f'\nRunning backtests on {len(data)} symbols...\n')

    results = {}

    # Boof 22
    print('Running Boof 22...')
    trades = []
    for sym, df in data.items():
        t = run_boof22(df, sym)
        trades.extend(t)
        print(f'  {sym}: {len(t)} trades')
    results['Boof 22'] = trades

    # Boof 23
    print('Running Boof 23...')
    trades = []
    for sym, df in data.items():
        t = run_boof23(df, sym)
        trades.extend(t)
        print(f'  {sym}: {len(t)} trades')
    results['Boof 23'] = trades

    # Boof 22.5 = 22 + ADX filter
    print('Running Boof 22.5 (22 + ADX filter)...')
    trades = []
    for sym, df in data.items():
        t = run_boof22_5(df, sym)
        trades.extend(t)
        print(f'  {sym}: {len(t)} trades (ADX filtered)')
    results['Boof 22.5'] = trades

    # Boof 23.5 = 23 + RSI2 filter
    print('Running Boof 23.5 (23 + RSI2 filter)...')
    trades = []
    for sym, df in data.items():
        t = run_boof23_5(df, sym)
        trades.extend(t)
        print(f'  {sym}: {len(t)} trades (RSI2 filtered)')
    results['Boof 23.5'] = trades

    # ── Rolling 2-month window scan ──────────────────────────────────────────
    print('\n' + '='*70)
    print('ROLLING 2-MONTH WINDOW — Boof 22 & 23 Win Rate Over Time')
    print('='*70)
    print(f'{"Window":<25} {"B22 WR":>8} {"B22 N":>7} {"B23 WR":>8} {"B23 N":>7}')
    print('-'*60)

    window_months = 2
    cur = START
    while cur < END:
        w_start = cur
        w_end   = cur + pd.DateOffset(months=window_months)
        if w_end > END: w_end = END

        b22_all, b23_all = [], []
        for sym, df_full in data.items():
            # Slice window
            mask = (df_full.index >= 0)  # numeric index — slice by position
            # Re-filter by timestamp: reload with timestamp index
            pass

        # Use timestamp-aware approach: reload slice per window
        b22_all, b23_all = [], []
        for sym in data.keys():
            names = [sym, 'GOOGL'] if sym == 'GOOG' else [sym]
            for name in names:
                for key in ["2025-01-01_2026-12-31", "2024-01-01_2026-12-31"]:
                    path = os.path.join(CACHE_DIR, f"{name}_{key}.pkl")
                    if os.path.exists(path):
                        df = pickle.load(open(path, "rb"))
                        if not isinstance(df, pd.DataFrame): continue
                        df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
                        df.columns = [c.lower() for c in df.columns]
                        df = df[~df.index.duplicated(keep='first')].sort_index()
                        df = df[(df.index >= w_start) & (df.index < w_end)]
                        if len(df) < 200: break
                        df = df.reset_index(drop=True)
                        b22_all += run_boof22(df, sym)
                        b23_all += run_boof23(df, sym)
                        break
                else:
                    continue
                break

        label = f"{w_start.strftime('%Y-%m-%d')} → {w_end.strftime('%Y-%m-%d')}"
        def wr_str(trades):
            if not trades: return '  --  ', '    0'
            p = np.array([t['pnl'] for t in trades])
            return f"{(p>0).mean()*100:>6.1f}%", f"{len(p):>6}"
        w22, n22 = wr_str(b22_all)
        w23, n23 = wr_str(b23_all)
        print(f"{label:<25}  {w22}  {n22}  {w23}  {n23}")
        cur += pd.DateOffset(months=1)  # slide by 1 month

    print('='*70)
    print('COMPLETE!')
