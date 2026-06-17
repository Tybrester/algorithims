"""
BOOF55 TP/SL matrix test on 1-ITM call, 30min hold
Tests multiple TP/SL combinations vs pure 30min hold (no TP/SL)
"""
import pandas as pd, pytz, numpy as np, os, math
from datetime import timedelta
from scipy.stats import norm
ET = pytz.timezone('America/New_York')

SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'
GAP_MIN = 0.01; RVOL_MIN = 1.5

def bs_call(S, K, T, r=0.05, sigma=0.50):
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

# Collect per-bar option P&L series for each trade
trade_paths = []  # list of {bars: [opt_ret_pct per bar], entry_prem, ...}

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
            exit_30 = min(entry_time + timedelta(minutes=30), eod)

            # 1-ITM strike
            strikeInt = 5 if entry_price > 500 else 2.5 if entry_price > 50 else 1
            atm = round(entry_price / strikeInt) * strikeInt
            K   = atm - strikeInt

            days_to_exp = max(1, (5 - entry_time.weekday()) % 7 + 1)
            T_entry = days_to_exp / 252
            entry_prem = bs_call(entry_price, K, T_entry)

            # Build per-minute option returns
            fwd = day_bars.loc[(day_bars.index > entry_time) & (day_bars.index <= exit_30)]
            bar_rets = []
            for b_idx, (ts, row) in enumerate(fwd.iterrows()):
                mins_elapsed = (b_idx + 1)
                T_bar = max(T_entry - mins_elapsed/(252*390), 0)
                bar_prem = bs_call(float(row['close']), K, T_bar)
                bar_rets.append((bar_prem - entry_prem) / entry_prem)

            if bar_rets:
                trade_paths.append({'rets': bar_rets, 'entry_prem': entry_prem, 'sym': sym, 'date': str(date)})
            fired = True

print(f'\n{len(trade_paths)} trades loaded\n', flush=True)

# ── Test TP/SL combos ──
TP_LEVELS = [0.25, 0.35, 0.50, 0.75, 1.00, None]
SL_LEVELS = [-0.25, -0.35, -0.50, -0.75, None]

SEP = '=' * 72
print(SEP)
print(f'{"TP":>6}  {"SL":>6}  {"N":>5}  {"WR":>6}  {"EV":>8}  {"PF":>6}  {"AvgW":>7}  {"AvgL":>7}  {"ExitType"}')
print('-' * 72)

results = []
for tp in TP_LEVELS:
    for sl in SL_LEVELS:
        trade_rets = []
        exit_counts = {'tp': 0, 'sl': 0, 'time': 0}
        for t in trade_paths:
            rets = t['rets']
            final_ret = rets[-1] if rets else 0
            hit_tp = False; hit_sl = False
            exit_ret = final_ret
            for r in rets:
                if tp and r >= tp:
                    exit_ret = tp; hit_tp = True; break
                if sl and r <= sl:
                    exit_ret = sl; hit_sl = True; break
            if hit_tp: exit_counts['tp'] += 1
            elif hit_sl: exit_counts['sl'] += 1
            else: exit_counts['time'] += 1
            trade_rets.append(exit_ret)

        a = np.array(trade_rets)
        n = len(a); wr = (a > 0).mean() * 100; ev = a.mean()
        wins = a[a > 0]; losses = a[a < 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 else 999
        avgw = wins.mean() if len(wins) > 0 else 0
        avgl = losses.mean() if len(losses) > 0 else 0
        tp_str = f'+{int(tp*100)}%' if tp else 'none'
        sl_str = f'-{int(abs(sl)*100)}%' if sl else 'none'
        exit_str = f'tp={exit_counts["tp"]} sl={exit_counts["sl"]} t={exit_counts["time"]}'
        print(f'{tp_str:>6}  {sl_str:>6}  {n:>5}  {wr:>5.1f}%  {ev:>+7.3f}  {pf:>6.3f}  {avgw:>+6.2f}  {avgl:>+6.2f}  {exit_str}')
        results.append((ev, pf, tp_str, sl_str))

print(SEP)
print('\nTop 5 by EV:')
for ev, pf, tp, sl in sorted(results, key=lambda x: x[0], reverse=True)[:5]:
    print(f'  TP={tp} SL={sl}  EV={ev:+.4f}  PF={pf:.3f}')
print('\nTop 5 by PF:')
for ev, pf, tp, sl in sorted(results, key=lambda x: x[1], reverse=True)[:5]:
    print(f'  TP={tp} SL={sl}  EV={ev:+.4f}  PF={pf:.3f}')
