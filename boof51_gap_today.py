import alpaca_trade_api as tradeapi, pytz
TZ = pytz.timezone('America/New_York')
api = tradeapi.REST('PKWKMWREJIGNRMBOQWORXFRMDS', '7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW',
                    'https://paper-api.alpaca.markets', api_version='v2')
SYMBOLS = ['UPST','APP','SMCI','HIMS','GOOGL','META','AFRM','TSLA','CLSK','HOOD',
           'ADBE','PANW','MU','AMD','COIN','NVDA','MRVL','AVGO','PLTR','CRM']

for sym in SYMBOLS:
    try:
        intra = api.get_bars(sym, '1Min', start='2026-06-15T04:00:00-04:00',
                             end='2026-06-15T09:35:00-04:00', feed='iex').df
        daily = api.get_bars(sym, '1Day', start='2026-06-01',
                             end='2026-06-14', feed='iex').df
        if intra.empty or len(daily) < 1:
            print(f'{sym:6s}  no data')
            continue
        et_idx   = intra.index.tz_convert(TZ)
        rth      = intra[et_idx.strftime('%H:%M') >= '09:30']
        pm       = intra[et_idx.strftime('%H:%M') <  '09:30']
        if rth.empty:
            print(f'{sym:6s}  no RTH bar')
            continue
        rth_open   = rth.iloc[0]['open']
        today_date = rth.index.tz_convert(TZ)[0].date()
        daily.index = daily.index.tz_convert(TZ)
        prior = daily[daily.index.date < today_date]
        if prior.empty:
            print(f'{sym:6s}  no prior daily bar')
            continue
        prev_close = float(prior.iloc[-1]['close'])
        gap        = (rth_open - prev_close) / prev_close * 100
        pm_high    = float(pm['high'].max()) if not pm.empty else None
        pmh_str    = f'pmh=${pm_high:.2f}' if pm_high else 'pmh=N/A'
        flag       = ' ***' if gap >= 0.5 else ''
        print(f'{sym:6s}  gap={gap:+5.2f}%  {pmh_str}{flag}')
    except Exception as e:
        print(f'{sym:6s}  ERROR: {e}')
