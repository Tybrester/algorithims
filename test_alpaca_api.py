"""Quick test of Alpaca API connectivity"""
import requests

ALPACA_KEY = 'PKGA4ZC63QX27XHF22CB6YP547'
ALPACA_SECRET = 'G9DHAvMtddnSUfbMw4182T4RpACeMHi9usRHSYQ8c87Q'
DATA_URL = 'https://data.alpaca.markets'

url = f"{DATA_URL}/v2/stocks/SPY/bars"
headers = {
    'APCA-API-KEY-ID': ALPACA_KEY,
    'APCA-API-SECRET-KEY': ALPACA_SECRET
}
params = {
    'timeframe': '5Min',
    'start': '2026-05-15',
    'limit': 100,
    'feed': 'iex'
}

print("Testing Alpaca API...")
print(f"URL: {url}")
print(f"Key: {ALPACA_KEY[:10]}...")

try:
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    print(f"\nStatus: {resp.status_code}")
    print(f"Response: {resp.text[:500]}")
    
    if resp.status_code == 200:
        data = resp.json()
        bars = data.get('bars', [])
        print(f"\n✅ Success! Got {len(bars)} bars")
    else:
        print(f"\n❌ Error: {resp.status_code}")
        
except Exception as e:
    print(f"\n❌ Exception: {e}")
