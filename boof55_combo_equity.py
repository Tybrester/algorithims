"""
BOOF55 Combo equity simulation
On each signal: buy ATM call (exit 30min) + stock (exit EOD)
Split capital: 50% to option, 50% to stock
$10,000 starting equity, 5% risk per trade total
"""
import pandas as pd, pytz, numpy as np, os, math
from datetime import timedelta
from scipy.stats import norm
ET = pytz.timezone('America/New_York')

SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'
GAP_MIN = 0.01; RVOL_MIN = 1.5
START_EQUITY = 10000.0
RISK_PCT = 0.05

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
        rvol = float(day_bars['volume'].sum()) / avg_vol
        if rvol < RVOL_MIN: continue
        signal_bars = day_bars.between_time('09:30', '10:00')
        if len(signal_bars) < 2: continue
        arr_s = signal_bars[['close']].values
        fired = False
        for k in range(1, len(arr_s)):
            if fired: break
            pc = arr_s[k-1, 0]; cc = arr_s[k, 0]
            broke = (pdh > 0 and pc <= pdh and cc > pdh) or (pmh > 0 and pc <= pmh and cc > pmh)
            if not broke: continue
            entry_price = cc
            entry_time  = signal_bars.index[k]
            eod = entry_time.replace(hour=15, minute=59, second=0, microsecond=0)

            # Stock PnL at EOD
            fwd_eod = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= eod)]
            ep_eod  = float(fwd_eod.iloc[-1]['close']) if len(fwd_eod) > 0 else entry_price
            stk_ret = (ep_eod - entry_price) / entry_price

            # Option PnL at 30min
            exit_30 = min(entry_time + timedelta(minutes=30), eod)
            fwd_30  = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= exit_30)]
            ep_30   = float(fwd_30.iloc[-1]['close']) if len(fwd_30) > 0 else entry_price
            days_to_exp = max(1, (5 - entry_time.weekday()) % 7 + 1)
            T_entry = days_to_exp / 252
            T_exit  = max(T_entry - 30/(252*390), 0)
            K = round(entry_price / 2.5) * 2.5
            entry_prem = bs_call(entry_price, K, T_entry, 0.05, 0.50)
            exit_prem  = bs_call(ep_30, K, T_exit, 0.05, 0.50)
            opt_ret    = (exit_prem - entry_prem) / entry_prem

            all_trades.append({
                'date': date, 'sym': sym,
                'entry_price': entry_price,
                'entry_prem': entry_prem, 'exit_prem': exit_prem,
                'stk_ret': stk_ret, 'opt_ret': opt_ret,
            })
            fired = True

all_trades.sort(key=lambda x: x['date'])

# Equity simulation — 1 trade per day, split 50/50 capital
equity   = START_EQUITY
max_eq   = equity
max_dd   = 0.0
yearly   = {}
trade_pnls = []
dates_seen = set()

for t in all_trades:
    d = t['date']
    if d in dates_seen: continue
    dates_seen.add(d)

    risk_usd   = equity * RISK_PCT
    half_risk  = risk_usd / 2

    # Stock leg: half_risk buys shares
    shares     = max(1, int(half_risk / t['entry_price']))
    stk_pnl    = shares * t['entry_price'] * t['stk_ret']

    # Option leg: half_risk buys contracts
    contracts  = max(1, int(half_risk / (t['entry_prem'] * 100)))
    opt_pnl    = contracts * (t['exit_prem'] - t['entry_prem']) * 100

    total_pnl  = stk_pnl + opt_pnl
    equity    += total_pnl
    max_eq     = max(max_eq, equity)
    dd         = (max_eq - equity) / max_eq * 100
    max_dd     = max(max_dd, dd)

    yr = str(d.year)
    if yr not in yearly: yearly[yr] = {'start': equity - total_pnl, 'end': equity, 'n': 0, 'wins': 0, 'pnl': 0}
    yearly[yr]['end']  = equity
    yearly[yr]['n']   += 1
    yearly[yr]['wins'] += 1 if total_pnl > 0 else 0
    yearly[yr]['pnl']  += total_pnl
    trade_pnls.append(total_pnl)

SEP = '=' * 62
print(f'\n{SEP}')
print(f'BOOF55 COMBO — Stock EOD + ATM Call 30min | $10k start | 5% risk')
print(f'{SEP}')
wins = [p for p in trade_pnls if p > 0]
losses = [p for p in trade_pnls if p < 0]
print(f'  Total trades  : {len(trade_pnls)}')
print(f'  Win Rate      : {len(wins)/len(trade_pnls)*100:.1f}%')
print(f'  Final Equity  : ${equity:,.0f}  ({(equity/START_EQUITY-1)*100:+.1f}%)')
print(f'  Max Drawdown  : {max_dd:.1f}%')
print(f'  Avg Win       : ${np.mean(wins):,.2f}')
print(f'  Avg Loss      : ${np.mean(losses):,.2f}')
print(f'\n{"Year":<6} {"N":>4}  {"WR":>6}  {"PnL $":>10}  {"End Eq":>10}  {"Ret":>7}')
print('-'*58)
for yr in sorted(yearly.keys()):
    y = yearly[yr]
    wr  = y['wins']/y['n']*100 if y['n']>0 else 0
    ret = (y['end']/y['start']-1)*100 if y['start']>0 else 0
    print(f'{yr:<6} {y["n"]:>4}  {wr:>5.1f}%  ${y["pnl"]:>9,.0f}  ${y["end"]:>9,.0f}  {ret:>+6.1f}%')
print(SEP)
