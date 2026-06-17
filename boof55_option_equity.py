"""
BOOF55 Option-only equity simulation
Buy 1 ATM call at signal, exit at 30min
$10,000 starting equity, risk 5% per trade ($500)
"""
import pandas as pd, pytz, numpy as np, os, math
from datetime import timedelta
from scipy.stats import norm
ET = pytz.timezone('America/New_York')

SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'
GAP_MIN = 0.01; RVOL_MIN = 1.5
START_EQUITY = 10000.0
RISK_PCT = 0.05  # 5% per trade

def bs_call(S, K, T, r, sigma):
    if T <= 0: return max(S - K, 0.01)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return max(S*norm.cdf(d1) - K*math.exp(-r*T)*norm.cdf(d2), 0.01)

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

# Collect all trades with dates for equity simulation
all_trades = []

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
        if avg_vol == 0: continue
        daily_vol_today = float(day_bars['volume'].sum())
        rvol = daily_vol_today / avg_vol
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
            exit_30 = min(entry_time + timedelta(minutes=30), eod)
            fwd_30  = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= exit_30)]
            ep_30   = float(fwd_30.iloc[-1]['close']) if len(fwd_30) > 0 else entry_price

            # ATM call pricing
            days_to_exp = max(1, (5 - entry_time.weekday()) % 7 + 1)
            T_entry = days_to_exp / 252
            T_exit  = max(T_entry - 30/(252*390), 0)
            sigma   = 0.50
            K = round(entry_price / 2.5) * 2.5

            entry_prem = bs_call(entry_price, K, T_entry, 0.05, sigma)
            exit_prem  = bs_call(ep_30, K, T_exit, 0.05, sigma)
            opt_ret_pct = (exit_prem - entry_prem) / entry_prem

            all_trades.append({
                'date': date,
                'sym': sym,
                'entry_price': entry_price,
                'entry_prem': entry_prem,
                'exit_prem': exit_prem,
                'opt_ret_pct': opt_ret_pct,
                'gap_pct': gap_pct,
                'rvol': rvol,
            })
            fired = True

# Sort by date for equity curve
all_trades.sort(key=lambda x: x['date'])

# Simulate equity curve — 1 trade per day max (take first signal each day)
equity = START_EQUITY
equity_curve = [equity]
dates_seen = set()
yearly = {}
max_eq = equity
max_dd = 0.0
trade_results = []

for t in all_trades:
    d = t['date']
    if d in dates_seen: continue  # 1 per day across all symbols
    dates_seen.add(d)

    risk_usd  = equity * RISK_PCT
    contracts = max(1, int(risk_usd / (t['entry_prem'] * 100)))
    cost      = contracts * t['entry_prem'] * 100
    pnl       = contracts * (t['exit_prem'] - t['entry_prem']) * 100

    equity += pnl
    equity_curve.append(equity)
    max_eq = max(max_eq, equity)
    dd = (max_eq - equity) / max_eq * 100
    max_dd = max(max_dd, dd)

    yr = str(d.year)
    if yr not in yearly: yearly[yr] = {'start': equity - pnl, 'end': equity, 'n': 0, 'wins': 0, 'pnl': 0}
    yearly[yr]['end']  = equity
    yearly[yr]['n']   += 1
    yearly[yr]['wins'] += 1 if pnl > 0 else 0
    yearly[yr]['pnl']  += pnl
    trade_results.append(pnl)

SEP = '=' * 60
print(f'\n{SEP}')
print(f'BOOF55 — ATM Call 30min Exit | ${START_EQUITY:,.0f} start | 5% risk')
print(f'{SEP}')
print(f'  Total trades : {len(trade_results)}')
rets = np.array([t["opt_ret_pct"]*100 for t in all_trades[:len(trade_results)]])
print(f'  Win Rate     : {(np.array(trade_results)>0).mean()*100:.1f}%')
print(f'  Final Equity : ${equity:,.0f}  ({(equity/START_EQUITY-1)*100:+.1f}%)')
print(f'  Max Drawdown : {max_dd:.1f}%')
print(f'  Avg Win      : ${np.array([p for p in trade_results if p>0]).mean():.2f}' if any(p>0 for p in trade_results) else '')
print(f'  Avg Loss     : ${np.array([p for p in trade_results if p<0]).mean():.2f}' if any(p<0 for p in trade_results) else '')

print(f'\n{"Year":<6} {"N":>4}  {"WR":>6}  {"PnL $":>9}  {"End Eq":>10}  {"Ret":>7}')
print('-'*55)
for yr in sorted(yearly.keys()):
    y = yearly[yr]
    wr = y['wins']/y['n']*100 if y['n']>0 else 0
    ret = (y['end']/y['start']-1)*100 if y['start']>0 else 0
    print(f'{yr:<6} {y["n"]:>4}  {wr:>5.1f}%  ${y["pnl"]:>8,.0f}  ${y["end"]:>9,.0f}  {ret:>+6.1f}%')
print(SEP)
