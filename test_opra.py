import requests
import os

ALPACA_KEY = 'PKGA4ZC63QX27XHF22CB6YP547'
ALPACA_SECRET = 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q'
DATA_URL = 'https://data.alpaca.markets'

url = f'{DATA_URL}/v1beta1/options/snapshots/AAPL'
headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
params = {'feed': 'opra'}

resp = requests.get(url, headers=headers, params=params, timeout=30)
print(f'Status: {resp.status_code}')
if resp.status_code == 200:
    data = resp.json()
    print(f'Snapshots count: {len(data.get("snapshots", {}))}')
    # Show first option
    for sym, opt in list(data.get('snapshots', {}).items())[:5]:
        greeks = opt.get('greeks', {})
        quote = opt.get('latestQuote', {})
        print(f'  {sym}: bid={quote.get("bidPrice", 0)}, ask={quote.get("askPrice", 0)}, delta={greeks.get("delta", 0):.2f}')
