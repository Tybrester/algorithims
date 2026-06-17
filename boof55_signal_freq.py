import pandas as pd, pytz, numpy as np, os
ET = pytz.timezone('America/New_York')
SYMBOLS = ['AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH','FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT','MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO']
CACHE_DIR = 'cache55_years'

signals = []  # (year, date, sym)

for sym in SYMBOLS:
    frames = []
    for y in ['2021','2022','2023','2024','2025_26']:
        p = f'{CACHE_DIR}/{sym}_{y}.parquet'
        if not os.path.exists(p): continue
        df = pd.read_parquet(p, columns=['open','high','low','close','volume'])
        if df.index.tz is None: df.index = df.index.tz_localize('UTC')
        df.index = df.index.tz_convert(ET)
        frames.append(df.between_time('04:00','16:00'))
    if not frames: continue
    full = pd.concat(frames).sort_index()
    full = full[~full.index.duplicated(keep='first')]

    rth = full.between_time('09:30','16:00')
    pm  = full.between_time('04:00','09:29')
    rg  = {d: g for d, g in rth.groupby(rth.index.normalize())}
    pg  = {d: g for d, g in pm.groupby(pm.index.normalize())}
    dates = sorted(rg.keys())
    vol_s = pd.Series({d: float(g['volume'].sum()) for d,g in rg.items()}).sort_index()

    for i, date in enumerate(dates):
        if i == 0: continue
        day_bars = rg[date]
        prev_day = rg.get(dates[i-1])
        if prev_day is None or prev_day.empty: continue
        prev_close = float(prev_day['close'].iloc[-1])
        open_price = float(day_bars['open'].iloc[0])
        if (open_price - prev_close) / prev_close <= 0.01: continue
        past = vol_s.iloc[max(0, i-20):i]
        avg_vol = float(past.mean()) if len(past) >= 5 else 0
        if avg_vol == 0: continue
        rvol = float(day_bars['volume'].sum()) / avg_vol
        if rvol < 1.5: continue
        pdh = float(rg[dates[i-1]]['high'].max()) if dates[i-1] in rg else 0
        pmh = float(pg[date]['high'].max()) if date in pg and not pg[date].empty else 0
        sb = day_bars.between_time('09:30','10:00')
        if len(sb) < 2: continue
        arr = sb[['close']].values
        for k in range(1, len(arr)):
            pc = arr[k-1, 0]; cc = arr[k, 0]
            if (pdh > 0 and pc <= pdh and cc > pdh) or (pmh > 0 and pc <= pmh and cc > pmh):
                signals.append((str(date.year), date.date(), sym))
                break

print(f'Total signals: {len(signals)}')
by_year = {}
for yr, d, s in signals:
    by_year.setdefault(yr, []).append((d, s))

trading_weeks = {'2021': 52, '2022': 52, '2023': 52, '2024': 52, '2025': 52, '2026': 24}
print(f'\n{"Year":<6} {"Signals":>8}  {"UniqDays":>9}  {"Per Wk":>7}  {"Per Mo":>7}  {"Per Yr":>7}')
print('-'*52)
for yr in sorted(by_year.keys()):
    sigs = by_year[yr]
    n = len(sigs)
    wks = trading_weeks.get(yr, 52)
    unique_days = len(set(d for d, s in sigs))
    print(f'{yr:<6} {n:>8}  {unique_days:>9}  {n/wks:>6.1f}x  {n/wks*4:>6.1f}x  {n:>7}')

total = len(signals)
total_wks = sum(trading_weeks[yr] for yr in by_year if yr in trading_weeks)
print(f'\n5yr avg: {total/total_wks:.1f} signals/wk  |  {total/total_wks*4:.1f}/mo  |  {total/total_wks*52:.0f}/yr')
print(f'\nAt $88 avg PnL/call trade + $15 stock:')
spw = total/total_wks
print(f'  Per week:  ${spw*103:.0f}')
print(f'  Per month: ${spw*103*4:.0f}')
print(f'  Per year:  ${spw*103*52:.0f}')
