"""
BOOF55 — 5-Year Backtest (2021-2026)
Exact live algo logic:
  - Gap > 1% from prev close
  - RVOL >= 1.5x (20-day rolling avg)
  - Breakout of PDH or PMH (prev bar below, curr bar above)
  - Signal window: 09:30-10:00 ET only
  - Exit: 2hr hold OR -1% stop, EOD at 15:59
  - Sizing: 5% risk / 1% stop = 5x equity position (just tracks % returns here)
"""
import pandas as pd
import numpy as np
import os, pytz
from datetime import datetime, timedelta

ET = pytz.timezone("America/New_York")

SYMBOLS = [
    'AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH',
    'FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT',
    'MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO',
]

CACHE_DIR  = 'cache55_years'
GAP_MIN    = 0.01
RVOL_MIN   = 1.5
STOP_PCT   = 0.02
HOLD_BARS  = 120   # 2hrs of 1m bars
RVOL_WIN   = 20    # trading days

# ── Load all cached parquet files for a symbol ──────────────────────────────
def load_symbol(sym):
    frames = []
    for year_label in ['2021','2022','2023','2024','2025_26']:
        path = f"{CACHE_DIR}/{sym}_{year_label}.parquet"
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path, columns=['open','high','low','close','volume'])
        if df.index.tz is None:
            df.index = pd.DatetimeIndex(df.index).tz_localize('UTC', ambiguous='NaT', nonexistent='NaT')
        df.index = df.index.tz_convert(ET)
        # Keep only RTH + pre-market (04:00-16:00) to cut memory
        df = df.between_time('04:00', '16:00')
        frames.append(df)
    if not frames:
        return None
    full = pd.concat(frames).sort_index()
    full = full[~full.index.duplicated(keep='first')]
    return full

# ── Build per-day PDH/PMH cache ──────────────────────────────────────────────
def build_day_cache(df):
    cache = {}
    rth      = df.between_time('09:30', '16:00')
    pm_bars  = df.between_time('04:00', '09:29')
    rth_grp  = {d: g for d, g in rth.groupby(rth.index.normalize())}
    pm_grp   = {d: g for d, g in pm_bars.groupby(pm_bars.index.normalize())}
    dates    = sorted(rth_grp.keys())
    for i, date in enumerate(dates):
        pdh = 0.0
        if i > 0:
            prev = rth_grp.get(dates[i-1])
            if prev is not None and not prev.empty:
                pdh = float(prev['high'].max())
        pm = pm_grp.get(date)
        pmh = float(pm['high'].max()) if pm is not None and not pm.empty else 0.0
        cache[date] = {'pdh': pdh, 'pmh': pmh}
    return cache

# ── RVOL baseline: avg volume of first bar each day over rolling 20 days ─────
def build_rvol_baseline(df):
    rth      = df.between_time('09:30', '16:00')
    rth_grp  = {d: g for d, g in rth.groupby(rth.index.normalize())}
    dates    = sorted(rth_grp.keys())
    first_bar_vols = {}
    for date in dates:
        day = rth_grp[date]
        if not day.empty:
            first_bar_vols[date] = float(day['volume'].iloc[0])
    baseline = {}
    for i, date in enumerate(dates):
        window = dates[max(0, i - RVOL_WIN):i]
        if len(window) < 5:
            baseline[date] = 0
        else:
            baseline[date] = np.mean([first_bar_vols[d] for d in window if d in first_bar_vols])
    return baseline

# ── Run backtest for one symbol ───────────────────────────────────────────────
def backtest_symbol(sym, df):
    rth       = df.between_time('09:30', '16:00')
    day_cache = build_day_cache(df)
    rvol_base = build_rvol_baseline(df)

    # Precompute cumulative volume per day (avoids O(n²) filtering)
    rth = rth.copy()
    rth['cumvol'] = rth.groupby(rth.index.normalize())['volume'].cumsum()
    rth['barnum'] = rth.groupby(rth.index.normalize()).cumcount() + 1

    # Pre-group all days once — avoids O(n) scan per day
    grouped   = {d: g for d, g in rth.groupby(rth.index.normalize())}
    dates     = sorted(grouped.keys())
    trades    = []

    for i, date in enumerate(dates):
        day_bars = grouped[date]
        if len(day_bars) < 2:
            continue

        cache   = day_cache.get(date, {})
        pdh     = cache.get('pdh', 0)
        pmh     = cache.get('pmh', 0)
        avg_vol = rvol_base.get(date, 0)

        if i == 0:
            continue
        prev_day = grouped.get(dates[i - 1])
        if prev_day is None or prev_day.empty:
            continue
        prev_close = float(prev_day['close'].iloc[-1])

        open_price = float(day_bars['open'].iloc[0])
        gap_pct    = (open_price - prev_close) / prev_close
        if gap_pct <= GAP_MIN:
            continue

        signal_bars = day_bars.between_time('09:30', '10:00')
        if len(signal_bars) < 2:
            continue

        fired = False
        arr = signal_bars[['open','high','low','close','volume','cumvol','barnum']].values
        for k in range(1, len(arr)):
            if fired:
                break

            prev_close_bar = arr[k-1, 3]   # close
            curr_close     = arr[k,   3]
            cumvol_k       = arr[k,   5]
            barnum_k       = int(arr[k, 6])

            # Gate 2: RVOL
            avg_per_bar = (cumvol_k / barnum_k) if barnum_k > 0 else 0
            rvol = avg_per_bar / avg_vol if avg_vol > 0 else 0
            if rvol < RVOL_MIN:
                continue

            # Gate 3: breakout
            broke_pdh = pdh > 0 and prev_close_bar <= pdh and curr_close > pdh
            broke_pmh = pmh > 0 and prev_close_bar <= pmh and curr_close > pmh
            if not broke_pdh and not broke_pmh:
                continue

            level       = 'PDH' if broke_pdh else 'PMH'
            entry_price = curr_close
            stop_price  = entry_price * (1 - STOP_PCT)
            entry_time  = signal_bars.index[k]
            hold_end    = entry_time + timedelta(hours=2)
            eod_time    = entry_time.replace(hour=15, minute=59, second=0, microsecond=0)
            exit_end    = min(hold_end, eod_time)

            fwd = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= exit_end)]
            exit_price  = entry_price
            exit_reason = '2hr_hold'

            fwd_arr = fwd[['low','close']].values
            for frow in fwd_arr:
                if frow[0] <= stop_price:
                    exit_price  = stop_price
                    exit_reason = 'stop_loss'
                    break
                exit_price = frow[1]

            pnl_pct = (exit_price - entry_price) / entry_price
            trades.append({
                'sym': sym, 'date': str(date.date()),
                'entry_time': str(entry_time), 'entry_price': entry_price,
                'exit_price': exit_price, 'exit_reason': exit_reason,
                'pnl_pct': pnl_pct, 'gap_pct': gap_pct, 'rvol': rvol, 'level': level,
            })
            fired = True

    return trades

# ── Main ─────────────────────────────────────────────────────────────────────
all_trades = []
missing    = []

print(f"\nBOOF55 5-Year Backtest — {len(SYMBOLS)} symbols\n{'='*60}")

for sym in SYMBOLS:
    df = load_symbol(sym)
    if df is None or len(df) < 1000:
        missing.append(sym)
        print(f"  {sym:<6} — NO DATA")
        continue
    trades = backtest_symbol(sym, df)
    all_trades.extend(trades)
    if trades:
        t_df = pd.DataFrame(trades)
        wr   = (t_df['pnl_pct'] > 0).mean()
        ev   = t_df['pnl_pct'].mean()
        print(f"  {sym:<6}  {len(trades):>4} trades  WR={wr*100:.1f}%  EV={ev*100:+.3f}%")
    else:
        print(f"  {sym:<6}  0 trades")

if not all_trades:
    print("\nNo trades — fetch data first with boof55_fetch_5yr.py")
    exit()

df = pd.DataFrame(all_trades)
df['year'] = pd.to_datetime(df['date']).dt.year

# ── Overall stats ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"OVERALL  ({df['date'].min()} → {df['date'].max()})")
print(f"{'='*60}")
n     = len(df)
wins  = df[df['pnl_pct'] > 0]
loss  = df[df['pnl_pct'] <= -STOP_PCT + 0.0001]
wr    = len(wins) / n
ev    = df['pnl_pct'].mean()
avg_w = wins['pnl_pct'].mean() if len(wins) else 0
avg_l = abs(loss['pnl_pct'].mean()) if len(loss) else 0
pf    = (len(wins) * avg_w) / (len(loss) * avg_l) if len(loss) > 0 and avg_l else float('inf')

# Compound equity curve (5% risk / 1% stop = 5x position)
leverage = 0.05 / STOP_PCT  # = 5x
equity   = 1.0
equity_curve = [1.0]
peak = 1.0
max_dd = 0.0
for _, row in df.iterrows():
    equity *= (1 + row['pnl_pct'] * leverage)
    equity_curve.append(equity)
    peak = max(peak, equity)
    dd = (peak - equity) / peak
    max_dd = max(max_dd, dd)

print(f"  Trades:       {n}")
print(f"  Win Rate:     {wr*100:.1f}%")
print(f"  Profit Factor:{pf:.2f}")
print(f"  EV/trade:     {ev*100:+.3f}%  ({ev*leverage*100:+.3f}% on equity)")
print(f"  Avg Win:      {avg_w*100:+.3f}%")
print(f"  Avg Loss:     {avg_l*100:-.3f}%")
print(f"  Max Drawdown: {max_dd*100:.1f}%")
print(f"  Final Equity: {equity:.2f}x  (${equity*3000:.0f} from $3000)")

# ── By year ───────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"BY YEAR")
print(f"{'='*60}")
print(f"  {'Year':<6}  {'N':>5}  {'WR':>7}  {'EV':>8}  {'PF':>6}  {'Ret':>8}")
yr_equity = 1.0
for year, grp in df.groupby('year'):
    n_y   = len(grp)
    wr_y  = (grp['pnl_pct'] > 0).mean()
    ev_y  = grp['pnl_pct'].mean()
    w_y   = grp[grp['pnl_pct'] > 0]['pnl_pct'].mean() if (grp['pnl_pct'] > 0).any() else 0
    l_y   = abs(grp[grp['pnl_pct'] <= -STOP_PCT + 0.0001]['pnl_pct'].mean()) if (grp['pnl_pct'] <= -STOP_PCT + 0.0001).any() else 0
    n_w   = (grp['pnl_pct'] > 0).sum()
    n_l   = (grp['pnl_pct'] <= -STOP_PCT + 0.0001).sum()
    pf_y  = (n_w * w_y) / (n_l * l_y) if n_l > 0 and l_y > 0 else float('inf')
    yr_ret = grp['pnl_pct'].sum() * leverage
    print(f"  {year:<6}  {n_y:>5}  {wr_y*100:>6.1f}%  {ev_y*100:>+7.3f}%  {pf_y:>6.2f}  {yr_ret*100:>+7.1f}%")

# ── By symbol ─────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"BY SYMBOL")
print(f"{'='*60}")
print(f"  {'Sym':<6}  {'N':>4}  {'WR':>7}  {'EV':>8}  {'T/yr':>5}")
for sym, grp in df.groupby('sym'):
    n_s  = len(grp)
    wr_s = (grp['pnl_pct'] > 0).mean()
    ev_s = grp['pnl_pct'].mean()
    yrs  = grp['year'].nunique()
    print(f"  {sym:<6}  {n_s:>4}  {wr_s*100:>6.1f}%  {ev_s*100:>+7.3f}%  {n_s/yrs:>5.1f}")

# ── Exit reason breakdown ─────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"EXIT REASONS")
print(f"{'='*60}")
for reason, grp in df.groupby('exit_reason'):
    n_r  = len(grp)
    ev_r = grp['pnl_pct'].mean()
    print(f"  {reason:<15}  {n_r:>5} ({n_r/n*100:.1f}%)  EV={ev_r*100:+.3f}%")

if missing:
    print(f"\n  Missing data (need to fetch): {', '.join(missing)}")
    print(f"  Run: python boof55_fetch_5yr.py")

df.to_csv('boof55_5yr_results.csv', index=False)
print(f"\nSaved to boof55_5yr_results.csv")
