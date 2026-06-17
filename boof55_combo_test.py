"""
BOOF55 Combo Test: Buy stock + ATM call on same signal
- Stock exits EOD
- Option exits at 30min
Compare combo vs stock-only-EOD and option-only-30min
Uses simplified Black-Scholes for option returns
"""
import pandas as pd, pytz, numpy as np, os
from datetime import timedelta
import math
ET = pytz.timezone('America/New_York')

SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'
GAP_MIN = 0.01; RVOL_MIN = 1.5

def bs_call(S, K, T, r, sigma):
    if T <= 0: return max(S - K, 0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    from scipy.stats import norm
    return S*norm.cdf(d1) - K*math.exp(-r*T)*norm.cdf(d2)

def option_pnl_pct(S_entry, S_exit, T_entry, sigma=0.50, r=0.05):
    K = round(S_entry / 2.5) * 2.5  # ATM strike rounded to $2.50
    T_exit = max(T_entry - 30/(252*390), 0)  # 30min less time
    entry_val = bs_call(S_entry, K, T_entry, r, sigma)
    exit_val  = bs_call(S_exit,  K, T_exit,  r, sigma)
    if entry_val <= 0: return 0
    return (exit_val - entry_val) / entry_val * 100

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

stock_eod    = []
opt_30min    = []
combo        = []  # avg of stock_eod + opt_30min
by_year_stock = {}
by_year_opt   = {}
by_year_combo = {}

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

            # Stock exit at EOD
            fwd_eod = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= eod)]
            ep_eod  = float(fwd_eod.iloc[-1]['close']) if len(fwd_eod) > 0 else entry_price
            stk_ret = (ep_eod - entry_price) / entry_price * 100

            # Option exit at 30min
            exit_30 = min(entry_time + timedelta(minutes=30), eod)
            fwd_30  = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= exit_30)]
            ep_30   = float(fwd_30.iloc[-1]['close']) if len(fwd_30) > 0 else entry_price

            # Days to expiry at entry (assume nearest Friday)
            days_to_exp = max(1, (5 - entry_time.weekday()) % 7 + 1)
            T_entry = days_to_exp / 252
            opt_ret = option_pnl_pct(entry_price, ep_30, T_entry)

            # Combo: 50% capital in stock, 50% in option (1 contract ~$100-300 premium)
            combo_ret = (stk_ret + opt_ret) / 2

            yr = str(date.year)
            stock_eod.append(stk_ret)
            opt_30min.append(opt_ret)
            combo.append(combo_ret)
            for d, arr2 in [(by_year_stock, stk_ret),(by_year_opt, opt_ret),(by_year_combo, combo_ret)]:
                if yr not in d: d[yr] = []
                d[yr].append(arr2)
            fired = True

def stats(arr):
    a = np.array(arr)
    n=len(a); wr=(a>0).mean()*100; ev=a.mean()
    w=a[a>0]; l=a[a<0]
    pf=w.sum()/abs(l.sum()) if len(l)>0 else 999
    return n,wr,ev,pf

SEP = '=' * 62
print(f'\n{SEP}')
print(f'BOOF55 Combo Test — 28 symbols 2021-2026')
print(f'{SEP}')
print(f'{"Strategy":<22} {"N":>5}  {"WR":>6}  {"EV":>8}  {"PF":>6}')
print('-'*62)
for label, data in [('Stock only (EOD)', stock_eod), ('Option only (30min ATM)', opt_30min), ('Combo 50/50', combo)]:
    n,wr,ev,pf = stats(data)
    print(f'{label:<22} {n:>5}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}')
print(SEP)

print(f'\nBY YEAR:')
all_years = sorted(by_year_stock.keys())
for label, d in [('Stock EOD', by_year_stock), ('Option 30m', by_year_opt), ('Combo 50/50', by_year_combo)]:
    print(f'\n  {label}:')
    print(f'  {"Year":<6} {"N":>5}  {"WR":>6}  {"EV":>8}  {"PF":>6}')
    print('  ' + '-'*35)
    for yr in all_years:
        t = d.get(yr, [])
        if not t: continue
        n,wr,ev,pf = stats(t)
        print(f'  {yr:<6} {n:>5}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}')
