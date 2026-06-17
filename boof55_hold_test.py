import pandas as pd, pytz, numpy as np, os
from datetime import timedelta
ET = pytz.timezone('America/New_York')

SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'
GAP_MIN = 0.01; RVOL_MIN = 1.5

def load_symbol(sym):
    frames = []
    for y in ['2021','2022','2023','2024','2025_26']:
        p = f'{CACHE_DIR}/{sym}_{y}.parquet'
        if not os.path.exists(p): continue
        df = pd.read_parquet(p, columns=['open','high','low','close','volume'])
        if df.index.tz is None: df.index = df.index.tz_localize('UTC')
        df.index = df.index.tz_convert(ET)
        df = df.between_time('04:00','16:00')
        frames.append(df)
    if not frames: return None
    full = pd.concat(frames).sort_index()
    return full[~full.index.duplicated(keep='first')]

def build_caches(df):
    rth = df.between_time('09:30','16:00')
    pm  = df.between_time('04:00','09:29')
    rg  = {d: g for d, g in rth.groupby(rth.index.normalize())}
    pg  = {d: g for d, g in pm.groupby(pm.index.normalize())}
    dates = sorted(rg.keys())
    day_cache = {}
    for i, date in enumerate(dates):
        pdh = float(rg[dates[i-1]]['high'].max()) if i > 0 and dates[i-1] in rg else 0
        pmh = float(pg[date]['high'].max()) if date in pg and not pg[date].empty else 0
        day_cache[date] = {'pdh': pdh, 'pmh': pmh}
    daily_vol = {d: float(g['volume'].sum()) for d, g in rg.items()}
    vol_s = pd.Series(daily_vol).sort_index()
    rvol_base = {}
    for i, date in enumerate(dates):
        past = vol_s.iloc[max(0, i-20):i]
        rvol_base[date] = float(past.mean()) if len(past) >= 5 else 0
    return day_cache, rvol_base, rg

HOLDS = {'30min': 30, '1hr': 60, '2hr': 120, '3hr': 180, 'EOD': 999}
all_trades = {k: [] for k in HOLDS}
all_trades_by_year = {k: {} for k in HOLDS}

for sym in SYMBOLS:
    print(f'  {sym}...', flush=True)
    df = load_symbol(sym)
    if df is None: continue
    day_cache, rvol_base, grouped = build_caches(df)
    dates = sorted(grouped.keys())
    for i, date in enumerate(dates):
        if i == 0: continue
        day_bars = grouped[date]
        prev_day = grouped.get(dates[i-1])
        if prev_day is None or prev_day.empty: continue
        prev_close = float(prev_day['close'].iloc[-1])
        open_price = float(day_bars['open'].iloc[0])
        gap_pct = (open_price - prev_close) / prev_close
        if gap_pct <= GAP_MIN: continue
        cache = day_cache.get(date, {}); pdh = cache.get('pdh', 0); pmh = cache.get('pmh', 0)
        avg_vol = rvol_base.get(date, 0)
        daily_vol_today = float(day_bars['volume'].sum())
        rvol = daily_vol_today / avg_vol if avg_vol > 0 else 0
        if rvol < RVOL_MIN: continue
        signal_bars = day_bars.between_time('09:30', '10:00')
        if len(signal_bars) < 2: continue
        arr = signal_bars[['close']].values
        fired = False
        for k in range(1, len(arr)):
            if fired: break
            pc = arr[k-1, 0]; cc = arr[k, 0]
            broke = (pdh > 0 and pc <= pdh and cc > pdh) or (pmh > 0 and pc <= pmh and cc > pmh)
            if not broke: continue
            entry_price = cc
            entry_time  = signal_bars.index[k]
            eod = entry_time.replace(hour=15, minute=59, second=0, microsecond=0)
            for hold_name, hold_mins in HOLDS.items():
                if hold_name == 'EOD':
                    exit_end = eod
                else:
                    exit_end = min(entry_time + timedelta(minutes=hold_mins), eod)
                fwd = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= exit_end)]
                ep = float(fwd.iloc[-1]['close']) if len(fwd) > 0 else entry_price
                pnl_pct = (ep - entry_price) / entry_price * 100
                all_trades[hold_name].append(pnl_pct)
                yr = str(date.year)
                if yr not in all_trades_by_year[hold_name]:
                    all_trades_by_year[hold_name][yr] = []
                all_trades_by_year[hold_name][yr].append(pnl_pct)
            fired = True

SEP = '=' * 58
print(f'\n{SEP}')
print(f'BOOF55 Hold Duration Comparison — 28 symbols 2021-2026')
print(f'{SEP}')
print(f'{"Hold":<8} {"N":>5}  {"WR":>6}  {"EV":>8}  {"PF":>6}  {"AvgW":>7}  {"AvgL":>7}')
print('-' * 58)
for hold_name in HOLDS:
    t = all_trades[hold_name]
    if not t: continue
    a = np.array(t)
    n = len(a); wr = (a > 0).mean() * 100; ev = a.mean()
    wins = a[a > 0]; losses = a[a < 0]
    pf   = wins.sum() / abs(losses.sum()) if len(losses) > 0 else 999
    avgw = wins.mean() if len(wins) > 0 else 0
    avgl = losses.mean() if len(losses) > 0 else 0
    print(f'{hold_name:<8} {n:>5}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}  {avgw:>+6.2f}%  {avgl:>+6.2f}%')
print(SEP)

# ── BY YEAR ──
print(f'\n{"BY YEAR":}')
all_years = sorted(set(yr for h in all_trades_by_year.values() for yr in h.keys()))
for hold_name in HOLDS:
    print(f'\n  {hold_name}:')
    print(f'  {"Year":<6} {"N":>5}  {"WR":>6}  {"EV":>8}  {"PF":>6}')
    print('  ' + '-' * 35)
    for yr in all_years:
        t = all_trades_by_year[hold_name].get(yr, [])
        if not t: continue
        a = np.array(t)
        n = len(a); wr = (a > 0).mean() * 100; ev = a.mean()
        wins = a[a > 0]; losses = a[a < 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 else 999
        print(f'  {yr:<6} {n:>5}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}')
