#!/usr/bin/env python3
"""
BOOF33 - Support Reclaim Expansion Long Strategy
Real 1-minute Alpaca cached data (~6 months)
"""

import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import warnings
warnings.filterwarnings('ignore')

# ── Credentials ───────────────────────────────────────────────
API_KEY    = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

# ── Universe ──────────────────────────────────────────────────
SYMBOLS = ['TSLA', 'NVDA', 'AMD', 'META', 'AMZN', 'NFLX',
           'PLTR', 'AVGO', 'SMCI', 'APP', 'COIN', 'MSTR',
           'SHOP', 'DDOG', 'CRWD', 'SNOW', 'NET', 'HOOD',
           'RDDT', 'UBER', 'AFRM', 'ARM']

# ── Parameters ────────────────────────────────────────────────
LOOKBACK         = 80
SUPPORT_TOL      = 0.002   # 0.20% zone
SWEEP_BUFFER     = 0.001   # 0.10% below support
MAX_CONFIRM_BARS = 10
COOLDOWN_BARS    = 30
MAX_HOLD_BARS    = 30
SLIPPAGE         = 0.0002

TP_LIST = [0.0025, 0.005, 0.0075, 0.010, 0.0125, 0.015]
SL_LIST = [0.0025, 0.004, 0.005]
MAX_HOLD_BARS_LONG = 60

SETUP_CACHE = 'boof33_setups.pkl'

# ── Data fetch (reuse boof32 cached CSVs where available) ─────
def fetch_data(symbol):
    cache_file = f'boof32_data_{symbol}.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=['datetime'])
        df['date'] = df['datetime'].dt.date
        return df
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end   = datetime.now()
    start = end - timedelta(days=182)
    req   = StockBarsRequest(symbol_or_symbols=symbol,
                             timeframe=TimeFrame.Minute,
                             start=start, end=end)
    bars = client.get_stock_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level='symbol')
    df = df.reset_index().rename(columns={'timestamp': 'datetime'})
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    df['date'] = df['datetime'].dt.date
    df.to_csv(cache_file, index=False)
    return df

# ── Indicators ────────────────────────────────────────────────
def add_indicators(day):
    day = day.copy()
    typical = (day['high'] + day['low'] + day['close']) / 3
    day['vwap']      = (typical * day['volume']).cumsum() / day['volume'].cumsum()
    day['vwap_slope']= day['vwap'].pct_change(5)
    day['ema20']     = day['close'].ewm(span=20, adjust=False).mean()
    day['ema50']     = day['close'].ewm(span=50, adjust=False).mean()
    day['avg_vol_20']= day['volume'].rolling(20).mean()
    return day

# ── Support detection ─────────────────────────────────────────
def find_support(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 30:
        return None, 0
    lows = window['low'].values
    best_level, best_touches = None, 0
    for low in lows:
        touches = np.sum(np.abs(lows - low) / low <= SUPPORT_TOL)
        if touches > best_touches:
            best_touches = touches
            best_level = low
    if best_touches < 2:
        return None, 0
    return best_level, best_touches

def prior_swing_high(day, i, lookback=20):
    if i < lookback:
        return None
    return day['high'].iloc[i - lookback:i].max()

def recent_higher_low(day, i, lookback=12):
    if i < lookback * 2:
        return False
    prev_low   = day['low'].iloc[i - lookback * 2:i - lookback].min()
    recent_low = day['low'].iloc[i - lookback:i].min()
    return recent_low > prev_low

# ── Signal detection ──────────────────────────────────────────
def detect_boof33_long(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}

    sweep_bar = day.iloc[i]
    if not (sweep_bar['low']   < support * (1 - SWEEP_BUFFER) and
            sweep_bar['close'] > support and
            sweep_bar['close'] > sweep_bar['vwap']):
        return False, {}

    swing_high = prior_swing_high(day, i)
    if swing_high is None:
        return False, {}

    for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(day) - 1)):
        bar = day.iloc[j]
        if not recent_higher_low(day, j):
            continue
        if bar['close'] > swing_high:
            return True, {
                'sweep_i':   i,
                'break_i':   j,
                'entry_i':   j + 1,
                'support':   support,
                'touches':   touches,
                'swing_high': swing_high,
            }
    return False, {}

# ── Variant A: support + sweep + reclaim + break structure (no higher-low)
def detect_variant_a(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    sweep_bar = day.iloc[i]
    if not (sweep_bar['low']   < support * (1 - SWEEP_BUFFER) and
            sweep_bar['close'] > support):
        return False, {}
    swing_high = prior_swing_high(day, i)
    if swing_high is None:
        return False, {}
    for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(day) - 1)):
        if day.iloc[j]['close'] > swing_high:
            return True, {'sweep_i': i, 'break_i': j, 'entry_i': j + 1,
                          'support': support, 'touches': touches, 'swing_high': swing_high}
    return False, {}

# ── Variant B: support + sweep + reclaim only
def detect_variant_b(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    sweep_bar = day.iloc[i]
    if not (sweep_bar['low']   < support * (1 - SWEEP_BUFFER) and
            sweep_bar['close'] > support):
        return False, {}
    entry_i = i + 1
    return True, {'sweep_i': i, 'break_i': i, 'entry_i': entry_i,
                  'support': support, 'touches': touches, 'swing_high': None}

# ── Variant C: support + reclaim only (no sweep required)
def detect_variant_c(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    sweep_bar = day.iloc[i]
    if not (sweep_bar['close'] > support):
        return False, {}
    entry_i = i + 1
    return True, {'sweep_i': i, 'break_i': i, 'entry_i': entry_i,
                  'support': support, 'touches': touches, 'swing_high': None}

# ── Scoring ───────────────────────────────────────────────────
def score_boof33(day, signal):
    score = 0
    sweep_i = signal['sweep_i']
    break_i = signal['break_i']
    sweep_bar = day.iloc[sweep_i]
    break_bar = day.iloc[break_i]
    avg_vol = day['avg_vol_20'].iloc[break_i]

    if pd.isna(avg_vol) or avg_vol <= 0:
        return 0

    touches = signal['touches']
    if touches >= 3: score += 1
    if touches >= 4: score += 1

    body = abs(sweep_bar['close'] - sweep_bar['open'])
    lower_wick = min(sweep_bar['open'], sweep_bar['close']) - sweep_bar['low']
    if body > 0 and lower_wick > body * 1.5: score += 1
    if sweep_bar['close'] > sweep_bar['open']:  score += 1
    if sweep_bar['close'] > sweep_bar['vwap']:  score += 1
    if break_bar['close'] > break_bar['open']:  score += 1
    if break_bar['volume'] > avg_vol:           score += 1
    if break_bar['volume'] > avg_vol * 1.2:     score += 1
    if break_bar['vwap_slope'] > 0:             score += 1
    if break_bar['ema20'] > break_bar['ema50']: score += 1

    return score

# ── Generic setup scanner ────────────────────────────────────
def scan_setups(symbol, df, detect_fn, label=''):
    setups = []
    dates = list(df.groupby('date'))
    for di, (date, day) in enumerate(dates):
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_trade_i = -999999
        for i in range(LOOKBACK + 50, len(day) - MAX_HOLD_BARS - MAX_CONFIRM_BARS - 2):
            if i - last_trade_i < COOLDOWN_BARS:
                continue
            found, signal = detect_fn(day, i)
            if not found:
                continue
            entry_i = signal['entry_i']
            if entry_i >= len(day):
                continue
            entry_price = day['open'].iloc[entry_i] * (1 + SLIPPAGE)
            end_i = min(entry_i + 1 + MAX_HOLD_BARS, len(day))
            future = day.iloc[entry_i + 1:end_i][['high','low','close']].copy().reset_index(drop=True)
            if future.empty:
                continue
            highs = future['high'].values
            mfe = (highs.max() - entry_price) / entry_price
            setups.append({
                'symbol':      symbol,
                'date':        date,
                'entry_time':  day['datetime'].iloc[entry_i],
                'entry_price': entry_price,
                'mfe':         mfe,
                'future_high': future['high'].values,
                'future_low':  future['low'].values,
                'future_close':future['close'].values,
                'variant':     label,
            })
            last_trade_i = i
    return setups

# ── Setup detection (cached, no TP/SL) ───────────────────────
def detect_setups(symbol, df):
    setups = []
    dates = list(df.groupby('date'))
    for di, (date, day) in enumerate(dates):
        print(f"  {symbol} {di+1}/{len(dates)}   ", end='\r', flush=True)
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_trade_i = -999999
        for i in range(LOOKBACK + 50, len(day) - MAX_HOLD_BARS - MAX_CONFIRM_BARS - 2):
            if i - last_trade_i < COOLDOWN_BARS:
                continue
            found, signal = detect_boof33_long(day, i)
            if not found:
                continue
            score = score_boof33(day, signal)
            entry_i = signal['entry_i']
            if entry_i >= len(day):
                continue
            entry_price = day['open'].iloc[entry_i] * (1 + SLIPPAGE)
            # Future slice starts AFTER entry bar, same-day only
            end_i = min(entry_i + 1 + MAX_HOLD_BARS, len(day))
            future = day.iloc[entry_i + 1:end_i][['high','low','close']].copy().reset_index(drop=True)
            if future.empty:
                continue
            highs = future['high'].values
            mfe = (highs.max() - entry_price) / entry_price
            bars_to_peak = int(np.argmax(highs))
            setups.append({
                'symbol':      symbol,
                'date':        date,
                'entry_time':  day['datetime'].iloc[entry_i],
                'score':       score,
                'support':     signal['support'],
                'touches':     signal['touches'],
                'entry_price': entry_price,
                'mfe':         mfe,
                'bars_to_peak': bars_to_peak,
                'future_high': future['high'].values,
                'future_low':  future['low'].values,
                'future_close':future['close'].values,
            })
            last_trade_i = i
    print()
    return setups

# ── Replay exits ──────────────────────────────────────────────
def replay_exits(setups, tp, sl):
    trades = []
    for s in setups:
        highs  = s['future_high']
        lows   = s['future_low']
        closes = s['future_close']
        ep     = s['entry_price']
        tp_price = ep * (1 + tp)
        sl_price = ep * (1 - sl)
        tp_hit = np.where(highs >= tp_price)[0]
        sl_hit = np.where(lows  <= sl_price)[0]
        first_tp = tp_hit[0] if len(tp_hit) else len(highs)
        first_sl = sl_hit[0] if len(sl_hit) else len(highs)
        if first_tp < len(highs) and first_tp <= first_sl:
            pnl, reason = tp - SLIPPAGE * 2, 'target'
        elif first_sl < len(highs):
            pnl, reason = -sl - SLIPPAGE * 2, 'stop'
        else:
            pnl, reason = (closes[-1] - ep) / ep - SLIPPAGE * 2, 'time'
        trades.append({**{k: v for k, v in s.items()
                          if k not in ('future_high','future_low','future_close')},
                       'pnl': pnl, 'exit_reason': reason, 'tp': tp, 'sl': sl})
    return trades

# ── Scale-out replay (50% at tp1, 50% at tp2, full stop at sl) ─
def replay_scaleout(setups, tp1, tp2, sl):
    trades = []
    for s in setups:
        highs  = s['future_high']
        lows   = s['future_low']
        closes = s['future_close']
        ep     = s['entry_price']
        tp1_price = ep * (1 + tp1)
        tp2_price = ep * (1 + tp2)
        sl_price  = ep * (1 - sl)
        sl_hit  = np.where(lows  <= sl_price)[0]
        tp1_hit = np.where(highs >= tp1_price)[0]
        tp2_hit = np.where(highs >= tp2_price)[0]
        first_sl  = sl_hit[0]  if len(sl_hit)  else len(highs)
        first_tp1 = tp1_hit[0] if len(tp1_hit) else len(highs)
        first_tp2 = tp2_hit[0] if len(tp2_hit) else len(highs)

        if first_sl < first_tp1:
            # stopped before tp1 — full loss
            pnl = -sl - SLIPPAGE * 2
            reason = 'stop'
        elif first_tp1 < len(highs):
            # tp1 hit — half out, move stop to breakeven for second half
            half1 = tp1 - SLIPPAGE * 2
            if first_tp2 < len(highs) and first_tp2 > first_tp1:
                # second half hits tp2
                half2 = tp2 - SLIPPAGE * 2
            else:
                # second half exits at time or BE
                if len(closes) > first_tp1:
                    exit_px = max(closes[-1], ep)  # BE floor
                    half2 = (exit_px - ep) / ep - SLIPPAGE * 2
                else:
                    half2 = 0.0
            pnl = 0.5 * half1 + 0.5 * half2
            reason = 'scale' if first_tp2 < len(highs) else 'scale_partial'
        else:
            pnl = (closes[-1] - ep) / ep - SLIPPAGE * 2
            reason = 'time'
        trades.append({**{k: v for k, v in s.items()
                          if k not in ('future_high','future_low','future_close')},
                       'pnl': pnl, 'exit_reason': reason})
    return trades

# ── Helpers ───────────────────────────────────────────────────
def pf(x):
    wins = x[x > 0].sum()
    loss = abs(x[x < 0].sum())
    return wins / loss if loss > 0 else float('inf')

def stats_row(trades, label=''):
    if not trades:
        print(f"  {label}: no trades")
        return
    x = pd.Series([t['pnl'] for t in trades])
    w = (x > 0).sum()
    tdays = len(set(t['date'] for t in trades))
    tpd = len(trades) / tdays if tdays else 0
    print(f"  {label:35s}  n:{len(trades):4d}  t/day:{tpd:.1f}"
          f"  WR:{w/len(x):.1%}  PF:{pf(x):.2f}  EV:{x.mean():.4%}")

# ── ET window filter (9:30-10:30) ─────────────────────────────
def et_morning(setups):
    out = []
    for s in setups:
        t = pd.Timestamp(s['entry_time'])
        h, m = t.hour, t.minute
        if (h == 15 and m >= 30) or (h == 16 and m <= 30):
            out.append(s)
    return out

# ── Main ──────────────────────────────────────────────────────
def main():
    print("BOOF33 - Support Reclaim Expansion Long")
    print(f"Symbols: {SYMBOLS}")
    print("=" * 60)

    # Load or build cache (append-only for new symbols)
    if os.path.exists(SETUP_CACHE):
        with open(SETUP_CACHE, 'rb') as f:
            all_setups = pickle.load(f)
        cached_syms = set(s['symbol'] for s in all_setups)
        print(f"Loaded {len(all_setups)} cached setups instantly")
    else:
        all_setups = []
        cached_syms = set()

    missing = [s for s in SYMBOLS if s not in cached_syms]
    if missing:
        print(f"Scanning {len(missing)} new symbols: {missing}")
        for symbol in missing:
            print(f"Scanning {symbol}...", end=' ', flush=True)
            try:
                df = fetch_data(symbol)
                print(f"{len(df):,} bars")
                setups = detect_setups(symbol, df)
                all_setups.extend(setups)
                print(f"  {symbol}: {len(setups)} setups")
            except Exception as e:
                print(f"ERROR: {e}")
        with open(SETUP_CACHE, 'wb') as f:
            pickle.dump(all_setups, f)
        print(f"Cached {len(all_setups)} total setups to {SETUP_CACHE}")

    FOCUS = ['AMD', 'CRWD', 'RDDT', 'META', 'HOOD']

    morning = et_morning([s for s in all_setups if s['symbol'] in FOCUS])
    print(f"\nFocus symbols: {FOCUS}")
    print(f"9:30-10:30 ET setups: {len(morning)}")

    if not morning:
        print("No morning setups found.")
        return

    # ── MFE Study ─────────────────────────────────────────────
    all_mfes = [s['mfe'] for s in morning]
    print(f"\n{'='*60}")
    print(f"  Raw Setup MFE  (no score filter)")
    print(f"{'='*60}")
    print(f"  Trades    : {len(morning)}")
    print(f"  Avg MFE   : {np.mean(all_mfes)*100:.3f}%")
    print(f"  Median MFE: {np.median(all_mfes)*100:.3f}%")

    print(f"\n  By Symbol:")
    for sym in FOCUS:
        sub = [s for s in morning if s['symbol'] == sym]
        if not sub:
            continue
        mfes = [s['mfe'] for s in sub]
        print(f"    {sym:6s}  n:{len(sub):3d}  Avg MFE:{np.mean(mfes)*100:.3f}%  Med MFE:{np.median(mfes)*100:.3f}%")

    # ════════════════════════════════════════════════════════════
    # TEST 1: All symbols, 9:30-10:00, close < VWAP
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("  TEST 1: All 22 symbols, 9:30-10:00, close<VWAP")
    print(f"{'='*60}")
    ALL_SYMS = SYMBOLS

    def in_window(s, h_start, m_start, h_end, m_end):
        t = pd.Timestamp(s['entry_time'])
        mins = (t.hour - 15) * 60 + t.minute
        return (h_start - 15) * 60 + m_start <= mins < (h_end - 15) * 60 + m_end

    T1_CACHE = 'boof33_t1.pkl'
    if os.path.exists(T1_CACHE):
        with open(T1_CACHE, 'rb') as f:
            t1_setups = pickle.load(f)
        cached_t1_syms = set(s['symbol'] for s in t1_setups)
        missing_t1 = [s for s in ALL_SYMS if s not in cached_t1_syms]
    else:
        t1_setups = []
        missing_t1 = ALL_SYMS

    if missing_t1:
        print(f"  Scanning {missing_t1}...")
        for sym in missing_t1:
            cached_df = f'boof32_data_{sym}.csv'
            if not os.path.exists(cached_df):
                continue
            df = pd.read_csv(cached_df, parse_dates=['datetime'])
            df['date'] = df['datetime'].dt.date
            for date, day in df.groupby('date'):
                day = day.copy().reset_index(drop=True)
                if len(day) < 150:
                    continue
                day = add_indicators(day)
                last_trade_i = -999999
                for i in range(LOOKBACK + 50, len(day) - MAX_HOLD_BARS - MAX_CONFIRM_BARS - 2):
                    if i - last_trade_i < COOLDOWN_BARS:
                        continue
                    support, _ = find_support(day, i)
                    if support is None:
                        continue
                    bar = day.iloc[i]
                    if not (bar['low'] < support * (1 - SWEEP_BUFFER) and
                            bar['close'] > support and
                            bar['close'] < bar['vwap']):
                        continue
                    entry_i = i + 1
                    if entry_i >= len(day):
                        continue
                    entry_price = day['open'].iloc[entry_i] * (1 + SLIPPAGE)
                    end_i = min(entry_i + 1 + MAX_HOLD_BARS, len(day))
                    future = day.iloc[entry_i + 1:end_i][['high','low','close']].copy().reset_index(drop=True)
                    if future.empty:
                        continue
                    highs = future['high'].values
                    mfe = (highs.max() - entry_price) / entry_price
                    t1_setups.append({
                        'symbol': sym, 'date': date,
                        'entry_time': day['datetime'].iloc[entry_i],
                        'entry_price': entry_price, 'mfe': mfe,
                        'future_high': future['high'].values,
                        'future_low':  future['low'].values,
                        'future_close':future['close'].values,
                    })
                    last_trade_i = i
        with open(T1_CACHE, 'wb') as f:
            pickle.dump(t1_setups, f)

    t1 = [s for s in t1_setups if in_window(s, 15, 30, 16, 0)]

    def mfe_row(label, setups):
        if not setups:
            print(f"  {label:30s}  n:   0")
            return
        mfes = [s['mfe'] for s in setups]
        print(f"  {label:30s}  n:{len(setups):4d}"
              f"  Avg:{np.mean(mfes)*100:.3f}%  Med:{np.median(mfes)*100:.3f}%")

    sym_rows = []
    for sym in ALL_SYMS:
        sub = [s for s in t1 if s['symbol'] == sym]
        if not sub:
            continue
        mfes = [s['mfe'] for s in sub]
        sym_rows.append((sym, len(sub), np.mean(mfes)*100, np.median(mfes)*100))
    sym_rows.sort(key=lambda x: -x[2])
    for sym, n, avg, med in sym_rows:
        print(f"  {sym:6s}  n:{n:4d}  Avg:{avg:.3f}%  Med:{med:.3f}%")

    # ════════════════════════════════════════════════════════════
    # TEST 2: Expanded universe vs RDDT/HOOD/AMD
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("  TEST 2: Expanded universe (9:30-10:00, close<VWAP)")
    print(f"{'='*60}")
    EXPAND = ['RDDT', 'HOOD', 'AMD', 'SHOP', 'AFRM', 'NET', 'DDOG', 'ARM']
    for sym in EXPAND:
        sub = [s for s in t1 if s['symbol'] == sym]
        if not sub:
            print(f"  {sym:6s}  n:   0")
            continue
        mfes = [s['mfe'] for s in sub]
        print(f"  {sym:6s}  n:{len(sub):4d}  Avg:{np.mean(mfes)*100:.3f}%  Med:{np.median(mfes)*100:.3f}%")

    # ════════════════════════════════════════════════════════════
    # TEST 3: MFE at 5 / 10 / 15 / 30 bars
    # ════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("  TEST 3: When does the move happen? (MFE by bar count)")
    print(f"{'='*60}")
    print(f"  Using all 22 symbols, 9:30-10:00, close<VWAP  n={len(t1)}")
    for bars in [5, 10, 15, 30]:
        mfes = []
        for s in t1:
            highs = s['future_high'][:bars]
            if len(highs) == 0:
                continue
            ep = s['entry_price']
            mfe = (highs.max() - ep) / ep * 100
            mfes.append(mfe)
        if mfes:
            print(f"  {bars:2d} bars (~{bars} min):  Avg:{np.mean(mfes):.3f}%  Med:{np.median(mfes):.3f}%"
                  f"  p75:{np.percentile(mfes,75):.3f}%")

    # ════════════════════════════════════════════════════════════
    # FOCUSED TEST: APP+MSTR+AFRM+RDDT+HOOD+NET
    # 9:30-10:00, close<VWAP, 60-bar future slice
    # ════════════════════════════════════════════════════════════
    BEST6 = ['APP', 'MSTR', 'AFRM', 'RDDT', 'HOOD', 'NET']
    FOCUSED_CACHE = 'boof33_focused.pkl'

    if os.path.exists(FOCUSED_CACHE):
        with open(FOCUSED_CACHE, 'rb') as f:
            focused_setups = pickle.load(f)
        cached_f = set(s['symbol'] for s in focused_setups)
        missing_f = [s for s in BEST6 if s not in cached_f]
    else:
        focused_setups = []
        missing_f = BEST6

    if missing_f:
        print(f"  Building focused cache for {missing_f}...")
        for sym in missing_f:
            cached_df = f'boof32_data_{sym}.csv'
            if not os.path.exists(cached_df):
                continue
            df = pd.read_csv(cached_df, parse_dates=['datetime'])
            df['date'] = df['datetime'].dt.date
            for date, day in df.groupby('date'):
                day = day.copy().reset_index(drop=True)
                if len(day) < 150:
                    continue
                day = add_indicators(day)
                last_trade_i = -999999
                for i in range(LOOKBACK + 50, len(day) - MAX_HOLD_BARS_LONG - MAX_CONFIRM_BARS - 2):
                    if i - last_trade_i < COOLDOWN_BARS:
                        continue
                    support, _ = find_support(day, i)
                    if support is None:
                        continue
                    bar = day.iloc[i]
                    if not (bar['low'] < support * (1 - SWEEP_BUFFER) and
                            bar['close'] > support and
                            bar['close'] < bar['vwap']):
                        continue
                    entry_i = i + 1
                    if entry_i >= len(day):
                        continue
                    entry_price = day['open'].iloc[entry_i] * (1 + SLIPPAGE)
                    end_i = min(entry_i + 1 + MAX_HOLD_BARS_LONG, len(day))
                    future = day.iloc[entry_i + 1:end_i][['high','low','close']].copy().reset_index(drop=True)
                    if future.empty:
                        continue
                    highs = future['high'].values
                    mfe = (highs.max() - entry_price) / entry_price
                    focused_setups.append({
                        'symbol':       sym,
                        'date':         date,
                        'entry_time':   day['datetime'].iloc[entry_i],
                        'entry_price':  entry_price,
                        'mfe':          mfe,
                        'future_high':  future['high'].values,
                        'future_low':   future['low'].values,
                        'future_close': future['close'].values,
                    })
                    last_trade_i = i
        with open(FOCUSED_CACHE, 'wb') as f:
            pickle.dump(focused_setups, f)
        print(f"  Cached {len(focused_setups)} focused setups")

    def in_window(s, h_start, m_start, h_end, m_end):
        t = pd.Timestamp(s['entry_time'])
        mins = (t.hour - 15) * 60 + t.minute
        return (h_start - 15) * 60 + m_start <= mins < (h_end - 15) * 60 + m_end

    focused = [s for s in focused_setups if in_window(s, 15, 30, 16, 0)]

    def mfe_row2(label, setups):
        if not setups:
            print(f"  {label:45s}  n:   0")
            return
        mfes = [s['mfe'] for s in setups]
        print(f"  {label:45s}  n:{len(setups):4d}"
              f"  Avg:{np.mean(mfes)*100:.3f}%  Med:{np.median(mfes)*100:.3f}%")

    # ── Exit Study ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Exit Study  (APP+MSTR+AFRM+RDDT+HOOD+NET, 9:30-10:00, <VWAP)")
    print(f"{'='*60}")
    for tp, sl in [(0.010, 0.004), (0.0125, 0.004), (0.015, 0.005)]:
        trades = replay_exits(focused, tp, sl)
        x = pd.Series([t['pnl'] for t in trades])
        w = (x > 0).sum()
        pf_val = pf(x)
        print(f"  TP:{tp:.2%} SL:{sl:.2%}  n:{len(trades):4d}"
              f"  WR:{w/len(x):.1%}  PF:{pf_val:.2f}  EV:{x.mean():.4%}")

    # ── Scale-out: 50% at +0.50%, 50% at +1.50%, stop -0.30% ──
    so_trades = replay_scaleout(focused, 0.005, 0.015, 0.003)
    so_x = pd.Series([t['pnl'] for t in so_trades])
    so_w = (so_x > 0).sum()
    so_reasons = pd.Series([t['exit_reason'] for t in so_trades]).value_counts().to_dict()
    print(f"  Scale-out 50%@0.50% / 50%@1.50% / SL:0.30%"
          f"  n:{len(so_trades):4d}  WR:{so_w/len(so_x):.1%}"
          f"  PF:{pf(so_x):.2f}  EV:{so_x.mean():.4%}")
    print(f"    Exits: {so_reasons}")

    # ── Hold Time Study ───────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Hold Time Study  (APP+MSTR+AFRM+RDDT+HOOD+NET)")
    print(f"{'='*60}")
    print(f"  n={len(focused)} trades")
    for bars, label in [(15,'15 min'), (30,'30 min'), (45,'45 min'), (60,'60 min')]:
        mfes = []
        for s in focused:
            h = s['future_high'][:bars]
            if len(h) == 0:
                continue
            mfes.append((h.max() - s['entry_price']) / s['entry_price'] * 100)
        if mfes:
            print(f"  {label}  Avg:{np.mean(mfes):.3f}%  Med:{np.median(mfes):.3f}%"
                  f"  p75:{np.percentile(mfes,75):.3f}%")


if __name__ == "__main__":
    main()
