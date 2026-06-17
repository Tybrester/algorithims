"""
Test: walk ITM until budget fills vs walk OTM until budget fills
$750 budget, compare total PnL
"""
import pandas as pd, pytz, numpy as np, os, math
from datetime import timedelta
from scipy.stats import norm
ET = pytz.timezone('America/New_York')

SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'
GAP_MIN = 0.01; RVOL_MIN = 1.5; BUDGET = 750; MAX_CONTRACTS = 10

def bs_call(S, K, T, r=0.05, sigma=0.50):
    if T <= 0: return max(S - K, 0.01)
    d1 = (math.log(max(S/K,0.001)) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return max(S*norm.cdf(d1) - K*math.exp(-r*T)*norm.cdf(d2), 0.01)

def bs_delta(S, K, T, r=0.05, sigma=0.50):
    if T <= 0: return 1.0 if S > K else 0.0
    d1 = (math.log(max(S/K,0.001)) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    return norm.cdf(d1)

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

# strategies: key -> (start_offset, walk_direction)
# offset = strikes from ATM (negative=ITM), direction = which way to walk if too expensive
STRATEGIES = {
    '1ITM_wOTM':  {'start': -1, 'walk':  +1},
    '1ITM_wITM':  {'start': -1, 'walk':  -1},
    '2ITM_wOTM':  {'start': -2, 'walk':  +1},
    '2ITM_wITM':  {'start': -2, 'walk':  -1},
    'ATM_wOTM':   {'start':  0, 'walk':  +1},
    'ATM_wITM':   {'start':  0, 'walk':  -1},
}

results = {k: [] for k in STRATEGIES}

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
        cache = day_cache.get(date, {}); pdh = cache.get('pdh',0); pmh = cache.get('pmh',0)
        avg_vol = rvol_base.get(date, 0)
        if avg_vol == 0: continue
        rvol = float(day_bars['volume'].sum()) / avg_vol
        if rvol < RVOL_MIN: continue
        signal_bars = day_bars.between_time('09:30','10:00')
        if len(signal_bars) < 2: continue
        arr_s = signal_bars[['close']].values
        fired = False
        for k in range(1, len(arr_s)):
            if fired: break
            pc = arr_s[k-1,0]; cc = arr_s[k,0]
            broke = (pdh>0 and pc<=pdh and cc>pdh) or (pmh>0 and pc<=pmh and cc>pmh)
            if not broke: continue

            S = cc
            strikeInt = 5 if S>500 else 2.5 if S>50 else 1
            atm = round(S/strikeInt)*strikeInt
            days_to_exp = max(1,(5-signal_bars.index[k].weekday())%7+1)
            T0 = days_to_exp/252
            T1 = max(T0 - 30/(252*390), 0)

            eod = signal_bars.index[k].replace(hour=15,minute=59,second=0,microsecond=0)
            exit_30 = min(signal_bars.index[k]+timedelta(minutes=30), eod)
            fwd = day_bars.loc[(day_bars.index>signal_bars.index[k])&(day_bars.index<=exit_30)]
            S1 = float(fwd.iloc[-1]['close']) if len(fwd)>0 else S

            for strat_name, cfg in STRATEGIES.items():
                start_offset = cfg['start']
                walk_dir     = cfg['walk']
                chosen_K = None; chosen_qty = 0; cost_per = 0

                # Try start strike, then walk in walk_dir up to 5 steps
                for step in range(6):
                    offset = start_offset + step*walk_dir
                    K = atm + offset*strikeInt
                    if K <= 0: continue
                    prem = bs_call(S, K, T0)
                    cost1 = prem * 100
                    if walk_dir == 1:  # walking OTM — stop when fits budget
                        if cost1 <= BUDGET:
                            chosen_K = K
                            chosen_qty = min(MAX_CONTRACTS, max(1, int(BUDGET/cost1)))
                            cost_per = prem
                            break
                    else:  # walking ITM — go as deep as budget allows (1 contract)
                        if cost1 <= BUDGET:
                            chosen_K = K
                            chosen_qty = 1  # 1 contract, deepest ITM that fits
                            cost_per = prem
                            # keep walking ITM (don't break, update if next also fits)
                        else:
                            break  # too expensive, use last valid

                if chosen_K is None: continue
                entry_prem = bs_call(S,  chosen_K, T0)
                exit_prem  = bs_call(S1, chosen_K, T1)
                # Apply -50% SL
                raw_ret = (exit_prem - entry_prem) / entry_prem
                ret = max(raw_ret, -0.50)
                total_pnl = ret * entry_prem * chosen_qty * 100
                results[strat_name].append({'ret': ret, 'pnl': total_pnl, 'K': chosen_K, 'qty': chosen_qty, 'atm': atm, 'strikeInt': strikeInt})
            fired = True

SEP = '='*75
print(f'\n{SEP}')
print(f'BOOF55 Strike Walk Strategy — $750 budget, 30min hold, -50% SL')
print(f'{SEP}')
print(f'{"Strategy":<14} {"N":>5}  {"WR":>6}  {"EV%":>8}  {"PF":>6}  {"AvgPnL$":>9}  {"AvgQty":>7}  {"AvgStrk"}')
print('-'*75)
for strat_name in STRATEGIES:
    r = results[strat_name]
    if not r: continue
    rets  = np.array([x['ret'] for x in r])
    pnls  = np.array([x['pnl'] for x in r])
    qtys  = np.array([x['qty'] for x in r])
    offsets = np.array([(x['atm']-x['K'])/x['strikeInt'] for x in r])  # + = ITM
    n=len(rets); wr=(rets>0).mean()*100; ev=rets.mean()*100
    wins=pnls[pnls>0]; losses=pnls[pnls<0]
    pf=wins.sum()/abs(losses.sum()) if len(losses)>0 else 999
    print(f'{strat_name:<14} {n:>5}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}  ${pnls.mean():>8.2f}  {qtys.mean():>6.1f}x  {offsets.mean():>+.1f} strikes ITM')
print(SEP)
