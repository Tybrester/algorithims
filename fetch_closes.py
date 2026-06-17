import requests
headers = {
    'APCA-API-KEY-ID': 'PKUE2IRNMB5ZUCK3ISPE3RIUX4',
    'APCA-API-SECRET-KEY': 'Cb3rxrN6SNSYkpYEbVn96i7FjM5KCBcpR8bLq7hKRciB'
}
syms = 'UPST,HOOD,MU,TSLA,MRVL,AMD'
r = requests.get(f'https://data.alpaca.markets/v2/stocks/snapshots?symbols={syms}&feed=iex', headers=headers)
if not r.ok:
    r = requests.get(f'https://data.alpaca.markets/v2/stocks/snapshots?symbols={syms}', headers=headers)
j = r.json()
for sym in syms.split(','):
    s = j.get(sym, {})
    prev  = s.get('prevDailyBar', {}).get('c', 0)
    close = s.get('dailyBar', {}).get('c', 0) or s.get('latestTrade', {}).get('p', 0)
    print(f"{sym}: prev_close=${prev:.2f}  today_close=${close:.2f}")
