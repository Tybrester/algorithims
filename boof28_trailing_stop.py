"""
BOOF 28 - Trailing Stop Test
Compare: Fixed exit (10:15) vs Trailing Stop (1% activation, 0.5% trail)
Uses 1-minute bars between 9:35 and 10:15 to simulate intrabar trailing stop
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","LRCX","KLAC",
    "MRVL","INTC","ON","NXPI","TXN","ARM","HOOD","COIN","SQ","SOFI","CAVA",
    "CAT","ETN","DE","GE","URI","ISRG","MRNA","VRTX","REGN","LLY",
    "META","MSFT","GOOGL","AAPL","TSLA","UBER","RCL","CCL","ABNB"
]

TRAIL_ACTIVATION = 0.010   # 1.00% - trailing stop activates
TRAIL_DISTANCE   = 0.005   # 0.50% - trail from peak

def load_cached(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    daily = d.groupby('date')['close'].last()
    ema = daily.ewm(span=50, adjust=False).mean().shift(1)
    return ema

def get_ema(s, date):
    ts = pd.Timestamp(date)
    v = s.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in s.index if pd.Timestamp(d).date() < date]
        v = s[prior[-1]] if prior else None
    return v

def simulate_trailing_stop(day_df, entry_price, direction, activate_pct, trail_pct):
    """
    Simulate 1-minute bar by bar from 9:35 to 10:15.
    Returns (exit_price, exit_reason) where exit_reason is 'trail' or 'time'
    """
    bars = day_df.between_time('09:35', '10:15')
    if len(bars) == 0:
        return entry_price, 'time'

    peak = entry_price
    trail_active = False

    for _, bar in bars.iterrows():
        # Use high/low to simulate worst/best case within bar
        if direction == 'LONG':
            current_high = bar['high']
            current_low  = bar['low']

            # Update peak
            if current_high > peak:
                peak = current_high

            # Check if trail activates
            if not trail_active and (peak - entry_price) / entry_price >= activate_pct:
                trail_active = True

            # Check trail stop hit
            if trail_active:
                stop = peak * (1 - trail_pct)
                if current_low <= stop:
                    return stop, 'trail'

        else:  # SHORT
            current_low  = bar['low']
            current_high = bar['high']

            # For short, peak = lowest price reached (most favorable)
            if current_low < peak:
                peak = current_low

            if not trail_active and (entry_price - peak) / entry_price >= activate_pct:
                trail_active = True

            if trail_active:
                stop = peak * (1 + trail_pct)
                if current_high >= stop:
                    return stop, 'trail'

    # No stop hit — exit at close of 10:15 bar
    last_bar = bars.iloc[-1]
    return last_bar['close'], 'time'

def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []

    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue
        q5   = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']

        # QQQ open for regime check
        qopen_bar = qday.between_time('09:30','09:30')
        if len(qopen_bar) == 0: continue
        qqq_open_price = qopen_bar.iloc[0]['open']

        e50 = get_ema(ema50, d)
        if e50 is None: continue

        bull = qqq_open_price > e50 and q5 >= 0.001
        bear = qqq_open_price < e50 and q5 <= -0.001

        if not bull and not bear: continue

        for sym in SYMBOLS:
            if sym not in all_data: continue
            df  = all_data[sym].copy()
            df  = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day) == 0: continue

            so = day.between_time('09:30','09:34')
            if len(so) == 0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']

            en = day.between_time('09:35','09:35')
            if len(en) == 0: continue
            entry_price = en.iloc[0]['open']

            direction = None
            if bull and 0.006 <= s5 <= 0.007:
                direction = 'LONG'
            elif bear and -0.015 <= s5 <= -0.008:
                direction = 'SHORT'

            if direction is None: continue

            # ── Fixed exit ────────────────────────────────────────
            ex = day.between_time('10:15','10:15')
            if len(ex) == 0: continue
            fixed_exit = ex.iloc[0]['open']
            if direction == 'LONG':
                fixed_pnl = (fixed_exit - entry_price) / entry_price * 100
            else:
                fixed_pnl = (entry_price - fixed_exit) / entry_price * 100

            # ── Trailing stop exit ────────────────────────────────
            trail_exit, reason = simulate_trailing_stop(
                day, entry_price, direction,
                TRAIL_ACTIVATION, TRAIL_DISTANCE
            )
            if direction == 'LONG':
                trail_pnl = (trail_exit - entry_price) / entry_price * 100
            else:
                trail_pnl = (entry_price - trail_exit) / entry_price * 100

            trades.append({
                'date':      d,
                'symbol':    sym,
                'direction': direction,
                'fixed_pnl': fixed_pnl,
                'trail_pnl': trail_pnl,
                'exit_reason': reason,
            })

    return trades

def report_comparison(trades, label):
    if not trades:
        print(f"\n{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    n  = len(df)

    def stats(col):
        s = df[col]
        wins = s[s > 0]; loss = s[s <= 0]
        wr  = len(wins) / n * 100
        avg = s.mean(); tot = s.sum()
        gp  = wins.sum(); gl = abs(loss.sum())
        pf  = gp / gl if gl > 0 else 0
        s2  = s.cumsum()
        dd  = (s2.expanding().max() - s2).max()
        return wr, avg, tot, pf, dd

    f_wr, f_avg, f_tot, f_pf, f_dd = stats('fixed_pnl')
    t_wr, t_avg, t_tot, t_pf, t_dd = stats('trail_pnl')

    trail_hits = len(df[df['exit_reason'] == 'trail'])

    print(f"\n{'='*75}")
    print(f" {label}")
    print(f"{'='*75}")
    print(f"  {'':22} {'Trades':>7}  {'WR%':>6}  {'Avg':>9}  {'Total':>9}  {'PF':>5}  {'MaxDD':>8}")
    print(f"  {'-'*70}")
    print(f"  {'Fixed (10:15)':22} {n:>7}  {f_wr:>5.1f}%  {f_avg:>+8.3f}%  {f_tot:>+8.2f}%  {f_pf:>5.2f}  -{f_dd:>6.2f}%")
    print(f"  {'Trailing Stop':22} {n:>7}  {t_wr:>5.1f}%  {t_avg:>+8.3f}%  {t_tot:>+8.2f}%  {t_pf:>5.2f}  -{t_dd:>6.2f}%")
    print(f"\n  Trail stop triggered: {trail_hits}/{n} trades ({trail_hits/n*100:.1f}%)")
    print(f"  Avg improvement per trade: {(t_avg - f_avg):+.3f}%")
    print(f"  Total improvement:         {(t_tot - f_tot):+.2f}%")

    # Distribution of improvement
    df['improvement'] = df['trail_pnl'] - df['fixed_pnl']
    improved = len(df[df['improvement'] > 0.01])
    hurt     = len(df[df['improvement'] < -0.01])
    neutral  = n - improved - hurt
    print(f"\n  Trail vs Fixed outcome:")
    print(f"    Trail better:  {improved:>5} trades ({improved/n*100:.1f}%)")
    print(f"    No difference: {neutral:>5} trades ({neutral/n*100:.1f}%)")
    print(f"    Trail worse:   {hurt:>5} trades  ({hurt/n*100:.1f}%)")

    # P&L buckets for trailing stop
    thresholds = [0.5, 1.0, 1.5, 2.0]
    print(f"\n  P&L Distribution — Trailing Stop:")
    print(f"  {'Threshold':10} {'Winners':>8} {'%':>6}  {'Losers':>8} {'%':>6}")
    print(f"  {'-'*45}")
    for thr in thresholds:
        w = len(df[df['trail_pnl'] >  thr])
        l = len(df[df['trail_pnl'] < -thr])
        print(f"  > {thr:.1f}%      {w:>8}  {w/n*100:>5.1f}%  {l:>8}  {l/n*100:>5.1f}%")

# ── Main ─────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + SYMBOLS:
    df = load_cached(sym)
    if df is not None:
        all_data[sym] = df
    else:
        print(f"  WARNING: {sym} not cached")
print(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

print(f"Trail activation: {TRAIL_ACTIVATION*100:.1f}%  |  Trail distance: {TRAIL_DISTANCE*100:.1f}%\n")

print("Running 2025..."); t25 = collect(all_data, ema50, s25s, s25e)
print("Running 2026..."); t26 = collect(all_data, ema50, s26s, s26e)

report_comparison(t25,       "2025 FULL YEAR")
report_comparison(t26,       "2026 YTD (Jan-Jun 9)")
report_comparison(t25 + t26, "COMBINED (2025 + 2026 YTD)")
