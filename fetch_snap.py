import requests
headers = {
    'APCA-API-KEY-ID': 'PK22C5W5QQLOX2NLK3LDFVKCHW',
    'APCA-API-SECRET-KEY': 'F8TBURaRyCVY3ekXEhJ7RkF3QXJbohRxDBxPg5LiS9nX'
}
r = requests.get('https://data.alpaca.markets/v2/stocks/snapshots?symbols=MCHP,PODD', headers=headers)
print(r.status_code, r.text[:200])
j = r.json()
for sym in ['MCHP','PODD']:
    s = j.get(sym, {})
    open_p  = s.get('dailyBar', {}).get('o', 0)
    latest  = s.get('latestTrade', {}).get('p', 0)
    prev    = s.get('prevDailyBar', {}).get('c', 0)
    print(f"{sym}: prev_close={prev:.2f}  open={open_p:.2f}  latest={latest:.2f}")
